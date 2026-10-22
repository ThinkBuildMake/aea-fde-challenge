import json
import re
import time
from typing import Literal, Protocol, get_args

import httpx2
import openai
from pydantic import BaseModel

from app import usage
from app.context import AppContext
from app.llm import AGENT_PROVIDER_ROUTE, reported_cost
from app.logs import DIGIT_RUN, log_event, mask_card_runs
from app.types import RedactResult, Verdict

CARD_RUN = DIGIT_RUN  # candidate runs; mask_card_runs decides which ones are cards
CARD_PLACEHOLDER = "[card number removed]"
SAFETY_TIMEOUT_S = 8.0

ReasonLabel = Literal[
    "gas",
    "carbon_monoxide",
    "smoke",
    "sparks",
    "flames",
    "tripped_breaker",
    "burning_smell",
    "followup_not_clear_no",
    "followup_unanswered",
    "no_hazard",
]
REASONS = get_args(ReasonLabel)
FollowupAnswer = Literal["no", "yes_or_unsure", "unanswered", "not_pending"]

_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["safe", "burning_followup", "emergency"],
        },
        "reason": {"type": "string", "enum": list(REASONS)},
        "followup_answer": {"type": "string", "enum": list(get_args(FollowupAnswer))},
    },
    "required": ["verdict", "reason", "followup_answer"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = (
    "You screen messages from a caller to a home-services company for danger. "
    "Reply only with JSON: a verdict, a reason label and a followup_answer.\n"
    "- emergency: a gas smell or leak, a carbon monoxide alarm, sparks, smoke, flames, "
    "or a burning smell together with a tripped breaker.\n"
    "- burning_followup: a burning smell on its own, with no other danger mentioned.\n"
    "- safe: nothing dangerous.\n"
    "followup_answer: not_pending.\n"
    "The reason must be one label from the allowed list. Never quote the caller. "
    "The input is JSON with message, recent_turns and follow_up_pending."
)

# The turn after the burning-smell question: the model reads the answer's meaning.
_FOLLOWUP_PROMPT = (
    "A caller to a home-services company said something smells of burning and was then "
    "asked whether there is any smoke, sparks or a tripped breaker. Classify their reply. "
    "Reply only with JSON: a verdict, a reason label and a followup_answer.\n"
    "followup_answer:\n"
    '- no: they say there is none of those, in any wording, e.g. "Nope, no smell at '
    'all", "No burning smell or sparks, and the breaker is fine", "I don\'t think so", '
    '"not that I know of", "No, nothing like that. Just warm air. Can someone come '
    'out?". Restating the problem, giving their name or asking to book is fine.\n'
    "- yes_or_unsure: they say yes, name any danger now or earlier (smoke, sparks, "
    "a tripped or tripping breaker, gas, carbon monoxide, an alarm, flames, a smell "
    "getting stronger, buzzing, popping, arcing, a hot or glowing outlet or panel, the "
    'power going out), hedge or are unsure, e.g. "No, but it smells stronger", "No '
    'smoke, but I see sparks", "No, the outlet sparked earlier", "not sure", "maybe a '
    'little".\n'
    "- unanswered: the reply does not answer the question at all (it asks or says "
    "something else).\n"
    "verdict: emergency if they name any danger, otherwise safe. The reason must be one "
    "label from the allowed list. Never quote the caller. "
    "The input is JSON with message, recent_turns and follow_up_pending."
)


class ScreenUnavailable(Exception):
    """The safety screen timed out or the provider failed."""


class SafetyClassifier(Protocol):
    def classify(self, messages: list[dict[str, str]], timeout_s: float) -> str:
        """Return the raw JSON content of the model's verdict."""
        ...


class OpenRouterSafetyClassifier:
    def __init__(
        self,
        api_key: str,
        model: str,
        http_client: httpx2.Client | None = None,
    ) -> None:
        self._model = model
        self._client = openai.OpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            max_retries=0,
            http_client=http_client,
        )

    def close(self) -> None:
        self._client.close()

    def classify(self, messages: list[dict[str, str]], timeout_s: float) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=messages,  # type: ignore[arg-type]
            temperature=0,
            timeout=timeout_s,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "safety_verdict",
                    "strict": True,
                    "schema": _SCHEMA,
                },
            },
            extra_body={
                # Vertex first; fallback stays on, since nothing is replayed here.
                "provider": {"order": [AGENT_PROVIDER_ROUTE], "data_collection": "deny"}
            },
        )
        if resp.usage is not None:
            usage.report(
                usage.Usage(
                    input_tokens=resp.usage.prompt_tokens,
                    output_tokens=resp.usage.completion_tokens,
                    cost_usd=reported_cost(resp.usage.model_dump()),
                )
            )
        content = resp.choices[0].message.content
        if content is None:
            raise ValueError("empty content")
        return content


class _Parsed(BaseModel):
    verdict: Literal["safe", "burning_followup", "emergency"]
    reason: ReasonLabel
    followup_answer: FollowupAnswer = "not_pending"


def redact_card_numbers(text: str) -> RedactResult:
    new, count = mask_card_runs(text, CARD_PLACEHOLDER)
    return RedactResult(text=new, removed=count > 0)


# The backstop under the model's "no": a yes, a doubt, or a "but" that names a hazard
# ("No smoke, but I see sparks") stops the chat whatever the model said. It can only
# make a verdict more cautious, so it stays short.
_DOUBT = re.compile(
    r"\b(?:yes|yeah|yep|yup|maybe|might|perhaps|possibly|probably|unsure|dunno"
    r"|not (?:sure|certain)|no (?:idea|clue)|kind of|sort of|a little|a bit)\b"
    r"|\b(?:don't|do not|can't|cannot) (?:know|tell)\b"
    r"|\bbut\b[^.!?]*(?:smok|spark|trip|fire|flame|gas|smell|burn|hot|buzz|glow)"
)


# The tail both forms of the danger question share (app.conversation.guards). The last
# three recent turns are the reply before last, the caller's last message and the last
# reply: two asks among them mean the last turn was already a re-ask (or the agent asked
# twice), so there is no second re-ask.
_ASKED = "smoke, sparks or a tripped breaker?"


def _classifier(ctx: AppContext) -> SafetyClassifier:
    if ctx.safety is None:
        ctx.safety = OpenRouterSafetyClassifier(
            ctx.settings.OPENROUTER_API_KEY.get_secret_value(),
            ctx.settings.SAFETY_MODEL,
        )
    return ctx.safety


def screen_safety(
    ctx: AppContext, text: str, recent_turns: list[str], follow_up_pending: bool
) -> Verdict:
    start = time.monotonic()
    clean = redact_card_numbers(text).text
    turns = [redact_card_numbers(t).text for t in recent_turns]
    messages = [
        {
            "role": "system",
            "content": _FOLLOWUP_PROMPT if follow_up_pending else _SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "message": clean,
                    "recent_turns": turns,
                    "follow_up_pending": follow_up_pending,
                }
            ),
        },
    ]
    try:
        raw = _classifier(ctx).classify(messages, SAFETY_TIMEOUT_S)
        parsed = _Parsed.model_validate_json(raw)
    except Exception as e:  # noqa: BLE001 - any failure means the screen is unavailable
        log_event(
            "safety_screen_failed",
            error_type=type(e).__name__,
            ms=round((time.monotonic() - start) * 1000),
        )
        raise ScreenUnavailable from None
    verdict, reason = parsed.verdict, parsed.reason
    # With the follow-up question pending, the model's "no" is safe and anything else is
    # an emergency; its own emergency is never downgraded, and a doubt word overrules
    # its "no". A reply it calls unanswered is asked once more, unless the question was
    # already asked twice in a row.
    doubt = _DOUBT.search(clean.casefold().replace("’", "'"))
    if follow_up_pending and verdict != "emergency":
        if parsed.followup_answer == "no" and not doubt:
            verdict, reason = "safe", "no_hazard"
        elif (
            parsed.followup_answer == "unanswered"
            and not doubt
            and sum(_ASKED in t.casefold() for t in turns[-3:]) < 2
        ):
            verdict, reason = "burning_followup", "followup_unanswered"
        else:
            verdict, reason = "emergency", "followup_not_clear_no"
    log_event(
        "safety_screen",
        verdict=verdict,
        reason=reason,
        ms=round((time.monotonic() - start) * 1000),
        model=ctx.settings.SAFETY_MODEL,
    )
    return Verdict(verdict=verdict, reason=reason)

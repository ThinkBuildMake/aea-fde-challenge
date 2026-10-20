import json
import re
import time
from typing import Literal, Protocol, get_args

import httpx2
import openai
from pydantic import BaseModel

from app import usage
from app.context import AppContext
from app.llm import reported_cost
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
    "If follow_up_pending is true, the caller was just asked whether there is smoke, "
    "sparks or a tripped breaker: only a clear no is safe; yes, unsure or unclear is "
    "emergency. The burning smell in recent_turns is already known, so a clear no to "
    "the follow-up is safe.\n"
    "followup_answer: when follow_up_pending is false, not_pending. Otherwise no if the "
    "caller says there is none of those; yes_or_unsure if they say yes, mention any "
    "danger, or are unsure; unanswered if the message does not answer the question at "
    "all (it asks or says something else).\n"
    "The reason must be one label from the allowed list. Never quote the caller. "
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
            extra_body={"provider": {"data_collection": "deny"}},
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


# A clear no is a short negative and nothing else of substance: every comma- or
# full-stop-separated part of the answer must be one of these, and one must be negative.
_NEG = r"(?:no|nope|nah|none|negative|not at all|nothing(?: like that)?|none of (?:those|that|them|the above))"
_HAZARD = (
    r"(?:smoke|sparks?|fire|flames?|tripped breaker|(?:burning )?(?:smells?|odou?rs?))"
)
# "there is no smoke or sparks", "no burning smell or anything like that" (not "there
# was no smoke": that says nothing about now)
_NO_HAZARDS = (
    rf"(?:there(?:'s| is| are) )?no {_HAZARD}(?: (?:or|and|nor) (?:no )?{_HAZARD})*"
    r"(?: or anything(?: like that)?)?"
)
_POLITE = r"(?:sir|ma'?am|thanks|thank you|that'?s it)"
_CLEAR_PART = re.compile(rf"(?:{_NEG}|{_NO_HAZARDS})(?: {_POLITE})?")
# "no smoke, no sparks, and no tripped breaker" and "no smoke, sparks, or tripped
# breaker" are one list of negatives; "no smoke, and sparks" and "no smoke, sparks"
# are not (a bare comma joins a list only when it ends in "or <hazard>", FR-1.1).
_LIST_COMMA = re.compile(
    rf"\b({_HAZARD}),\s*(?:(?:and\s+)?(?=no\s+{_HAZARD}\b)|(?:or|nor)\s+(?={_HAZARD}\b)"
    rf"|(?={_HAZARD}(?:,\s*{_HAZARD})*,?\s+(?:or|nor)\s+{_HAZARD}\b))"
)
_POLITE_PART = re.compile(_POLITE)


# After the negative, a caller may restate their problem ("Just warm air."). Such a
# part is fine only if it names no hazard and holds no doubt, contrast or change. A
# plain "but" or a question after the no is allowed ("it runs but the air is warm",
# "can someone come out?"); the hazard words still apply, and "no?" is not a clear no.
_RISKY = re.compile(
    r"smok|spark|burn|smell|odou?r|fume|gas|fire|flame|breaker|trip|shock|melt|"
    r"buzz|sizzl|crackl|wir(?:e|ing)|carbon|alarm|hot|overheat|scorch|"
    r"glow|\barc(?:s|ed|ing)?\b|flash|\bbang|\bpop(?:s|ped|ping)?\b|beep|detector|"
    r"lights? went|power went|power (?:is )?out|"
    r"\b(?:though|although|except|however|actually|wait|still|now|worse|stronger|"
    r"maybe|might|perhaps|sure|unsure|think|guess|tell|know|idea|clue|certain|"
    r"kind of|sort of|little|bit|yes|yeah|yep|earlier)\b"
)


# The tail both forms of the danger question share (app.conversation.guards). The last
# three recent turns are the reply before last, the caller's last message and the last
# reply: two asks among them mean the last turn was already a re-ask (or the agent asked
# twice), so there is no second re-ask.
_ASKED = "smoke, sparks or a tripped breaker?"


def _is_clear_no(text: str) -> bool:
    t = _LIST_COMMA.sub(r"\1 or ", text.casefold().replace("\u2019", "'"))
    parts = [" ".join(p.split()) for p in re.split(r"[,.;!]+", t)]
    parts = [p for p in parts if p]
    if not parts or not _CLEAR_PART.fullmatch(parts[0]):
        return False
    return all(
        _CLEAR_PART.fullmatch(p) or _POLITE_PART.fullmatch(p) or not _RISKY.search(p)
        for p in parts[1:]
    )


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
        {"role": "system", "content": _SYSTEM_PROMPT},
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
    # With the follow-up question pending, a clear no is safe and anything else is an
    # emergency; the model's own emergency is never downgraded. The model may only turn
    # a stop into one more ask: a message with no hazard or doubt word that it calls
    # unanswered, unless the question was already asked twice in a row.
    if follow_up_pending and verdict != "emergency":
        if _is_clear_no(clean):
            verdict, reason = "safe", "no_hazard"
        elif (
            parsed.followup_answer == "unanswered"
            and not _RISKY.search(clean.casefold())
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

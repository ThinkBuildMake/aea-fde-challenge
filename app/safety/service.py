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
from app.logs import log_event
from app.types import RedactResult, Verdict

CARD_RUN = re.compile(r"(?<!\d)\d(?:[ \t-]{0,3}\d){12,}(?!\d)")
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
    "no_hazard",
]
REASONS = get_args(ReasonLabel)

_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["safe", "burning_followup", "emergency"],
        },
        "reason": {"type": "string", "enum": list(REASONS)},
    },
    "required": ["verdict", "reason"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = (
    "You screen messages from a caller to a home-services company for danger. "
    "Reply only with JSON: a verdict and a reason label.\n"
    "- emergency: a gas smell or leak, a carbon monoxide alarm, sparks, smoke, flames, "
    "or a burning smell together with a tripped breaker.\n"
    "- burning_followup: a burning smell on its own, with no other danger mentioned.\n"
    "- safe: nothing dangerous.\n"
    "If follow_up_pending is true, the caller was just asked whether there is smoke, "
    "sparks or a tripped breaker: only a clear no is safe; yes, unsure or unclear is "
    "emergency.\n"
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


def redact_card_numbers(text: str) -> RedactResult:
    new, count = CARD_RUN.subn(CARD_PLACEHOLDER, text)
    return RedactResult(text=new, removed=count > 0)


_NOT_CLEAR = (
    "not sure", "unsure", "maybe", "don't know", "dont know", "idk",
    "i think", "possibly", "might", "yes", "no idea", "no clue", "can't tell",
    "cant tell", "cannot tell", "not certain",
)  # fmt: skip
_NO_STARTS = ("no", "nope", "nah", "none", "negative", "not at all")


def _is_clear_no(text: str) -> bool:
    t = text.casefold().strip()
    if any(p in t for p in _NOT_CLEAR):
        return False
    return any(re.match(rf"{re.escape(s)}\b", t) for s in _NO_STARTS)


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
    if (
        follow_up_pending
        and verdict != "emergency"
        and not (verdict == "safe" and _is_clear_no(clean))
    ):
        verdict, reason = "emergency", "followup_not_clear_no"
    log_event(
        "safety_screen",
        verdict=verdict,
        reason=reason,
        ms=round((time.monotonic() - start) * 1000),
        model=ctx.settings.SAFETY_MODEL,
    )
    return Verdict(verdict=verdict, reason=reason)

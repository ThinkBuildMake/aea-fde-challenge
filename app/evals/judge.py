"""gradeAnswer: the judge model checks each expected fact in a transcript (EV-5)."""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

from openai import OpenAI
from pydantic import BaseModel

from app.evals.records import FactCheck, Judge, Scenario, TranscriptLine
from app.llm import OPENROUTER_BASE_URL
from app.settings import Settings

JUDGE_SYSTEM = (
    "You grade a support chat between a caller and Meridian's assistant against a "
    "numbered list of expected facts. A fact is present only when the Assistant's own "
    "lines convey it; what the Caller says never counts. A fact the Assistant states "
    "with a different value (another price, time, policy or name) is absent, and that "
    "statement is listed as a contradiction. List contradictions only where the "
    "Assistant contradicts one of the expected facts, each as one short sentence. "
    "Answer with JSON only: one entry per fact by its number, and the contradictions."
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "present": {"type": "boolean"},
                },
                "required": ["index", "present"],
                "additionalProperties": False,
            },
        },
        "contradictions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["facts", "contradictions"],
    "additionalProperties": False,
}


@dataclass
class Grade:
    facts_missing: list[str] = field(default_factory=list)
    judge: Judge = field(default_factory=Judge)
    cost_usd: float = 0.0


class JudgeClient(Protocol):
    def ask(self, messages: list[dict[str, str]]) -> tuple[str, float]:
        """The model's raw JSON content and the call's cost in USD."""
        ...


def openrouter_cost(usage: dict[str, Any]) -> float:
    """The call's cost; with a bring-your-own-key route `cost` is 0 and the real
    figure is cost_details.upstream_inference_cost."""
    upstream = (usage.get("cost_details") or {}).get("upstream_inference_cost")
    return float(usage.get("cost") or upstream or 0.0)


class OpenRouterJudge:
    def __init__(self, settings: Settings) -> None:
        self.model = settings.JUDGE_MODEL
        self.client = OpenAI(
            api_key=settings.OPENROUTER_API_KEY.get_secret_value(),
            base_url=OPENROUTER_BASE_URL,
            max_retries=1,
            timeout=60,
        )

    def close(self) -> None:
        self.client.close()

    def ask(self, messages: list[dict[str, str]]) -> tuple[str, float]:
        raw = self.client.chat.completions.with_raw_response.create(
            model=self.model,
            messages=cast(Any, messages),
            temperature=0,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "fact_grades",
                    "strict": True,
                    "schema": SCHEMA,
                },
            },
            extra_body={
                "reasoning": {"effort": "low"},
                "usage": {"include": True},
                "provider": {"data_collection": "deny"},
            },
        )
        data = json.loads(raw.text)
        content = data["choices"][0]["message"].get("content") or ""
        return content, openrouter_cost(data.get("usage") or {})


class _FactReply(BaseModel):
    index: int
    present: bool


class _Reply(BaseModel):
    facts: list[_FactReply]
    contradictions: list[str]


def _request(facts: Sequence[str], transcript: Sequence[TranscriptLine]) -> str:
    numbered = "\n".join(f"{n}. {fact}" for n, fact in enumerate(facts, 1))
    chat = "\n".join(
        f"{'Caller' if line.role == 'caller' else 'Assistant'}: {line.text}"
        for line in transcript
    )
    return f"Expected facts:\n{numbered}\n\nTranscript:\n{chat}"


def grade_answer(
    scenario: Scenario,
    transcript: Sequence[TranscriptLine],
    judge: JudgeClient | None,
) -> Grade:
    """Each expected fact present or absent, plus contradictions. No judge: not graded.
    A failed call or an unreadable reply is verdict "error" (never a pass), noting only
    the error type."""
    facts = scenario.expected.facts
    if judge is None:
        return Grade()
    if not facts:
        return Grade(judge=Judge(verdict="pass"))
    cost = 0.0
    try:
        content, cost = judge.ask(
            [
                {"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user", "content": _request(facts, transcript)},
            ]
        )
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
        reply = _Reply.model_validate_json(text)
    except Exception as error:  # noqa: BLE001 - a judge failure is recorded, not raised
        return Grade(
            judge=Judge(verdict="error", notes=type(error).__name__), cost_usd=cost
        )
    present = {f.index for f in reply.facts if f.present}
    checks = [
        FactCheck(fact=fact, present=n in present) for n, fact in enumerate(facts, 1)
    ]
    missing = [c.fact for c in checks if not c.present]
    passed = not missing and not reply.contradictions
    return Grade(
        facts_missing=missing,
        judge=Judge(
            verdict="pass" if passed else "fail",
            contradictions=reply.contradictions,
            facts=checks,
        ),
        cost_usd=cost,
    )

"""The caller model: plays the customer from a scenario's brief, one message at a time."""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

from openai import OpenAI

from app.evals.records import Scenario
from app.llm import OPENROUTER_BASE_URL, reported_cost
from app.settings import Settings

Transcript = Sequence[tuple[str, str]]  # (role, text), role is "caller" or "agent"

SYSTEM = (
    "You are playing a customer on a chat with the home-services company Meridian's "
    "assistant. Stay in character, write short plain messages, and answer only what is "
    "asked using the facts in your brief; never invent account details that are not "
    "there, and never add requests or facts that are not in your brief. Your brief:\n"
    "{brief}\n\nReply with one JSON object and nothing else: "
    '{{"message": "<your next message>", "done": <true when you got what you needed, '
    'were handed to a person, or gave up>, "solved": <true or false: was your problem '
    "solved; only when done>}}. When done, put your last message (a yes, a thank you or "
    "a goodbye) in message; it is still sent."
)


@dataclass
class CallerMove:
    text: str | None
    done: bool = False
    solved: bool | None = None
    cost_usd: float = 0.0


class CallerModel(Protocol):
    def next_move(self, scenario: Scenario, transcript: Transcript) -> CallerMove: ...


@dataclass
class ScriptedCaller:
    """Test double: replays a script per scenario id, can raise for chosen scenarios."""

    script: dict[str, list[str | CallerMove]] = field(default_factory=dict)
    fail_on: set[str] = field(default_factory=set)

    def next_move(self, scenario: Scenario, transcript: Transcript) -> CallerMove:
        if scenario.id in self.fail_on:
            raise RuntimeError(f"scripted caller failure for {scenario.id}")
        queue = self.script.get(scenario.id, [])
        if not queue:
            return CallerMove(None, done=True, solved=True)
        move = queue.pop(0)
        return CallerMove(move) if isinstance(move, str) else move


def parse_move(raw: str, cost_usd: float) -> CallerMove:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    try:
        data = json.loads(text)
    except ValueError:
        return CallerMove(raw.strip() or None, cost_usd=cost_usd)
    if not isinstance(data, dict):
        return CallerMove(raw.strip() or None, cost_usd=cost_usd)
    message = str(data.get("message") or "").strip()
    solved = data.get("solved")
    return CallerMove(
        message or None,
        done=bool(data.get("done")) or not message,
        solved=solved if isinstance(solved, bool) else None,
        cost_usd=cost_usd,
    )


class OpenRouterCaller:
    def __init__(self, settings: Settings) -> None:
        self.model = settings.CALLER_MODEL
        self.client = OpenAI(
            api_key=settings.OPENROUTER_API_KEY.get_secret_value(),
            base_url=OPENROUTER_BASE_URL,
            max_retries=1,
            timeout=30,
        )

    def next_move(self, scenario: Scenario, transcript: Transcript) -> CallerMove:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": SYSTEM.format(brief=scenario.caller_brief)}
        ]
        for role, text in transcript:
            messages.append(
                {"role": "assistant" if role == "caller" else "user", "content": text}
            )
        raw = self.client.chat.completions.with_raw_response.create(
            model=self.model,
            messages=cast(Any, messages),
            extra_body={"reasoning": {"effort": "low"}, "usage": {"include": True}},
        )
        data = json.loads(raw.text)
        usage = data.get("usage") or {}
        content = data["choices"][0]["message"].get("content") or ""
        return parse_move(content, float(reported_cost(usage) or 0.0))

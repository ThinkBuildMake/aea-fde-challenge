"""Model provider seam. S13 adds the OpenRouter provider; these are the stub and the test double."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

PLACEHOLDER_REPLY = "This is a placeholder reply. The assistant is not connected yet."


@dataclass
class ModelResult:
    message: dict[str, Any]
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost_usd: float | None = None


class ModelProvider(Protocol):
    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        timeout_s: float,
    ) -> ModelResult: ...


class StubModelProvider:
    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        timeout_s: float,
    ) -> ModelResult:
        return ModelResult(message={"role": "assistant", "content": PLACEHOLDER_REPLY})


class FakeModelProvider:
    """Scripted provider for tests: canned replies, an optional delay, an optional failure."""

    def __init__(
        self,
        replies: list[str] | None = None,
        delay_s: float = 0.0,
        sleep: Callable[[float], None] = time.sleep,
        fail_with: Exception | None = None,
    ) -> None:
        self.replies = list(replies) if replies else [PLACEHOLDER_REPLY]
        self.delay_s = delay_s
        self.sleep = sleep
        self.fail_with = fail_with
        self.received: list[list[dict[str, Any]]] = []

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        timeout_s: float,
    ) -> ModelResult:
        self.received.append(messages)
        if self.delay_s:
            self.sleep(self.delay_s)
        if self.fail_with is not None:
            raise self.fail_with
        text = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return ModelResult(message={"role": "assistant", "content": text})

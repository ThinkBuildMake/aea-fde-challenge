"""Model provider seam. S13 adds the OpenRouter provider; these are the stub and the test double."""

import copy
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, cast

import httpx2
import openai
from openai import OpenAI, omit

from app.settings import Settings

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
AGENT_PROVIDER_ROUTE = "google-vertex"
PLACEHOLDER_REPLY = "This is a placeholder reply. The assistant is not connected yet."


@dataclass
class ModelResult:
    message: dict[str, Any]
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost_usd: float | None = None


def reported_cost(usage: dict[str, Any]) -> float | None:
    """The call's price from OpenRouter usage: under BYOK `cost` is only OpenRouter's fee,
    and the provider's price is in cost_details.upstream_inference_cost."""
    cost = usage.get("cost")
    upstream = (usage.get("cost_details") or {}).get("upstream_inference_cost")
    if usage.get("is_byok") and upstream is not None:
        return (cost or 0) + upstream
    return cost


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


class OpenRouterProvider:
    """The agent model on OpenRouter. Returns the provider's raw assistant message so a
    later turn can replay it unchanged, including its reasoning notes."""

    def __init__(
        self, settings: Settings, http_client: httpx2.Client | None = None
    ) -> None:
        self.model = settings.AGENT_MODEL
        self.client = OpenAI(
            api_key=settings.OPENROUTER_API_KEY.get_secret_value(),
            base_url=OPENROUTER_BASE_URL,
            max_retries=0,
            http_client=http_client,
        )

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        timeout_s: float,
    ) -> ModelResult:
        raw = self.client.chat.completions.with_raw_response.create(
            model=self.model,
            messages=cast(Any, messages),
            tools=cast(Any, tools) if tools else omit,
            timeout=timeout_s,
            extra_body={
                "reasoning": {"effort": "low"},
                "provider": {"order": [AGENT_PROVIDER_ROUTE], "allow_fallbacks": False},
                "usage": {"include": True},
            },
        )
        data = json.loads(raw.text)
        usage = data.get("usage") or {}
        return ModelResult(
            message=data["choices"][0]["message"],
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            cost_usd=reported_cost(usage),
        )


class FakeModelProvider:
    """Scripted provider for tests: canned replies, an optional delay, an optional failure."""

    def __init__(
        self,
        replies: list[str] | None = None,
        delay_s: float = 0.0,
        sleep: Callable[[float], None] = time.sleep,
        fail_with: Exception | None = None,
        results: list[ModelResult] | None = None,
        hang: threading.Event | None = None,
        reject_replay: bool = False,
    ) -> None:
        self.hang = hang
        self.reject_replay = reject_replay
        self.results = list(results) if results else None
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
        self.received.append(copy.deepcopy(messages))
        if self.hang is not None:
            self.hang.wait()
            raise TimeoutError("released")
        if self.reject_replay and sum(m["role"] == "user" for m in messages) > 1:
            raise status_error(400)
        if self.delay_s:
            self.sleep(self.delay_s)
        if self.fail_with is not None:
            raise self.fail_with
        if self.results is not None:
            return self.results.pop(0) if len(self.results) > 1 else self.results[0]
        text = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return ModelResult(message={"role": "assistant", "content": text})


def status_error(code: int) -> openai.APIStatusError:
    """The error the OpenAI client raises for an HTTP status, for tests."""
    response = httpx2.Response(
        code, request=httpx2.Request("POST", f"{OPENROUTER_BASE_URL}/chat/completions")
    )
    cls = {400: openai.BadRequestError, 429: openai.RateLimitError}.get(
        code, openai.APIStatusError
    )
    return cls(f"status {code}", response=response, body=None)

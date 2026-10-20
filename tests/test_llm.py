import json
from typing import Any

import httpx2
import openai
import pytest

from app.llm import FakeModelProvider, ModelResult, OpenRouterProvider, reported_cost
from app.settings import Settings

ASSISTANT = {
    "role": "assistant",
    "content": "",
    "reasoning": "thinking",
    "reasoning_details": [
        {"type": "reasoning.encrypted", "data": "abc", "format": "google-gemini-v1"}
    ],
    "refusal": None,
    "tool_calls": [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "search_knowledge", "arguments": '{"query":"fee"}'},
        }
    ],
}
TOOLS = [{"type": "function", "function": {"name": "search_knowledge"}}]


def provider(settings: Settings, handler) -> OpenRouterProvider:
    client = httpx2.Client(transport=httpx2.MockTransport(handler))
    return OpenRouterProvider(settings, http_client=client)


def ok_response(message: dict[str, Any], usage: dict[str, Any]) -> httpx2.Response:
    return httpx2.Response(
        200, json={"choices": [{"message": message}], "usage": usage}
    )


def test_openrouter_request_is_pinned(tmp_settings: Settings):
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(500, json={"error": {"message": "boom"}})

    messages = [
        {"role": "user", "content": "hi"},
        ASSISTANT,
        {"role": "tool", "tool_call_id": "call_1", "content": "{}"},
    ]
    llm = provider(tmp_settings, handler)
    with pytest.raises(openai.APIStatusError):
        llm.complete(messages, tools=TOOLS, timeout_s=5)
    assert len(seen) == 1
    assert seen[0].url.path.endswith("/chat/completions")
    body = json.loads(seen[0].content)
    assert body["model"] == tmp_settings.AGENT_MODEL
    assert body["provider"] == {"order": ["google-vertex"], "allow_fallbacks": False}
    assert body["reasoning"] == {"effort": "low"}
    assert body["tools"] == TOOLS
    assert body["messages"] == messages


def test_openrouter_returns_raw_message_and_cost(tmp_settings: Settings):
    usage = {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0001}
    llm = provider(tmp_settings, lambda request: ok_response(ASSISTANT, usage))
    result = llm.complete([{"role": "user", "content": "hi"}], timeout_s=5)
    assert result.message == ASSISTANT
    assert (result.prompt_tokens, result.completion_tokens) == (10, 5)
    assert result.cost_usd == 0.0001


BYOK_USAGE = {
    "prompt_tokens": 10,
    "completion_tokens": 5,
    "cost": 0,
    "is_byok": True,
    "cost_details": {"upstream_inference_cost": 0.00002},
}


def test_reported_cost_adds_the_upstream_price_under_byok():
    assert reported_cost(BYOK_USAGE) == 0.00002
    assert reported_cost({"cost": 0.0001, "is_byok": False}) == 0.0001
    assert reported_cost({"cost": 0.0001}) == 0.0001
    assert reported_cost({"cost": 0, "is_byok": True}) == 0
    assert reported_cost({}) is None


def test_openrouter_byok_call_costs_its_upstream_price(tmp_settings: Settings):
    llm = provider(tmp_settings, lambda request: ok_response(ASSISTANT, BYOK_USAGE))
    result = llm.complete([{"role": "user", "content": "hi"}], timeout_s=5)
    assert result.cost_usd == 0.00002


def test_fake_scripts_tool_calls():
    first = ModelResult(message=ASSISTANT, cost_usd=0.001)
    second = ModelResult(message={"role": "assistant", "content": "done"})
    fake = FakeModelProvider(results=[first, second])
    assert fake.complete([], timeout_s=1) is first
    assert fake.complete([], timeout_s=1) is second
    assert len(fake.received) == 2

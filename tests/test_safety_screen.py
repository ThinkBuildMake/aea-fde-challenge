import dataclasses
import json
import re

import httpx2
import pytest

from app import usage
from app.main import create_app
from app.safety.service import (
    CARD_PLACEHOLDER,
    REASONS,
    OpenRouterSafetyClassifier,
    ScreenUnavailable,
    screen_safety,
)
from app.settings import Settings

DIGIT_RUN = re.compile(r"\d(?:[ -]?\d){12,18}")


class FakeClassifier:
    def __init__(self, verdict: str, reason: str) -> None:
        self.reply = json.dumps({"verdict": verdict, "reason": reason})
        self.seen: list[str] = []

    def classify(self, messages: list[dict[str, str]], timeout_s: float) -> str:
        self.seen.extend(m["content"] for m in messages)
        return self.reply


def _ctx(settings: Settings, classifier):
    ctx = create_app(settings).state.ctx
    return dataclasses.replace(ctx, safety=classifier)


def test_emergency_verdict_passes_through(tmp_settings: Settings) -> None:
    msg = "I smell gas in the kitchen"
    ctx = _ctx(tmp_settings, FakeClassifier("emergency", "gas"))
    v = screen_safety(ctx, msg, [], False)
    assert v.verdict == "emergency"
    assert v.reason in REASONS
    assert msg.casefold() not in v.reason.casefold()


def test_burning_followup_passes_through(tmp_settings: Settings) -> None:
    ctx = _ctx(tmp_settings, FakeClassifier("burning_followup", "burning_smell"))
    v = screen_safety(ctx, "There's a burning smell from the vents", [], False)
    assert v.verdict == "burning_followup"


@pytest.mark.parametrize(
    "reply", [("safe", "no_hazard"), ("burning_followup", "burning_smell")]
)
def test_not_sure_after_followup_is_emergency(
    tmp_settings: Settings, reply: tuple[str, str]
) -> None:
    ctx = _ctx(tmp_settings, FakeClassifier(*reply))
    v = screen_safety(
        ctx, "not sure", ["Any smoke, sparks or a tripped breaker?"], True
    )
    assert v.verdict == "emergency"


def _failing(handler) -> OpenRouterSafetyClassifier:
    return OpenRouterSafetyClassifier(
        "fake-key",
        "m",
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )


def _completion(content: str | None) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "x",
            "object": "chat.completion",
            "created": 0,
            "model": "m",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": content},
                }
            ],
        },
    )


def _timeout(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ReadTimeout("slow", request=request)


@pytest.mark.parametrize(
    "handler",
    [
        _timeout,
        lambda r: httpx2.Response(500, json={"error": "boom"}),
        lambda r: httpx2.Response(429, json={"error": "rate"}),
        lambda r: _completion("not json"),
        lambda r: _completion(json.dumps({"verdict": "maybe", "reason": "gas"})),
        lambda r: _completion(json.dumps({"verdict": "safe", "reason": "free text"})),
        lambda r: _completion(None),
        lambda r: httpx2.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 0,
                "model": "m",
                "choices": [],
            },
        ),
    ],
)
def test_failed_screen_raises(tmp_settings: Settings, handler) -> None:
    ctx = _ctx(tmp_settings, _failing(handler))
    with pytest.raises(ScreenUnavailable):
        screen_safety(ctx, "hello there", [], False)


def test_classifier_never_sees_card_digits(tmp_settings: Settings) -> None:
    fake = FakeClassifier("safe", "no_hazard")
    ctx = _ctx(tmp_settings, fake)
    screen_safety(
        ctx, "card 4111 1111 1111 1111", ["my number is 5500-0000-0000-0004"], False
    )
    joined = "\n".join(fake.seen)
    assert DIGIT_RUN.search(joined) is None
    assert CARD_PLACEHOLDER in joined


@pytest.mark.parametrize(
    ("text", "pending", "model_says", "expected"),
    [
        ("yes, the breaker tripped", True, "safe", "emergency"),
        ("No, no smoke or sparks", True, "safe", "safe"),
        ("hmm", True, "burning_followup", "emergency"),
        ("no", False, "emergency", "emergency"),
        ("no idea", True, "safe", "emergency"),
        ("no clue", True, "safe", "emergency"),
        ("No, I can't tell", True, "safe", "emergency"),
        ("not certain", True, "safe", "emergency"),
        ("No, nothing like that", True, "burning_followup", "safe"),
        ("No", True, "burning_followup", "safe"),
        ("Yes, the breaker tripped", True, "burning_followup", "emergency"),
        ("No, but now there is smoke", True, "emergency", "emergency"),
    ],
)
def test_vr2_followup_rules(
    tmp_settings: Settings, text: str, pending: bool, model_says: str, expected: str
) -> None:
    reason = {"safe": "no_hazard", "emergency": "gas"}.get(model_says, "burning_smell")
    ctx = _ctx(tmp_settings, FakeClassifier(model_says, reason))
    assert screen_safety(ctx, text, [], pending).verdict == expected


def test_screen_reports_its_tokens_and_cost(tmp_settings: Settings) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        response = _completion(json.dumps({"verdict": "safe", "reason": "no_hazard"}))
        body = json.loads(response.content)
        body["usage"] = {
            "prompt_tokens": 120,
            "completion_tokens": 8,
            "total_tokens": 128,
            "cost": 0,
            "is_byok": True,
            "cost_details": {"upstream_inference_cost": 0.00002},
        }
        return httpx2.Response(200, json=body)

    ctx = _ctx(tmp_settings, _failing(handler))
    with usage.collect() as seen:
        screen_safety(ctx, "hello there", [], False)
    assert seen == [usage.Usage(input_tokens=120, output_tokens=8, cost_usd=0.00002)]

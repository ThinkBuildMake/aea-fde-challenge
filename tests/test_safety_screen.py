import dataclasses
import json
import re

import httpx2
import pytest

from app import usage
from app.conversation import guards
from app.main import create_app
from app.safety.service import (
    _SCHEMA,
    CARD_PLACEHOLDER,
    REASONS,
    OpenRouterSafetyClassifier,
    ScreenUnavailable,
    screen_safety,
)
from app.settings import Settings

DIGIT_RUN = re.compile(r"\d(?:[ -]?\d){12,18}")


class FakeClassifier:
    def __init__(
        self, verdict: str, reason: str, followup_answer: str | None = None
    ) -> None:
        reply = {"verdict": verdict, "reason": reason}
        if followup_answer:
            reply["followup_answer"] = followup_answer
        self.reply = json.dumps(reply)
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
    ("text", "pending", "model_says", "answer", "expected"),
    [
        # The model reads the meaning; its "no" is safe in any wording.
        ("Nope, no smell at all", True, "safe", "no", "safe"),
        (
            "No burning smell or sparks, and the breaker is fine.",
            True,
            "safe",
            "no",
            "safe",
        ),
        ("I don't think so", True, "safe", "no", "safe"),
        ("not that I know of", True, "safe", "no", "safe"),
        (
            "No, nothing like that. Can someone come out to look at it?",
            True,
            "safe",
            "no",
            "safe",
        ),
        (
            "No, nothing like that. The AC just runs but the air is warm.",
            True,
            "safe",
            "no",
            "safe",
        ),
        # Anything but its "no" stops the chat.
        ("yes, the breaker tripped", True, "safe", "yes_or_unsure", "emergency"),
        (
            "No, there's still a smell",
            True,
            "burning_followup",
            "yes_or_unsure",
            "emergency",
        ),
        ("okay, let's schedule it.", True, "safe", "not_pending", "emergency"),
        # Its own emergency is never downgraded.
        ("No", True, "emergency", "no", "emergency"),
        ("no", False, "emergency", "not_pending", "emergency"),
        # A yes, a doubt or a "but" naming a hazard overrules its "no".
        ("Yes, the breaker tripped", True, "safe", "no", "emergency"),
        ("no idea", True, "safe", "no", "emergency"),
        ("no clue", True, "safe", "no", "emergency"),
        ("No, I can't tell", True, "safe", "no", "emergency"),
        ("not certain", True, "safe", "no", "emergency"),
        ("No, not sure though", True, "safe", "no", "emergency"),
        ("No, maybe a little smoke", True, "safe", "no", "emergency"),
        ("No? I don\u2019t know", True, "safe", "no", "emergency"),
        ("No smoke, but I see sparks", True, "safe", "no", "emergency"),
        ("None of those, but it smells stronger", True, "safe", "no", "emergency"),
        ("No smoke at all, but it smells hot", True, "safe", "no", "emergency"),
        ("No, but the breaker keeps tripping", True, "safe", "no", "emergency"),
    ],
)
def test_vr2_followup_rules(
    tmp_settings: Settings,
    text: str,
    pending: bool,
    model_says: str,
    answer: str,
    expected: str,
) -> None:
    reason = {"safe": "no_hazard", "emergency": "gas"}.get(model_says, "burning_smell")
    ctx = _ctx(tmp_settings, FakeClassifier(model_says, reason, answer))
    assert screen_safety(ctx, text, [], pending).verdict == expected


@pytest.mark.parametrize("pending", [True, False])
def test_followup_has_its_own_prompt(tmp_settings: Settings, pending: bool) -> None:
    fake = FakeClassifier("safe", "no_hazard", "no" if pending else None)
    screen_safety(_ctx(tmp_settings, fake), "No", [], pending)
    asked = "asked whether there is any smoke, sparks or a tripped breaker"
    assert (asked in fake.seen[0]) is pending


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


ASKED = ["My AC is blowing warm air", guards.BURNING_FOLLOWUP_TEXT]
REASKED = [*ASKED, "How much is labor on a compressor?", guards.BURNING_FOLLOWUP_TEXT]


@pytest.mark.parametrize("model_says", ["safe", "burning_followup"])
@pytest.mark.parametrize(
    "text", ["How much is labor on a compressor?", "okay, let's schedule it."]
)
def test_s52_unanswered_followup_is_asked_again(
    tmp_settings: Settings, text: str, model_says: str
) -> None:
    ctx = _ctx(tmp_settings, FakeClassifier(model_says, "no_hazard", "unanswered"))
    v = screen_safety(ctx, text, ASKED, True)
    assert (v.verdict, v.reason) == ("burning_followup", "followup_unanswered")


@pytest.mark.parametrize(
    ("text", "answer"),
    [
        ("Maybe, how hot does the compressor get?", "unanswered"),  # a doubt word
        ("okay, let's schedule it.", "yes_or_unsure"),
        ("okay, let's schedule it.", "not_pending"),
        ("okay, let's schedule it.", None),  # the field is missing
    ],
)
def test_s52_other_non_answers_still_stop(
    tmp_settings: Settings, text: str, answer: str | None
) -> None:
    ctx = _ctx(tmp_settings, FakeClassifier("safe", "no_hazard", answer))
    v = screen_safety(ctx, text, ASKED, True)
    assert (v.verdict, v.reason) == ("emergency", "followup_not_clear_no")


def test_s52_asked_again_only_once(tmp_settings: Settings) -> None:
    ctx = _ctx(tmp_settings, FakeClassifier("safe", "no_hazard", "unanswered"))
    v = screen_safety(ctx, "okay, let's schedule it.", REASKED, True)
    assert (v.verdict, v.reason) == ("emergency", "followup_not_clear_no")


@pytest.mark.parametrize(
    ("text", "reply", "expected"),
    [
        ("yeah kind of", ("safe", "no_hazard", "no"), "followup_not_clear_no"),
        ("okay, let's schedule it.", ("emergency", "smoke", "unanswered"), "smoke"),
        ("No", ("emergency", "smoke", "no"), "smoke"),
    ],
)
def test_s52_model_safe_only_by_its_no(
    tmp_settings: Settings, text: str, reply: tuple[str, str, str], expected: str
) -> None:
    ctx = _ctx(tmp_settings, FakeClassifier(*reply))
    v = screen_safety(ctx, text, ASKED, True)
    assert (v.verdict, v.reason) == ("emergency", expected)


def test_s52_schema_asks_for_the_followup_answer() -> None:
    field = _SCHEMA["properties"]["followup_answer"]
    assert field["enum"] == ["no", "yes_or_unsure", "unanswered", "not_pending"]
    assert "followup_answer" in _SCHEMA["required"]

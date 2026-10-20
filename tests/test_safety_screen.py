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
    _is_clear_no,
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
        (
            "None of those, but it smells stronger",
            True,
            "burning_followup",
            "emergency",
        ),
        ("No, but now there is smoke", True, "burning_followup", "emergency"),
        ("No smoke, but I see sparks", True, "burning_followup", "emergency"),
        ("No, it's getting hotter", True, "burning_followup", "emergency"),
        ("No, the breaker tripped", True, "burning_followup", "emergency"),
        ("No, there's still a smell", True, "safe", "emergency"),
        ("Nope", True, "burning_followup", "safe"),
        ("No sir", True, "burning_followup", "safe"),
        ("Not at all", True, "burning_followup", "safe"),
        ("Nah", True, "burning_followup", "safe"),
        ("Nothing like that", True, "burning_followup", "safe"),
        ("No, no smoke or sparks.", True, "burning_followup", "safe"),
        (
            "No smoke, no sparks, and no tripped breaker.",
            True,
            "burning_followup",
            "safe",
        ),
        ("No smoke, sparks, or tripped breaker.", True, "burning_followup", "safe"),
        ("No smoke, sparks everywhere", True, "burning_followup", "emergency"),
        ("No smoke, and sparks", True, "burning_followup", "emergency"),
        ("Nope, no smoke", True, "burning_followup", "safe"),
        ("No, sparks", True, "burning_followup", "emergency"),
        # A clear no followed only by a restatement of the problem is still a clear no.
        ("No, nothing like that. Just warm air.", True, "burning_followup", "safe"),
        ("No. The AC is just blowing warm air.", True, "burning_followup", "safe"),
        ("Nope, it just won't cool the house", True, "burning_followup", "safe"),
        (
            "No, nothing like that. The AC just runs but the air is warm.",
            True,
            "burning_followup",
            "safe",
        ),
        ("No, but the breaker keeps tripping", True, "burning_followup", "emergency"),
        (
            "No, nothing like that. Can someone come out to look at it?",
            True,
            "burning_followup",
            "safe",
        ),
        ("No? I don't know", True, "burning_followup", "emergency"),
        (
            "No, no smoke or smells. Can someone come out? I'm Hannah Rivera, 512-651-1296.",
            True,
            "burning_followup",
            "safe",
        ),
        ("No smoke, smells", True, "burning_followup", "emergency"),
        ("No smoke, sparks", True, "burning_followup", "emergency"),
        ("No sparks, smoke!", True, "burning_followup", "emergency"),
        ("No smoke, sparks or fire", True, "burning_followup", "safe"),
        ("No smoke, but it smells", True, "burning_followup", "emergency"),
        ("No. Is a burning smell bad?", True, "burning_followup", "emergency"),
        ("No, the furnace just won't start", True, "burning_followup", "safe"),
        # Anything risky, hedged or contrasted after the no stays an emergency.
        (
            "No, just warm air but it smells a bit",
            True,
            "burning_followup",
            "emergency",
        ),
        (
            "No, just warm air. I think I smell gas",
            True,
            "burning_followup",
            "emergency",
        ),
        ("No, not sure though", True, "burning_followup", "emergency"),
        ("No, maybe a little smoke", True, "burning_followup", "emergency"),
        ("No, it is buzzing and hot", True, "burning_followup", "emergency"),
        ("No, the outlet sparked earlier", True, "burning_followup", "emergency"),
        ("No, I can't tell", True, "burning_followup", "emergency"),
        ("Just warm air, no", True, "burning_followup", "emergency"),
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


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("No burning smell or anything like that.", True),
        (
            "No burning smell or anything like that. I'm Grace Okafor, 512-555-0103.",
            True,
        ),
        (
            (
                "No, there is no smoke, smell, or sparks, and no tripped breaker. "
                "It is just warm air."
            ),
            True,
        ),
        (
            "No burning smell or anything like that. Can someone come out to look at it?",
            True,
        ),
        ("No smoke, sparks", False),
        ("not that I know of", False),
        ("No smoke but I smell burning", False),
        ("no sparks, just smoke", False),
        ("I don't think so", False),
        ("No, but the breaker tripped", False),
        ("No burning smell or anything like that, but sparks", False),
        ("There is smoke", False),
        ("No, there is smoke", False),
    ],
)
def test_s52_more_clear_nos(text: str, expected: bool) -> None:
    assert _is_clear_no(text) is expected


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
        ("How hot does the compressor get?", "unanswered"),  # a _RISKY word
        ("okay, let's schedule it.", "yes_or_unsure"),
        ("okay, let's schedule it.", "no"),
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
        ("not that I know of", ("safe", "no_hazard", "no"), "followup_not_clear_no"),
        (
            "No smoke, sparks",
            ("burning_followup", "burning_smell", "no"),
            "followup_not_clear_no",
        ),
        ("okay, let's schedule it.", ("emergency", "smoke", "unanswered"), "smoke"),
        ("No", ("emergency", "smoke", "no"), "smoke"),
    ],
)
def test_s52_model_never_makes_it_safe(
    tmp_settings: Settings, text: str, reply: tuple[str, str, str], expected: str
) -> None:
    ctx = _ctx(tmp_settings, FakeClassifier(*reply))
    v = screen_safety(ctx, text, ASKED, True)
    assert (v.verdict, v.reason) == ("emergency", expected)


def test_s52_schema_asks_for_the_followup_answer() -> None:
    field = _SCHEMA["properties"]["followup_answer"]
    assert field["enum"] == ["no", "yes_or_unsure", "unanswered", "not_pending"]
    assert "followup_answer" in _SCHEMA["required"]

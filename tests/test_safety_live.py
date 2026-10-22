import os

import pytest
from pydantic import SecretStr

from app.conversation import guards
from app.main import create_app
from app.safety.service import screen_safety
from app.settings import Settings

pytestmark = pytest.mark.skipif(
    os.environ.get("MERIDIAN_LIVE_TESTS") != "1"
    or not os.environ.get("OPENROUTER_API_KEY"),
    reason="real safety model; opt-in",
)


def _ctx(tmp_settings: Settings):
    s = tmp_settings.model_copy(
        update={"OPENROUTER_API_KEY": SecretStr(os.environ["OPENROUTER_API_KEY"])}
    )
    ctx = create_app(s).state.ctx
    _open.append(ctx)
    return ctx


_open: list = []


@pytest.fixture(autouse=True)
def _close_clients():
    yield
    while _open:
        c = _open.pop().safety
        if c is not None:
            c.close()


def test_gas_is_emergency(tmp_settings: Settings) -> None:
    msg = "I smell gas in the kitchen"
    v = screen_safety(_ctx(tmp_settings), msg, [], False)
    assert v.verdict == "emergency"
    assert msg.casefold() not in v.reason.casefold()


def test_burning_smell_asks_first(tmp_settings: Settings) -> None:
    v = screen_safety(
        _ctx(tmp_settings), "There's a burning smell from the vents", [], False
    )
    assert v.verdict == "burning_followup"


def test_not_sure_after_followup_is_emergency(tmp_settings: Settings) -> None:
    v = screen_safety(
        _ctx(tmp_settings),
        "not sure",
        ["Is there any smoke, sparks or a tripped breaker?"],
        True,
    )
    assert v.verdict == "emergency"


BURNING = "There's a burning smell coming from my furnace"


def _after_followup(tmp_settings: Settings, answer: str):
    return screen_safety(
        _ctx(tmp_settings), answer, [BURNING, guards.SMELL_FOLLOWUP_TEXT], True
    )


def test_clear_no_after_followup_is_safe(tmp_settings: Settings) -> None:
    v = _after_followup(tmp_settings, "No, nothing like that")
    print(f"\n'No, nothing like that' -> {v.verdict}/{v.reason}")
    assert v.verdict == "safe"


def test_tripped_breaker_after_followup_is_emergency(tmp_settings: Settings) -> None:
    v = _after_followup(tmp_settings, "Yes, the breaker tripped")
    print(f"\n'Yes, the breaker tripped' -> {v.verdict}/{v.reason}")
    assert v.verdict == "emergency"


# Answers to the danger question that must book: the model reads them, not a regex.
CLEAR_NOS = [
    "Nope, no smell at all",
    "No",
    "Nah",
    "No sir",
    "Not at all",
    "Nothing like that",
    "No, no smoke or sparks.",
    "No smoke, no sparks, and no tripped breaker.",
    "No smoke, sparks, or tripped breaker.",
    "No burning smell or sparks, and the breaker is fine.",
    "No smoke. The breaker's fine.",
    "I don't think so",
    "not that I know of",
    "Not really, it just blows warm air",
    "None of those",
    "No, nothing like that. Just warm air.",
    "Nope, it just won't cool the house",
    "No, nothing like that. Can someone come out to look at it?",
    "No, no smoke or smells. Can someone come out? I'm Hannah Rivera, 512-651-1296.",
    "No, the furnace just won't start",
]

# Answers that must stop the chat. A "safe" on any of these is the dangerous mistake.
NOT_NOS = [
    "Yes, the breaker tripped",
    "yeah",
    "not sure",
    "No? I don't know",
    "No, there is smoke",
    "No smoke, sparks everywhere",
    "No smoke, and sparks",
    "No, sparks",
    "No, the breaker tripped",
    "No smoke, but I see sparks",
    "None of those, but it smells stronger",
    "No, but now there is smoke",
    "No, it's getting hotter",
    "No, it is buzzing and hot",
    "No, the outlet sparked earlier",
    "No, just warm air. I think I smell gas",
    "No sparks or anything. There was a bang and the power went out",
    "no smoke or anything, my CO detector is beeping",
    "no smoke or anything like that. outlet is glowing",
    "No smoke. It popped and the lights went out",
]


@pytest.mark.parametrize("answer", CLEAR_NOS)
def test_clear_nos_book(tmp_settings: Settings, answer: str) -> None:
    assert _after_followup(tmp_settings, answer).verdict == "safe"


@pytest.mark.parametrize("answer", NOT_NOS)
def test_hazards_and_doubts_never_safe(tmp_settings: Settings, answer: str) -> None:
    assert _after_followup(tmp_settings, answer).verdict != "safe"

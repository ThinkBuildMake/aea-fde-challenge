import os

import pytest
from pydantic import SecretStr

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
    return create_app(s).state.ctx


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

"""The cancel-confirm model on labelled replies to the cancel terms (opt-in, real model)."""

import os

import pytest
from pydantic import SecretStr

from app.conversation import confirm
from app.main import create_app
from app.settings import Settings

pytestmark = pytest.mark.skipif(
    os.environ.get("MERIDIAN_LIVE_TESTS") != "1"
    or not os.environ.get("OPENROUTER_API_KEY"),
    reason="real confirm model; opt-in",
)

ASK = (
    "Cancelling now carries the $49 late-cancellation fee. Do you want me to cancel it?"
)

# Replies that must cancel: the model reads them, not a regex.
YESES = [
    "Yes",
    "Yes, cancel it",
    "yes please",
    "Sure, go ahead.",
    "OK, cancel it",
    "Confirm",
    "Please cancel it.",
    "Yes, that works for me",
    "Yes please, thanks so much",
    "Sounds good, go ahead",
    "Yeah I'm fine with the fee",
    "I accept the fee, please go ahead and cancel it. That is all.",
    "That's fine, I'll pay the $49. Yes, cancel it.",
    "Understood about the fee. Go ahead and cancel.",
    "Sure, go ahead and cancel it, thanks",
    "Yep, just cancel it. I'll rebook later.",
    "Go for it",
    "Cancel my visit",
]

# Replies that must not cancel. A cancel on any of these is the costly mistake.
NOT_YESES = [
    "don't I need to give 48 hours notice?",
    "Can you waive the $49?",
    "ok but only if there's no fee",
    "I'm not sure",
    "Maybe I'll cancel, I'm not sure",
    "Yes? What does it cost?",
    "What is the fee?",
    "The fee is too high.",
    "I don't accept the fee.",
    "Is there a fee? Cancel it.",
    "Let me check with my wife first, ok",
    "I'll call back later, ok bye",
    "Hmm, ok",
    "No",
    "No thanks",
    "Never mind",
    "Actually no, I'll just be there",
    "Yes I would like you to cancel it but only if you can make sure there is no charge",
]


@pytest.fixture
def ctx(tmp_settings: Settings, capsys: pytest.CaptureFixture[str]):
    s = tmp_settings.model_copy(
        update={"OPENROUTER_API_KEY": SecretStr(os.environ["OPENROUTER_API_KEY"])}
    )
    ctx = create_app(s).state.ctx
    yield ctx
    if ctx.confirm is not None:
        ctx.confirm.close()
    # A failed call reads as "no", so it would pass a not-yes case for the wrong reason.
    assert "cancel_confirm_failed" not in capsys.readouterr().out


@pytest.mark.parametrize("text", YESES)
def test_yeses_cancel(ctx, text: str) -> None:
    assert confirm.accepts_cancel(ctx, text, ASK) is True


@pytest.mark.parametrize("text", NOT_YESES)
def test_anything_else_never_cancels(ctx, text: str) -> None:
    assert confirm.accepts_cancel(ctx, text, ASK) is False

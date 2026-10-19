from app.context import AppContext
from app.types import RedactResult, Verdict


class ScreenUnavailable(Exception):
    """The safety screen timed out or the provider failed."""


def redact_card_numbers(text: str) -> RedactResult:
    """Stub: identity."""
    return RedactResult(text=text, removed=False)


def screen_safety(
    ctx: AppContext, text: str, recent_turns: list[str], follow_up_pending: bool
) -> Verdict:
    """Stub: everything is safe."""
    return Verdict(verdict="safe", reason="stub")

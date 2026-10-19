import sqlite3

from app.context import AppContext
from app.types import (
    CallbackWindow,
    HandoffCaller,
    HandoffRecord,
    HandoffView,
    HeldWindow,
    JoinWaitlistResult,
    WaitlistCaller,
    WaitlistRequest,
    WaitlistView,
)


class NoHandoff(Exception):
    """The conversation has no handoff."""


def placeholder_handoff(
    conversation_public_id: str = "stub", window: CallbackWindow | None = None
) -> HandoffView:
    return HandoffView(
        id=0,
        conversation_public_id=conversation_public_id,
        kind="handoff",
        reason="stub",
        by_error=False,
        caller=HandoffCaller(
            customer_id=None,
            name=None,
            phone=None,
            city=None,
            zone=None,
            stated_by_caller=False,
        ),
        intent="unknown",
        told_caller="stub",
        summary="stub: stub",
        summary_source="system",
        preferred_window=window,
        status="open",
        created_at="1970-01-01T00:00:00.000Z",
        followed_up_at=None,
    )


def create_handoff(tx: sqlite3.Connection, record: HandoffRecord) -> HandoffView:
    return placeholder_handoff()


def set_callback_window(
    ctx: AppContext, conversation_id: str, window: CallbackWindow
) -> HandoffView:
    return placeholder_handoff(window=window)


def join_waitlist(ctx: AppContext, entry: WaitlistRequest) -> JoinWaitlistResult:
    view = WaitlistView(
        id=0,
        conversation_public_id="stub",
        caller=WaitlistCaller(
            customer_id=entry.customer_id, name="stub", phone="stub", city="stub"
        ),
        service_type=entry.service_type,
        zone=entry.zone,
        held=HeldWindow(date=entry.held_date, window=entry.held_window),
        created_at="1970-01-01T00:00:00.000Z",
        waiting_seconds=0,
    )
    return JoinWaitlistResult(entry=view, created=False)

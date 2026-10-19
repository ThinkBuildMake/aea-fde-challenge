import sqlite3
from collections.abc import Iterator
from typing import Any

import pytest

from app.context import AppContext
from app.db import connect_app_db
from app.followups.service import (
    HandoffNotFound,
    NoHandoff,
    create_handoff,
    list_handoffs,
    mark_handoff_followed_up,
    set_callback_window,
)
from app.llm import FakeModelProvider
from app.main import create_app
from app.settings import Settings
from app.types import HandoffRecord

TOLD = "I will pass this to a supervisor."


@pytest.fixture
def ctx(started: Settings) -> AppContext:
    return create_app(started, model=FakeModelProvider()).state.ctx


@pytest.fixture
def conn(ctx: AppContext) -> Iterator[sqlite3.Connection]:
    connection = ctx.open_app_db()
    connection.execute(
        "INSERT INTO conversations (id, customer_id, intent) "
        "VALUES ('c1', 'MHC-10002', 'billing_lookup')"
    )
    yield connection
    connection.close()


def record(**changes: Any) -> HandoffRecord:
    fields: dict[str, Any] = {
        "conversation_id": "c1",
        "kind": "handoff",
        "reason": "billing_dispute",
        "by_error": False,
        "customer_id": "MHC-10002",
        "intent": "billing_lookup",
        "told_caller": TOLD,
    }
    return HandoffRecord(**{**fields, **changes})


def make(conn: sqlite3.Connection, ctx: AppContext, rec: HandoffRecord):
    conn.execute("BEGIN")
    try:
        view = create_handoff(conn, rec, ctx)
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
    return view


def count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM handoffs").fetchone()[0]


def test_handoff_carries_the_full_record(conn: sqlite3.Connection, ctx: AppContext):
    view = make(conn, ctx, record(kind="supervisor_callback"))
    row = conn.execute(
        "SELECT kind, reason, intent, told_caller, customer_id, caller_name, "
        "caller_phone, stated_by_caller, by_error FROM handoffs"
    ).fetchone()
    assert tuple(row) == (
        "supervisor_callback",
        "billing_dispute",
        "billing_lookup",
        TOLD,
        "MHC-10002",
        "Omar Patel",
        "512-555-0102",
        0,
        0,
    )
    assert view.caller.city == "Kyle" and view.caller.zone == "south"
    assert view.summary == f"billing_dispute: {TOLD}"
    assert view.by_error is False


def test_dispute_reasons_become_supervisor_callbacks(
    conn: sqlite3.Connection, ctx: AppContext
):
    assert make(conn, ctx, record()).kind == "supervisor_callback"


def test_second_handoff_returns_the_first_unchanged(
    conn: sqlite3.Connection, ctx: AppContext
):
    first = make(conn, ctx, record())
    second = make(conn, ctx, record(reason="complaint", told_caller="other"))
    assert second == first and second.reason == "billing_dispute"
    assert count(conn) == 1


def test_unmatched_caller_keeps_stated_contact(
    conn: sqlite3.Connection, ctx: AppContext
):
    view = make(
        conn,
        ctx,
        record(
            customer_id=None,
            reason="no_account_match",
            stated_name="Sam",
            stated_phone="512-555-0000",
        ),
    )
    assert (view.caller.name, view.caller.phone) == ("Sam", "512-555-0000")
    assert view.caller.stated_by_caller is True


@pytest.mark.parametrize("field", ["reason", "told_caller"])
def test_empty_fields_are_refused(conn: sqlite3.Connection, ctx: AppContext, field):
    with pytest.raises(sqlite3.IntegrityError):
        make(conn, ctx, record(**{field: ""}))
    assert count(conn) == 0


def test_empty_intent_is_stored_as_unknown(conn: sqlite3.Connection, ctx: AppContext):
    assert make(conn, ctx, record(intent="")).intent == "unknown"


def test_by_error_marks_failure_handoffs(conn: sqlite3.Connection, ctx: AppContext):
    view = make(conn, ctx, record(reason="provider_failure", by_error=True))
    assert view.by_error is True
    assert conn.execute("SELECT by_error FROM handoffs").fetchone()[0] == 1


class Failing:
    """Delegates to a real connection but fails on statements containing a marker."""

    def __init__(self, real: sqlite3.Connection, marker: str):
        self.real, self.marker = real, marker

    def execute(self, sql: str, *args: Any):
        if self.marker in sql:
            raise sqlite3.OperationalError("disk I/O error")
        return self.real.execute(sql, *args)

    def close(self) -> None:
        self.real.close()


def test_failed_write_leaves_nothing(conn: sqlite3.Connection, ctx: AppContext):
    wrapper: Any = Failing(conn, "JOIN conversations")
    conn.execute("BEGIN")
    with pytest.raises(sqlite3.OperationalError):
        create_handoff(wrapper, record(), ctx)
    conn.execute("ROLLBACK")
    assert count(conn) == 0


def add_turn(conn: sqlite3.Connection, seq: int, fallback: int, error: str | None):
    conn.execute(
        "INSERT INTO turns (conversation_id, seq, caller_text, reply_text, "
        "latency_ms, error, fallback_used) VALUES ('c1', ?, 'hi', 'Sorry, trouble.', 5, ?, ?)",
        (seq, error, fallback),
    )


def test_set_window_without_handoff_raises_no_handoff(
    conn: sqlite3.Connection, ctx: AppContext
):
    add_turn(conn, 1, 0, None)
    with pytest.raises(NoHandoff):
        set_callback_window(ctx, "c1", "morning")
    assert count(conn) == 0


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        ("provider_timeout", "provider_failure"),
        ("scheduling_unavailable", "scheduling_unavailable"),
    ],
)
def test_fallback_creates_a_by_error_handoff(
    conn: sqlite3.Connection, ctx: AppContext, error: str, reason: str
):
    add_turn(conn, 1, 1, error)
    view = set_callback_window(ctx, "c1", "morning")
    assert (view.reason, view.by_error, view.preferred_window) == (
        reason,
        True,
        "morning",
    )
    assert view.summary_source == "system" and view.caller.name == "Omar Patel"
    assert conn.execute("SELECT outcome FROM conversations").fetchone()[0] == "handoff"


def test_failed_fallback_write_leaves_nothing(
    conn: sqlite3.Connection, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
):
    add_turn(conn, 1, 1, "provider_timeout")
    real_open = ctx.open_app_db
    monkeypatch.setattr(
        ctx, "open_app_db", lambda: Failing(real_open(), "UPDATE handoffs")
    )
    with pytest.raises(sqlite3.OperationalError):
        set_callback_window(ctx, "c1", "morning")
    check = connect_app_db(ctx.settings.APP_DB_PATH)
    assert check.execute("SELECT COUNT(*) FROM handoffs").fetchone()[0] == 0
    assert check.execute("SELECT outcome FROM conversations").fetchone()[0] is None
    check.close()


def seed(conn: sqlite3.Connection, cid: str, created_at: str, status: str = "open"):
    conn.execute("INSERT INTO conversations (id) VALUES (?)", (cid,))
    conn.execute(
        "INSERT INTO handoffs (conversation_id, kind, reason, intent, told_caller, "
        "status, created_at) VALUES (?, 'handoff', 'r', 'i', 't', ?, ?)",
        (cid, status, created_at),
    )


def test_list_handoffs_by_status_oldest_first(
    conn: sqlite3.Connection, ctx: AppContext
):
    seed(conn, "n1", "2026-01-02T00:00:00.000Z")
    seed(conn, "n2", "2026-01-01T00:00:00.000Z")
    seed(conn, "n3", "2026-01-03T00:00:00.000Z", "followed_up")
    open_ = list_handoffs(ctx, "open")
    assert [h.created_at for h in open_] == [
        "2026-01-01T00:00:00.000Z",
        "2026-01-02T00:00:00.000Z",
    ]
    assert len(list_handoffs(ctx, "followed_up")) == 1


def test_mark_followed_up_then_again_then_undo(
    conn: sqlite3.Connection, ctx: AppContext
):
    seed(conn, "n1", "2026-01-01T00:00:00.000Z")
    hid = conn.execute("SELECT id FROM handoffs").fetchone()[0]
    first = mark_handoff_followed_up(ctx, hid, True)
    assert first.status == "followed_up" and first.followed_up_at is not None
    again = mark_handoff_followed_up(ctx, hid, True)
    assert again.followed_up_at == first.followed_up_at
    undone = mark_handoff_followed_up(ctx, hid, False)
    assert undone.status == "open" and undone.followed_up_at is None


def test_mark_unknown_handoff_raises(ctx: AppContext):
    with pytest.raises(HandoffNotFound):
        mark_handoff_followed_up(ctx, 9999, True)

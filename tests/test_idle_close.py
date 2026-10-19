import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

from app.context import AppContext
from app.conversation.service import close_idle_conversations
from app.db import connect_app_db
from app.llm import FakeModelProvider
from app.main import create_app
from app.settings import Settings

NOW = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)


def stamp(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


@pytest.fixture
def ctx(started: Settings) -> AppContext:
    return create_app(started, model=FakeModelProvider()).state.ctx


@pytest.fixture
def conn(started: Settings) -> Iterator[sqlite3.Connection]:
    connection = connect_app_db(started.APP_DB_PATH)
    yield connection
    connection.close()


def idle(ctx: AppContext) -> datetime:
    return NOW - timedelta(minutes=ctx.settings.IDLE_CLOSE_MINUTES + 1)


def add(
    conn: sqlite3.Connection,
    cid: str,
    last: datetime,
    turns: int = 1,
    resolved: bool = False,
    handoff: bool = False,
) -> None:
    conn.execute(
        "INSERT INTO conversations (id, last_activity_at, turn_count, resolved_at) "
        "VALUES (?, ?, ?, ?)",
        (cid, stamp(last), turns, stamp(last) if resolved else None),
    )
    if handoff:
        conn.execute(
            "INSERT INTO handoffs (conversation_id, kind, reason, intent, told_caller) "
            "VALUES (?, 'callback', 'r', 'i', 't')",
            (cid,),
        )


def row(conn: sqlite3.Connection, cid: str) -> tuple[str | None, str | None, str | None]:
    found = conn.execute(
        "SELECT outcome, outcome_reason, ended_at FROM conversations WHERE id = ?",
        (cid,),
    ).fetchone()
    return found[0], found[1], found[2]


def test_idle_resolved_without_handoff_is_contained(ctx, conn):
    add(conn, "c1", idle(ctx), resolved=True)
    assert close_idle_conversations(ctx, NOW) == 1
    outcome, reason, ended_at = row(conn, "c1")
    assert (outcome, reason) == ("contained", None)
    assert ended_at is not None and ended_at.endswith("Z")


def test_idle_unresolved_is_failed_idle_unresolved(ctx, conn):
    add(conn, "c1", idle(ctx))
    add(conn, "c2", idle(ctx), resolved=True, handoff=True)
    close_idle_conversations(ctx, NOW)
    assert row(conn, "c1")[:2] == ("failed", "idle_unresolved")
    assert row(conn, "c2")[:2] == ("failed", "idle_unresolved")


def test_idle_without_message_is_failed_no_message(ctx, conn):
    add(conn, "c1", idle(ctx), turns=0)
    add(conn, "c2", idle(ctx), turns=0, resolved=True)
    close_idle_conversations(ctx, NOW)
    assert row(conn, "c1")[:2] == ("failed", "no_message")
    assert row(conn, "c2")[:2] == ("failed", "no_message")


def test_ended_conversation_is_left_alone_and_sweep_is_twice_safe(ctx, conn):
    hour_ago = NOW - timedelta(hours=1)
    add(conn, "c1", hour_ago, resolved=True, handoff=True)
    conn.execute(
        "UPDATE conversations SET outcome = 'handoff', ended_at = ? WHERE id = 'c1'",
        (stamp(hour_ago),),
    )
    before = row(conn, "c1")
    assert close_idle_conversations(ctx, NOW) == 0
    assert row(conn, "c1") == before
    assert close_idle_conversations(ctx, NOW) == 0
    assert row(conn, "c1") == before


def test_ob1_no_idle_conversation_left_without_outcome(ctx, conn):
    add(conn, "resolved", idle(ctx), resolved=True)
    add(conn, "unresolved", idle(ctx))
    add(conn, "empty", idle(ctx), turns=0)
    add(conn, "ended", idle(ctx))
    conn.execute(
        "UPDATE conversations SET outcome = 'safety_stop', ended_at = ? "
        "WHERE id = 'ended'",
        (stamp(idle(ctx)),),
    )
    add(conn, "active", NOW - timedelta(minutes=1))
    assert close_idle_conversations(ctx, NOW) == 3
    left = conn.execute(
        "SELECT count(*) FROM conversations WHERE outcome IS NULL AND last_activity_at < ?",
        (stamp(NOW - timedelta(minutes=ctx.settings.IDLE_CLOSE_MINUTES)),),
    ).fetchone()[0]
    assert left == 0
    for cid in ("resolved", "unresolved", "empty"):
        assert row(conn, cid)[2] == stamp(NOW)
    assert row(conn, "active") == (None, None, None)

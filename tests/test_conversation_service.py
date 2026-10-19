import sqlite3
from collections.abc import Iterator

import pytest

from app.conversation.service import end_with_handoff
from app.db import connect_app_db
from app.settings import Settings


@pytest.fixture
def conn(started: Settings) -> Iterator[sqlite3.Connection]:
    connection = connect_app_db(started.APP_DB_PATH)
    connection.execute("INSERT INTO conversations (id) VALUES ('c1')")
    yield connection
    connection.close()


def row(conn: sqlite3.Connection) -> tuple[str | None, str | None]:
    found = conn.execute(
        "SELECT outcome, ended_at FROM conversations WHERE id = 'c1'"
    ).fetchone()
    return found[0], found[1]


def test_end_with_handoff_twice_in_one_transaction(conn: sqlite3.Connection):
    conn.execute("BEGIN")
    end_with_handoff(conn, "c1")
    first = row(conn)
    end_with_handoff(conn, "c1")
    conn.execute("COMMIT")
    outcome, ended_at = row(conn)
    assert outcome == "handoff"
    assert ended_at is not None and ended_at.endswith("Z")
    assert (outcome, ended_at) == first


def test_end_with_handoff_never_changes_an_existing_outcome(conn: sqlite3.Connection):
    conn.execute(
        "UPDATE conversations SET outcome = 'contained', "
        "ended_at = '2026-01-01T00:00:00.000Z' WHERE id = 'c1'"
    )
    conn.execute("BEGIN")
    end_with_handoff(conn, "c1")
    conn.execute("COMMIT")
    assert row(conn) == ("contained", "2026-01-01T00:00:00.000Z")

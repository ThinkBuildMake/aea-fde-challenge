import sqlite3
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.llm import FakeModelProvider
from app.main import create_app
from app.settings import Settings


@pytest.fixture
def client(started: Settings) -> TestClient:
    return TestClient(create_app(started, model=FakeModelProvider()))


@pytest.fixture
def db(started: Settings) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(started.APP_DB_PATH, isolation_level=None)
    yield conn
    conn.close()


def new_conversation(client: TestClient, db: sqlite3.Connection) -> str:
    cid = client.post("/conversations").json()["conversationId"]
    db.execute(
        "UPDATE conversations SET customer_id = 'MHC-10002' WHERE id = ?", (cid,)
    )
    return cid


def seed_handoff(db: sqlite3.Connection, cid: str) -> None:
    db.execute(
        "INSERT INTO handoffs (conversation_id, kind, reason, intent, told_caller) "
        "VALUES (?, 'handoff', 'r', 'i', 't')",
        (cid,),
    )


def add_turn(db: sqlite3.Connection, cid: str, seq: int, fallback: int, error=None):
    db.execute(
        "INSERT INTO turns (conversation_id, seq, caller_text, reply_text, "
        "latency_ms, error, fallback_used) VALUES (?, ?, 'hi', 'Sorry.', 5, ?, ?)",
        (cid, seq, error, fallback),
    )


def window(db: sqlite3.Connection, cid: str):
    return db.execute(
        "SELECT preferred_window FROM handoffs WHERE conversation_id = ?", (cid,)
    ).fetchone()


def test_caller_picks_a_window(client: TestClient, db: sqlite3.Connection):
    cid = new_conversation(client, db)
    seed_handoff(db, cid)
    response = client.post(
        f"/conversations/{cid}/callback-window", json={"window": "evening"}
    )
    assert response.status_code == 200
    assert response.json()["handoff"]["preferredWindow"] == "evening"
    assert window(db, cid) == ("evening",)
    client.post(f"/conversations/{cid}/callback-window", json={"window": "morning"})
    assert window(db, cid) == ("morning",)


def test_bad_window_is_refused(client: TestClient, db: sqlite3.Connection):
    cid = new_conversation(client, db)
    seed_handoff(db, cid)
    response = client.post(
        f"/conversations/{cid}/callback-window", json={"window": "midnight"}
    )
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_window"
    assert window(db, cid) == (None,)


def test_no_handoff_no_window(client: TestClient, db: sqlite3.Connection):
    cid = new_conversation(client, db)
    add_turn(db, cid, 1, 1, "provider_timeout")
    add_turn(db, cid, 2, 0)
    response = client.post(
        f"/conversations/{cid}/callback-window", json={"window": "morning"}
    )
    assert response.status_code == 404
    assert response.json()["error"] == "no_handoff"
    assert db.execute("SELECT COUNT(*) FROM handoffs").fetchone() == (0,)


def test_no_turns_no_window(client: TestClient, db: sqlite3.Connection):
    cid = new_conversation(client, db)
    response = client.post(
        f"/conversations/{cid}/callback-window", json={"window": "morning"}
    )
    assert response.status_code == 404


def test_failure_driven_handoff_is_marked(client: TestClient, db: sqlite3.Connection):
    cid = new_conversation(client, db)
    add_turn(db, cid, 1, 1, "provider_timeout")
    response = client.post(
        f"/conversations/{cid}/callback-window", json={"window": "morning"}
    )
    assert response.status_code == 200
    assert db.execute(
        "SELECT reason, by_error, preferred_window FROM handoffs WHERE conversation_id = ?",
        (cid,),
    ).fetchone() == ("provider_failure", 1, "morning")


def test_unknown_conversation_is_404(client: TestClient):
    response = client.post(
        "/conversations/nope/callback-window", json={"window": "morning"}
    )
    assert response.status_code == 404
    assert response.json()["error"] == "conversation_not_found"

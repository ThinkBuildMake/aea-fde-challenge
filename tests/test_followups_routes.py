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


def seed_at(
    db: sqlite3.Connection,
    n: int,
    created_at: str,
    status: str = "open",
    followed_up_at: str | None = None,
) -> tuple[int, str]:
    cid = f"secret-conversation-{n}"
    db.execute("INSERT INTO conversations (id) VALUES (?)", (cid,))
    cur = db.execute(
        "INSERT INTO handoffs (conversation_id, kind, reason, intent, told_caller, "
        "status, created_at, followed_up_at) VALUES (?, 'handoff', 'r', 'i', 't', ?, ?, ?)",
        (cid, status, created_at, followed_up_at),
    )
    assert cur.lastrowid is not None
    return cur.lastrowid, cid


def seed_queue(db: sqlite3.Connection) -> list[tuple[int, str]]:
    return [
        seed_at(db, 1, "2026-01-02T00:00:00.000Z"),
        seed_at(db, 2, "2026-01-01T00:00:00.000Z"),
        seed_at(
            db, 3, "2026-01-03T00:00:00.000Z", "followed_up", "2026-01-04T00:00:00.000Z"
        ),
    ]


def test_open_queue_oldest_first(client: TestClient, db: sqlite3.Connection):
    (newer, _), (older, _), _ = seed_queue(db)
    response = client.get("/handoffs")
    assert response.status_code == 200
    handoffs = response.json()["handoffs"]
    assert [h["id"] for h in handoffs] == [older, newer]
    assert {h["status"] for h in handoffs} == {"open"}
    assert all(h["conversationPublicId"] for h in handoffs)
    assert "secret-conversation" not in response.text
    print([(h["id"], h["createdAt"]) for h in handoffs])


def test_followed_up_list(client: TestClient, db: sqlite3.Connection):
    seed_queue(db)
    response = client.get("/handoffs?status=followed_up")
    assert response.status_code == 200
    handoffs = response.json()["handoffs"]
    assert len(handoffs) == 1 and handoffs[0]["status"] == "followed_up"
    print(len(handoffs), handoffs[0]["status"])


def test_bad_status_is_refused(client: TestClient):
    response = client.get("/handoffs?status=done")
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_status"
    print(response.status_code, response.json()["error"])


def test_mark_followed_up(client: TestClient, db: sqlite3.Connection):
    hid, _ = seed_at(db, 1, "2026-01-01T00:00:00.000Z")
    response = client.post(f"/handoffs/{hid}/followed-up")
    assert response.status_code == 200
    handoff = response.json()["handoff"]
    assert handoff["status"] == "followed_up" and handoff["followedUpAt"]
    row = db.execute(
        "SELECT status, followed_up_at FROM handoffs WHERE id = ?", (hid,)
    ).fetchone()
    assert row[0] == "followed_up" and row[1]
    missing = client.post("/handoffs/9999/followed-up")
    assert missing.status_code == 404
    assert missing.json()["error"] == "handoff_not_found"
    print(handoff["status"], handoff["followedUpAt"], missing.status_code)


def test_marking_twice_changes_nothing(client: TestClient, db: sqlite3.Connection):
    stamp = "2026-01-01T00:00:00.000Z"
    hid, _ = seed_at(db, 1, stamp, "followed_up", stamp)
    response = client.post(f"/handoffs/{hid}/followed-up")
    assert response.status_code == 200
    assert response.json()["handoff"]["followedUpAt"] == stamp
    row = db.execute("SELECT followed_up_at FROM handoffs WHERE id = ?", (hid,))
    assert row.fetchone()[0] == stamp
    print(response.json()["handoff"]["followedUpAt"])


def test_undo(client: TestClient, db: sqlite3.Connection):
    stamp = "2026-01-01T00:00:00.000Z"
    hid, _ = seed_at(db, 1, stamp, "followed_up", stamp)
    response = client.post(f"/handoffs/{hid}/followed-up", json={"followedUp": False})
    assert response.status_code == 200
    handoff = response.json()["handoff"]
    assert handoff["status"] == "open" and handoff["followedUpAt"] is None
    row = db.execute(
        "SELECT status, followed_up_at FROM handoffs WHERE id = ?", (hid,)
    ).fetchone()
    assert tuple(row) == ("open", None)
    print(handoff["status"], handoff["followedUpAt"])

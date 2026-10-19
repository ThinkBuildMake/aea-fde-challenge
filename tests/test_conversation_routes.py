import re
import sqlite3
import uuid

import pytest
from fastapi.testclient import TestClient

from app.conversation.routes import GREETING
from app.llm import FakeModelProvider
from app.main import create_app
from app.settings import Settings

NOW = "strftime('%Y-%m-%dT%H:%M:%fZ','now')"
NO_TEXT = "Sorry that did not solve it. Would you like me to pass you to a person?"


@pytest.fixture
def client(started: Settings) -> TestClient:
    return TestClient(create_app(started, model=FakeModelProvider()))


@pytest.fixture
def db(started: Settings):
    conn = sqlite3.connect(started.APP_DB_PATH, isolation_level=None)
    yield conn
    conn.close()


def resolved(client: TestClient, db: sqlite3.Connection) -> str:
    cid = client.post("/conversations").json()["conversationId"]
    db.execute(f"UPDATE conversations SET resolved_at = {NOW} WHERE id = ?", (cid,))
    return cid


def solved(client: TestClient, cid: str, answer: str):
    return client.post(f"/conversations/{cid}/solved", json={"answer": answer})


def state(db: sqlite3.Connection, cid: str):
    return db.execute(
        "SELECT outcome, solved, solved_at, ended_at FROM conversations WHERE id = ?",
        (cid,),
    ).fetchone()


def test_start_conversation_returns_active_with_greeting_and_utc_started_at(
    client: TestClient, db: sqlite3.Connection
):
    response = client.post("/conversations")
    assert response.status_code == 201
    body = response.json()
    uuid.UUID(body["conversationId"])
    assert body["status"] == "active"
    assert body["greeting"] == GREETING
    assert isinstance(body["demoFaults"], bool)
    started_at = db.execute(
        "SELECT started_at FROM conversations WHERE id = ?", (body["conversationId"],)
    ).fetchone()[0]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z", started_at)


def test_yes_ends_resolved_conversation_as_contained(
    client: TestClient, db: sqlite3.Connection
):
    cid = resolved(client, db)
    response = solved(client, cid, "yes")
    assert response.status_code == 200
    assert response.json()["status"] == "ended"
    assert response.json()["saved"] is True
    outcome, answer, solved_at, ended_at = state(db, cid)
    assert (outcome, answer) == ("contained", "yes")
    assert solved_at.endswith("Z") and ended_at.endswith("Z")


def test_no_keeps_conversation_open_and_offers_a_person(
    client: TestClient, db: sqlite3.Connection
):
    cid = resolved(client, db)
    response = solved(client, cid, "no")
    assert response.status_code == 200
    assert response.json()["status"] == "active"
    assert response.json()["text"] == NO_TEXT
    outcome, answer, _, ended_at = state(db, cid)
    assert (outcome, answer, ended_at) == (None, "no", None)


@pytest.mark.parametrize("first", ["yes", "no"])
@pytest.mark.parametrize("second", ["yes", "no"])
def test_second_answer_is_already_answered(
    client: TestClient, db: sqlite3.Connection, first: str, second: str
):
    cid = resolved(client, db)
    solved(client, cid, first)
    response = solved(client, cid, second)
    assert response.status_code == 409
    assert response.json()["error"] == "already_answered"
    assert state(db, cid)[1] == first


def test_no_tap_after_a_handoff(client: TestClient, db: sqlite3.Connection):
    cid = resolved(client, db)
    db.execute(
        "INSERT INTO handoffs (conversation_id, kind, reason, intent, told_caller) "
        "VALUES (?, 'callback', 'r', 'i', 't')",
        (cid,),
    )
    db.execute(
        f"UPDATE conversations SET outcome = 'handoff', ended_at = {NOW} WHERE id = ?",
        (cid,),
    )
    response = solved(client, cid, "yes")
    assert response.status_code == 409
    assert response.json()["error"] == "conversation_ended"
    outcome, answer, _, _ = state(db, cid)
    assert (outcome, answer) == ("handoff", None)


def test_only_yes_or_no(client: TestClient, db: sqlite3.Connection):
    cid = resolved(client, db)
    response = solved(client, cid, "maybe")
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_answer"
    assert state(db, cid) == (None, None, None, None)


def test_unknown_conversation_is_404(client: TestClient):
    response = solved(client, str(uuid.uuid4()), "yes")
    assert response.status_code == 404
    assert response.json()["error"] == "conversation_not_found"


def test_ob1_solved_answer_and_outcome_are_recorded(
    client: TestClient, db: sqlite3.Connection
):
    yes_id = resolved(client, db)
    solved(client, yes_id, "yes")
    outcome, answer, solved_at, ended_at = state(db, yes_id)
    assert (outcome, answer) == ("contained", "yes")
    assert solved_at and ended_at

    no_id = resolved(client, db)
    solved(client, no_id, "no")
    _, answer, solved_at, _ = state(db, no_id)
    assert answer == "no" and solved_at

    refused = resolved(client, db)
    assert solved(client, refused, "maybe").status_code == 422
    assert state(db, refused) == (None, None, None, None)
    assert solved(client, yes_id, "no").status_code == 409
    assert state(db, yes_id)[:2] == ("contained", "yes")

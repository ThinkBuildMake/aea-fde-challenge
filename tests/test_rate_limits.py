import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.conversation.guards import TURN_CAP_TEXT
from app.evals.runner import Worker
from app.llm import FakeModelProvider
from app.main import create_app
from app.settings import Settings

HIGH = 10**6


def make_client(
    settings: Settings, model: FakeModelProvider | None = None, **caps: int
) -> TestClient:
    base = {
        "NEW_CONVERSATIONS_PER_HOUR": HIGH,
        "MESSAGES_PER_MINUTE": HIGH,
        "BUSINESS_WRITES_PER_MINUTE": HIGH,
    }
    tuned = settings.model_copy(update={**base, **caps})
    return TestClient(create_app(tuned, model=model or FakeModelProvider()))


@pytest.fixture
def db(started: Settings) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(started.APP_DB_PATH, isolation_level=None)
    yield conn
    conn.close()


def start(client: TestClient, **headers: str) -> str:
    return client.post("/conversations", headers=headers).json()["conversationId"]


def send(client: TestClient, cid: str, text: str = "hello", **headers: str):
    return client.post(
        f"/conversations/{cid}/messages", json={"text": text}, headers=headers
    )


def turns(db: sqlite3.Connection, cid: str) -> int:
    return db.execute(
        "SELECT COUNT(*) FROM turns WHERE conversation_id = ?", (cid,)
    ).fetchone()[0]


def test_sixth_message_in_a_minute_is_rate_limited(started: Settings):
    model = FakeModelProvider(replies=["Sure."])
    client = make_client(started, model, MESSAGES_PER_MINUTE=5)
    cid = start(client)
    xff = {"X-Forwarded-For": "198.51.100.7"}

    codes = [send(client, cid, **xff).status_code for _ in range(5)]
    calls = len(model.received)
    sixth = send(client, cid, **xff)

    assert codes == [200] * 5
    assert sixth.status_code == 429
    assert sixth.json()["error"] == "rate_limited"
    assert len(model.received) == calls
    spoofed = send(client, cid, **{"X-Forwarded-For": "203.0.113.9, 198.51.100.7"})
    assert spoofed.status_code == 429
    other = send(client, cid, **{"X-Forwarded-For": "198.51.100.7, 203.0.113.9"})
    assert other.status_code == 200


def test_fourth_new_conversation_is_rate_limited(
    started: Settings, db: sqlite3.Connection
):
    client = make_client(started, NEW_CONVERSATIONS_PER_HOUR=3)

    codes = [client.post("/conversations").status_code for _ in range(3)]
    fourth = client.post("/conversations")

    assert codes == [201] * 3
    assert fourth.status_code == 429
    assert fourth.json()["error"] == "rate_limited"
    assert db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 3


def test_turn_cap_ends_conversation_failed_turn_cap(
    started: Settings, db: sqlite3.Connection
):
    model = FakeModelProvider(replies=["Sure."])
    client = make_client(started, model, TURN_CAP=4)
    cid = start(client)
    replies = [send(client, cid) for _ in range(4)]
    calls = len(model.received)

    fifth = send(client, cid)

    assert [r.status_code for r in replies] == [200] * 4
    assert all(TURN_CAP_TEXT not in r.json()["text"] for r in replies[:3])
    assert replies[3].json()["text"].endswith(TURN_CAP_TEXT)
    assert TURN_CAP_TEXT == (
        "This conversation has reached its limit. "
        "Please start a new conversation, or ask for a call back."
    )
    assert fifth.status_code == 409
    assert fifth.json()["error"] == "turn_limit_reached"
    outcome, reason, ended_at = db.execute(
        "SELECT outcome, outcome_reason, ended_at FROM conversations WHERE id = ?",
        (cid,),
    ).fetchone()
    assert (outcome, reason) == ("failed", "turn_cap")
    assert ended_at is not None
    assert len(model.received) == calls
    assert turns(db, cid) == 4


def test_message_one_over_the_cap_is_413(started: Settings, db: sqlite3.Connection):
    client = make_client(started)
    cid = start(client)

    response = send(client, cid, "a" * (started.MESSAGE_MAX_CHARS + 1))

    assert response.status_code == 413
    assert response.json()["error"] == "message_too_long"
    assert turns(db, cid) == 0


def test_message_at_the_cap_is_accepted(started: Settings):
    client = make_client(started)
    cid = start(client)

    response = send(client, cid, "a" * started.MESSAGE_MAX_CHARS)

    assert response.status_code == 200


@pytest.mark.parametrize("text", ["   ", "\n\t "])
def test_blank_message_is_422_empty_message(started: Settings, text: str):
    model = FakeModelProvider()
    client = make_client(started, model)
    cid = start(client)

    response = send(client, cid, text)

    assert response.status_code == 422
    assert response.json()["error"] == "empty_message"
    assert model.received == []


def test_business_writes_share_one_per_address_cap(
    started: Settings, db: sqlite3.Connection
):
    client = make_client(started, BUSINESS_WRITES_PER_MINUTE=2)
    cid = start(client)
    db.execute(
        "UPDATE conversations SET outcome = 'failed', ended_at = 'x' WHERE id = ?",
        (cid,),
    )
    db.execute(
        "INSERT INTO handoffs (conversation_id, kind, reason, intent, told_caller) "
        "VALUES (?, 'handoff', 'r', 'i', 't')",
        (cid,),
    )
    public = db.execute(
        "SELECT public_id FROM conversations WHERE id = ?", (cid,)
    ).fetchone()[0]
    handoff = db.execute("SELECT id FROM handoffs").fetchone()[0]

    flag = client.post(f"/conversations/{public}/flag", json={"note": "wrong"})
    candidate = client.post(f"/conversations/{public}/eval-candidate")
    followed = client.post(f"/handoffs/{handoff}/followed-up")

    assert flag.status_code == 201
    assert candidate.status_code == 201
    assert followed.status_code == 429
    assert followed.json()["error"] == "rate_limited"


def test_refused_messages_never_reach_the_model(
    started: Settings, db: sqlite3.Connection
):
    model = FakeModelProvider(replies=["Sure."])
    client = make_client(started, model, MESSAGES_PER_MINUTE=4, TURN_CAP=1)
    cid = start(client)
    assert send(client, cid).status_code == 200
    calls = len(model.received)

    refusals = [
        send(client, cid, "a" * (started.MESSAGE_MAX_CHARS + 1)).status_code,
        send(client, cid, "  ").status_code,
        send(client, cid).status_code,
        send(client, cid).status_code,
    ]

    assert refusals == [413, 422, 409, 429]
    assert len(model.received) == calls
    assert turns(db, cid) == 1


def test_eval_worker_lift_still_applies(started: Settings, tmp_path: Path):
    low = started.model_copy(
        update={"NEW_CONVERSATIONS_PER_HOUR": 1, "MESSAGES_PER_MINUTE": 1}
    )
    worker = Worker(0, low, tmp_path / "worker", None)
    worker.reseed()
    worker.app.state.ctx.model = FakeModelProvider(replies=["Sure."])
    client = TestClient(worker.app)

    cids = [start(client) for _ in range(3)]
    codes = [send(client, cids[0]).status_code for _ in range(3)]

    assert len(set(cids)) == 3
    assert codes == [200] * 3

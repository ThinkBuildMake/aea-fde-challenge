import itertools
import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.llm import FakeModelProvider
from app.main import create_app
from app.settings import Settings

_ids = itertools.count(1)


def stamp(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def ago(**delta: float) -> datetime:
    return datetime.now(UTC) - timedelta(**delta)


@pytest.fixture
def client(started: Settings) -> TestClient:
    return TestClient(create_app(started, model=FakeModelProvider()))


@pytest.fixture
def db(started: Settings):
    conn = sqlite3.connect(started.APP_DB_PATH, isolation_level=None)
    yield conn
    conn.close()


def seed(
    db: sqlite3.Connection,
    *,
    outcome: str | None = "contained",
    solved: str | None = None,
    intent: str = "unknown",
    intents: tuple[str, ...] = (),
    turns: int = 1,
    started: datetime | None = None,
    last: datetime | None = None,
    reason: str | None = None,
    flagged: bool = False,
    booked: bool = False,
) -> str:
    cid = f"c{next(_ids)}"
    began = started or ago(hours=1)
    db.execute(
        "INSERT INTO conversations (id, started_at, last_activity_at, ended_at, "
        "outcome, intent, intents_seen, solved, turn_count) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            cid,
            stamp(began),
            stamp(last or began),
            stamp(began) if outcome else None,
            outcome,
            intent,
            json.dumps(list(intents)),
            solved,
            turns,
        ),
    )
    if reason:
        db.execute(
            "INSERT INTO handoffs (conversation_id, kind, reason, intent, told_caller)"
            " VALUES (?,?,?,?,?)",
            (cid, "policy", reason, intent, "A person will call you."),
        )
    if flagged:
        db.execute(
            "INSERT INTO flags (conversation_id, note) VALUES (?, 'wrong')", (cid,)
        )
    if booked:
        db.execute(
            "INSERT INTO visit_changes (conversation_id, action, appointment_id, "
            "slot_id, customer_id) VALUES (?, 'book', 1, 1, 'cust')",
            (cid,),
        )
    return cid


def turn(db: sqlite3.Connection, cid: str, at: datetime, fallback: int) -> None:
    db.execute(
        "INSERT INTO turns (conversation_id, seq, created_at, caller_text, reply_text,"
        " latency_ms, fallback_used) VALUES (?, ?, ?, 'hi', 'hello', 10, ?)",
        (cid, next(_ids), stamp(at), fallback),
    )


def test_settled_share(client, db):
    for _ in range(6):
        seed(db, solved="yes")
    seed(db)
    for _ in range(3):
        seed(db, outcome="handoff", reason="policy")
    seed(db, turns=0)
    seed(db, started=ago(days=10), solved="yes")
    body = client.get("/overview").json()["success"]
    assert body["settledPct"] == 60
    assert (body["settledCount"], body["totalCount"]) == (6, 10)
    assert body["targetBandPct"] == [60, 75]
    assert len(body["series"]) == 7
    dates = [p["date"] for p in body["series"]]
    assert dates == sorted(dates)
    assert dates[-1] == datetime.now(UTC).strftime("%Y-%m-%d")
    assert body["series"][-1]["settledPct"] == 60
    assert body["series"][0]["settledPct"] is None


def test_booking_completion(client, db):
    seed(db, intents=("book_visit",), booked=True)
    seed(db, intents=("billing_lookup", "book_visit"), booked=True)
    seed(db, intents=("book_visit",), booked=True)
    seed(db, intents=("book_visit",))
    seed(db, intents=("billing_lookup",), booked=True)
    got = client.get("/overview").json()["supporting"]
    assert got["bookingCompletionPct"] == 75


def test_handoffs_on_handled_topics(client, db):
    for _ in range(4):
        seed(db, intent="policy_question")
    seed(db, outcome="handoff", intent="billing_lookup", reason="no_document_answer")
    seed(db, outcome="handoff", intent="out_of_scope", reason="out_of_scope")
    got = client.get("/overview").json()["supporting"]
    assert got["handoffsOnHandledTopicsPct"] == 20
    assert got["topHandoffReason"] == "no_document_answer"


def test_flagged_wrong(client, db):
    seed(db, flagged=True)
    for _ in range(5):
        seed(db)
    seed(db, outcome="handoff", reason="policy", flagged=True)
    got = client.get("/overview").json()["supporting"]
    assert got["flaggedWrongPct"] == 16.7


def test_status_counts_kept_apart(client, db):
    cid = seed(db, last=ago(minutes=3))
    turn(db, cid, ago(hours=1), 1)
    turn(db, cid, ago(hours=2), 1)
    turn(db, cid, ago(hours=25), 1)
    turn(db, cid, ago(hours=1), 0)
    seed(db, outcome="handoff", reason="policy")
    other = seed(db, outcome="handoff", reason="policy")
    db.execute(
        "UPDATE handoffs SET status = 'followed_up' WHERE conversation_id = ?", (other,)
    )
    status = client.get("/overview").json()["status"]
    assert status["errorsShown24h"] == 2
    assert status["handoffsWaiting"] == 1
    last = datetime.fromisoformat(status["lastConversationAt"])
    assert timedelta(minutes=2) < datetime.now(UTC) - last < timedelta(minutes=4)


def test_failing_flags_query_leaves_rest(client, db):
    seed(db, solved="yes", intents=("book_visit",), booked=True, intent="book_visit")
    seed(db, outcome="handoff", reason="policy", intent="policy_question")
    db.execute("DROP TABLE flags")
    res = client.get("/overview")
    assert res.status_code == 200
    body = res.json()
    assert body["supporting"]["flaggedWrongPct"] is None
    assert body["success"]["settledPct"] == 50
    assert body["supporting"]["bookingCompletionPct"] == 100
    assert body["supporting"]["handoffsOnHandledTopicsPct"] == 50
    assert body["volume"]["outcomes"]["contained"] == 1
    assert body["volume"]["outcomes"]["handoff"] == 1
    assert body["status"]["handoffsWaiting"] == 1


def test_bad_days_refused(client):
    for days in (0, 91):
        res = client.get(f"/overview?days={days}")
        assert res.status_code == 422
        assert res.json()["error"] == "invalid_days"


def test_new_conversation_counts_on_next_request(client, db):
    seed(db, solved="yes")
    first = client.get("/overview").json()
    assert first["success"]["totalCount"] == 1
    seed(db, outcome=None, last=ago(seconds=5))
    second = client.get("/overview").json()
    assert second["success"]["totalCount"] == 2
    assert second["volume"]["conversationsByDay"][-1]["count"] == 2
    assert second["volume"]["outcomes"]["active"] == 1


def test_days_sets_series_length(client):
    body = client.get("/overview?days=30").json()
    assert len(body["success"]["series"]) == 30
    assert len(body["volume"]["conversationsByDay"]) == 30

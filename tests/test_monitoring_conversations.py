import itertools
import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.llm import FakeModelProvider
from app.main import create_app
from app.safety.service import CARD_RUN
from app.settings import Settings

ADMIN = {"Authorization": "Bearer test-admin-token"}
_n = itertools.count(1)


@pytest.fixture
def client(started: Settings) -> TestClient:
    return TestClient(create_app(started, model=FakeModelProvider()))


@pytest.fixture
def db(started: Settings):
    conn = sqlite3.connect(started.APP_DB_PATH, isolation_level=None)
    yield conn
    conn.close()


def stamp(minutes_ago: int) -> str:
    moment = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def seed(
    db: sqlite3.Connection,
    *,
    outcome: str | None = "contained",
    minutes_ago: int = 5,
    customer_id: str | None = None,
    turns: list[str] | None = None,
    cost: float = 0.0,
) -> tuple[str, str]:
    n = next(_n)
    secret, public = f"secret{n:04d}" + "a" * 20, f"public{n:04d}" + "b" * 20
    began = stamp(minutes_ago)
    db.execute(
        "INSERT INTO conversations (id, public_id, started_at, last_activity_at, ended_at,"
        " outcome, customer_id, turn_count, cost_usd) VALUES (?,?,?,?,?,?,?,?,?)",
        (secret, public, began, began, began if outcome else None, outcome,
         customer_id, len(turns or []), cost),
    )  # fmt: skip
    for seq, text in enumerate(turns or [], start=1):
        db.execute(
            "INSERT INTO turns (conversation_id, seq, caller_text, reply_text,"
            " model_messages, tools_called, retrieved, latency_ms, cost_usd, trace_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                secret, seq, text, f"reply {seq}",
                json.dumps([{"role": "assistant", "content": "RAW-MODEL-SECRET"}]),
                json.dumps([{"name": "find_slots", "ok": True, "ms": 12, "error": None}]),
                json.dumps([{"passageId": "p1", "sourceFile": "kb/a.md", "score": 0.5}]),
                120 + seq, 0.005, f"trace-{seq}",
            ),
        )  # fmt: skip
    return secret, public


def count(db: sqlite3.Connection, table: str) -> int:
    return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_list_filters_by_outcome_newest_first(client: TestClient, db):
    seed(db, minutes_ago=30)
    _, handoff = seed(
        db, outcome="handoff", minutes_ago=20, customer_id="MHC-52445",
        turns=["hi", "bye"], cost=0.01,
    )  # fmt: skip
    seed(db, minutes_ago=10)
    body = client.get("/conversations?outcome=handoff").json()
    assert len(body["conversations"]) == 1
    item = body["conversations"][0]
    assert item["publicId"] == handoff
    assert item["turnCount"] == 2
    assert item["costUsd"] == 0.01
    assert item["customerName"] == "Michael Chen"
    everything = client.get("/conversations").json()["conversations"]
    starts = [c["startedAt"] for c in everything]
    assert len(everything) == 3 and starts == sorted(starts, reverse=True)


def test_detail_lists_turns_without_secrets(client: TestClient, db):
    secret, public = seed(db, turns=["one", "two"])
    response = client.get(f"/conversations/{public}")
    assert response.status_code == 200
    turns = response.json()["turns"]
    assert [t["seq"] for t in turns] == [1, 2]
    first = turns[0]
    assert first["callerText"] == "one" and first["replyText"] == "reply 1"
    assert first["toolsCalled"] == [{"name": "find_slots", "ok": True, "ms": 12}]
    assert first["latencyMs"] == 121 and first["costUsd"] == 0.005
    assert first["traceId"] == "trace-1"
    for forbidden in (secret, "RAW-MODEL-SECRET", "modelMessages", "model_messages"):
        assert forbidden not in response.text


def test_flag_needs_a_note(client: TestClient, db):
    _, public = seed(db)
    for note in ("", "   "):
        response = client.post(f"/conversations/{public}/flag", json={"note": note})
        assert response.status_code == 422
        assert response.json()["error"] == "note_required"
    assert count(db, "flags") == 0


def test_flag_is_stored_and_listed(client: TestClient, db):
    _, public = seed(db)
    response = client.post(
        f"/conversations/{public}/flag", json={"note": "quoted the wrong window"}
    )
    assert response.status_code == 201
    assert response.json()["flag"]["id"] > 0
    detail = client.get(f"/conversations/{public}").json()
    assert [f["note"] for f in detail["flags"]] == ["quoted the wrong window"]
    assert detail["summary"]["flagged"] is True


def test_eval_candidate_is_created_once(client: TestClient, db):
    _, public = seed(db, turns=["hello"])
    first = client.post(f"/conversations/{public}/eval-candidate")
    second = client.post(f"/conversations/{public}/eval-candidate")
    assert (first.status_code, second.status_code) == (201, 200)
    expected = "CAND-" + public[:8]
    assert first.json()["candidate"]["scenarioId"] == expected
    assert second.json()["candidate"]["scenarioId"] == expected
    assert count(db, "eval_candidates") == 1
    detail = client.get(f"/conversations/{public}").json()
    assert detail["evalCandidate"]["scenarioId"] == expected


def test_active_conversation_cannot_become_a_test(client: TestClient, db):
    _, public = seed(db, outcome=None)
    response = client.post(f"/conversations/{public}/eval-candidate")
    assert response.status_code == 409
    assert response.json()["error"] == "conversation_active"
    assert count(db, "eval_candidates") == 0


def test_draft_holds_no_card_number(client: TestClient, db):
    _, public = seed(db, turns=["my card is 4111 1111 1111 1111"])
    client.post(f"/conversations/{public}/eval-candidate")
    text = client.get("/admin/eval-candidates", headers=ADMIN).text
    assert not re.search(r"\d{13,19}", text) and not CARD_RUN.search(text)
    assert "4111" not in text


def test_bad_outcome_filter_is_refused(client: TestClient):
    response = client.get("/conversations?outcome=lost")
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_outcome"


def test_business_routes_never_expose_or_accept_the_secret_id(client: TestClient, db):
    secret, public = seed(db, turns=["hello"])
    client.post(f"/conversations/{public}/flag", json={"note": "bad"})
    client.post(f"/conversations/{public}/eval-candidate")
    responses = [
        client.get("/conversations"),
        client.get(f"/conversations/{public}"),
        client.post(f"/conversations/{public}/flag", json={"note": "again"}),
        client.post(f"/conversations/{public}/eval-candidate"),
        client.get("/admin/eval-candidates", headers=ADMIN),
    ]
    assert all(secret not in r.text for r in responses)
    flags, drafts = count(db, "flags"), count(db, "eval_candidates")
    for method, path in [
        ("GET", f"/conversations/{secret}"),
        ("POST", f"/conversations/{secret}/flag"),
        ("POST", f"/conversations/{secret}/eval-candidate"),
    ]:
        response = client.request(method, path, json={"note": "x"})
        assert response.status_code == 404
        assert response.json()["error"] == "conversation_not_found"
    assert (count(db, "flags"), count(db, "eval_candidates")) == (flags, drafts)

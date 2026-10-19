import itertools
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.llm import FakeModelProvider
from app.main import create_app
from app.monitoring import view
from app.settings import Settings
from app.types import Guarantee
from tests.test_booking_agreement import open_slot, sched
from tests.test_overview import ago, db, seed, stamp

__all__ = ["db"]


@pytest.fixture
def client(started: Settings) -> TestClient:
    return TestClient(create_app(started, model=FakeModelProvider()))


def add_turn(db, cid, seq, ms, at, *, write=0, fallback=0):
    db.execute(
        "INSERT INTO turns (conversation_id, seq, created_at, caller_text, reply_text,"
        " latency_ms, has_write, fallback_used) VALUES (?,?,?,'hi','yo',?,?,?)",
        (cid, seq, stamp(at), ms, write, fallback),
    )


def overview(client) -> dict:
    return client.get("/overview").json()


def guarantee(body: dict, key: str) -> dict:
    return next(g for g in body["guarantees"] if g["key"] == key)


def first_replies(db, times: list[int], when: datetime):
    for ms in times:
        add_turn(db, seed(db, started=when), 1, ms, when)


def test_slow_first_reply_breaches(client, db):
    first_replies(db, [3000] * 18 + [7000] * 2, ago(hours=2))
    first_replies(db, [60000], ago(hours=25))
    body = overview(client)
    pf = guarantee(body, "PF-1")
    print("PF-1", pf)
    assert (pf["now"], pf["limit"], pf["status"]) == (7000, 6000, "breach")
    rows = view.guarantee_rows(
        [Guarantee.model_validate(g) for g in body["guarantees"]]
    )
    assert rows[0]["limit"] == "at most 6 s" and rows[0]["status"] == "Over limit"


def test_first_reply_at_limit_is_ok(client, db):
    first_replies(db, [6000], ago(hours=1))
    assert guarantee(overview(client), "PF-1")["status"] == "ok"


def test_booking_on_open_slot_counted_once(client, db, started):
    cid = seed(db)
    slot = open_slot(started)
    cust = sched(
        started, "SELECT customer_id FROM appointments WHERE appointment_id=1"
    )[0][0]
    sched(started, "UPDATE appointments SET slot_id=? WHERE appointment_id=1", slot)
    db.execute(
        "INSERT INTO visit_changes (conversation_id, action, appointment_id, slot_id, "
        "customer_id) VALUES (?, 'book', 1, ?, ?)",
        (cid, slot, cust),
    )
    db.execute(
        "INSERT INTO visit_changes (conversation_id, action, appointment_id, slot_id, "
        "customer_id, retired_at) VALUES (?, 'book', 999, 1, 'x', '2026-10-19T00:00:00.000Z')",
        (cid,),
    )
    vr = guarantee(overview(client), "VR-6/7/8")
    print("VR", vr)
    assert (vr["now"], vr["limit"], vr["status"]) == (1, 0, "breach")


def test_orphan_appointment_counted(client, started):
    sched(
        started,
        "INSERT INTO appointments (appointment_id, slot_id, customer_id, created_at, status) "
        "VALUES (160, ?, 'MHC-10002', '2026-10-16', 'scheduled')",
        open_slot(started),
    )
    vr = guarantee(overview(client), "VR-6/7/8")
    print("VR", vr)
    assert (vr["now"], vr["status"]) == (1, "breach")


def test_public_url_named(started, db):
    s = started.model_copy(update={"PUBLIC_URL": "https://meridian.example.app"})
    body = TestClient(create_app(s, model=FakeModelProvider())).get("/overview").json()
    print(body["status"]["publicUrl"])
    assert body["status"]["publicUrl"] == "https://meridian.example.app"


def test_latency_series_and_recent(client, db):
    now = datetime.now(UTC)
    hour = now.replace(minute=30, second=0, microsecond=0) - timedelta(hours=3)
    if hour > now:
        hour -= timedelta(hours=1)
    first_replies(db, [1000, 5000], hour)
    cids = []
    for i in range(7):
        began = ago(minutes=10 + i)
        cid = seed(db, intent="book_visit", started=began)
        if i == 0:
            db.execute(
                "UPDATE conversations SET customer_id='MHC-10002' WHERE id=?", (cid,)
            )
        add_turn(db, cid, 1, 1200 + i, began)
        cids.append(cid)
    seed(db, turns=0, started=ago(minutes=1))
    body = overview(client)
    series = body["latencySeries24h"]
    print(series[-4:], body["recent"][:2])
    assert len(series) == 24
    top = now.replace(minute=0, second=0, microsecond=0)
    assert series[-1]["hour"] == stamp(top)
    gaps = {
        datetime.fromisoformat(b["hour"]) - datetime.fromisoformat(a["hour"])
        for a, b in itertools.pairwise(series)
    }
    assert gaps == {timedelta(hours=1)}
    bucket = next(p for p in series if p["hour"] == stamp(hour.replace(minute=0)))
    assert bucket["p95FirstReplyMs"] == 5000
    assert series[0]["p95FirstReplyMs"] is None
    recent = body["recent"]
    assert [r["publicId"] for r in recent] == cids[:5]
    assert set(recent[0]) == {
        "publicId",
        "startedAt",
        "intent",
        "zone",
        "outcome",
        "latencyMs",
    }
    assert (recent[0]["zone"], recent[0]["latencyMs"]) == ("south", 1200)
    assert recent[1]["zone"] is None


def test_limits_are_requirement_numbers(client):
    body = overview(client)
    got = [(g["key"], g["limit"]) for g in body["guarantees"]]
    assert got == [
        ("PF-1", 6000),
        ("PF-2", 10000),
        ("VR-6/7/8", 0),
        ("DE-1", 0),
        ("CO-1", 100),
    ]
    rows = view.guarantee_rows(
        [Guarantee.model_validate(g) for g in body["guarantees"]]
    )
    assert [r["limit"] for r in rows] == [
        "at most 6 s",
        "at most 10 s",
        "0",
        "0",
        "alert at $100",
    ]


def test_scheduling_missing_leaves_vr_no_data(client, started, db):
    seed(db)
    started.SCHEDULING_DB_PATH.unlink()
    resp = client.get("/overview")
    assert resp.status_code == 200
    assert guarantee(resp.json(), "VR-6/7/8")["status"] == "no_data"
    assert resp.json()["recent"][0]["zone"] is None

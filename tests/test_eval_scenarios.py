"""File check over the 31 eval scenarios (EV-1, EV-2, CT-2)."""

import json
import re
import shutil
import sqlite3
from pathlib import Path

import pytest

from tests.conftest import REPO, SEED

SCENARIO_DIR = REPO / "eval" / "scenarios"
CALLS = REPO / "data" / "meridian_dataset" / "call_transcripts"

EV1_IDS = sorted(
    [f"BK-{n}" for n in (1, 2, 3)]
    + [f"WA-{n}" for n in (1, 2, 3)]
    + [f"ME-{n}" for n in (1, 2, 3)]
    + [f"BI-{n}" for n in (1, 2, 3)]
    + [f"AP-{n}" for n in (1, 2, 3)]
    + ["DI-1", "RF-1", "LT-1", "NS-1", "RD-1"]
    + [f"SF-{n}" for n in (1, 2, 3)]
    + [f"T-{n}" for n in range(1, 9)]
)
TOP_KEYS = {
    "id",
    "title",
    "basedOn",
    "driver",
    "kind",
    "customerId",
    "invoiceId",
    "opening",
    "callerBrief",
    "maxTurns",
    "expected",
}
EXPECTED_KEYS = {"outcome", "facts", "forbidden", "dbChange", "handoffReason"}
COUNT_KEYS = (
    "appointmentsAdded",
    "appointmentsCancelled",
    "appointmentsMoved",
    "slotsBooked",
    "slotsFreed",
    "waitlistRows",
    "handoffRows",
)
HANDLED = {"booking", "warranty", "membership", "billing", "appointment"}
INVOICE_SCENARIOS = {"BI-1", "BI-2", "BI-3", "DI-1", "RF-1", "T-5", "T-7"}


def load_all() -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text()) for p in SCENARIO_DIR.glob("*.json")}


@pytest.fixture(scope="module")
def scenarios() -> dict[str, dict]:
    return load_all()


@pytest.fixture
def seed_db(tmp_path: Path):
    copy = tmp_path / "seed.sqlite"
    shutil.copyfile(SEED, copy)
    conn = sqlite3.connect(copy)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def test_exactly_the_31_ev1_ids(scenarios):
    assert len(EV1_IDS) == 31
    assert sorted(scenarios) == EV1_IDS
    for stem, s in scenarios.items():
        assert s["id"] == stem


def test_no_scenario_misses_a_field(scenarios):
    for sid, s in scenarios.items():
        assert set(s) == TOP_KEYS, sid
        for key in ("title", "basedOn", "driver", "kind", "customerId"):
            assert isinstance(s[key], str) and s[key].strip(), (sid, key)
        for key in ("opening", "callerBrief"):
            assert len(s[key].strip()) > 20, (sid, key)
        assert isinstance(s["maxTurns"], int) and s["maxTurns"] > 0, sid
        assert s["invoiceId"] is None or s["invoiceId"].startswith("INV-"), sid
        e = s["expected"]
        assert set(e) == EXPECTED_KEYS, sid
        assert e["outcome"] in {"contained", "handoff", "safety_stop"}, sid
        assert isinstance(e["facts"], list) and e["facts"], sid
        assert all(isinstance(f, str) and f.strip() for f in e["facts"]), sid
        assert isinstance(e["forbidden"], list), sid
        assert all(isinstance(f, str) and f.strip() for f in e["forbidden"]), sid
        db = e["dbChange"]
        assert set(db) == {*COUNT_KEYS, "detail"}, sid
        for key in COUNT_KEYS:
            assert isinstance(db[key], int) and db[key] >= 0, (sid, key)
        assert isinstance(db["detail"], str) and db["detail"].strip(), sid
        if e["outcome"] == "contained":
            assert e["handoffReason"] is None, sid
            assert db["handoffRows"] == 0, sid
        else:
            assert isinstance(e["handoffReason"], str) and e["handoffReason"], sid
            assert db["handoffRows"] == 1, sid


def test_source_and_customer_are_real(scenarios, seed_db):
    customers = {r[0] for r in seed_db.execute("SELECT customer_id FROM customers")}
    for sid, s in scenarios.items():
        if s["basedOn"] != "authored":
            assert re.fullmatch(r"CALL-\d{8}-\d{4}", s["basedOn"]), sid
            assert (CALLS / f"{s['basedOn']}.txt").is_file(), sid
        assert s["customerId"] in customers, sid


def test_balance_scenarios_carry_their_invoice(scenarios, seed_db):
    for sid in ("BI-1", "BI-2"):
        s = scenarios[sid]
        row = seed_db.execute(
            "SELECT customer_id FROM invoices WHERE invoice_id = ?", (s["invoiceId"],)
        ).fetchone()
        assert row is not None, sid
        assert row["customer_id"] == s["customerId"], sid
    for sid in INVOICE_SCENARIOS:
        row = seed_db.execute(
            "SELECT customer_id FROM invoices WHERE invoice_id = ?",
            (scenarios[sid]["invoiceId"],),
        ).fetchone()
        assert row is not None and row["customer_id"] == scenarios[sid]["customerId"]
    for sid, s in scenarios.items():
        if sid not in INVOICE_SCENARIOS:
            assert s["invoiceId"] is None, sid


def test_caller_brief_names_the_database_customer(scenarios, seed_db):
    for sid, s in scenarios.items():
        row = seed_db.execute(
            "SELECT name, phone FROM customers WHERE customer_id = ?",
            (s["customerId"],),
        ).fetchone()
        assert row["name"] in s["callerBrief"], sid
        if sid != "BI-3":
            assert row["phone"] in s["callerBrief"], sid
    assert "512-555-0188" in scenarios["BI-3"]["callerBrief"]
    assert "512-511-2742" not in scenarios["BI-3"]["callerBrief"]


def test_seeded_customers_look_up_and_book(scenarios, seed_db):
    for cid in ("MHC-10001", "MHC-10002", "MHC-10003", "MHC-10004"):
        row = seed_db.execute(
            "SELECT name, phone FROM customers WHERE customer_id = ?", (cid,)
        ).fetchone()
        booking = [
            s
            for s in scenarios.values()
            if s["customerId"] == cid
            and s["expected"]["outcome"] == "contained"
            and s["expected"]["dbChange"]["appointmentsAdded"] >= 1
            and s["expected"]["dbChange"]["slotsBooked"] >= 1
            and row["name"] in s["callerBrief"]
            and row["phone"] in s["callerBrief"]
        ]
        assert booking, cid


def test_sf3_carries_its_answer(scenarios):
    brief = scenarios["SF-3"]["callerBrief"]
    assert "no smoke, no sparks, no tripped breaker" in brief


def test_set_matches_ev1_structure(scenarios):
    by_driver: dict[str, dict[str, str]] = {}
    for sid, s in scenarios.items():
        if s["driver"] in HANDLED:
            by_driver.setdefault(s["driver"], {})[s["kind"]] = sid
    assert set(by_driver) == HANDLED
    for driver, kinds in by_driver.items():
        assert set(kinds) == {"happy", "edge", "escalation"}, driver
    happy_edge = [s for s in scenarios.values() if s["kind"] in {"happy", "edge"}]
    assert len(happy_edge) == 10
    assert all(s["expected"]["outcome"] == "contained" for s in happy_edge)
    for sid in ("DI-1", "RF-1", "LT-1", "NS-1", "RD-1"):
        assert scenarios[sid]["driver"] == "escalate", sid
        assert scenarios[sid]["kind"] == "escalation", sid
        assert scenarios[sid]["expected"]["outcome"] == "handoff", sid
    safety = {sid: scenarios[sid] for sid in ("SF-1", "SF-2", "SF-3")}
    assert all(
        s["driver"] == "safety" and s["kind"] == "safety" for s in safety.values()
    )
    assert safety["SF-1"]["expected"]["outcome"] == "safety_stop"
    assert safety["SF-2"]["expected"]["outcome"] == "safety_stop"
    assert safety["SF-3"]["expected"]["outcome"] == "contained"
    traps = [s for sid, s in scenarios.items() if sid.startswith("T-")]
    assert len(traps) == 8
    assert all(s["driver"] == "trap" and s["kind"] == "trap" for s in traps)
    must_escalate = [
        sid
        for sid, s in scenarios.items()
        if s["expected"]["outcome"] in {"handoff", "safety_stop"}
    ]
    assert len(must_escalate) == 14
    assert {s["expected"]["outcome"] for s in scenarios.values()} == {
        "contained",
        "handoff",
        "safety_stop",
    }

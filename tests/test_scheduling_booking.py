import sqlite3
import time
from collections.abc import Iterator
from contextlib import closing

import pytest

from app.context import AppContext
from app.main import create_app
from app.scheduling.service import (
    NotEligible,
    SchedulingUnavailable,
    SlotUnavailable,
    book_visit,
)
from app.settings import Settings

ISSUE = "AC blowing warm air"


@pytest.fixture
def ctx(started: Settings) -> AppContext:
    return create_app(started).state.ctx


@pytest.fixture
def db(started: Settings) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(started.SCHEDULING_DB_PATH)
    yield connection
    connection.close()


@pytest.fixture
def cid(ctx: AppContext) -> str:
    with closing(ctx.open_app_db()) as app_db:
        row = app_db.execute(
            "INSERT INTO conversations DEFAULT VALUES RETURNING id"
        ).fetchone()
    return row[0]


def dump(db: sqlite3.Connection, *tables: str) -> dict[str, list]:
    return {t: db.execute(f"SELECT * FROM {t}").fetchall() for t in tables}


def audit_count(ctx: AppContext) -> int:
    with closing(ctx.open_app_db()) as app_db:
        return app_db.execute("SELECT count(*) FROM visit_changes").fetchone()[0]


def refused(ctx, db, cid, customer, slot, error):
    before = dump(db, "appointment_slots", "appointments")
    with pytest.raises(error) as caught:
        book_visit(ctx, customer, slot, ISSUE, cid)
    assert dump(db, "appointment_slots", "appointments") == before
    assert audit_count(ctx) == 0
    return caught.value


def test_book_writes_one_slot_one_visit_one_audit_row(ctx, db, cid):
    before = dump(db, "appointment_slots", "appointments")
    visit = book_visit(ctx, "MHC-10004", 56, ISSUE, cid)
    assert visit.model_dump() == {
        "appointment_id": 160,
        "slot_id": 56,
        "date": "2026-10-19",
        "window": "08:00-12:00",
        "technician_name": "Marta Kowalski",
        "service_type": "hvac_repair",
        "zone": "north",
    }
    after = dump(db, "appointment_slots", "appointments")
    changed = [
        (a, b)
        for a, b in zip(before["appointment_slots"], after["appointment_slots"])
        if a != b
    ]
    assert len(changed) == 1
    assert changed[0][0][0] == 56 and changed[0][0][-1] == "open"
    assert changed[0][1][-1] == "booked"
    assert after["appointments"][:-1] == before["appointments"]
    assert len(after["appointments"]) == len(before["appointments"]) + 1
    row = db.execute(
        "SELECT slot_id, customer_id, issue_description, created_at, status, "
        "is_warranty_visit FROM appointments WHERE appointment_id = 160"
    ).fetchone()
    assert row == (56, "MHC-10004", ISSUE, "2026-10-16", "scheduled", 0)
    with closing(ctx.open_app_db()) as app_db:
        rows = app_db.execute(
            "SELECT conversation_id, action, appointment_id, slot_id, customer_id, "
            "confirmed_date, confirmed_window, confirmed_technician, "
            "late_fee_applied FROM visit_changes"
        ).fetchall()
    assert [tuple(r) for r in rows] == [
        (
            cid,
            "book",
            160,
            56,
            "MHC-10004",
            "2026-10-19",
            "08:00-12:00",
            "Marta Kowalski",
            None,
        )
    ]


def test_book_taken_slot_refused(ctx, db, cid):
    refused(ctx, db, cid, "MHC-10004", 159, SlotUnavailable)


def test_book_blocked_slot_refused(ctx, db, cid):
    (slot,) = db.execute(
        "SELECT slot_id FROM appointment_slots WHERE status = 'blocked' LIMIT 1"
    ).fetchone()
    refused(ctx, db, cid, "MHC-10004", slot, SlotUnavailable)


def test_book_unknown_slot_refused(ctx, db, cid):
    refused(ctx, db, cid, "MHC-10004", 999999, SlotUnavailable)


def test_book_member_only_needs_member(ctx, db, cid):
    error = refused(ctx, db, cid, "MHC-10004", 1, NotEligible)
    assert error.reason == "member_only"


def test_book_other_zone_refused(ctx, db, cid):
    error = refused(ctx, db, cid, "MHC-10004", 115, NotEligible)
    assert error.reason == "wrong_zone"


def test_book_estimate_refused(ctx, db, cid):
    (slot,) = db.execute(
        "SELECT slot_id FROM appointment_slots WHERE status = 'open' "
        "AND zone = 'north' AND service_type = 'estimate' LIMIT 1"
    ).fetchone()
    error = refused(ctx, db, cid, "MHC-10004", slot, NotEligible)
    assert error.reason == "wrong_service_type"


def test_book_unknown_customer_refused(ctx, db, cid):
    error = refused(ctx, db, cid, "MHC-99999", 56, NotEligible)
    assert error.reason == "unknown_customer"


def test_book_before_reference_date_refused(started, db, cid):
    late = create_app(started.model_copy(update={"REFERENCE_DATE": "2026-10-19"}))
    error = refused(late.state.ctx, db, cid, "MHC-10001", 1, NotEligible)
    assert error.reason == "before_reference_date"


def test_member_can_book_member_only_slot(ctx, db, cid):
    visit = book_visit(ctx, "MHC-10001", 1, ISSUE, cid)
    assert visit.slot_id == 1


def test_failed_audit_insert_keeps_booking(ctx, db, cid, monkeypatch, capsys):
    class Broken:
        def execute(self, *args, **kwargs):
            raise sqlite3.OperationalError("disk full")

        def close(self):
            pass

    monkeypatch.setattr(ctx, "open_app_db", lambda: Broken())
    visit = book_visit(ctx, "MHC-10004", 56, ISSUE, cid)
    assert visit.appointment_id == 160
    assert db.execute(
        "SELECT status FROM appointment_slots WHERE slot_id = 56"
    ).fetchone() == ("booked",)
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln]
    assert len(lines) == 1
    assert '"visit_change_audit_failed"' in lines[0]
    assert '"appointment_id": 160' in lines[0]


def test_booking_leaves_supplied_schema_and_other_tables(ctx, db, cid):
    schema = "SELECT type, name, sql FROM sqlite_master ORDER BY name"
    before = (
        db.execute(schema).fetchall(),
        dump(db, "customers", "technicians", "invoices"),
        db.execute("PRAGMA journal_mode").fetchone(),
    )
    book_visit(ctx, "MHC-10004", 56, ISSUE, cid)
    after = (
        db.execute(schema).fetchall(),
        dump(db, "customers", "technicians", "invoices"),
        db.execute("PRAGMA journal_mode").fetchone(),
    )
    assert after == before


def test_locked_file_fails_bounded_with_nothing_written(ctx, started, cid):
    holder = sqlite3.connect(started.SCHEDULING_DB_PATH, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    try:
        start = time.monotonic()
        with pytest.raises(SchedulingUnavailable):
            book_visit(ctx, "MHC-10004", 56, ISSUE, cid)
        assert time.monotonic() - start < 10
    finally:
        holder.rollback()
        holder.close()
    assert audit_count(ctx) == 0
    with closing(sqlite3.connect(started.SCHEDULING_DB_PATH)) as check:
        assert check.execute(
            "SELECT status FROM appointment_slots WHERE slot_id = 56"
        ).fetchone() == ("open",)


def test_unreadable_file_raises_unavailable(ctx, started, cid):
    started.SCHEDULING_DB_PATH.write_bytes(b"")
    with pytest.raises(SchedulingUnavailable):
        book_visit(ctx, "MHC-10004", 56, ISSUE, cid)

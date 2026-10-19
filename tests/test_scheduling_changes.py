import sqlite3
from collections.abc import Iterator
from contextlib import closing

import pytest

from app.context import AppContext
from app.main import create_app
from app.scheduling.service import (
    AppointmentNotFound,
    NotEligible,
    SlotUnavailable,
    cancel_visit,
    move_visit,
)
from app.settings import Settings
from app.types import CancelResult


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


def audit_rows(ctx: AppContext) -> list[tuple]:
    with closing(ctx.open_app_db()) as app_db:
        return app_db.execute(
            "SELECT action, appointment_id, slot_id, previous_slot_id, customer_id, "
            "confirmed_date, confirmed_window, confirmed_technician, late_fee_applied "
            "FROM visit_changes"
        ).fetchall()


def slot_status(db: sqlite3.Connection, slot_id: int) -> str:
    return db.execute(
        "SELECT status FROM appointment_slots WHERE slot_id = ?", (slot_id,)
    ).fetchone()[0]


def appointment(db: sqlite3.Connection, appointment_id: int) -> tuple:
    return db.execute(
        "SELECT slot_id, status FROM appointments WHERE appointment_id = ?",
        (appointment_id,),
    ).fetchone()


def late_clock(started: Settings) -> AppContext:
    return create_app(
        started.model_copy(update={"REFERENCE_DATE": "2026-10-21"})
    ).state.ctx


def test_move_frees_the_old_window(ctx, db, cid):
    moved = move_visit(ctx, "MHC-10001", 159, 56, cid)
    assert moved.booking.slot_id == 56 and moved.booking.appointment_id == 159
    assert moved.late_fee_applies is False
    assert slot_status(db, 56) == "booked" and slot_status(db, 159) == "open"
    assert appointment(db, 159) == (56, "scheduled")
    rows = audit_rows(ctx)
    assert len(rows) == 1
    action, appt, slot, previous, customer, date, window, _tech, fee = rows[0]
    assert (action, appt, slot, previous, customer) == (
        "move",
        159,
        56,
        159,
        "MHC-10001",
    )
    assert (date, window, fee) == ("2026-10-19", "08:00-12:00", 0)


def test_cancel_inside_24_hours_carries_the_fee(started, db, cid):
    ctx = late_clock(started)
    result = cancel_visit(ctx, "MHC-10001", 159, cid)
    assert result == CancelResult(
        appointment_id=159, freed_slot_id=159, late_fee_applies=True, hours_before=20.0
    )
    assert appointment(db, 159) == (159, "cancelled")
    assert slot_status(db, 159) == "open"
    rows = audit_rows(ctx)
    assert [r[:4] for r in rows] == [("cancel", 159, 159, None)]
    assert rows[0][5:8] == (None, None, None) and rows[0][8] == 1


def test_cancel_beyond_24_hours_is_free(ctx, db, cid):
    result = cancel_visit(ctx, "MHC-10001", 159, cid)
    assert result.late_fee_applies is False and result.hours_before == 140.0


def test_cancel_someone_elses_visit_not_found(ctx, db, cid):
    before = dump(db, "appointment_slots", "appointments")
    with pytest.raises(AppointmentNotFound):
        cancel_visit(ctx, "MHC-10002", 159, cid)
    assert dump(db, "appointment_slots", "appointments") == before
    assert appointment(db, 159) == (159, "scheduled")
    assert audit_rows(ctx) == []


def test_move_into_taken_slot_changes_nothing(ctx, db, cid):
    before = dump(db, "appointment_slots", "appointments")
    with pytest.raises(SlotUnavailable):
        move_visit(ctx, "MHC-10001", 159, 31, cid)
    assert dump(db, "appointment_slots", "appointments") == before
    assert appointment(db, 159) == (159, "scheduled")
    assert audit_rows(ctx) == []


def test_cancelled_visit_cannot_move(ctx, db, cid):
    cancel_visit(ctx, "MHC-10001", 159, cid)
    with pytest.raises(NotEligible) as caught:
        move_visit(ctx, "MHC-10001", 159, 56, cid)
    assert caught.value.reason == "not_scheduled"
    assert slot_status(db, 56) == "open"
    assert [r[0] for r in audit_rows(ctx)] == ["cancel"]


def test_cancelling_twice_is_not_found(ctx, cid):
    cancel_visit(ctx, "MHC-10001", 159, cid)
    with pytest.raises(AppointmentNotFound):
        cancel_visit(ctx, "MHC-10001", 159, cid)

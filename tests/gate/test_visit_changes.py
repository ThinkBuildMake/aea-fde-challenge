import sqlite3
from contextlib import closing

import pytest

from app.main import create_app
from app.scheduling.service import (
    AppointmentNotFound,
    SlotUnavailable,
    cancel_visit,
    move_visit,
)
from app.settings import Settings
from tests.gate.bookings import orphans

TABLES = ("appointment_slots", "appointments")


def setup(started: Settings):
    ctx = create_app(started).state.ctx
    with closing(ctx.open_app_db()) as app_db:
        cid = app_db.execute(
            "INSERT INTO conversations DEFAULT VALUES RETURNING id"
        ).fetchone()[0]
    return ctx, cid


def snapshot(db: sqlite3.Connection) -> dict[str, list]:
    return {t: db.execute(f"SELECT * FROM {t}").fetchall() for t in TABLES}


def changes(ctx) -> int:
    with closing(ctx.open_app_db()) as app_db:
        return app_db.execute("SELECT count(*) FROM visit_changes").fetchone()[0]


def status(db: sqlite3.Connection, slot_id: int) -> str:
    return db.execute(
        "SELECT status FROM appointment_slots WHERE slot_id = ?", (slot_id,)
    ).fetchone()[0]


def test_move_and_cancel_keep_slots_consistent(started: Settings):
    """VR-6: a move or cancel never leaves a slot booked without a visit, or a visit without a booked slot."""
    ctx, cid = setup(started)
    with closing(sqlite3.connect(started.SCHEDULING_DB_PATH)) as db:
        assert orphans(db) == (0, 0)
        move_visit(ctx, "MHC-10001", 159, 56, cid)
        assert (status(db, 159), status(db, 56)) == ("open", "booked")
        assert orphans(db) == (0, 0)
        before = snapshot(db)
        with pytest.raises(SlotUnavailable):
            move_visit(ctx, "MHC-10001", 159, 31, cid)
        assert snapshot(db) == before and orphans(db) == (0, 0)
        cancel_visit(ctx, "MHC-10001", 159, cid)
        assert status(db, 56) == "open"
        assert orphans(db) == (0, 0)


def test_moves_and_cancels_touch_only_own_visits(started: Settings):
    """AZ-2: another customer's visit is not found and nothing changes."""
    ctx, cid = setup(started)
    with closing(sqlite3.connect(started.SCHEDULING_DB_PATH)) as db:
        before = snapshot(db)
        with pytest.raises(AppointmentNotFound):
            move_visit(ctx, "MHC-10002", 159, 56, cid)
        with pytest.raises(AppointmentNotFound):
            cancel_visit(ctx, "MHC-10002", 159, cid)
        assert snapshot(db) == before
    assert changes(ctx) == 0

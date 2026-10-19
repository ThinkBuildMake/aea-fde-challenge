import sqlite3
import threading
from contextlib import closing

from app.main import create_app
from app.scheduling.service import SlotUnavailable, book_visit
from app.settings import Settings
from tests.gate.bookings import open_slots, orphans

RACES = 20


def test_racing_bookings_write_one(started: Settings):
    """RL-1: 0 double bookings over 20 repeated races."""
    ctx = create_app(started).state.ctx
    with closing(ctx.open_app_db()) as app_db:
        cid = app_db.execute(
            "INSERT INTO conversations DEFAULT VALUES RETURNING id"
        ).fetchone()[0]
    with closing(sqlite3.connect(started.SCHEDULING_DB_PATH)) as db:
        slots = open_slots(db)[:RACES]
    assert len(slots) == RACES
    for slot in slots:
        barrier = threading.Barrier(2)
        outcomes: list[str] = []

        def attempt(slot=slot, barrier=barrier, outcomes=outcomes):
            barrier.wait()
            try:
                book_visit(ctx, "MHC-10004", slot, "AC blowing warm air", cid)
                outcomes.append("booked")
            except SlotUnavailable:
                outcomes.append("slot_unavailable")

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sorted(outcomes) == ["booked", "slot_unavailable"]
        with closing(sqlite3.connect(started.SCHEDULING_DB_PATH)) as db:
            assert db.execute(
                "SELECT count(*) FROM appointments WHERE slot_id = ?", (slot,)
            ).fetchone() == (1,)
    with closing(sqlite3.connect(started.SCHEDULING_DB_PATH)) as db:
        assert orphans(db) == (0, 0)

"""Shared pieces of the booking gate tests: the orphan query and the killable child."""

import os
import signal
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ORPHAN_SLOTS = (
    "SELECT count(*) FROM appointment_slots s WHERE s.status = 'booked' AND NOT EXISTS "
    "(SELECT 1 FROM appointments a WHERE a.slot_id = s.slot_id AND a.status = 'scheduled')"
)
ORPHAN_APPOINTMENTS = (
    "SELECT count(*) FROM appointments a JOIN appointment_slots s USING (slot_id) "
    "WHERE a.status = 'scheduled' AND s.status <> 'booked'"
)


def orphans(conn: sqlite3.Connection) -> tuple[int, int]:
    """(booked slots without an appointment, appointments on a non-booked slot)"""
    return (
        conn.execute(ORPHAN_SLOTS).fetchone()[0],
        conn.execute(ORPHAN_APPOINTMENTS).fetchone()[0],
    )


def open_slots(
    conn: sqlite3.Connection, reference_date: str = "2026-10-16"
) -> list[int]:
    return [
        r[0]
        for r in conn.execute(
            "SELECT slot_id FROM appointment_slots WHERE status = 'open' "
            "AND zone = 'north' AND service_type <> 'estimate' AND slot_date >= ? "
            "ORDER BY slot_id",
            (reference_date,),
        )
    ]


def main(scheduling_db: str, app_db: str, slot_id: int, countdown: int) -> None:
    """Book one slot; SIGKILL this process at SQLite VM step `countdown` (0 = never)."""
    from app.main import create_app
    from app.scheduling import service
    from app.settings import Settings

    root = Path(app_db).parent
    settings = Settings(
        OPENROUTER_API_KEY="test-key",  # type: ignore[arg-type]
        ADMIN_TOKEN="test-admin-token",  # type: ignore[arg-type]
        SCHEDULING_DB_PATH=Path(scheduling_db),
        APP_DB_PATH=Path(app_db),
        INDEX_PATH=root / "index" / "knowledge_index.npz",
    )
    ctx = create_app(settings).state.ctx
    with closing(ctx.open_app_db()) as conn:
        cid = conn.execute(
            "INSERT INTO conversations DEFAULT VALUES RETURNING id"
        ).fetchone()[0]
    steps = 0
    real_connect = service.connect

    def tick() -> int:
        nonlocal steps
        steps += 1
        if steps == countdown:
            os.kill(os.getpid(), signal.SIGKILL)
        return 0

    def counting_connect(c):
        conn = real_connect(c)
        conn.set_progress_handler(tick, 1)
        return conn

    service.connect = counting_connect
    service.book_visit(ctx, "MHC-10004", slot_id, "AC blowing warm air", cid)
    print(steps)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]))

import sqlite3

from app.settings import Settings
from app.startup import run_startup


def test_missing_supplied_file_is_copied_from_the_seed(tmp_settings: Settings):
    assert not tmp_settings.SCHEDULING_DB_PATH.exists()
    run_startup(tmp_settings)
    assert (
        tmp_settings.SCHEDULING_DB_PATH.read_bytes()
        == tmp_settings.SEED_DB_PATH.read_bytes()
    )


def test_booking_made_after_the_seed_survives_a_restart(tmp_settings: Settings):
    run_startup(tmp_settings)
    conn = sqlite3.connect(tmp_settings.SCHEDULING_DB_PATH)
    columns = [row[1] for row in conn.execute("PRAGMA table_info(appointments)")]
    assert conn.execute("SELECT count(*) FROM appointments").fetchone()[0] == 159
    slot_id = conn.execute("SELECT slot_id FROM appointments LIMIT 1").fetchone()[0]
    values = {
        "appointment_id": 160,
        "slot_id": slot_id,
        "customer_id": "MHC-10001",
        "status": "scheduled",
        "issue_description": "S01 redeploy check",
        "created_at": "2026-10-16",
    }
    names = [name for name in values if name in columns]
    conn.execute(
        f"INSERT INTO appointments ({', '.join(names)}) VALUES ({', '.join('?' * len(names))})",
        [values[name] for name in names],
    )
    conn.commit()
    conn.close()

    run_startup(tmp_settings)
    run_startup(tmp_settings)

    conn = sqlite3.connect(tmp_settings.SCHEDULING_DB_PATH)
    row = conn.execute(
        "SELECT issue_description FROM appointments WHERE appointment_id = 160"
    ).fetchone()
    assert row == ("S01 redeploy check",)
    assert conn.execute("SELECT count(*) FROM appointments").fetchone()[0] == 160
    conn.close()

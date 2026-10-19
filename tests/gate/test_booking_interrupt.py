import random
import signal
import sqlite3
import subprocess
import sys
from contextlib import closing

from app.settings import Settings
from tests.conftest import REPO
from tests.gate.bookings import open_slots, orphans

KILLS = 10


def run_child(started: Settings, slot: int, countdown: int):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "tests.gate.bookings",
            str(started.SCHEDULING_DB_PATH),
            str(started.APP_DB_PATH),
            str(slot),
            str(countdown),
        ],
        check=False,
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_interrupted_bookings_leave_no_orphans(started: Settings):
    """RL-2: 0 orphans after 10 forced interruptions."""
    with closing(sqlite3.connect(started.SCHEDULING_DB_PATH)) as db:
        slots = open_slots(db)
    dry = run_child(started, slots[0], 0)
    assert dry.returncode == 0, dry.stderr
    total_steps = int(dry.stdout.strip().splitlines()[-1])
    assert total_steps > 1
    for slot in slots[1 : KILLS + 1]:
        child = run_child(started, slot, random.randint(1, total_steps))
        assert child.returncode == -signal.SIGKILL, child.stderr
        with closing(sqlite3.connect(started.SCHEDULING_DB_PATH)) as db:
            assert orphans(db) == (0, 0)

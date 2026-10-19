import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from app.db import apply_migrations, connect_app_db
from app.evals.checks import (
    db_diff,
    forbidden_hits,
    invariant_violations,
    seeded_customer_strings,
    unsupported_figures,
)
from app.startup import MIGRATIONS_DIR


@pytest.fixture
def copy(tmp_path: Path, seed_path: Path) -> Path:
    path = tmp_path / "copy.sqlite"
    shutil.copyfile(seed_path, path)
    return path


@pytest.fixture
def app_db(tmp_path: Path) -> Path:
    path = tmp_path / "app.sqlite"
    with closing(connect_app_db(path)) as conn:
        apply_migrations(conn, MIGRATIONS_DIR)
    return path


def run(copy: Path, *statements: str) -> None:
    with closing(sqlite3.connect(copy)) as conn:
        for statement in statements:
            conn.execute(statement)
        conn.commit()


def book(slot: int, customer: str) -> list[str]:
    return [
        f"UPDATE appointment_slots SET status = 'booked' WHERE slot_id = {slot}",
        (
            "INSERT INTO appointments (slot_id, customer_id, issue_description, "
            f"created_at, status) VALUES ({slot}, '{customer}', 'x', '2026-10-16', "
            "'scheduled')"
        ),
    ]


def slot_where(seed: Path, where: str) -> int:
    with closing(sqlite3.connect(seed)) as conn:
        return conn.execute(
            f"SELECT slot_id FROM appointment_slots WHERE {where} ORDER BY slot_id"
        ).fetchone()[0]


def problems(seed: Path, copy: Path, app_db: Path) -> list[str]:
    return invariant_violations(seed, copy, app_db, None)


def test_untouched_and_legal_booking_hold(seed_path: Path, copy: Path, app_db: Path):
    assert problems(seed_path, copy, app_db) == []
    run(copy, *book(56, "MHC-10001"))
    assert problems(seed_path, copy, app_db) == []


def test_invariant_queries_catch_violations(
    seed_path: Path, copy: Path, app_db: Path, tmp_path: Path
):
    blocked = slot_where(seed_path, "status = 'blocked'")
    reserved = slot_where(
        seed_path,
        "status = 'reserved_members' AND zone = 'north' AND service_type <> 'estimate'",
    )
    cases: dict[str, tuple[list[str], str]] = {
        "booked slot, no appointment": (
            ["UPDATE appointment_slots SET status = 'booked' WHERE slot_id = 56"],
            "VR-6 slot 56 is booked",
        ),
        "scheduled appointment on an open slot": (
            [book(56, "MHC-10001")[1]],
            "VR-6 appointment",
        ),
        "two appointments on one slot": (
            [*book(56, "MHC-10001"), book(56, "MHC-10004")[1]],
            "more than one",
        ),
        "slot blocked in the seed": (book(blocked, "MHC-10001"), "slot was blocked"),
        "member-only slot, no membership": (
            book(reserved, "MHC-10004"),
            "member-only",
        ),
        "wrong zone": (book(56, "MHC-10002"), "zone"),
        "date out of range": (
            [
                "UPDATE appointment_slots SET slot_date = '2026-12-01' WHERE slot_id = 56",
                *book(56, "MHC-10001"),
            ],
            "out of range",
        ),
    }
    for name, (statements, expected) in cases.items():
        path = tmp_path / "case.sqlite"
        shutil.copyfile(seed_path, path)
        run(path, *statements)
        found = problems(seed_path, path, app_db)
        assert any(expected in line for line in found), (name, found)


def test_audit_row_that_disagrees_with_the_slot_is_caught(
    seed_path: Path, copy: Path, app_db: Path
):
    run(copy, *book(56, "MHC-10001"))
    with closing(connect_app_db(app_db)) as conn:
        conn.execute("INSERT INTO conversations (id) VALUES ('c1')")
        conn.execute(
            "INSERT INTO visit_changes (conversation_id, action, appointment_id, slot_id, "
            "customer_id, confirmed_date, confirmed_window, confirmed_technician) "
            "VALUES ('c1', 'book', 1, 56, 'MHC-10001', '2026-10-19', '12:00-16:00', 'X')"
        )
    found = invariant_violations(seed_path, copy, app_db, "c1")
    assert any(line.startswith("VR-8") for line in found), found
    assert invariant_violations(seed_path, copy, app_db, "other") == []


def test_db_diff_lists_added_and_changed_rows(seed_path: Path, copy: Path):
    assert db_diff(seed_path, copy) == {}
    run(copy, *book(56, "MHC-10001"))
    diff = db_diff(seed_path, copy)
    assert set(diff) == {"appointments", "appointment_slots"}
    (added,) = diff["appointments"]["added"]
    assert added["slot_id"] == 56 and added["customer_id"] == "MHC-10001"
    (changed,) = diff["appointment_slots"]["changed"]
    assert changed["key"] == 56
    assert changed["before"]["status"] == "open"
    assert changed["after"]["status"] == "booked"
    assert diff["appointments"]["changed"] == diff["appointments"]["removed"] == []


def test_figure_check():
    def count(reply: str, *tool: str) -> int:
        return unsupported_figures([(reply, list(tool))])

    assert count("The diagnostic is $79.") == 1
    assert count("The diagnostic is $79.", '{"passages": [{"text": "fee 89"}]}') == 1
    assert count("It is $89.", '{"cents": 8900}') == 0
    assert count("It is $89.", "The fee is $89.") == 0
    assert count("Owed: $1,200.50", '{"balance": 1200.5}') == 0
    assert count("Owed: $1,200.50", '{"balanceCents": 120050}') == 0
    assert count("$10 and $20", "10") == 1
    assert count("It is $19.", '{"date": "2026-10-19", "id": "INV-200019"}') == 1
    assert (
        count("It is $12.", '{"window": "12:00-16:00", "phone": "512-555-0112"}') == 1
    )
    assert count("It is $19.", '{"cents": 1900}') == 0
    assert count("No money here.") == 0
    earlier = [("", ['{"cents": 8900}']), ("It is $89.", [])]
    assert unsupported_figures(earlier) == 0


def test_forbidden_hits_and_customer_strings(seed_path: Path):
    assert forbidden_hits(["The OLD price is $75"], ["old price", "internal"]) == [
        "old price"
    ]
    strings = seeded_customer_strings(seed_path, ["MHC-10001"])
    assert "Linda Foster" in strings["MHC-10001"]
    assert "512-555-0101" in strings["MHC-10001"]

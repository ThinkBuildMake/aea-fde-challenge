import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from app.context import AppContext
from app.errors import AppError
from app.main import create_app
from app.scheduling import reset
from app.scheduling.service import (
    SUPPLIED_TABLES,
    book_visit,
    cancel_visit,
    reset_scheduling,
)
from app.settings import Settings
from tests.conftest import SEED
from tests.test_supplied_schema import diff_count

ISSUE = "AC blowing warm air"
SEED_COUNTS = {"open": 323, "booked": 159, "reservedMembers": 42, "blocked": 4}


@pytest.fixture(autouse=True)
def env(started: Settings, monkeypatch: pytest.MonkeyPatch) -> Settings:
    for name, value in {
        "OPENROUTER_API_KEY": "test-key",
        "ADMIN_TOKEN": "test-admin-token",
        "SCHEDULING_DB_PATH": started.SCHEDULING_DB_PATH,
        "APP_DB_PATH": started.APP_DB_PATH,
        "INDEX_PATH": started.INDEX_PATH,
    }.items():
        monkeypatch.setenv(name, str(value))
    return started


@pytest.fixture
def ctx(env: Settings) -> AppContext:
    return create_app(env).state.ctx


@pytest.fixture
def cid(ctx: AppContext) -> str:
    with closing(ctx.open_app_db()) as db:
        return db.execute(
            "INSERT INTO conversations DEFAULT VALUES RETURNING id"
        ).fetchone()[0]


def rows(path: Path, sql: str) -> list[tuple]:
    with closing(sqlite3.connect(path)) as db:
        return db.execute(sql).fetchall()


def test_command_restores_the_seed_slot_counts(env, ctx, cid, capsys):
    book_visit(ctx, "MHC-10001", 56, ISSUE, cid)
    assert rows(
        env.SCHEDULING_DB_PATH, "SELECT status FROM appointment_slots WHERE slot_id=56"
    ) == [("booked",)]
    capsys.readouterr()
    assert reset.main() == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["restored"] is True
    assert printed["slotCounts"] == SEED_COUNTS
    grouped = dict(
        rows(
            env.SCHEDULING_DB_PATH,
            "SELECT status, count(*) FROM appointment_slots GROUP BY status",
        )
    )
    assert grouped == {"open": 323, "booked": 159, "reserved_members": 42, "blocked": 4}
    assert rows(
        env.SCHEDULING_DB_PATH, "SELECT status FROM appointment_slots WHERE slot_id=56"
    ) == [("open",)]
    assert rows(env.SCHEDULING_DB_PATH, "SELECT count(*) FROM appointments") == [(159,)]


def test_command_leaves_conversations_handoffs_and_waitlist(env, cid):
    with closing(sqlite3.connect(env.APP_DB_PATH)) as db:
        db.execute(
            "INSERT INTO handoffs (conversation_id, kind, reason, intent, told_caller) VALUES (?, 'k', 'r', 'i', 't')",
            (cid,),
        )
        db.execute(
            "INSERT INTO waitlist_entries (conversation_id, customer_id, caller_name, caller_phone, service_type, zone, held_date, held_window) "
            "VALUES (?, 'MHC-10001', 'A', '5125550100', 'hvac_repair', 'north', '2026-10-20', 'morning')",
            (cid,),
        )
        db.commit()
    tables = ("conversations", "handoffs", "waitlist_entries")
    before = [rows(env.APP_DB_PATH, f"SELECT * FROM {t}") for t in tables]
    assert all(len(r) == 1 for r in before)
    assert reset.main() == 0
    after = [rows(env.APP_DB_PATH, f"SELECT * FROM {t}") for t in tables]
    for table, b, a in zip(tables, before, after, strict=True):
        print(f"{table}: before {len(b)} after {len(a)} identical {a == b}")
    print(
        "waitlist held:",
        rows(env.APP_DB_PATH, "SELECT held_date, held_window FROM waitlist_entries"),
    )
    assert after == before


def test_command_retires_the_book_row(env, ctx, cid):
    book_visit(ctx, "MHC-10001", 56, ISSUE, cid)
    sql = "SELECT id, conversation_id, action, appointment_id, slot_id, customer_id, committed_at, retired_at FROM visit_changes"
    (before,) = rows(env.APP_DB_PATH, sql)
    assert before[2] == "book" and before[7] is None
    assert reset.main() == 0
    (after,) = rows(env.APP_DB_PATH, sql)
    assert after[7] is not None
    assert after[:7] == before[:7]


def test_command_takes_a_backup_first(env, ctx, cid, capsys):
    book_visit(ctx, "MHC-10001", 56, ISSUE, cid)
    capsys.readouterr()
    assert reset.main() == 0
    snapshot = json.loads(capsys.readouterr().out)["snapshotId"]
    folder = env.SCHEDULING_DB_PATH.parent / "backups" / snapshot
    assert sorted(p.name for p in folder.iterdir()) == sorted(
        [env.SCHEDULING_DB_PATH.name, env.APP_DB_PATH.name]
    )
    saved = folder / env.SCHEDULING_DB_PATH.name
    assert rows(saved, "SELECT status FROM appointment_slots WHERE slot_id=56") == [
        ("booked",)
    ]
    assert rows(saved, "SELECT count(*) FROM appointments") == [(160,)]
    app_saved = folder / env.APP_DB_PATH.name
    assert rows(app_saved, "SELECT id FROM conversations") == [(cid,)]
    assert rows(app_saved, "SELECT retired_at FROM visit_changes") == [(None,)]


def dump(path: Path) -> dict[str, list[tuple]]:
    return {t: rows(path, f"SELECT * FROM {t} ORDER BY rowid") for t in SUPPLIED_TABLES}


def test_reset_restores_all_five_tables_exactly_and_twice(env, ctx, cid):
    book_visit(ctx, "MHC-10001", 56, ISSUE, cid)
    second = book_visit(ctx, "MHC-10001", 57, ISSUE, cid)
    cancel_visit(ctx, "MHC-10001", second.appointment_id, cid)
    for _ in range(2):
        reset_scheduling(ctx)
        assert dump(env.SCHEDULING_DB_PATH) == dump(SEED)


def test_reset_leaves_the_supplied_schema_as_supplied(env, ctx, cid):
    book_visit(ctx, "MHC-10001", 56, ISSUE, cid)
    reset_scheduling(ctx)
    assert diff_count(env.SCHEDULING_DB_PATH) == 0
    assert rows(env.SCHEDULING_DB_PATH, "PRAGMA journal_mode") == [("delete",)]
    assert rows(env.SCHEDULING_DB_PATH, "PRAGMA user_version") == [(0,)]
    names = {
        n
        for (n,) in rows(
            env.SCHEDULING_DB_PATH, "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert names == set(SUPPLIED_TABLES)


def test_reset_fails_cleanly_without_the_seed(env, ctx, cid):
    book_visit(ctx, "MHC-10001", 56, ISSUE, cid)
    before = env.SCHEDULING_DB_PATH.read_bytes()
    ctx.settings = env.model_copy(
        update={"SEED_DB_PATH": env.SEED_DB_PATH.parent / "missing.sqlite"}
    )
    with pytest.raises(AppError) as error:
        reset_scheduling(ctx)
    assert (error.value.status, error.value.code) == (500, "reset_failed")
    assert env.SCHEDULING_DB_PATH.read_bytes() == before
    assert not (env.SCHEDULING_DB_PATH.parent / "backups").exists()


def test_extended_busy_code_answers_busy(env, ctx, cid, monkeypatch):
    book_visit(ctx, "MHC-10001", 56, ISSUE, cid)
    before = env.SCHEDULING_DB_PATH.read_bytes()
    busy = sqlite3.OperationalError("database is locked")
    busy.sqlite_errorcode = 517  # SQLITE_BUSY_SNAPSHOT

    def locked(conn, seed):
        raise busy

    monkeypatch.setattr("app.scheduling.service._restore", locked)
    with pytest.raises(AppError) as error:
        reset_scheduling(ctx)
    print("status:", error.value.status, "code:", error.value.code)
    assert (error.value.status, error.value.code) == (409, "busy")
    assert env.SCHEDULING_DB_PATH.read_bytes() == before


def test_retire_failure_after_commit_says_the_seed_was_restored(
    env, ctx, cid, monkeypatch
):
    book_visit(ctx, "MHC-10001", 56, ISSUE, cid)

    def broken(ctx):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr("app.scheduling.service._retire_visit_changes", broken)
    with pytest.raises(AppError) as error:
        reset_scheduling(ctx)
    print("status:", error.value.status, "code:", error.value.code)
    print("message:", error.value.message)
    assert (error.value.status, error.value.code) == (500, "reset_failed")
    assert "restored" in error.value.message
    grouped = dict(
        rows(
            env.SCHEDULING_DB_PATH,
            "SELECT status, count(*) FROM appointment_slots GROUP BY status",
        )
    )
    print("slot counts:", grouped)
    assert grouped == {"open": 323, "booked": 159, "reserved_members": 42, "blocked": 4}

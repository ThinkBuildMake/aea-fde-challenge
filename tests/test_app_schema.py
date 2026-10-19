import sqlite3

from app.db import latest_migration_version
from app.settings import Settings
from tests.conftest import MIGRATIONS

EXPECTED_COLUMNS = {
    "visit_changes": [
        "id",
        "conversation_id",
        "action",
        "appointment_id",
        "slot_id",
        "previous_slot_id",
        "customer_id",
        "confirmed_date",
        "confirmed_window",
        "confirmed_technician",
        "late_fee_applied",
        "committed_at",
        "retired_at",
    ],
    "conversations": [
        "id",
        "public_id",
        "started_at",
        "last_activity_at",
        "ended_at",
        "outcome",
        "outcome_reason",
        "intent",
        "customer_id",
        "intents_seen",
        "identify_attempts",
        "resolved_at",
        "solved",
        "solved_at",
        "turn_count",
        "cost_usd",
    ],
    "turns": [
        "id",
        "conversation_id",
        "seq",
        "kind",
        "created_at",
        "caller_text",
        "reply_text",
        "model_messages",
        "safety_verdict",
        "tools_called",
        "retrieved",
        "offered",
        "has_write",
        "latency_ms",
        "error",
        "fallback_used",
        "trace_id",
        "prompt_tokens",
        "completion_tokens",
        "cost_usd",
        "cost_source",
    ],
    "handoffs": [
        "id",
        "conversation_id",
        "kind",
        "reason",
        "by_error",
        "customer_id",
        "caller_name",
        "caller_phone",
        "stated_by_caller",
        "intent",
        "told_caller",
        "summary_source",
        "preferred_window",
        "status",
        "created_at",
        "followed_up_at",
    ],
    "waitlist_entries": [
        "id",
        "conversation_id",
        "customer_id",
        "caller_name",
        "caller_phone",
        "service_type",
        "zone",
        "held_date",
        "held_window",
        "created_at",
    ],
    "flags": ["id", "conversation_id", "note", "created_at"],
    "eval_candidates": [
        "id",
        "conversation_id",
        "scenario_id",
        "scenario",
        "created_at",
    ],
}


def test_fresh_start_creates_the_seven_app_tables_with_their_columns(started: Settings):
    conn = sqlite3.connect(started.APP_DB_PATH)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    assert tables == set(EXPECTED_COLUMNS)
    for table, columns in EXPECTED_COLUMNS.items():
        actual = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
        assert actual == columns, table
    conn.close()


def test_schema_version_is_the_latest_migration(started: Settings):
    conn = sqlite3.connect(started.APP_DB_PATH)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    assert version == latest_migration_version(MIGRATIONS)
    assert version == 1


def test_app_connection_enforces_foreign_keys_and_uses_wal(started: Settings):
    from app.db import connect_app_db

    conn = connect_app_db(started.APP_DB_PATH)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    conn.close()

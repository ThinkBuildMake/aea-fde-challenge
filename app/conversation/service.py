import sqlite3
from datetime import datetime

from app.context import AppContext


def close_idle_conversations(ctx: AppContext, now: datetime) -> int:
    """Stub: closes nothing."""
    return 0


def end_with_handoff(tx: sqlite3.Connection, conversation_id: str) -> None:
    """Set the handoff outcome in the caller's transaction, once."""
    tx.execute(
        "UPDATE conversations SET outcome = 'handoff', "
        "ended_at = strftime('%Y-%m-%dT%H:%M:%fZ','now'), "
        "last_activity_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
        "WHERE id = ? AND outcome IS NULL",
        (conversation_id,),
    )

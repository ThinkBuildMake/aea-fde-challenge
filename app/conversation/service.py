import sqlite3
from datetime import datetime

from app.context import AppContext


def close_idle_conversations(ctx: AppContext, now: datetime) -> int:
    """Stub: closes nothing."""
    return 0


def end_with_handoff(tx: sqlite3.Connection, conversation_id: str) -> None:
    """Stub: no-op."""

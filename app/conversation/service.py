import sqlite3
from datetime import UTC, datetime, timedelta

from app.context import AppContext


def _stamp(moment: datetime) -> str:
    """Format like every stored timestamp, so strings compare in time order."""
    utc = moment.astimezone(UTC)
    return utc.isoformat(timespec="milliseconds").replace("+00:00", "Z")


_CONTAINED = (
    "turn_count > 0 AND resolved_at IS NOT NULL AND NOT EXISTS "
    "(SELECT 1 FROM handoffs h WHERE h.conversation_id = conversations.id)"
)


def close_idle_conversations(ctx: AppContext, now: datetime) -> int:
    """Give every conversation idle past the limit its outcome; return how many.

    One guarded UPDATE: only rows with no outcome change, never an ended one.
    Errors propagate; the caller decides what a failed sweep means.
    """
    cutoff = _stamp(now - timedelta(minutes=ctx.settings.IDLE_CLOSE_MINUTES))
    conn = ctx.open_app_db()
    try:
        cursor = conn.execute(
            "UPDATE conversations SET "
            "outcome = CASE WHEN turn_count = 0 THEN 'failed' "
            f"WHEN {_CONTAINED} THEN 'contained' ELSE 'failed' END, "
            "outcome_reason = CASE WHEN turn_count = 0 THEN 'no_message' "
            f"WHEN {_CONTAINED} THEN NULL ELSE 'idle_unresolved' END, "
            "ended_at = ? "
            "WHERE outcome IS NULL AND last_activity_at < ?",
            (_stamp(now), cutoff),
        )
        return cursor.rowcount
    finally:
        conn.close()


def end_with_handoff(tx: sqlite3.Connection, conversation_id: str) -> None:
    """Set the handoff outcome in the caller's transaction, once."""
    tx.execute(
        "UPDATE conversations SET outcome = 'handoff', "
        "ended_at = strftime('%Y-%m-%dT%H:%M:%fZ','now'), "
        "last_activity_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
        "WHERE id = ? AND outcome IS NULL",
        (conversation_id,),
    )

import sqlite3
from contextlib import closing
from typing import Literal

from app.context import AppContext
from app.conversation.service import end_with_handoff
from app.scheduling import store as scheduling_store
from app.scheduling.store import zone_for_city
from app.types import (
    CallbackWindow,
    HandoffCaller,
    HandoffRecord,
    HandoffView,
    HeldWindow,
    JoinWaitlistResult,
    WaitlistCaller,
    WaitlistRequest,
    WaitlistView,
)


class NoHandoff(Exception):
    """The conversation has no handoff."""


class HandoffNotFound(Exception):
    """No handoff has this id."""


def placeholder_handoff(
    conversation_public_id: str = "stub", window: CallbackWindow | None = None
) -> HandoffView:
    return HandoffView(
        id=0,
        conversation_public_id=conversation_public_id,
        kind="handoff",
        reason="stub",
        by_error=False,
        caller=HandoffCaller(
            customer_id=None,
            name=None,
            phone=None,
            city=None,
            zone=None,
            stated_by_caller=False,
        ),
        intent="unknown",
        told_caller="stub",
        summary="stub: stub",
        summary_source="system",
        preferred_window=window,
        status="open",
        created_at="1970-01-01T00:00:00.000Z",
        followed_up_at=None,
    )


SUPERVISOR_REASONS = frozenset(
    {"billing_dispute", "refund_demand", "complaint", "manager_request"}
)
FALLBACK_REASONS = frozenset({"provider_failure", "scheduling_unavailable"})

_COLUMNS = (
    "h.id, c.public_id, h.kind, h.reason, h.by_error, h.customer_id, h.caller_name, "
    "h.caller_phone, h.stated_by_caller, h.intent, h.told_caller, h.summary_source, "
    "h.preferred_window, h.status, h.created_at, h.followed_up_at"
)


def _customer(ctx: AppContext, customer_id: str) -> tuple[str, str, str] | None:
    with closing(scheduling_store.connect(ctx)) as scheduling:
        row = scheduling.execute(
            "SELECT name, phone, city FROM customers WHERE customer_id = ?",
            (customer_id,),
        ).fetchone()
    return None if row is None else (row[0], row[1], row[2])


def _views(
    tx: sqlite3.Connection, where: str, params: tuple, ctx: AppContext | None
) -> list[HandoffView]:
    rows = tx.execute(
        f"SELECT {_COLUMNS} FROM handoffs h JOIN conversations c "
        f"ON c.id = h.conversation_id WHERE {where} ORDER BY h.created_at, h.id",
        params,
    ).fetchall()
    views = []
    for row in rows:
        customer_id: str | None = row[5]
        city: str | None = None
        if ctx is not None and customer_id is not None:
            found = _customer(ctx, customer_id)
            city = None if found is None else found[2]
        views.append(
            HandoffView(
                id=row[0],
                conversation_public_id=row[1],
                kind=row[2],
                reason=row[3],
                by_error=bool(row[4]),
                caller=HandoffCaller(
                    customer_id=customer_id,
                    name=row[6],
                    phone=row[7],
                    city=city,
                    zone=None if city is None else zone_for_city(city),
                    stated_by_caller=bool(row[8]),
                ),
                intent=row[9],
                told_caller=row[10],
                summary=f"{row[3]}: {row[10]}",
                summary_source=row[11],
                preferred_window=row[12],
                status=row[13],
                created_at=row[14],
                followed_up_at=row[15],
            )
        )
    return views


def _view(
    tx: sqlite3.Connection, conversation_id: str, ctx: AppContext | None
) -> HandoffView | None:
    views = _views(tx, "h.conversation_id = ?", (conversation_id,), ctx)
    return views[0] if views else None


def list_handoffs(
    ctx: AppContext, status: Literal["open", "followed_up"]
) -> list[HandoffView]:
    """Handoffs with this status, oldest first."""
    with closing(ctx.open_app_db()) as conn:
        return _views(conn, "h.status = ?", (status,), ctx)


def mark_handoff_followed_up(
    ctx: AppContext, handoff_id: int, followed_up: bool
) -> HandoffView:
    """open -> followed_up (once), or the undo followed_up -> open; otherwise no change."""
    with closing(ctx.open_app_db()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            if followed_up:
                conn.execute(
                    "UPDATE handoffs SET status = 'followed_up', "
                    "followed_up_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                    "WHERE id = ? AND status = 'open'",
                    (handoff_id,),
                )
            else:
                conn.execute(
                    "UPDATE handoffs SET status = 'open', followed_up_at = NULL "
                    "WHERE id = ? AND status = 'followed_up'",
                    (handoff_id,),
                )
            views = _views(conn, "h.id = ?", (handoff_id,), ctx)
            if not views:
                raise HandoffNotFound(handoff_id)
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        return views[0]


def create_handoff(
    tx: sqlite3.Connection, record: HandoffRecord, ctx: AppContext | None = None
) -> HandoffView:
    """Write the handoff in the caller's open transaction; a second call returns the first."""
    name, phone, stated = (
        record.stated_name,
        record.stated_phone,
        bool(record.stated_name or record.stated_phone),
    )
    if record.customer_id is not None:
        stated = False
        name = phone = None
        if ctx is not None and (found := _customer(ctx, record.customer_id)):
            name, phone = found[0], found[1]
    kind = "supervisor_callback" if record.reason in SUPERVISOR_REASONS else record.kind
    tx.execute(
        "INSERT INTO handoffs (conversation_id, kind, reason, by_error, customer_id, "
        "caller_name, caller_phone, stated_by_caller, intent, told_caller, "
        "summary_source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (conversation_id) DO NOTHING",
        (
            record.conversation_id,
            kind,
            record.reason,
            int(record.by_error),
            record.customer_id,
            name,
            phone,
            int(stated),
            record.intent or "unknown",
            record.told_caller,
            record.summary_source,
        ),
    )
    view = _view(tx, record.conversation_id, ctx)
    if view is None:
        raise sqlite3.OperationalError("handoff row missing after insert")
    return view


def set_callback_window(
    ctx: AppContext, conversation_id: str, window: CallbackWindow
) -> HandoffView:
    """Set the window; after a provider fallback with no handoff, record one first."""
    conn = ctx.open_app_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            if (
                conn.execute(
                    "SELECT 1 FROM handoffs WHERE conversation_id = ?",
                    (conversation_id,),
                ).fetchone()
                is None
            ):
                _handoff_after_fallback(conn, ctx, conversation_id)
            conn.execute(
                "UPDATE handoffs SET preferred_window = ? WHERE conversation_id = ?",
                (window, conversation_id),
            )
            view = _view(conn, conversation_id, ctx)
            if view is None:
                raise NoHandoff(conversation_id)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        return view
    finally:
        conn.close()


def _handoff_after_fallback(
    conn: sqlite3.Connection, ctx: AppContext, conversation_id: str
) -> None:
    last = conn.execute(
        "SELECT t.fallback_used, t.error, t.reply_text, c.customer_id, c.intent "
        "FROM conversations c JOIN turns t ON t.conversation_id = c.id "
        "WHERE c.id = ? ORDER BY t.seq DESC LIMIT 1",
        (conversation_id,),
    ).fetchone()
    if last is None or not last[0]:
        raise NoHandoff(conversation_id)
    reason = (
        "scheduling_unavailable"
        if last[1] == "scheduling_unavailable"
        else "provider_failure"
    )
    create_handoff(
        conn,
        HandoffRecord(
            conversation_id=conversation_id,
            kind="handoff",
            reason=reason,
            by_error=True,
            customer_id=last[3],
            intent=last[4],
            told_caller=last[2],
            summary_source="system",
        ),
        ctx,
    )
    end_with_handoff(conn, conversation_id)


_WAITLIST_COLUMNS = (
    "w.id, c.public_id, w.customer_id, w.caller_name, w.caller_phone, w.service_type, "
    "w.zone, w.held_date, w.held_window, w.created_at, "
    "CAST((julianday('now') - julianday(w.created_at)) * 86400 AS INTEGER)"
)
_UNIQUE_KEY = (
    "w.customer_id = ? AND w.service_type = ? AND w.held_date = ? AND w.held_window = ?"
)


def _waitlist_views(
    conn: sqlite3.Connection, ctx: AppContext, where: str, params: tuple
) -> list[WaitlistView]:
    rows = conn.execute(
        f"SELECT {_WAITLIST_COLUMNS} FROM waitlist_entries w JOIN conversations c "
        f"ON c.id = w.conversation_id WHERE {where} ORDER BY w.created_at, w.id",
        params,
    ).fetchall()
    views = []
    for row in rows:
        found = _customer(ctx, row[2])
        views.append(
            WaitlistView(
                id=row[0],
                conversation_public_id=row[1],
                caller=WaitlistCaller(
                    customer_id=row[2],
                    name=row[3],
                    phone=row[4],
                    city="" if found is None else found[2],
                ),
                service_type=row[5],
                zone=row[6],
                held=HeldWindow(date=row[7], window=row[8]),
                created_at=row[9],
                waiting_seconds=max(row[10], 0),
            )
        )
    return views


def list_waitlist(ctx: AppContext) -> list[WaitlistView]:
    """Every waitlist entry, oldest first."""
    with closing(ctx.open_app_db()) as conn:
        return _waitlist_views(conn, ctx, "1 = 1", ())


def join_waitlist(ctx: AppContext, entry: WaitlistRequest) -> JoinWaitlistResult:
    """Record a copy of the held window; asking again for the same visit returns the entry."""
    found = _customer(ctx, entry.customer_id)
    if found is None:
        raise ValueError("customer not found")
    key = (
        entry.customer_id,
        entry.service_type,
        entry.held_date,
        entry.held_window,
    )
    with closing(ctx.open_app_db()) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                "INSERT INTO waitlist_entries (conversation_id, customer_id, "
                "caller_name, caller_phone, service_type, zone, held_date, held_window) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (customer_id, "
                "service_type, held_date, held_window) DO NOTHING",
                (
                    entry.conversation_id,
                    entry.customer_id,
                    found[0],
                    found[1],
                    entry.service_type,
                    entry.zone,
                    entry.held_date,
                    entry.held_window,
                ),
            )
            created = cursor.rowcount == 1
            view = _waitlist_views(conn, ctx, _UNIQUE_KEY, key)[0]
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    return JoinWaitlistResult(entry=view, created=created)

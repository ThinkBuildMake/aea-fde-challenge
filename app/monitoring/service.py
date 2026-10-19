import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal

from app.context import AppContext
from app.conversation.service import close_idle_conversations
from app.knowledge.service import index_status
from app.logs import log_event
from app.scheduling.service import scheduling_status
from app.types import (
    DayCount,
    Guarantee,
    Health,
    HealthComponents,
    Outcomes,
    Overview,
    OverviewSpend,
    OverviewStatus,
    OverviewSuccess,
    OverviewSupporting,
    OverviewVolume,
    SeriesPoint,
)


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def app_db_status(ctx: AppContext) -> Literal["ok", "error"]:
    try:
        db = ctx.open_app_db()
        try:
            db.execute("SELECT 1 FROM conversations LIMIT 1")
        finally:
            db.close()
    except sqlite3.Error:
        return "error"
    return "ok"


def get_health(ctx: AppContext) -> Health:
    """ok only when the scheduling DB, the app DB and the index are all healthy; reads only."""
    components = HealthComponents(
        scheduling_db="ok" if scheduling_status(ctx) == "ok" else "error",
        app_db=app_db_status(ctx),
        index="loaded" if index_status(ctx).loaded else "missing",
    )
    healthy = (components.scheduling_db, components.app_db, components.index) == (
        "ok",
        "ok",
        "loaded",
    )
    return Health(status="ok" if healthy else "degraded", components=components)


HANDLED_INTENTS = (
    "book_visit",
    "change_visit",
    "policy_question",
    "warranty_question",
    "membership_question",
    "billing_lookup",
)
IN_WINDOW = "started_at >= ? AND turn_count > 0"


def _stamp(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _pct(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def _guarded[T](name: str, fn: Callable[[], T], fallback: T) -> T:
    """Run one figure's queries; a database error leaves only that figure empty."""
    try:
        return fn()
    except sqlite3.Error:
        log_event("overview_query_failed", figure=name)
        return fallback


def _status(db: sqlite3.Connection, now: datetime) -> tuple[str | None, int, int]:
    last = db.execute(
        "SELECT MAX(last_activity_at) FROM conversations WHERE turn_count > 0"
    ).fetchone()[0]
    errors = db.execute(
        "SELECT COUNT(*) FROM turns WHERE fallback_used = 1 AND created_at >= ?",
        (_stamp(now - timedelta(hours=24)),),
    ).fetchone()[0]
    waiting = db.execute(
        "SELECT COUNT(*) FROM handoffs WHERE status = 'open'"
    ).fetchone()[0]
    return last, errors, waiting


def _success(
    db: sqlite3.Connection, since: str
) -> tuple[int, int, dict[str, float | None]]:
    rows = db.execute(
        "SELECT substr(started_at, 1, 10), COUNT(*), "
        "SUM(outcome = 'contained' AND solved = 'yes') "
        f"FROM conversations WHERE {IN_WINDOW} GROUP BY 1",
        (since,),
    ).fetchall()
    by_day = {day: _pct(settled or 0, total) for day, total, settled in rows}
    return (
        sum(settled or 0 for _, _, settled in rows),
        sum(total for _, total, _ in rows),
        by_day,
    )


def _booking_completion(db: sqlite3.Connection, since: str) -> float | None:
    wanted, booked = db.execute(
        "SELECT COUNT(*), COALESCE(SUM(EXISTS (SELECT 1 FROM visit_changes v "
        "WHERE v.conversation_id = c.id AND v.action = 'book')), 0) "
        f"FROM conversations c WHERE {IN_WINDOW} AND EXISTS "
        "(SELECT 1 FROM json_each(c.intents_seen) WHERE value = 'book_visit')",
        (since,),
    ).fetchone()
    return _pct(booked, wanted)


def _handled_topics(
    db: sqlite3.Connection, since: str
) -> tuple[float | None, str | None]:
    marks = ",".join("?" * len(HANDLED_INTENTS))
    handled, handed = db.execute(
        "SELECT COUNT(*), COALESCE(SUM(outcome = 'handoff'), 0) FROM conversations "
        f"WHERE {IN_WINDOW} AND intent IN ({marks})",
        (since, *HANDLED_INTENTS),
    ).fetchone()
    top = db.execute(
        "SELECT h.reason FROM handoffs h JOIN conversations c ON c.id = h.conversation_id "
        f"WHERE {IN_WINDOW} "
        f"AND c.outcome = 'handoff' AND c.intent IN ({marks}) "
        "GROUP BY h.reason ORDER BY COUNT(*) DESC, h.reason LIMIT 1",
        (since, *HANDLED_INTENTS),
    ).fetchone()
    return _pct(handed, handled), top[0] if top else None


def _flagged_wrong(db: sqlite3.Connection, since: str) -> float | None:
    contained, flagged = db.execute(
        "SELECT COUNT(*), COALESCE(SUM(EXISTS (SELECT 1 FROM flags f "
        "WHERE f.conversation_id = c.id)), 0) FROM conversations c "
        f"WHERE {IN_WINDOW} AND outcome = 'contained'",
        (since,),
    ).fetchone()
    return _pct(flagged, contained)


def _volume(db: sqlite3.Connection, since: str) -> tuple[dict[str, int], Outcomes]:
    per_day = dict(
        db.execute(
            "SELECT substr(started_at, 1, 10), COUNT(*) FROM conversations "
            f"WHERE {IN_WINDOW} GROUP BY 1",
            (since,),
        ).fetchall()
    )
    counts = dict(
        db.execute(
            "SELECT COALESCE(outcome, 'active'), COUNT(*) FROM conversations "
            f"WHERE {IN_WINDOW} GROUP BY 1",
            (since,),
        ).fetchall()
    )
    return per_day, Outcomes(
        contained=counts.get("contained", 0),
        handoff=counts.get("handoff", 0),
        safety_stop=counts.get("safety_stop", 0),
        failed=counts.get("failed", 0),
        active=counts.get("active", 0),
    )


def get_overview(
    ctx: AppContext, days: int = 7, now: datetime | None = None
) -> Overview:
    """Compute the business view from the app tables on every request."""
    s = ctx.settings
    now = now or datetime.now(UTC)
    try:
        close_idle_conversations(ctx, now)
    except sqlite3.Error:
        log_event("overview_close_idle_failed")
    dates = [
        (now - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d") for i in range(days)
    ]
    since = f"{dates[0]}T00:00:00.000Z"
    db = ctx.open_app_db()
    try:
        last, errors, waiting = _guarded(
            "status", lambda: _status(db, now), (None, 0, 0)
        )
        settled, total, series = _guarded(
            "success", lambda: _success(db, since), (0, 0, {})
        )
        booking = _guarded(
            "booking_completion", lambda: _booking_completion(db, since), None
        )
        handled, top_reason = _guarded(
            "handled_topics", lambda: _handled_topics(db, since), (None, None)
        )
        flagged = _guarded("flagged_wrong", lambda: _flagged_wrong(db, since), None)
        per_day, outcomes = _guarded(
            "volume",
            lambda: _volume(db, since),
            ({}, Outcomes(contained=0, handoff=0, safety_stop=0, failed=0, active=0)),
        )
    finally:
        db.close()
    return Overview(
        as_of=now_iso(),
        status=OverviewStatus(
            public_url=s.PUBLIC_URL,
            last_conversation_at=last,
            errorsShown24h=errors,
            handoffs_waiting=waiting,
        ),
        success=OverviewSuccess(
            settled_pct=_pct(settled, total),
            settled_count=settled,
            total_count=total,
            target_band_pct=[60, 75],
            series=[SeriesPoint(date=d, settled_pct=series.get(d)) for d in dates],
        ),
        supporting=OverviewSupporting(
            booking_completion_pct=booking,
            handoffs_on_handled_topics_pct=handled,
            top_handoff_reason=top_reason,
            flagged_wrong_pct=flagged,
        ),
        volume=OverviewVolume(
            conversations_by_day=[
                DayCount(date=d, count=per_day.get(d, 0)) for d in dates
            ],
            outcomes=outcomes,
        ),
        recent=[],
        guarantees=[
            Guarantee(
                key="PF-1",
                name="Time to first reply",
                now=None,
                limit=6000,
                status="no_data",
            )
        ],
        latency_series_24h=[],
        spend=OverviewSpend(total_usd=None, alert_usd=s.SPEND_ALERT_USD, alert=False),
    )

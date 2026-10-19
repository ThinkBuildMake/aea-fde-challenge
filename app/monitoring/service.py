import math
import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime, timedelta
from typing import Literal

from app.context import AppContext
from app.conversation.service import _stamp, close_idle_conversations
from app.knowledge.service import index_status
from app.logs import log_event
from app.monitoring.agreement import booking_mismatches
from app.scheduling.service import scheduling_status
from app.scheduling.store import SchedulingUnavailable, connect, zone_for_city
from app.types import (
    DayCount,
    Guarantee,
    Health,
    HealthComponents,
    LatencyPoint,
    Outcomes,
    Overview,
    OverviewSpend,
    OverviewStatus,
    OverviewSuccess,
    OverviewSupporting,
    OverviewVolume,
    RecentConversation,
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


def _pct(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def _guarded[T](name: str, fn: Callable[[], T], fallback: T) -> T:
    """Run one figure's queries; a database error leaves only that figure empty."""
    try:
        return fn()
    except (sqlite3.Error, SchedulingUnavailable):
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


PF1_LIMIT_MS = 6000  # PF-1: p95 first reply at most 6 s
PF2_LIMIT_MS = 10000  # PF-2: p95 turn that writes at most 10 s
VR_LIMIT = 0  # VR-6/7/8: no booking disagreeing with the database
DE1_LIMIT = 0  # DE-1: no unhandled error shown to a caller
FALLBACK_LIMIT_MS = 15000  # DE-1: the fallback reply arrives within 15 s
RECENT_COUNT = 5


def read_total_spend(ctx: AppContext) -> float | None:
    """Total model spend in USD: provider key usage plus the manual OpenAI line."""
    usage = ctx.spend.total()
    return None if usage is None else usage + ctx.settings.OPENAI_SPEND_USD


def _p95(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def _first_reply_times(db: sqlite3.Connection, since: str) -> list[tuple[str, int]]:
    return db.execute(
        "SELECT created_at, latency_ms FROM turns WHERE seq = 1 AND kind = 'message' "
        "AND created_at >= ?",
        (since,),
    ).fetchall()


def _write_turn_p95(db: sqlite3.Connection, since: str) -> int | None:
    return _p95(
        [
            ms
            for (ms,) in db.execute(
                "SELECT latency_ms FROM turns WHERE has_write = 1 AND kind = 'message' "
                "AND created_at >= ?",
                (since,),
            )
        ]
    )


def _late_fallbacks(db: sqlite3.Connection, since: str) -> int:
    return db.execute(
        "SELECT COUNT(*) FROM turns WHERE fallback_used = 1 AND latency_ms > ? "
        "AND created_at >= ?",
        (FALLBACK_LIMIT_MS, since),
    ).fetchone()[0]


def _latency_series(
    replies: list[tuple[str, int]], now: datetime
) -> list[LatencyPoint]:
    """One p95 point per hour for 24 hours, oldest first, ending in the current hour."""
    top = now.replace(minute=0, second=0, microsecond=0)
    hours = [top - timedelta(hours=23 - i) for i in range(24)]
    starts = [_stamp(h) for h in hours]
    buckets: list[list[int]] = [[] for _ in hours]
    for at, ms in replies:
        for i in range(23, -1, -1):
            if at >= starts[i]:
                buckets[i].append(ms)
                break
    return [
        LatencyPoint(hour=start, p95_first_reply_ms=_p95(b))
        for start, b in zip(starts, buckets, strict=True)
    ]


def _recent(ctx: AppContext, db: sqlite3.Connection) -> list[RecentConversation]:
    rows = db.execute(
        "SELECT c.id, c.started_at, c.intent, c.outcome, c.customer_id, "
        "(SELECT latency_ms FROM turns t WHERE t.conversation_id = c.id "
        "AND t.seq = 1 AND t.kind = 'message') FROM conversations c "
        "WHERE c.turn_count > 0 ORDER BY c.started_at DESC, c.rowid DESC LIMIT ?",
        (RECENT_COUNT,),
    ).fetchall()
    cities: dict[str, str] = {}
    ids = [r[4] for r in rows if r[4]]
    if ids:
        try:
            with closing(connect(ctx)) as sched:
                cities = dict(
                    sched.execute(
                        "SELECT customer_id, city FROM customers WHERE customer_id IN "
                        f"({','.join('?' * len(ids))})",
                        ids,
                    )
                )
        except (sqlite3.Error, SchedulingUnavailable):
            log_event("overview_query_failed", figure="recent_zones")
    return [
        RecentConversation(
            public_id=cid,
            started_at=started,
            intent=intent,
            zone=zone_for_city(cities[cust]) if cust in cities else None,
            outcome=outcome,
            latency_ms=ms,
        )
        for cid, started, intent, outcome, cust, ms in rows
    ]


def _guarantee(
    key: str, name: str, value: float | None, limit: float, *, at_limit: bool = False
) -> Guarantee:
    if value is None:
        status = "no_data"
    else:
        status = "breach" if (value >= limit if at_limit else value > limit) else "ok"
    return Guarantee(key=key, name=name, now=value, limit=limit, status=status)


def get_overview(
    ctx: AppContext, days: int = 7, now: datetime | None = None
) -> Overview:
    """Compute the business view from the app tables on every request."""
    s = ctx.settings
    now = now or datetime.now(UTC)
    try:
        close_idle_conversations(ctx, now)
    except Exception as exc:  # noqa: BLE001 - the overview must still render
        log_event("overview_close_idle_failed", error=type(exc).__name__)
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
        day_ago = _stamp(now - timedelta(hours=24))
        replies = _guarded("first_replies", lambda: _first_reply_times(db, day_ago), [])
        write_p95 = _guarded("write_turns", lambda: _write_turn_p95(db, day_ago), None)
        late = _guarded("late_fallbacks", lambda: _late_fallbacks(db, day_ago), None)
        recent = _guarded("recent", lambda: _recent(ctx, db), [])
    finally:
        db.close()
    mismatches = _guarded(
        "booking_agreement", lambda: float(booking_mismatches(ctx)), None
    )
    spend = read_total_spend(ctx)
    first_p95 = _p95([ms for _, ms in replies])
    return Overview(
        as_of=now_iso(),
        status=OverviewStatus(
            public_url=s.PUBLIC_URL,
            last_conversation_at=last,
            errors_shown_24h=errors,
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
        recent=recent,
        guarantees=[
            _guarantee("PF-1", "Time to first reply", first_p95, PF1_LIMIT_MS),
            _guarantee(
                "PF-2",
                "Time for a turn that books, moves or cancels",
                write_p95,
                PF2_LIMIT_MS,
            ),
            _guarantee("VR-6/7/8", "Booking mismatches", mismatches, VR_LIMIT),
            _guarantee("DE-1", "Errors shown to callers", late, DE1_LIMIT),
            _guarantee(
                "CO-1",
                "Total model spend",
                spend,
                s.SPEND_ALERT_USD,
                at_limit=True,
            ),
        ],
        latency_series_24h=_latency_series(replies, now),
        spend=OverviewSpend(
            total_usd=spend,
            alert_usd=s.SPEND_ALERT_USD,
            alert=spend is not None and spend >= s.SPEND_ALERT_USD,
        ),
    )

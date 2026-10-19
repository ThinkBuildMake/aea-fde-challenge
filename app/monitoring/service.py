import sqlite3
from datetime import UTC, datetime
from typing import Literal

from app.context import AppContext
from app.knowledge.service import index_status
from app.scheduling.service import scheduling_status
from app.types import (
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


def get_overview(ctx: AppContext) -> Overview:
    """Stub: nulls, zeros and empty lists."""
    s = ctx.settings
    return Overview(
        as_of=now_iso(),
        status=OverviewStatus(
            public_url=s.PUBLIC_URL,
            last_conversation_at=None,
            errors_shown_24h=0,
            handoffs_waiting=0,
        ),
        success=OverviewSuccess(
            settled_pct=None,
            settled_count=0,
            total_count=0,
            target_band_pct=[60, 75],
            series=[],
        ),
        supporting=OverviewSupporting(
            booking_completion_pct=None,
            handoffs_on_handled_topics_pct=None,
            top_handoff_reason=None,
            flagged_wrong_pct=None,
        ),
        volume=OverviewVolume(
            conversations_by_day=[],
            outcomes=Outcomes(
                contained=0, handoff=0, safety_stop=0, failed=0, active=0
            ),
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

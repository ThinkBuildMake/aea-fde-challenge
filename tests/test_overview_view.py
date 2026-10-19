from app.monitoring import view
from app.types import (
    DayCount,
    Guarantee,
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

AS_OF = "2026-10-16T17:00:00.000Z"


def at(minutes: int) -> str:
    return f"2026-10-16T{(17 * 60 - minutes) // 60:02d}:{(17 * 60 - minutes) % 60:02d}:00.000Z"


def make(**changes) -> Overview:
    base = Overview(
        as_of=AS_OF,
        status=OverviewStatus(
            public_url="https://x.example",
            last_conversation_at=at(3),
            errors_shown_24h=2,
            handoffs_waiting=1,
        ),
        success=OverviewSuccess(
            settled_pct=62,
            settled_count=171,
            total_count=276,
            target_band_pct=[60, 75],
            series=[
                SeriesPoint(date=f"2026-10-{10 + i}", settled_pct=v)
                for i, v in enumerate([54, 58, 61, 57, 63, 66, 62])
            ],
        ),
        supporting=OverviewSupporting(
            booking_completion_pct=88,
            handoffs_on_handled_topics_pct=7,
            top_handoff_reason="no matching document",
            flagged_wrong_pct=2,
        ),
        volume=OverviewVolume(
            conversations_by_day=[
                DayCount(date=f"2026-10-{10 + i}", count=c)
                for i, c in enumerate([3, 5, 2, 4, 6, 1, 2])
            ],
            outcomes=Outcomes(
                contained=6, handoff=3, safety_stop=1, failed=2, active=1
            ),
        ),
        recent=[
            RecentConversation(
                public_id="a",
                started_at=at(21),
                intent="safety",
                zone=None,
                outcome="safety_stop",
                latency_ms=2100,
            ),
            RecentConversation(
                public_id="b",
                started_at=at(3),
                intent="book_visit",
                zone="central",
                outcome="contained",
                latency_ms=4100,
            ),
        ],
        guarantees=[
            Guarantee(key="PF-1", name="x", now=7200, limit=6000, status="breach"),
            Guarantee(key="PF-2", name="x", now=7900, limit=10000, status="ok"),
            Guarantee(key="VR-6", name="x", now=0, limit=0, status="ok"),
            Guarantee(key="DE-1", name="x", now=0, limit=0, status="ok"),
            Guarantee(key="CO-1", name="x", now=104, limit=100, status="ok"),
        ],
        latency_series_24h=[
            LatencyPoint(hour=f"{i:02d}", p95_first_reply_ms=3000) for i in range(24)
        ],
        spend=OverviewSpend(total_usd=104.0, alert_usd=100.0, alert=True),
    )
    return base.model_copy(update=changes)


def test_relative_times():
    assert view.ago(AS_OF, at(3)) == "3 minutes ago"
    assert view.ago(AS_OF, at(1)) == "1 minute ago"
    assert view.ago(AS_OF, AS_OF) == "Just now"
    assert view.ago(AS_OF, None) == "No conversations yet"
    assert view.ago(AS_OF, at(90)) == "1 hour ago"
    assert view.short_ago(AS_OF, at(3)) == "3 min"


def test_formatting():
    assert view.money(104.0) == "$104"
    assert view.money(38.5) == "$38.50"
    assert view.money(None) == "unknown"
    assert view.pct(62.0) == "62%"
    assert view.seconds(4100) == "4.1 s"


def test_guarantee_rows_in_wireframe_order():
    rows = view.overview_view(make())["guarantees"]
    assert [r["limit"] for r in rows] == [
        "at most 6 s",
        "at most 10 s",
        "0",
        "0",
        "alert at $100",
    ]
    assert [r["status"] for r in rows] == ["Over limit"] + ["Within limit"] * 4
    assert rows[2]["name"] == "Booking mismatches (daily check)"


def test_recent_newest_first():
    rows = view.overview_view(make())["recent"]
    assert [r["when"] for r in rows] == ["3 min", "21 min"]
    assert rows[0]["what"] == "Book a visit, central zone"
    assert rows[1]["outcome"] == "Safety stop"


def test_chart_geometry():
    pts = view.line_points([54, 58, 61, 57, 63, 66, 62], 40, 500, 10, 140, 100)
    assert len(pts.split()) == 7 and pts.startswith("40.0,69.8")
    assert view.band(60, 75) == (42.5, 19.5, 53.5)


def test_spend_line_and_banner():
    v = view.overview_view(make())
    assert v["spend_line"] == "Total model spend: $104 of the $100 alert."
    assert v["banner"]

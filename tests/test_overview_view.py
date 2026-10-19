import pytest

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


def make_overview(**changes) -> Overview:
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
            settled_count=143,
            total_count=231,
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
                public_id="c",
                started_at=at(12),
                intent="billing_dispute",
                zone=None,
                outcome="handoff",
                latency_ms=3300,
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
            Guarantee(key="CO-1", name="x", now=38, limit=100, status="ok"),
        ],
        latency_series_24h=[
            LatencyPoint(hour=f"{i:02d}", p95_first_reply_ms=3000) for i in range(24)
        ],
        spend=OverviewSpend(total_usd=38.0, alert_usd=100.0, alert=False),
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
    assert view.money(99.999) == "$100"
    assert view.money(99.994) == "$99.99"
    assert view.pct(None) == "No data yet"
    assert view.seconds(None) == "No data yet"
    assert view.pct(62.0) == "62%"
    assert view.seconds(4100) == "4.1 s"


def test_guarantee_rows_in_wireframe_order():
    rows = view.overview_view(make_overview())["guarantees"]
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
    rows = view.overview_view(make_overview())["recent"]
    assert [r["when"] for r in rows] == ["3 min", "12 min", "21 min"]
    assert rows[0]["what"] == "Book a visit, central zone"
    assert [r["outcome"] for r in rows] == ["Contained", "Handoff", "Safety stop"]


def test_chart_geometry():
    pts = view.line_points([54, 58, 61, 57, 63, 66, 62], 40, 500, 10, 140, 100)
    assert len(pts.split()) == 7 and pts.startswith("40.0,69.8")
    assert view.band(60, 75) == (42.5, 19.5, 53.5)


def over_spend() -> Overview:
    base = make_overview()
    guarantees = [
        g.model_copy(update={"now": 104, "status": "breach"}) if g.key == "CO-1" else g
        for g in base.guarantees
    ]
    return make_overview(
        guarantees=guarantees,
        spend=OverviewSpend(total_usd=104.0, alert_usd=100.0, alert=True),
    )


def test_spend_line_and_banner():
    v = view.overview_view(over_spend())
    assert v["spend_line"] == "Total model spend: $104 of the $100 alert."
    assert v["banner"]
    assert v["guarantees"][-1]["status"] == "Over limit"
    assert view.overview_view(make_overview())["banner"] is None


def test_all_vr_guarantees_fold_into_one_row():
    gs = [
        Guarantee(key="PF-1", name="x", now=1000, limit=6000, status="ok"),
        Guarantee(key="PF-2", name="x", now=1000, limit=10000, status="ok"),
        Guarantee(key="VR-6", name="x", now=1, limit=0, status="breach"),
        Guarantee(key="VR-7", name="x", now=2, limit=0, status="breach"),
        Guarantee(key="VR-8", name="x", now=0, limit=0, status="ok"),
        Guarantee(key="DE-1", name="x", now=0, limit=0, status="ok"),
        Guarantee(key="CO-1", name="x", now=38, limit=100, status="ok"),
    ]
    rows = view.guarantee_rows(gs)
    assert len(rows) == 5
    assert rows[2]["name"] == "Booking mismatches (daily check)"
    assert rows[2]["now"] == "3" and rows[2]["status"] == "Over limit"


def test_line_dots_match_line_points():
    assert view.line_dots([None, None, 50], 40, 500, 10, 140, 100) == [(500.0, 75.0)]
    assert view.line_dots([2.0], 30, 390, 0, 100, 8) == [(30.0, 75.0)]
    values = [54, None, 61, 57]
    dots = view.line_dots(values, 40, 500, 10, 140, 100)
    assert len(dots) == 3
    assert " ".join(f"{x:.1f},{y:.1f}" for x, y in dots) == view.line_points(
        values, 40, 500, 10, 140, 100
    )


def test_view_has_dots_for_both_charts():
    v = view.overview_view(make_overview())
    assert len(v["settled"]["dots"]) == 7
    assert v["settled"]["dots"][0] == (40.0, 69.8)
    assert len(v["latency"]["dots"]) == 24


@pytest.mark.parametrize(
    ("code", "words"),
    [
        ("no_plumber_in_zone", "no plumber in zone"),
        ("no matching document", "no matching document"),
        (None, None),
    ],
)
def test_top_reason_reads_as_words(code, words):
    o = make_overview()
    o = o.model_copy(
        update={
            "supporting": o.supporting.model_copy(update={"top_handoff_reason": code})
        }
    )
    assert view.overview_view(o)["supporting"]["reason"] == words

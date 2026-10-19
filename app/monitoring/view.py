"""Display model for the business view's Overview tab.

Pure functions: an Overview in, strings and SVG coordinates out. The template only
lays the results out.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.types import Guarantee, Overview

NO_DATA = "No data yet"

INTENT_LABELS = {
    "book_visit": "Book a visit",
    "change_visit": "Move or cancel a visit",
    "policy_question": "Policy question",
    "warranty_question": "Warranty question",
    "membership_question": "Membership question",
    "billing_lookup": "Billing question",
    "billing_dispute": "Billing dispute",
    "membership_change": "Membership change",
    "complaint_or_refund": "Complaint or refund",
    "safety": "Safety concern",
    "new_system_quote": "New system quote",
    "technician_late": "Technician late",
    "out_of_scope": "Out of scope",
}

# label, tone class
OUTCOME_LABELS = {
    "contained": ("Contained", "ok"),
    "handoff": ("Handoff", "warn"),
    "safety_stop": ("Safety stop", "stop"),
    "failed": ("Failed", "stop"),
    "active": ("Active", "muted"),
}

STATUS_LABELS = {
    "ok": ("Within limit", "ok"),
    "breach": ("Over limit", "stop"),
    "no_data": ("No data yet", "muted"),
}

# (match, measure name, kind)
GUARANTEE_ROWS = [
    ("PF-1", "Time to first reply, p95", "seconds"),
    ("PF-2", "Turn that books, moves or cancels, p95", "seconds"),
    ("VR", "Booking mismatches (daily check)", "count"),
    ("DE-1", "Errors shown to callers", "count"),
    ("CO-1", "Total model spend", "money"),
]


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _minutes(as_of: str, at: str) -> int:
    return max(0, int((_parse(as_of) - _parse(at)).total_seconds() // 60))


def ago(as_of: str, at: str | None) -> str:
    if at is None:
        return "No conversations yet"
    m = _minutes(as_of, at)
    if m < 1:
        return "Just now"
    if m < 60:
        return f"{m} minute{'' if m == 1 else 's'} ago"
    h = m // 60
    return f"{h} hour{'' if h == 1 else 's'} ago"


def short_ago(as_of: str, at: str) -> str:
    m = _minutes(as_of, at)
    return f"{m} min" if m < 60 else f"{m // 60} h"


def pct(v: float | None) -> str:
    return NO_DATA if v is None else f"{v:g}%"


def money(v: float | None) -> str:
    if v is None:
        return "unknown"
    v = round(v, 2)
    return f"${v:.0f}" if v == int(v) else f"${v:.2f}"


def seconds(ms: float | None) -> str:
    return NO_DATA if ms is None else f"{ms / 1000:.1f} s"


def line_dots(
    values: list[float | None],
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    vmax: float,
) -> list[tuple[float, float]]:
    """SVG coordinates of each value, as the wireframe's pts(); None values are skipped."""
    last = max(len(values) - 1, 1)
    return [
        (round(x0 + (x1 - x0) * i / last, 1), round(y1 - (y1 - y0) * v / vmax, 1))
        for i, v in enumerate(values)
        if v is not None
    ]


def line_points(
    values: list[float | None],
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    vmax: float,
) -> str:
    """SVG polyline points for the same values."""
    return " ".join(
        f"{x:.1f},{y:.1f}" for x, y in line_dots(values, x0, x1, y0, y1, vmax)
    )


def band(lo: float, hi: float) -> tuple[float, float, float]:
    """Top, height and label y of the target band in the 140-high settled chart."""
    top = 140 - 130 * hi / 100
    return round(top, 1), round(130 * (hi - lo) / 100, 1), round(top + 11, 1)


def _guarantee_cells(g: Guarantee, kind: str) -> tuple[str, str]:
    if kind == "seconds":
        return seconds(g.now), f"at most {g.limit / 1000:g} s"
    if kind == "money":
        return money(
            g.now
        ) if g.now is not None else NO_DATA, f"alert at {money(g.limit)}"
    return NO_DATA if g.now is None else f"{g.now:g}", f"{g.limit:g}"


def _fold_vr(guarantees: list[Guarantee]) -> list[Guarantee]:
    """Every VR-* guarantee becomes one: summed now, worst status."""
    vr = [g for g in guarantees if g.key.startswith("VR-")]
    if len(vr) < 2:
        return guarantees
    nows = [g.now for g in vr if g.now is not None]
    statuses = {g.status for g in vr}
    status = (
        "breach" if "breach" in statuses else "ok" if "ok" in statuses else "no_data"
    )
    merged = vr[0].model_copy(
        update={"now": sum(nows) if nows else None, "status": status}
    )
    return [merged if g is vr[0] else g for g in guarantees if g not in vr[1:]]


def guarantee_rows(guarantees: list[Guarantee]) -> list[dict[str, str]]:
    rest = _fold_vr(list(guarantees))
    rows: list[dict[str, str]] = []
    for match, name, kind in GUARANTEE_ROWS:
        g = next(
            (x for x in rest if x.key == match or x.key.startswith(match + "-")), None
        )
        if g is None:
            continue
        rest.remove(g)
        rows.append(_row(g, name, kind))
    rows.extend(_row(g, g.name, "count") for g in rest)
    return rows


def _row(g: Guarantee, name: str, kind: str) -> dict[str, str]:
    now, limit = _guarantee_cells(g, kind)
    status, tone = STATUS_LABELS[g.status]
    return {"name": name, "now": now, "limit": limit, "status": status, "tone": tone}


def what(intent: str | None, zone: str | None) -> str:
    label = INTENT_LABELS.get(intent or "", "Other")
    return f"{label}, {zone} zone" if zone else label


@dataclass(frozen=True)
class Bar:
    x: float
    y: float
    h: float
    count: int
    label: str


def volume_bars(days: list[tuple[str, int]]) -> list[Bar]:
    """Bars for a 400x120 chart: baseline y=90, tallest bar 70 high."""
    top = max([c for _, c in days], default=0) or 1
    slot = 400 / max(len(days), 1)
    bars = []
    for i, (date, count) in enumerate(days):
        h = round(70 * count / top, 1)
        bars.append(
            Bar(round(slot * i + slot * 0.2, 1), round(90 - h, 1), h, count, date[5:])
        )
    return bars


SETTLED_BOX = (40, 500, 10, 140, 100)


def overview_view(o: Overview) -> dict[str, Any]:
    lo, hi = (o.success.target_band_pct + [60, 75])[:2]
    band_top, band_h, band_label_y = band(lo, hi)
    lat = [
        None if p.p95_first_reply_ms is None else p.p95_first_reply_ms / 1000
        for p in o.latency_series_24h
    ]
    vmax = max([8.0, *[v for v in lat if v is not None]])
    limit_y = 100 - 100 * 6 / vmax
    settled = [p.settled_pct for p in o.success.series]
    out = o.volume.outcomes
    recent = sorted(o.recent, key=lambda r: r.started_at, reverse=True)
    sp = o.spend
    return {
        "status": {
            "public_url": o.status.public_url or "Not set",
            "public_url_tone": "ok" if o.status.public_url else "muted",
            "last": ago(o.as_of, o.status.last_conversation_at),
            "errors": o.status.errors_shown_24h,
            "waiting": o.status.handoffs_waiting,
        },
        "settled": {
            "pct": pct(o.success.settled_pct),
            "count": o.success.settled_count,
            "total": o.success.total_count,
            "band_lo": lo,
            "band_hi": hi,
            "band_top": band_top,
            "band_h": band_h,
            "band_label_y": band_label_y,
            "line": line_points(settled, *SETTLED_BOX),
            "dots": line_dots(settled, *SETTLED_BOX),
        },
        "supporting": {
            "booking": pct(o.supporting.booking_completion_pct),
            "handoffs": pct(o.supporting.handoffs_on_handled_topics_pct),
            "reason": o.supporting.top_handoff_reason,
            "flagged": pct(o.supporting.flagged_wrong_pct),
        },
        "recent": [
            {
                "when": short_ago(o.as_of, r.started_at),
                "what": what(r.intent, r.zone),
                "outcome": OUTCOME_LABELS.get(r.outcome or "", ("Active", "muted"))[0],
                "tone": OUTCOME_LABELS.get(r.outcome or "", ("Active", "muted"))[1],
                "latency": seconds(r.latency_ms),
            }
            for r in recent
        ],
        "guarantees": guarantee_rows(o.guarantees),
        "latency": {
            "line": line_points(lat, 30, 390, 0, 100, vmax),
            "dots": line_dots(lat, 30, 390, 0, 100, vmax),
            "limit_y": round(limit_y, 1),
            "limit_label_y": round(limit_y - 4, 1),
        },
        "volume": {
            "bars": volume_bars(
                [(d.date, d.count) for d in o.volume.conversations_by_day]
            ),
            "outcomes": [
                ("contained", "Contained", out.contained),
                ("handoff", "Handoff", out.handoff),
                ("safety_stop", "Safety stop", out.safety_stop),
                ("failed", "Failed", out.failed),
                ("active", "Active", out.active),
            ],
        },
        "spend_line": f"Total model spend: {money(sp.total_usd)} of the {money(sp.alert_usd)} alert.",
        "banner": f"Total model spend has passed the {money(sp.alert_usd)} alert."
        if sp.alert
        else None,
    }


def page_data(trace_base: str) -> dict[str, Any]:
    """Labels and the trace link base the Handoffs, Waitlist and Conversations scripts read."""
    return {
        "intents": INTENT_LABELS,
        "outcomes": {k: list(v) for k, v in OUTCOME_LABELS.items()},
        "traceBase": trace_base.rstrip("/"),
    }

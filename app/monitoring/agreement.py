"""VR-6/7/8 live check: do the bookings in the scheduling copy agree with the audit rows?"""

import sqlite3
from contextlib import closing

from app.context import AppContext
from app.scheduling.store import connect, zone_for_city

_LATEST_ROWS = (
    "SELECT * FROM visit_changes WHERE id IN (SELECT MAX(id) FROM visit_changes "
    "WHERE retired_at IS NULL GROUP BY appointment_id)"
)


def _seed_baseline(ctx: AppContext) -> tuple[int, set[int]]:
    """The seed's highest appointment id and its member-reserved slots (read only)."""
    uri = f"file:{ctx.settings.SEED_DB_PATH}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as seed:
        top = seed.execute("SELECT MAX(appointment_id) FROM appointments").fetchone()[0]
        reserved = seed.execute(
            "SELECT slot_id FROM appointment_slots WHERE status = 'reserved_members'"
        ).fetchall()
    return top or 0, {slot_id for (slot_id,) in reserved}


def _booking_agrees(
    ctx: AppContext,
    conn: sqlite3.Connection,
    appt: sqlite3.Row,
    row: sqlite3.Row | None,
    member_only: bool,
) -> bool:
    slot = conn.execute(
        "SELECT s.slot_date, s.window, s.zone, s.service_type, s.status, "
        "t.name AS technician FROM appointment_slots s "
        "JOIN technicians t ON t.tech_id = s.tech_id WHERE s.slot_id = ?",
        (appt["slot_id"],),
    ).fetchone()
    customer = conn.execute(
        "SELECT city, membership_tier FROM customers WHERE customer_id = ?",
        (appt["customer_id"],),
    ).fetchone()
    if slot is None or customer is None or appt["status"] != "scheduled":
        return False
    holders = conn.execute(
        "SELECT COUNT(*) FROM appointments WHERE slot_id = ? AND status = 'scheduled'",
        (appt["slot_id"],),
    ).fetchone()[0]
    ok = (
        slot["status"] == "booked"
        and holders == 1
        and zone_for_city(customer["city"]) == slot["zone"]
        and slot["service_type"] != "estimate"
        and slot["slot_date"] >= ctx.settings.REFERENCE_DATE
        and (not member_only or customer["membership_tier"] in ("standard", "plus"))
    )
    if row is not None and row["confirmed_date"] is not None:
        ok = ok and (
            row["confirmed_date"] == slot["slot_date"]
            and row["confirmed_window"] == slot["window"]
            and row["confirmed_technician"] == slot["technician"]
        )
    return ok


def _cancel_agrees(conn: sqlite3.Connection, appt: sqlite3.Row) -> bool:
    if appt["status"] != "cancelled":
        return False
    slot = conn.execute(
        "SELECT status FROM appointment_slots WHERE slot_id = ?", (appt["slot_id"],)
    ).fetchone()
    if slot is None:
        return False
    other = conn.execute(
        "SELECT 1 FROM appointments WHERE slot_id = ? AND status = 'scheduled' "
        "AND appointment_id <> ?",
        (appt["slot_id"], appt["appointment_id"]),
    ).fetchone()
    return slot["status"] == "open" or other is not None


def booking_mismatches(ctx: AppContext) -> int:
    """Appointments that disagree with their latest live audit row, or that have none past the seed.

    Retired rows are ignored. Raises sqlite3.Error or SchedulingUnavailable when a
    database cannot be read.
    """
    top, reserved = _seed_baseline(ctx)
    with closing(ctx.open_app_db()) as app_db:
        app_db.row_factory = sqlite3.Row
        rows = {r["appointment_id"]: r for r in app_db.execute(_LATEST_ROWS)}
        freed = {
            r[0]
            for r in app_db.execute(
                "SELECT slot_id FROM visit_changes WHERE retired_at IS NULL "
                "AND action = 'cancel' UNION SELECT previous_slot_id "
                "FROM visit_changes WHERE retired_at IS NULL AND action = 'move'"
            )
        }
    bad = 0
    with closing(connect(ctx)) as conn:
        conn.row_factory = sqlite3.Row
        orphans = conn.execute(
            "SELECT appointment_id FROM appointments WHERE appointment_id > ?", (top,)
        ).fetchall()
        for appointment_id in rows.keys() | {r[0] for r in orphans}:
            row = rows.get(appointment_id)
            appt = conn.execute(
                "SELECT * FROM appointments WHERE appointment_id = ?", (appointment_id,)
            ).fetchone()
            if appt is None:
                bad += 1
                continue
            action = row["action"] if row else None
            if action in (None, "book", "move") and not (
                row is None and appt["status"] == "cancelled"
            ):
                member_only = (
                    appt["slot_id"] in reserved and appt["slot_id"] not in freed
                )
                good = _booking_agrees(ctx, conn, appt, row, member_only) and (
                    row is None
                    or (
                        row["customer_id"] == appt["customer_id"]
                        and row["slot_id"] == appt["slot_id"]
                    )
                )
            else:
                good = _cancel_agrees(conn, appt)
            bad += not good
    return bad

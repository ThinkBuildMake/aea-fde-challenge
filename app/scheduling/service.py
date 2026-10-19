import json
import re
import sqlite3
import uuid
from contextlib import closing
from datetime import date, datetime, timedelta

from app.context import AppContext
from app.logs import log_event
from app.scheduling.store import SchedulingUnavailable, connect, zone_for_city
from app.types import (
    AppointmentView,
    Billing,
    BookedVisit,
    CancelResult,
    CustomerRef,
    Invoice,
    LineItem,
    MoveResult,
    OpenWindows,
    PaymentLink,
    ResetResult,
    SlotCounts,
    Window,
)


class SlotUnavailable(Exception):
    """The slot is no longer bookable."""


class NotEligible(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class AppointmentNotFound(Exception):
    """No such appointment for this customer."""


class InvoiceNotFound(Exception):
    """No such invoice for this customer."""


class NothingOwed(Exception):
    """The invoice has no balance."""


def _name(value: str) -> str:
    return " ".join(value.split()).casefold()


def _digits(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def _address(value: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", "", value).split()).casefold()


def identify_customer(
    ctx: AppContext,
    name: str,
    phone: str | None = None,
    account_number: str | None = None,
    service_address: str | None = None,
) -> CustomerRef | None:
    wanted_phone = _digits(phone or "")
    wanted_account = (account_number or "").strip()
    wanted_address = _address(service_address or "")
    if not (wanted_phone or wanted_account or wanted_address):
        return None
    with closing(connect(ctx)) as conn:
        rows = conn.execute("SELECT * FROM customers").fetchall()
    matches = [
        r
        for r in rows
        if _name(r["name"]) == _name(name)
        and (
            (wanted_phone and _digits(r["phone"] or "") == wanted_phone)
            or (wanted_account and r["customer_id"] == wanted_account)
            or (
                wanted_address
                and _address(r["service_address"] or "") == wanted_address
            )
        )
    ]
    if len(matches) != 1:
        return None
    r = matches[0]
    return CustomerRef(
        customer_id=r["customer_id"],
        name=r["name"],
        city=r["city"],
        zone=zone_for_city(r["city"]),
        membership_tier=r["membership_tier"],
        membership_renewal_date=r["membership_renewal_date"],
        system_brand=r["system_brand"],
        system_install_date=r["system_install_date"],
    )


def _iso_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def find_open_windows(
    ctx: AppContext,
    customer_id: str,
    service_type: str,
    preferred_date: str | None = None,
    preferred_window: str | None = None,
) -> OpenWindows:
    def none(reason: str) -> OpenWindows:
        return OpenWindows(windows=[], matched_request=False, reason=reason)

    try:
        with closing(connect(ctx)) as conn:
            customer = conn.execute(
                "SELECT city, membership_tier FROM customers WHERE customer_id = ?",
                (customer_id,),
            ).fetchone()
            if customer is None:
                return none("unknown_customer")
            zone = zone_for_city(customer["city"])
            if zone is None:
                return none("city_not_in_zone_map")
            if service_type not in ("hvac_repair", "hvac_tune_up", "plumbing"):
                return none("no_open_windows")
            statuses = (
                ("open", "reserved_members")
                if customer["membership_tier"] in ("standard", "plus")
                else ("open",)
            )
            marks = ",".join("?" * len(statuses))
            rows = conn.execute(
                "SELECT s.slot_id, s.slot_date, s.window, s.zone, s.service_type, "
                "s.status, t.name FROM appointment_slots s "
                "JOIN technicians t ON t.tech_id = s.tech_id "
                "WHERE s.zone = ? AND s.service_type = ? "
                f"AND s.status IN ({marks}) AND s.slot_date >= ? "
                "ORDER BY s.slot_date, s.window, s.slot_id",
                (zone, service_type, *statuses, ctx.settings.REFERENCE_DATE),
            ).fetchall()
            if not rows and service_type == "plumbing":
                has_plumbing = conn.execute(
                    "SELECT 1 FROM appointment_slots "
                    "WHERE zone = ? AND service_type = 'plumbing' LIMIT 1",
                    (zone,),
                ).fetchone()
                if has_plumbing is None:
                    return none("no_plumber_in_zone")
    except sqlite3.Error as e:
        raise SchedulingUnavailable("scheduling database unavailable") from e
    windows = [
        Window(
            slot_id=r["slot_id"],
            date=r["slot_date"],
            window=r["window"],
            service_type=r["service_type"],
            zone=r["zone"],
            technician_name=r["name"],
            member_only=r["status"] == "reserved_members",
        )
        for r in rows
    ]
    if not windows:
        return none("no_open_windows")
    matching = [
        w
        for w in windows
        if (preferred_date is None or w.date == preferred_date)
        and (preferred_window is None or w.window == preferred_window)
    ]
    if matching:
        return OpenWindows(windows=matching, matched_request=True, reason=None)
    wanted = _iso_date(preferred_date)
    if wanted:
        windows.sort(
            key=lambda w: (
                abs((date.fromisoformat(w.date) - wanted).days),
                w.date,
                w.window,
                w.slot_id,
            )
        )
    return OpenWindows(windows=windows, matched_request=False, reason=None)


def list_appointments(ctx: AppContext, customer_id: str) -> list[AppointmentView]:
    try:
        with closing(connect(ctx)) as conn:
            rows = conn.execute(
                "SELECT a.appointment_id, a.issue_description, s.slot_date, s.window, "
                "s.service_type, s.zone, t.name FROM appointments a "
                "JOIN appointment_slots s ON s.slot_id = a.slot_id "
                "JOIN technicians t ON t.tech_id = s.tech_id "
                "WHERE a.customer_id = ? AND a.status = 'scheduled' "
                "ORDER BY s.slot_date, s.window, a.appointment_id",
                (customer_id,),
            ).fetchall()
    except sqlite3.Error as e:
        raise SchedulingUnavailable("scheduling database unavailable") from e
    now = datetime.fromisoformat(
        f"{ctx.settings.REFERENCE_DATE}T{ctx.settings.REFERENCE_TIME}"
    )
    return [
        AppointmentView(
            appointment_id=r["appointment_id"],
            date=r["slot_date"],
            window=r["window"],
            technician_name=r["name"],
            service_type=r["service_type"],
            zone=r["zone"],
            issue=r["issue_description"] or "",
            late_cancel_fee_applies=datetime.fromisoformat(
                f"{r['slot_date']}T{r['window'][:5]}"
            )
            - now
            < timedelta(hours=24),
        )
        for r in rows
    ]


def get_appointment(
    ctx: AppContext, customer_id: str, appointment_id: int
) -> AppointmentView:
    for appointment in list_appointments(ctx, customer_id):
        if appointment.appointment_id == appointment_id:
            return appointment
    raise AppointmentNotFound("appointment not found")


def book_visit(
    ctx: AppContext,
    customer_id: str,
    slot_id: int,
    issue: str,
    conversation_id: str,
) -> BookedVisit:
    visit = _claim_slot(ctx, customer_id, slot_id, issue)
    _record_book(ctx, conversation_id, customer_id, visit)
    return visit


def _claim_slot(
    ctx: AppContext, customer_id: str, slot_id: int, issue: str
) -> BookedVisit:
    """Check, claim the slot and insert the appointment in one write-locked transaction."""
    try:
        with closing(connect(ctx)) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                visit = _book_in_transaction(ctx, conn, customer_id, slot_id, issue)
                conn.commit()
                return visit
            except BaseException:
                conn.rollback()
                raise
    except sqlite3.Error as exc:
        raise SchedulingUnavailable("scheduling database unavailable") from exc


def _book_in_transaction(
    ctx: AppContext,
    conn: sqlite3.Connection,
    customer_id: str,
    slot_id: int,
    issue: str,
) -> BookedVisit:
    slot = conn.execute(
        "SELECT s.slot_date, s.window, s.zone, s.service_type, s.status, "
        "t.name AS technician_name FROM appointment_slots s "
        "JOIN technicians t ON t.tech_id = s.tech_id WHERE s.slot_id = ?",
        (slot_id,),
    ).fetchone()
    if slot is None or slot["status"] in ("booked", "blocked"):
        raise SlotUnavailable("slot is not available")
    customer = conn.execute(
        "SELECT city, membership_tier FROM customers WHERE customer_id = ?",
        (customer_id,),
    ).fetchone()
    if customer is None:
        raise NotEligible("unknown_customer")
    if zone_for_city(customer["city"]) != slot["zone"]:
        raise NotEligible("wrong_zone")
    if slot["service_type"] == "estimate":
        raise NotEligible("wrong_service_type")
    if slot["slot_date"] < ctx.settings.REFERENCE_DATE:
        raise NotEligible("before_reference_date")
    allowed = ["open"]
    if customer["membership_tier"] in ("standard", "plus"):
        allowed.append("reserved_members")
    elif slot["status"] == "reserved_members":
        raise NotEligible("member_only")
    claimed = conn.execute(
        "UPDATE appointment_slots SET status = 'booked' "
        f"WHERE slot_id = ? AND status IN ({','.join('?' * len(allowed))})",
        (slot_id, *allowed),
    )
    if claimed.rowcount != 1:
        raise SlotUnavailable("slot is not available")
    created = conn.execute(
        "INSERT INTO appointments (slot_id, customer_id, issue_description, "
        "created_at, status, is_warranty_visit) VALUES (?, ?, ?, ?, 'scheduled', 0)",
        (slot_id, customer_id, issue, ctx.settings.REFERENCE_DATE),
    )
    return BookedVisit(
        appointment_id=created.lastrowid or 0,
        slot_id=slot_id,
        date=slot["slot_date"],
        window=slot["window"],
        technician_name=slot["technician_name"],
        service_type=slot["service_type"],
        zone=slot["zone"],
    )


def _record_book(
    ctx: AppContext, conversation_id: str, customer_id: str, visit: BookedVisit
) -> None:
    """The audit row; a failure here is logged and never undoes the booking."""
    try:
        with closing(ctx.open_app_db()) as app_db:
            app_db.execute(
                "INSERT INTO visit_changes (conversation_id, action, appointment_id, "
                "slot_id, customer_id, confirmed_date, confirmed_window, "
                "confirmed_technician) VALUES (?, 'book', ?, ?, ?, ?, ?, ?)",
                (
                    conversation_id,
                    visit.appointment_id,
                    visit.slot_id,
                    customer_id,
                    visit.date,
                    visit.window,
                    visit.technician_name,
                ),
            )
    except Exception as exc:  # noqa: BLE001 - never undo the booking
        log_event(
            "visit_change_audit_failed",
            appointment_id=visit.appointment_id,
            slot_id=visit.slot_id,
            error=type(exc).__name__,
        )


def move_visit(
    ctx: AppContext, customer_id: str, appointment_id: int, new_slot_id: int
) -> MoveResult:
    raise SchedulingUnavailable("not implemented")


def cancel_visit(
    ctx: AppContext, customer_id: str, appointment_id: int
) -> CancelResult:
    raise SchedulingUnavailable("not implemented")


def get_billing(ctx: AppContext, customer_id: str) -> Billing:
    with closing(connect(ctx)) as conn:
        rows = conn.execute(
            "SELECT invoice_id, issued_date, due_date, amount_cents, balance_cents, "
            "line_items FROM invoices WHERE customer_id = ? "
            "ORDER BY issued_date DESC, invoice_id DESC",
            (customer_id,),
        ).fetchall()
    invoices = [
        Invoice(
            invoice_id=r["invoice_id"],
            issued_date=r["issued_date"],
            due_date=r["due_date"],
            amount_cents=r["amount_cents"],
            balance_cents=r["balance_cents"],
            line_items=[LineItem(**line) for line in json.loads(r["line_items"])],
        )
        for r in rows
    ]
    return Billing(
        balance_cents=sum(i.balance_cents for i in invoices), invoices=invoices
    )


def create_payment_link(
    ctx: AppContext, customer_id: str, invoice_id: str
) -> PaymentLink:
    with closing(connect(ctx)) as conn:
        row = conn.execute(
            "SELECT balance_cents FROM invoices WHERE invoice_id = ? AND customer_id = ?",
            (invoice_id, customer_id),
        ).fetchone()
    if row is None:
        raise InvoiceNotFound("invoice not found")
    if row["balance_cents"] <= 0:
        raise NothingOwed("nothing owed")
    return PaymentLink(
        url=f"https://pay.example.com/invoice/{invoice_id}?token={uuid.uuid4().hex}",
        valid_for_hours=24,
    )


def reset_scheduling(ctx: AppContext) -> ResetResult:
    return ResetResult(
        snapshot_id="stub",
        slot_counts=SlotCounts(open=0, booked=0, reserved_members=0, blocked=0),
    )


def scheduling_status(ctx: AppContext) -> str:
    if not ctx.settings.SCHEDULING_DB_PATH.is_file():
        return "error"
    try:
        with closing(connect(ctx)) as conn:
            conn.execute("SELECT 1 FROM appointment_slots LIMIT 1").fetchall()
    except sqlite3.Error:
        return "error"
    return "ok"

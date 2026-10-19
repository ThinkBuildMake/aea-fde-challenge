import json
import re
import uuid
from contextlib import closing

from app.context import AppContext
from app.scheduling.store import connect, zone_for_city
from app.types import (
    AppointmentView,
    Billing,
    Booking,
    CancelResult,
    CustomerRef,
    Invoice,
    LineItem,
    MoveResult,
    OpenWindows,
    PaymentLink,
    ResetResult,
    SlotCounts,
)


class SchedulingUnavailable(Exception):
    """The supplied scheduling database could not be used."""


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


def find_open_windows(
    ctx: AppContext,
    customer_id: str,
    service_type: str,
    preferred_date: str | None = None,
    preferred_window: str | None = None,
) -> OpenWindows:
    return OpenWindows(windows=[], matched_request=False, reason="no_open_windows")


def list_appointments(ctx: AppContext, customer_id: str) -> list[AppointmentView]:
    return []


def get_appointment(
    ctx: AppContext, customer_id: str, appointment_id: int
) -> AppointmentView:
    raise SchedulingUnavailable("not implemented")


def book_visit(ctx: AppContext, customer_id: str, slot_id: int, issue: str) -> Booking:
    raise SchedulingUnavailable("not implemented")


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
    return "ok"

from app.context import AppContext
from app.types import (
    AppointmentView,
    Billing,
    Booking,
    CancelResult,
    CustomerRef,
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


def identify_customer(
    ctx: AppContext,
    name: str,
    phone: str | None = None,
    account_number: str | None = None,
    service_address: str | None = None,
) -> CustomerRef | None:
    return None


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
    return Billing(balance_cents=0, invoices=[])


def create_payment_link(
    ctx: AppContext, customer_id: str, invoice_id: str
) -> PaymentLink:
    raise SchedulingUnavailable("not implemented")


def reset_scheduling(ctx: AppContext) -> ResetResult:
    return ResetResult(
        snapshot_id="stub",
        slot_counts=SlotCounts(open=0, booked=0, reserved_members=0, blocked=0),
    )


def scheduling_status(ctx: AppContext) -> str:
    return "ok"

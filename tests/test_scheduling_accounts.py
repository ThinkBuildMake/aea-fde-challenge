import sqlite3
from collections.abc import Iterator
from urllib.parse import urlparse

import pytest

from app.context import AppContext
from app.main import create_app
from app.scheduling.service import (
    InvoiceNotFound,
    NothingOwed,
    create_payment_link,
    get_billing,
    identify_customer,
)
from app.settings import Settings


@pytest.fixture
def ctx(started: Settings) -> AppContext:
    return create_app(started).state.ctx


@pytest.fixture
def db(started: Settings) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(started.SCHEDULING_DB_PATH)
    yield connection
    connection.close()


def test_identify_by_name_and_phone(ctx: AppContext):
    ref = identify_customer(ctx, "Linda Foster", phone="512-555-0101")
    assert ref is not None
    assert ref.customer_id == "MHC-10001"
    assert ref.zone == "north"
    assert ref.membership_tier == "standard"
    dumped = str(ref.model_dump())
    for key in ("phone", "email", "service_address", "zip"):
        assert key not in ref.model_dump()
    for value in ("512-555-0101", "linda.foster@example.com", "4412 Oak Hollow"):
        assert value not in dumped


def test_identify_by_phone_with_country_code(ctx: AppContext):
    ref = identify_customer(ctx, "Linda Foster", phone="+1 (512) 555-0101")
    assert ref is not None and ref.customer_id == "MHC-10001"


def test_identify_by_name_and_account_number_ignores_name_case(ctx: AppContext):
    ref = identify_customer(ctx, "omar patel", account_number="MHC-10002")
    assert ref is not None
    assert ref.customer_id == "MHC-10002"


def test_identify_by_name_and_address_ignores_punctuation(ctx: AppContext):
    ref = identify_customer(ctx, "Grace Okafor", service_address="2207 windcrest ave.")
    assert ref is not None
    assert ref.customer_id == "MHC-10003"


def test_mismatch_is_null_like_unknown_name_and_adds_no_customer(
    ctx: AppContext, db: sqlite3.Connection
):
    before = db.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    assert identify_customer(ctx, "Omar Patel", phone="512-555-0101") is None
    assert identify_customer(ctx, "Nobody Here", phone="512-555-0101") is None
    assert db.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == before


def test_az1_name_alone_matches_nothing(ctx: AppContext):
    assert identify_customer(ctx, "Linda Foster") is None
    assert identify_customer(ctx, "Linda Foster", phone="", account_number="") is None
    assert identify_customer(ctx, "Linda Foster", phone="---") is None


def test_az1_other_customers_account_or_address_matches_nothing(ctx: AppContext):
    assert identify_customer(ctx, "Omar Patel", account_number="MHC-10001") is None
    assert (
        identify_customer(ctx, "Omar Patel", service_address="4412 Oak Hollow Dr")
        is None
    )


def test_billing_for_own_account(ctx: AppContext):
    billing = get_billing(ctx, "MHC-10002")
    assert billing.balance_cents == 47800
    invoice = billing.invoices[0]
    assert invoice.invoice_id == "INV-204411"
    assert [line.cents for line in invoice.line_items] == [8900, 24500, 14400]


def test_az1_billing_never_lists_another_customers_invoice(ctx: AppContext):
    billing = get_billing(ctx, "MHC-10001")
    assert billing.balance_cents == 0
    assert [i.invoice_id for i in billing.invoices] == []


def test_payment_link_for_own_invoice(ctx: AppContext, db: sqlite3.Connection):
    link = create_payment_link(ctx, "MHC-10002", "INV-204411")
    host = urlparse(link.url).hostname or ""
    assert urlparse(link.url).scheme == "https"
    assert host == "example.com" or host.endswith(".example.com")
    assert link.valid_for_hours == 24
    row = db.execute(
        "SELECT balance_cents FROM invoices WHERE invoice_id = 'INV-204411'"
    ).fetchone()
    assert row[0] == 47800


def test_no_link_for_another_customers_invoice(ctx: AppContext):
    with pytest.raises(InvoiceNotFound):
        create_payment_link(ctx, "MHC-10001", "INV-204411")


def test_az1_unknown_invoice_same_error_as_foreign_invoice(ctx: AppContext):
    with pytest.raises(InvoiceNotFound) as foreign:
        create_payment_link(ctx, "MHC-10001", "INV-204411")
    with pytest.raises(InvoiceNotFound) as unknown:
        create_payment_link(ctx, "MHC-10001", "INV-999999")
    assert str(foreign.value) == str(unknown.value)


def test_paid_invoice_raises_nothing_owed(ctx: AppContext):
    with pytest.raises(NothingOwed):
        create_payment_link(ctx, "MHC-24034", "INV-200000")

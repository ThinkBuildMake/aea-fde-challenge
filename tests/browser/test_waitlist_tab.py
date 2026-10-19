import re

from playwright.sync_api import Page, expect

from app.types import HeldWindow, WaitlistCaller, WaitlistList, WaitlistView
from tests.browser.conftest import json_route

WAITLIST = re.compile(r".*/waitlist$")


def entry() -> WaitlistView:
    return WaitlistView(
        id=1,
        conversation_public_id="CALL-0001",
        caller=WaitlistCaller(
            customer_id="C-1", name="Omar Patel", phone="512-555-0101", city="Kyle"
        ),
        service_type="hvac_repair",
        zone="south",
        held=HeldWindow(date="2026-10-21", window="08:00-12:00"),
        created_at="2026-10-19T08:00:00+00:00",
        waiting_seconds=7200,
    )


def test_waitlist_row(page: Page, live_url: str, overview_stub):
    body = WaitlistList(entries=[entry()]).model_dump(by_alias=True, mode="json")
    json_route(page, WAITLIST, body)
    page.goto(live_url + "/business?tab=waitlist")
    panel = page.locator("[data-tab=waitlist]")
    expect(panel.locator(".card-title")).to_have_text("Waitlist for earlier windows")
    expect(panel).to_contain_text(
        "Each caller already holds a later booked visit. Call them if an earlier window opens in their zone."
    )
    row = page.locator(".waitlist-row")
    expect(row).to_have_count(1)
    expect(row.locator(".who")).to_have_text("Omar Patel, Kyle, south")
    expect(row.locator(".want")).to_have_text(
        "HVAC repair, earlier than Wednesday 2026-10-21 8 to 12"
    )
    expect(row.locator(".since")).to_have_text("2 h ago")
    expect(page.locator(".tile")).to_have_count(4)


def test_waitlist_empty(page: Page, live_url: str, overview_stub):
    json_route(page, WAITLIST, {"entries": []})
    page.goto(live_url + "/business?tab=waitlist")
    expect(page.locator("[data-tab=waitlist] .empty")).to_have_text("No data yet")

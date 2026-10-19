import re

from playwright.sync_api import Page, expect

from app.types import (
    HandoffList,
    HandoffView,
)
from tests.browser.conftest import json_route

HANDOFFS = re.compile(r".*/handoffs(\?.*)?$")


def handoff(**kw) -> dict:
    base = {
        "id": 7,
        "conversation_public_id": "CALL-0007",
        "kind": "supervisor_callback",
        "reason": "billing_dispute",
        "by_error": False,
        "caller": {
            "customer_id": "C-1",
            "name": "Omar Patel",
            "phone": "512-555-0101",
            "city": "Kyle",
            "zone": "south",
            "stated_by_caller": False,
        },
        "intent": "billing_dispute",
        "told_caller": "A supervisor calls within 1 business day about the double charge.",
        "summary": "",
        "summary_source": "template",
        "preferred_window": "afternoon",
        "status": "open",
        "created_at": "2026-10-19T10:00:00+00:00",
        "followed_up_at": None,
    }
    base.update(kw)
    return base


def view(**kw) -> dict:
    return HandoffView(**handoff(**kw)).model_dump(by_alias=True, mode="json")


def stub_list(page: Page, *items: dict) -> None:
    body = HandoffList(handoffs=[HandoffView(**i) for i in items])
    json_route(page, HANDOFFS, body.model_dump(by_alias=True, mode="json"))


def test_handoff_row(page: Page, live_url: str, overview_stub):
    stub_list(page, handoff())
    page.goto(live_url + "/business?tab=handoffs")
    panel = page.locator("[data-tab=handoffs]")
    expect(panel.locator(".card-title")).to_have_text("Handoffs and callback requests")
    expect(panel).to_contain_text(
        "Each row is what the person who follows up needs: who, why, what the caller was told."
    )
    row = page.locator(".handoff-row")
    expect(row).to_have_count(1)
    expect(row.locator(".who")).to_contain_text("Omar Patel")
    expect(row.locator(".summary")).to_have_text(
        "Billing dispute. Told: A supervisor calls within 1 business day about the double charge."
    )
    expect(row.locator(".window")).to_have_text("Prefers afternoon")
    expect(row.locator("button")).to_have_text("Mark followed up")


def test_mark_followed_up_and_undo(page: Page, live_url: str, overview_stub):
    calls: list[dict] = []
    stub_list(page, handoff())
    json_route(
        page,
        re.compile(r".*/handoffs/7/followed-up$"),
        {"handoff": view(status="followed_up")},
        calls=calls,
    )
    page.goto(live_url + "/business?tab=handoffs")
    waiting = page.locator("[data-tile=handoffs-waiting] .tile-value")
    expect(waiting).to_have_text("1")
    btn = page.locator(".handoff-row button")
    btn.click()
    expect(btn).to_have_text("Followed up (undo)")
    expect(waiting).to_have_text("0")
    assert calls[-1]["body"] == {"followedUp": True}
    btn.click()
    expect(btn).to_have_text("Mark followed up")
    expect(waiting).to_have_text("1")
    assert calls[-1]["body"] == {"followedUp": False}


def test_safety_stop_row_is_marked(page: Page, live_url: str, overview_stub):
    stub_list(
        page,
        handoff(id=1, kind="safety_stop", reason="safety_stop"),
        handoff(id=2),
    )
    json_route(
        page,
        re.compile(r".*/handoffs/\d+/followed-up$"),
        {"handoff": view(status="followed_up")},
    )
    page.goto(live_url + "/business?tab=handoffs")
    rows = page.locator(".handoff-row")
    expect(rows).to_have_count(2)
    mark = rows.nth(0).locator("[data-mark=safety_stop]")
    expect(mark).to_have_text("Safety stop")
    expect(rows.nth(1).locator("[data-mark=safety_stop]")).to_have_count(0)
    btn = rows.nth(0).locator("button")
    btn.click()
    expect(btn).to_have_text("Followed up (undo)")


def test_failure_handoff_says_after_an_error(page: Page, live_url: str, overview_stub):
    stub_list(
        page,
        handoff(id=1, reason="provider_failure", by_error=True),
        handoff(id=2),
    )
    page.goto(live_url + "/business?tab=handoffs")
    rows = page.locator(".handoff-row .summary")
    expect(rows.nth(0)).to_contain_text("Provider failure, after an error. Told:")
    expect(rows.nth(1)).not_to_contain_text("after an error")


def test_tiles_on_every_tab(page: Page, live_url: str, overview_stub):
    json_route(page, HANDOFFS, {"handoffs": []})
    json_route(page, re.compile(r".*/waitlist$"), {"entries": []})
    json_route(page, re.compile(r".*/conversations\?.*"), {"conversations": []})
    for tab in ("handoffs", "waitlist", "conversations"):
        page.goto(live_url + f"/business?tab={tab}")
        assert page.locator(".tile-label").all_inner_texts() == [
            "Public URL",
            "Last conversation",
            "Errors shown to callers, last 24 h",
            "Handoffs waiting for follow-up",
        ]


def test_no_sideways_scroll_at_390(page: Page, live_url: str, overview_stub):
    page.set_viewport_size({"width": 390, "height": 800})
    stub_list(page, handoff(kind="safety_stop"))
    page.goto(live_url + "/business?tab=handoffs")
    expect(page.locator(".handoff-row")).to_have_count(1)
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )


def test_list_failure_says_could_not_load(page: Page, live_url: str, overview_stub):
    json_route(page, HANDOFFS, {"error": {"code": "x"}}, status=500)
    page.goto(live_url + "/business?tab=handoffs")
    expect(page.locator("#rows .empty")).to_have_text(
        "Could not load handoffs. Reload to try again."
    )


def test_followed_up_failure_shows_inline_error(
    page: Page, live_url: str, overview_stub
):
    stub_list(page, handoff())
    json_route(
        page, re.compile(r".*/handoffs/7/followed-up$"), {"error": {}}, status=500
    )
    page.goto(live_url + "/business?tab=handoffs")
    btn = page.locator(".handoff-row button")
    btn.click()
    error = page.locator(".handoff-row .send-error")
    expect(error).to_have_text("Could not save. Try again.")
    expect(error).to_have_attribute("role", "alert")
    expect(btn).to_have_text("Mark followed up")
    expect(btn).to_be_enabled()
    expect(page.locator("[data-tile=handoffs-waiting] .tile-value")).to_have_text("1")


def test_safety_stop_text_is_separated(page: Page, live_url: str, overview_stub):
    stub_list(page, handoff(kind="safety_stop", reason="safety_stop"))
    page.goto(live_url + "/business?tab=handoffs")
    expect(page.locator(".handoff-row .summary")).to_have_text(
        "Safety stop. Told: A supervisor calls within 1 business day about the double charge."
    )

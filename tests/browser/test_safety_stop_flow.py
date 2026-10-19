"""S31 in the browser: the gas chip stops the chat, and staff see the stop in Handoffs.

The app is the real one; only the danger screen's network call is scripted.
"""

import sqlite3

import pytest
from playwright.sync_api import Page, expect

from app.conversation import guards
from app.safety.service import OpenRouterSafetyClassifier
from app.settings import Settings
from tests.browser.test_chat_states import RED_BG, RED_FG, banner_check


def schedule_dump(settings: Settings) -> list[str]:
    conn = sqlite3.connect(settings.SCHEDULING_DB_PATH)
    try:
        return list(conn.iterdump())
    finally:
        conn.close()


def test_gas_chip_stops_the_chat(
    page: Page, live_url: str, started: Settings, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        OpenRouterSafetyClassifier,
        "classify",
        lambda self, messages, timeout_s: '{"verdict": "emergency", "reason": "gas"}',
    )
    before = schedule_dump(started)
    page.goto(live_url + "/")

    page.get_by_role("button", name="I smell gas").click()

    banner_check(page, "Safety stop. Leave the home and call 911.", RED_BG, RED_FG)
    bubble = page.locator(".msg-row.bot .bubble").last
    expect(bubble).to_have_text(guards.emergency_text(False))
    print("reply:", bubble.inner_text())
    expect(page.get_by_role("textbox", name="Type your message")).to_be_hidden()
    expect(page.locator("#composer")).to_be_hidden()
    expect(page.locator("#ended-text")).to_have_text("This conversation has ended.")
    print(
        "text box visible:",
        page.get_by_role("textbox", name="Type your message").is_visible(),
    )
    assert schedule_dump(started) == before
    print("scheduling db unchanged:", len(before), "lines")

    page.goto(live_url + "/business?tab=handoffs")

    row = page.locator(".handoff-row")
    expect(row).to_have_count(1)
    expect(row.locator("[data-mark=safety_stop]")).to_have_text("Safety stop")
    expect(row.locator(".who")).to_have_text("Caller not identified")
    expect(row.locator(".summary")).to_contain_text("Told: Please leave the house now")
    print("handoff row:", row.inner_text().splitlines())
    button = row.locator("button")
    button.click()
    expect(button).to_have_text("Followed up (undo)")
    conn = sqlite3.connect(started.APP_DB_PATH)
    status = conn.execute("SELECT kind, status FROM handoffs").fetchall()
    conn.close()
    print("app db handoffs:", status)
    assert status == [("safety_stop", "followed_up")]

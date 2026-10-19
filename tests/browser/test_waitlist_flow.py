"""S34: the real chat page goes from Wants earlier to Waitlisted, and the unstubbed
Waitlist tab shows the entry. Real Conversation, Scheduling and Follow-ups modules on a
seed copy; only the model is recorded."""

import re
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn
from playwright.sync_api import Browser, Page, expect

from app.knowledge.embeddings import FakeEmbedder
from app.knowledge.service import rebuild_index
from app.llm import FakeModelProvider
from app.main import create_app
from app.settings import Settings
from tests.browser.test_booking_flow import send
from tests.gate.test_identify_and_book import CHIP, EARLIER, OMAR, up_to_windows
from tests.gate.test_waitlist_join import (
    BOOKED_TEXT,
    EARLIER_LABELS,
    earlier_turn,
    join_turn,
    omar_holds_115,
)

WAITLIST_LINE = (
    "On the waitlist for an earlier window. The team will call you if one opens."
)


@pytest.fixture
def waitlist_url(kb_settings: Settings) -> Iterator[str]:
    held_115 = omar_holds_115(kb_settings)  # S33's demo left slot 115 booked for Omar
    model = FakeModelProvider(
        results=[
            *up_to_windows(OMAR),
            *earlier_turn(),
            *join_turn(held_115, BOOKED_TEXT, book=True),
        ]
    )
    app = create_app(kb_settings, model=model, embedder=FakeEmbedder())
    rebuild_index(app.state.ctx)
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started:
        assert time.monotonic() < deadline, "server did not start"
        time.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def wants_earlier(browser: Browser, url: str, width: int) -> Page:
    """Chip, "No", identify as Omar, then click "Nothing earlier?"."""
    page = browser.new_context(viewport={"width": width, "height": 900}).new_page()
    page.goto(url + "/")
    bot = page.locator(".bubble.bot")
    page.get_by_role("button", name=CHIP).click()
    expect(bot).to_have_count(2)
    send(page, "No")
    expect(bot).to_have_count(3)
    send(page, OMAR)
    expect(bot).to_have_count(4)
    windows = page.locator(".choices .choice")
    expect(windows.first).to_have_text("Wednesday October 21, 1 PM to 5 PM, Jun Park")
    windows.last.click()
    expect(page.locator(".choices .choice")).to_have_count(3)
    return page


def test_wants_earlier_then_waitlisted_end_to_end(browser: Browser, waitlist_url: str):
    errors: list[str] = []
    page = wants_earlier(browser, waitlist_url, 1280)
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    buttons = page.locator(".choices .choice")
    print(f"earlier choices={buttons.all_text_contents()}")
    expect(buttons).to_have_text(EARLIER_LABELS)
    expect(page.locator("#composer")).to_be_hidden()
    print(f"composer visible={page.locator('#composer').is_visible()}")
    assert EARLIER not in buttons.all_text_contents()

    buttons.first.click()
    card = page.locator(".booking-card")
    expect(card).to_be_visible()
    lines = card.locator(":scope > div").all_text_contents()
    print(f"card={lines}")
    assert lines[:3] == [
        "Visit booked",
        "Wednesday October 21, 1 PM to 5 PM",
        "Technician Jun Park",
    ]
    expect(card.locator(".waitlist-line")).to_have_text(WAITLIST_LINE)
    expect(page.locator("#solved-bar")).to_be_visible()
    expect(page.locator("#composer")).to_be_visible()

    page.goto(waitlist_url + "/business?tab=waitlist")
    row = page.locator(".waitlist-row")
    expect(row).to_have_count(1)
    expect(row.locator(".who")).to_have_text("Omar Patel, Kyle, south")
    expect(row.locator(".want")).to_have_text(
        "HVAC repair, earlier than Wednesday 2026-10-21 1 to 5"
    )
    expect(row.locator(".since")).to_have_text(re.compile(r"^(Just now|\d+ min ago)$"))
    print(
        "waitlist row:",
        row.locator(".who").text_content(),
        "|",
        row.locator(".want").text_content(),
        "|",
        row.locator(".since").text_content(),
    )
    assert errors == []
    page.context.close()


def test_waitlisted_fits_390(browser: Browser, waitlist_url: str):
    page = wants_earlier(browser, waitlist_url, 390)
    page.locator(".choices .choice").first.click()
    expect(page.locator(".booking-card .waitlist-line")).to_have_text(WAITLIST_LINE)
    chat_width = page.evaluate("document.documentElement.scrollWidth")
    page.goto(waitlist_url + "/business?tab=waitlist")
    expect(page.locator(".waitlist-row")).to_have_count(1)
    tab_width = page.evaluate("document.documentElement.scrollWidth")
    print(f"390px scrollWidth chat={chat_width} waitlist tab={tab_width}")
    assert chat_width <= 390 and tab_width <= 390
    page.context.close()

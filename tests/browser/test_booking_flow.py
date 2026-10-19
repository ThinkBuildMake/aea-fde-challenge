"""S33: the real chat page books a visit through the real Conversation, Scheduling and
Knowledge modules; only the model is recorded. The card comes from the committed row."""

import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import closing

import pytest
import uvicorn
from playwright.sync_api import Browser, Page, expect

from app.knowledge.embeddings import FakeEmbedder
from app.knowledge.service import rebuild_index
from app.llm import FakeModelProvider
from app.main import create_app
from app.settings import Settings
from tests.gate.test_identify_and_book import (
    CHIP,
    EARLIER,
    OMAR,
    OMAR_FIRST,
    pick,
    up_to_windows,
)


@pytest.fixture
def booking_url(kb_settings: Settings) -> Iterator[str]:
    model = FakeModelProvider(results=[*up_to_windows(OMAR), *pick(115, OMAR_FIRST)])
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


def send(page: Page, text: str) -> None:
    page.get_by_role("textbox", name="Type your message").fill(text)
    page.get_by_role("button", name="Send", exact=True).click()


def book_in_browser(browser: Browser, url: str, width: int) -> Page:
    """Chip, "No", identify as Omar, then click the first window."""
    page = browser.new_context(viewport={"width": width, "height": 900}).new_page()
    page.goto(url + "/")
    bot = page.locator(".bubble.bot")
    page.get_by_role("button", name=CHIP).click()
    expect(bot).to_have_count(2)
    send(page, "No")
    expect(bot).to_have_count(3)
    send(page, OMAR)
    expect(bot).to_have_count(4)
    block = page.locator(".choices")
    expect(block.locator(".choices-label")).to_have_text("Open windows in your area")
    buttons = block.locator(".choice")
    expect(buttons).to_have_count(4)
    expect(buttons.first).to_have_text(OMAR_FIRST)
    expect(buttons.last).to_have_text(EARLIER)
    print(f"{width}px windows: {buttons.all_text_contents()}")
    buttons.first.click()
    expect(page.locator(".booking-card")).to_be_visible()
    return page


def test_identify_and_book_end_to_end(
    browser: Browser, booking_url: str, kb_settings: Settings
):
    page = book_in_browser(browser, booking_url, 1280)
    card = page.locator(".booking-card")
    lines = card.locator(":scope > div").all_text_contents()
    style = card.evaluate(
        "c => [getComputedStyle(c).borderTopColor, getComputedStyle(c).backgroundColor]"
    )
    with closing(sqlite3.connect(kb_settings.SCHEDULING_DB_PATH)) as conn:
        status = conn.execute(
            "SELECT status FROM appointment_slots WHERE slot_id = 115"
        ).fetchone()[0]
        mine = conn.execute(
            "SELECT slot_id, status FROM appointments WHERE customer_id = 'MHC-10002' "
            "AND slot_id = 115"
        ).fetchall()
    print(f"card={lines} colors={style} slot 115={status} appointments={mine}")
    assert lines == [
        "Visit booked",
        "Wednesday October 21, 8 AM to 12 PM",
        "Technician Jun Park",
        "Diagnostic fee $89, credited toward the repair",
    ]
    assert style == ["rgb(27, 127, 75)", "rgb(240, 248, 243)"]
    assert page.locator(".choices").count() == 0
    assert status == "booked"
    assert mine == [(115, "scheduled")]
    page.context.close()


def test_identify_and_book_fits_390(browser: Browser, booking_url: str):
    page = book_in_browser(browser, booking_url, 390)
    width = page.evaluate("document.documentElement.scrollWidth")
    print(f"390px scrollWidth={width}")
    assert width <= 390
    expect(page.locator(".booking-card .booking-title")).to_have_text("Visit booked")
    page.context.close()

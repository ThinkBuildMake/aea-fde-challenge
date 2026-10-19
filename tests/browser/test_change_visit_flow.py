"""S35: the real chat page moves Linda Foster's visit through the real Conversation,
Scheduling and Knowledge modules; only the model is recorded. A member's card says the
diagnostic fee is waived."""

import os
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest
import uvicorn
from playwright.sync_api import Browser, Page, expect

from app.knowledge.embeddings import FakeEmbedder
from app.knowledge.service import rebuild_index
from app.llm import FakeModelProvider
from app.main import create_app
from app.settings import Settings
from tests.browser.test_booking_flow import send
from tests.gate.test_change_a_visit import (
    LINDA_ASK,
    LINDA_MONDAY,
    MOVE_ASK,
    linda_lookup,
    move_to_monday,
)

# Screenshots go only where the run asks for them, never into the repo.
SHOTS = os.environ.get("MERIDIAN_SCREENSHOT_DIR")


@pytest.fixture
def move_url(kb_settings: Settings) -> Iterator[str]:
    model = FakeModelProvider(results=[*linda_lookup(), *move_to_monday()])
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


def move_in_browser(browser: Browser, url: str, width: int) -> Page:
    """Ask about the visit, ask for Monday, then click the first Monday window."""
    page = browser.new_context(viewport={"width": width, "height": 900}).new_page()
    page.goto(url + "/")
    bot = page.locator(".bubble.bot")
    send(page, LINDA_ASK)
    expect(bot).to_have_count(2)
    send(page, MOVE_ASK)
    expect(bot).to_have_count(3)
    buttons = page.locator(".choices .choice")
    expect(buttons.first).to_have_text(LINDA_MONDAY)
    print(f"{width}px windows: {buttons.all_text_contents()}")
    buttons.first.click()
    expect(page.locator(".booking-card")).to_be_visible()
    if SHOTS:
        page.screenshot(path=str(Path(SHOTS) / f"s35-move-{width}.png"), full_page=True)
    return page


def test_move_shows_the_waived_card(
    browser: Browser, move_url: str, kb_settings: Settings
):
    page = move_in_browser(browser, move_url, 1280)
    lines = page.locator(".booking-card > div").all_text_contents()
    with closing(sqlite3.connect(kb_settings.SCHEDULING_DB_PATH)) as conn:
        slots = dict(
            conn.execute(
                "SELECT slot_id, status FROM appointment_slots WHERE slot_id IN (56, 159)"
            ).fetchall()
        )
        moved = conn.execute(
            "SELECT slot_id, status FROM appointments WHERE appointment_id = 159"
        ).fetchone()
    print(f"card={lines} slots={slots} appointment 159={moved}")
    assert lines == [
        "Visit booked",
        "Monday October 19, 8 AM to 12 PM",
        "Technician Marta Kowalski",
        "Diagnostic fee waived for members",
    ]
    assert slots == {56: "booked", 159: "open"}
    assert moved == (56, "scheduled")
    assert page.locator(".choices").count() == 0
    page.context.close()


def test_move_fits_390(browser: Browser, move_url: str):
    page = move_in_browser(browser, move_url, 390)
    width = page.evaluate("document.documentElement.scrollWidth")
    print(f"390px scrollWidth={width}")
    assert width <= 390
    expect(page.locator(".booking-card > div").last).to_have_text(
        "Diagnostic fee waived for members"
    )
    page.context.close()

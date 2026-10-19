"""S37: the outage, its call back and the turn cap, clicked through the real chat page and
business view on the real Conversation, Follow-ups and Monitoring modules; only the model
is scripted. Set MERIDIAN_SCREENSHOT_DIR to keep screenshots of each step."""

import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from typing import Any

import pytest
import uvicorn
from playwright.sync_api import Browser, Page, expect

from app.conversation import guards
from app.knowledge.embeddings import FakeEmbedder
from app.llm import FakeModelProvider
from app.main import create_app
from app.settings import Settings
from tests.browser.test_handoff_flow import snap
from tests.test_turn import assistant, result, tool_call

NORMAL_CHIPS = 4


@contextmanager
def serve(settings: Settings, model: FakeModelProvider, **update: Any) -> Iterator[str]:
    app = create_app(
        settings.model_copy(update=update), model=model, embedder=FakeEmbedder()
    )
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
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def handled_conversation(page: Page, url: str) -> None:
    """A booking conversation the agent handles, so the handled-topics figure is a number."""
    cid = page.request.post(url + "/conversations").json()["conversationId"]
    page.request.post(
        f"{url}/conversations/{cid}/messages", data={"text": "I need a repair visit"}
    )


def overview_figures(page: Page, url: str) -> tuple[str, str]:
    page.goto(url + "/business")
    return (
        page.locator("[data-tile=errors] .tile-value").inner_text(),
        page.locator(
            "[data-block=handoffs-handled-topics] .support-value"
        ).inner_text(),
    )


@pytest.mark.parametrize("width", [1280, 390])
def test_outage_to_call_back(browser: Browser, kb_settings: Settings, width: int):
    model = FakeModelProvider(
        results=[
            result(
                assistant(
                    calls=[
                        tool_call(
                            "r", "report_status", intent="book_visit", resolved=True
                        )
                    ]
                )
            ),
            result(assistant("Happy to help.")),
        ]
    )
    page = browser.new_context(viewport={"width": width, "height": 900}).new_page()
    with serve(kb_settings, model, DEMO_FAULT_INJECTION=True) as url:
        handled_conversation(page, url)
        errors_before, handled_before = overview_figures(page, url)

        page.goto(url + "/")
        chip = page.locator(".chip", has_text="Simulate an outage")
        expect(chip).to_have_count(1)
        t0 = time.monotonic()
        chip.click()
        banner = page.locator("#chat-banner")
        expect(banner).to_have_text("Something went wrong on our side", timeout=15000)
        elapsed = time.monotonic() - t0
        expect(banner).to_have_class("chat-banner warn")
        bot = page.locator(".bubble.bot")
        expect(bot.last).to_have_text(guards.FALLBACK_TEXT)
        picker = page.locator(".callback-picker")
        expect(picker.locator("button")).to_have_text(
            ["Morning", "Afternoon", "Evening"]
        )
        snap(page, "s37-1-outage", width)
        print(f"\n[{width}px] {elapsed:.1f}s banner={banner.inner_text()!r} "
              f"class={banner.get_attribute('class')!r}\nreply={bot.last.inner_text()!r}")  # fmt: skip

        page.get_by_role("button", name="Morning").click()
        expect(page.locator("#ended-text")).to_have_text(
            "This conversation has been handed over."
        )
        snap(page, "s37-2-morning", width)
        with closing(sqlite3.connect(kb_settings.APP_DB_PATH)) as conn:
            stored = conn.execute(
                "SELECT h.reason, h.by_error, h.preferred_window, c.outcome "
                "FROM handoffs h JOIN conversations c ON c.id = h.conversation_id"
            ).fetchall()
        assert stored == [("provider_failure", 1, "morning", "handoff")]

        page.goto(url + "/business?tab=handoffs")
        row = page.locator(".handoff-row")
        expect(row).to_have_count(1)
        expect(row).to_contain_text("Provider failure, after an error")
        expect(row.locator(".window")).to_have_text("Prefers morning")
        snap(page, "s37-3-handoffs", width)
        print(f"handoff row={row.locator('.summary').inner_text()!r} "
              f"window={row.locator('.window').inner_text()!r} stored={stored}")  # fmt: skip

        errors_after, handled_after = overview_figures(page, url)
        snap(page, "s37-4-overview", width)
        print(f"Errors shown to callers: {errors_before} -> {errors_after}; "
              f"handoffs on handled topics: {handled_before} -> {handled_after}")  # fmt: skip
        assert int(errors_after) == int(errors_before) + 1
        assert handled_after == handled_before
    assert elapsed < 15


def test_chip_hidden_with_setting_off(browser: Browser, kb_settings: Settings):
    page = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
    with serve(kb_settings, FakeModelProvider(), DEMO_FAULT_INJECTION=False) as url:
        page.goto(url + "/")
        page.wait_for_load_state("networkidle")
        outage = page.locator(".chip", has_text="Simulate an outage")
        expect(page.locator(".chip")).to_have_count(NORMAL_CHIPS)
        expect(outage).to_have_count(0)
        snap(page, "s37-5-chip-off", 1280)
        print(f"\nchips={page.locator('.chip').all_inner_texts()} "
              f"outage chips={outage.count()}")  # fmt: skip


@pytest.mark.parametrize("width", [1280, 390])
def test_turn_cap_ends_the_chat(browser: Browser, kb_settings: Settings, width: int):
    page = browser.new_context(viewport={"width": width, "height": 900}).new_page()
    model = FakeModelProvider(replies=["Sure."])
    with serve(kb_settings, model, TURN_CAP=4) as url:
        page.goto(url + "/")
        bot = page.locator(".bubble.bot")
        for i in range(5):
            page.locator("#msg").fill(f"message {i + 1}")
            page.locator("#composer button").click()
            expect(bot).to_have_count(i + 2)
        expect(bot.last).to_have_text(guards.TURN_CAP_TEXT)
        expect(page.locator("#ended")).to_be_visible()
        expect(page.locator("#composer")).to_be_hidden()
        expect(page.locator("#start-new")).to_have_text("Start a new conversation")
        snap(page, "s37-6-turn-cap", width)
        with closing(sqlite3.connect(kb_settings.APP_DB_PATH)) as conn:
            ended = conn.execute(
                "SELECT outcome, outcome_reason FROM conversations"
            ).fetchall()
        print(f"\n[{width}px] 4th reply={bot.nth(4).inner_text()!r}\n"
              f"after the 5th: {bot.last.inner_text()!r} "
              f"footer={page.locator('#ended-text').inner_text()!r} db={ended}")  # fmt: skip
        assert ended == [("failed", "turn_cap")]

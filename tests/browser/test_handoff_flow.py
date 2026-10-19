"""S32: a disputed charge and a request for a person, clicked through the real chat page and
the Handoffs tab on the real Conversation, Follow-ups and Knowledge modules; only the model
is recorded. Set MERIDIAN_SCREENSHOT_DIR to keep screenshots of each step."""

import os
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import closing

import pytest
import uvicorn
from playwright.sync_api import Browser, Page, expect

from app.conversation import guards
from app.knowledge.embeddings import FakeEmbedder
from app.knowledge.service import rebuild_index
from app.llm import FakeModelProvider
from app.main import create_app
from app.settings import Settings
from tests.gate.test_handoff_seams import recording

NOTE = (
    "The person who calls will already have this conversation, so you will not need "
    "to repeat it."
)


@pytest.fixture
def flow_url(kb_settings: Settings) -> Iterator[str]:
    model = FakeModelProvider(
        results=[*recording("charged_twice"), *recording("asks_for_person")]
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


def snap(page: Page, name: str, width: int) -> None:
    folder = os.environ.get("MERIDIAN_SCREENSHOT_DIR")
    if folder:
        page.screenshot(
            path=os.path.join(folder, f"{name}-{width}.png"), full_page=True
        )


def dispute(page: Page, url: str, width: int) -> None:
    """Click the chip and check the handed-over reply, banner and picker."""
    page.goto(url + "/")
    page.get_by_role("button", name="I was charged twice").click()
    bot = page.locator(".bubble.bot")
    expect(bot).to_have_count(2)
    banner = page.locator("#chat-banner")
    expect(banner).to_have_text("Passed to a person")
    expect(banner).to_have_class("chat-banner warn")
    expect(bot.last).to_have_text(guards.SUPERVISOR_DISPUTE_TEXT)
    picker = page.locator(".callback-picker")
    expect(picker.locator(".callback-title")).to_have_text(
        "When is the best time for the call back?"
    )
    expect(picker.locator("button")).to_have_text(["Morning", "Afternoon", "Evening"])
    expect(picker.locator(".callback-note")).to_have_text(NOTE)
    snap(page, "1-dispute", width)
    print(f"\n[{width}px] banner={banner.inner_text()!r}")
    print(f"reply={bot.last.inner_text()!r}")
    print(f"picker={picker.locator('.callback-title').inner_text()!r} "
          f"{picker.locator('button').all_inner_texts()} note={NOTE!r}")  # fmt: skip


@pytest.mark.parametrize("width", [1280, 390])
def test_dispute_to_followed_up(
    browser: Browser, flow_url: str, kb_settings: Settings, width: int
):
    page = browser.new_context(viewport={"width": width, "height": 900}).new_page()
    dispute(page, flow_url, width)

    page.get_by_role("button", name="Afternoon").click()
    expect(page.locator("#ended-text")).to_have_text(
        "This conversation has been handed over."
    )
    expect(page.locator("#start-new")).to_have_text("Start a new conversation")
    expect(page.locator("#composer")).to_be_hidden()
    with closing(sqlite3.connect(kb_settings.APP_DB_PATH)) as conn:
        stored = conn.execute("SELECT preferred_window FROM handoffs").fetchall()
    assert stored == [("afternoon",)]
    snap(page, "2-picked", width)
    print(f"footer={page.locator('#ended-text').inner_text()!r} "
          f"button={page.locator('#start-new').inner_text()!r} stored={stored}")  # fmt: skip

    page.goto(flow_url + "/business?tab=handoffs")
    row = page.locator(".handoff-row")
    expect(row).to_have_count(1)
    summary = row.locator(".summary")
    expect(summary).to_contain_text("Charged twice", ignore_case=True)
    expect(summary).to_contain_text("supervisor")
    expect(summary).to_contain_text("within 1 business day")
    expect(row.locator(".window")).to_have_text("Prefers afternoon")
    expect(row.locator(".who")).to_have_text("Caller not identified")
    waiting = page.locator("[data-tile=handoffs-waiting] .tile-value")
    expect(waiting).to_have_text("1")
    before = waiting.inner_text()
    snap(page, "3-handoffs", width)
    print(f"row: who={row.locator('.who').inner_text()!r}")
    print(f"summary={summary.inner_text()!r}")
    print(f"window={row.locator('.window').inner_text()!r} waiting={before}")

    row.get_by_role("button", name="Mark followed up").click()
    expect(row.locator("button")).to_have_text("Followed up (undo)")
    expect(waiting).to_have_text("0")
    listed = page.request.get(
        flow_url + "/handoffs?status=followed_up",
        headers={"Accept": "application/json"},
    ).json()["handoffs"]
    assert len(listed) == 1 and listed[0]["followedUpAt"]
    snap(page, "4-followed-up", width)
    print(f"button={row.locator('button').inner_text()!r} waiting {before} -> "
          f"{waiting.inner_text()} followedUpAt={listed[0]['followedUpAt']}")  # fmt: skip
    page.context.close()


def test_asking_for_a_person(browser: Browser, flow_url: str):
    page = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
    dispute(page, flow_url, 1280)
    page.get_by_role("button", name="Start a new conversation").click()
    page.get_by_role("textbox", name="Type your message").fill(
        "Can I just talk to a person?"
    )
    page.get_by_role("button", name="Send", exact=True).click()
    bot = page.locator(".bubble.bot")
    expect(bot.last).to_have_text(guards.PERSON_TEXT)
    expect(page.locator("#chat-banner")).to_have_text("Passed to a person")
    expect(page.locator(".callback-picker button")).to_have_text(
        ["Morning", "Afternoon", "Evening"]
    )
    snap(page, "5-person", 1280)
    print(f"\nreply={bot.last.inner_text()!r}")
    print(f"banner={page.locator('#chat-banner').inner_text()!r}")
    page.context.close()

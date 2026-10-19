"""The Overview tab against the real get_overview: no stub, real conversations."""

import pytest
from playwright.sync_api import Page, expect

from app.settings import Settings
from app.startup import run_startup

PUBLIC_URL = "https://meridian.example.app"


@pytest.fixture
def started(tmp_settings: Settings) -> Settings:
    settings = tmp_settings.model_copy(update={"PUBLIC_URL": PUBLIC_URL})
    run_startup(settings)
    return settings


def open_overview(page: Page, live_url: str) -> None:
    page.goto(live_url + "/business")
    expect(page.locator("#overview-body")).to_be_visible()


def test_public_url_tile_shows_the_deployed_address(page: Page, live_url: str):
    open_overview(page, live_url)
    tile = page.locator("[data-tile=public-url] .tile-value")
    print(
        "Public URL tile:", tile.inner_text(), "| class:", tile.get_attribute("class")
    )
    expect(tile).to_have_text(PUBLIC_URL)
    expect(tile).to_have_class("tile-value ok")


def test_new_conversation_shows_within_a_minute(page: Page, live_url: str):
    page.clock.install()
    open_overview(page, live_url)
    expect(page.locator("[data-block=recent]")).to_contain_text("No conversations yet")
    page.evaluate("window.__noReload = 1")

    cid = page.request.post(live_url + "/conversations").json()["conversationId"]
    sent = page.request.post(
        f"{live_url}/conversations/{cid}/messages",
        data={"text": "Are you open on Sundays?"},
    )
    assert sent.ok
    assert page.request.post(
        f"{live_url}/conversations/{cid}/solved", data={"answer": "yes"}
    ).ok
    page.clock.fast_forward("00:30")

    row = page.locator(".recent-row").first
    expect(row.locator(".when")).to_have_text("0 min")
    expect(row.locator(".what")).to_have_text("Other")
    expect(row.locator(".outcome")).to_have_text("Contained")
    assert page.evaluate("window.__noReload") == 1

    ms = page.request.get(live_url + "/overview").json()["latencySeries24h"][-1][
        "p95FirstReplyMs"
    ]
    dot = page.locator("[data-block=first-reply] circle")
    expect(dot).to_have_count(1)
    print(
        "after 30 s:",
        row.inner_text().replace("\n", " | "),
        "| noReload",
        page.evaluate("window.__noReload"),
        "| p95 ms",
        ms,
        "| dot",
        dot.get_attribute("cx"),
        dot.get_attribute("cy"),
    )
    assert ms is not None
    assert dot.get_attribute("cx") == "390.0"
    assert dot.get_attribute("cy") == f"{100 - 100 * (ms / 1000) / 8:.1f}"

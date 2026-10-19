import pytest
from playwright.sync_api import Page, expect

from app.monitoring import routes
from app.types import Overview
from tests.test_overview_view import make_overview, over_spend


@pytest.fixture
def stub(monkeypatch: pytest.MonkeyPatch) -> dict[str, Overview]:
    holder = {"o": make_overview()}
    monkeypatch.setattr(routes, "get_overview", lambda ctx, *a, **k: holder["o"])
    return holder


def open_tab(page: Page, live_url: str) -> None:
    page.goto(live_url + "/business?tab=overview")
    expect(page.locator("#overview-body")).to_be_visible()


def test_status_tiles(page: Page, live_url: str, stub):
    open_tab(page, live_url)
    labels = page.locator(".tile-label").all_inner_texts()
    values = page.locator(".tile-value").all_inner_texts()
    assert labels == [
        "Public URL",
        "Last conversation",
        "Errors shown to callers, last 24 h",
        "Handoffs waiting for follow-up",
    ]
    assert values == ["https://x.example", "3 minutes ago", "2", "1"]
    assert "answered in" not in page.inner_text("body")


def test_success_metric(page: Page, live_url: str, stub):
    open_tab(page, live_url)
    block = page.locator("[data-block=settled]")
    expect(block).to_contain_text("Calls settled by the agent (rolling 7 days)")
    expect(block.locator(".metric-big")).to_have_text("62%")
    expect(block.locator(".count-line")).to_have_text(
        '143 of 231 conversations: no handoff and the caller tapped "yes, that solved it"'
    )
    expect(block).to_contain_text(
        "Target 60% to 75%. Callers who skip the tap count as not settled."
    )
    expect(block).to_contain_text("target band 60 to 75%")
    assert block.locator("rect").count() == 1
    assert len(block.locator("polyline").get_attribute("points").split()) == 7


def test_supporting_metrics(page: Page, live_url: str, stub):
    open_tab(page, live_url)
    tiles = page.locator(".support")
    assert [t.locator(".label").inner_text() for t in tiles.all()] == [
        "Booking completion",
        "Handoffs on topics the agent should handle",
        "Flagged wrong",
    ]
    assert [t.locator(".support-value").inner_text() for t in tiles.all()] == [
        "88%",
        "7%",
        "2%",
    ]
    expect(tiles.nth(0)).to_contain_text("No target yet.")
    expect(tiles.nth(1)).to_contain_text(
        "Top reason: no matching document. No target yet."
    )


def test_what_just_happened(page: Page, live_url: str, stub):
    open_tab(page, live_url)
    rows = page.locator(".recent-row")
    assert rows.locator(".when").all_inner_texts() == ["3 min", "12 min", "21 min"]
    assert rows.locator(".outcome").all_inner_texts() == [
        "Contained",
        "Handoff",
        "Safety stop",
    ]
    assert rows.locator(".latency").all_inner_texts() == ["4.1 s", "3.3 s", "2.1 s"]


def test_what_just_happened_empty(page: Page, live_url: str, stub):
    stub["o"] = make_overview(recent=[])
    open_tab(page, live_url)
    expect(page.locator("[data-block=recent]")).to_contain_text("No conversations yet")
    assert page.locator(".recent-row").count() == 0


def test_unset_public_url_is_muted(page: Page, live_url: str, stub):
    status = stub["o"].status.model_copy(update={"public_url": None})
    stub["o"] = make_overview(status=status)
    open_tab(page, live_url)
    tile = page.locator("[data-tile=public-url] .tile-value")
    expect(tile).to_have_text("Not set")
    expect(tile).to_have_class("tile-value muted")


def test_promises_table(page: Page, live_url: str, stub):
    open_tab(page, live_url)
    rows = page.locator(".promises tbody tr")
    assert rows.count() == 5
    assert rows.locator("td:nth-child(3)").all_inner_texts() == [
        "at most 6 s",
        "at most 10 s",
        "0",
        "0",
        "alert at $100",
    ]
    assert (
        rows.locator("td:nth-child(4)").all_inner_texts()
        == ["Over limit"] + ["Within limit"] * 4
    )
    assert "Uptime" not in page.inner_text("body")


def test_spend_line_and_banner(page: Page, live_url: str, stub):
    stub["o"] = over_spend()
    open_tab(page, live_url)
    expect(page.locator(".promises tbody tr").last.locator("td").nth(3)).to_have_text(
        "Over limit"
    )
    expect(page.locator("[data-spend-line]")).to_have_text(
        "Total model spend: $104 of the $100 alert."
    )
    expect(page.locator("[data-banner=spend]")).to_be_visible()


def test_no_banner_without_alert(page: Page, live_url: str, stub):
    open_tab(page, live_url)
    expect(page.locator("[data-banner=spend]")).to_have_count(0)


def test_refreshes_every_30_seconds(page: Page, live_url: str, stub):
    page.clock.install()
    open_tab(page, live_url)
    page.evaluate("window.__noReload = 1")
    status = stub["o"].status.model_copy(
        update={"errors_shown_24h": 5, "handoffs_waiting": 4}
    )
    stub["o"] = make_overview(status=status)
    page.clock.fast_forward("00:30")
    expect(page.locator(".tile-value").nth(2)).to_have_text("5")
    expect(page.locator(".tile-value").nth(3)).to_have_text("4")
    assert page.evaluate("window.__noReload") == 1
    assert "Refreshes every 30 seconds (lag under 1 minute)." in page.inner_text("body")


def test_no_sideways_scroll_at_390(page: Page, live_url: str, stub):
    page.set_viewport_size({"width": 390, "height": 844})
    open_tab(page, live_url)
    widths = page.evaluate(
        "[document.documentElement.scrollWidth, document.body.scrollWidth]"
    )
    assert max(widths) <= 390


def test_first_reply_line(page: Page, live_url: str, stub):
    open_tab(page, live_url)
    block = page.locator("[data-block=first-reply]")
    expect(block).to_contain_text(
        "Time to first reply, p95 by hour, last 24 h (limit 6 s)"
    )
    expect(block).to_contain_text("limit 6 s")
    assert block.locator("line[stroke-dasharray]").count() == 1
    assert len(block.locator("polyline").get_attribute("points").split()) == 24
    text = page.inner_text("body")
    assert "Public URL checks" not in text and "Dark = missed check" not in text


def test_volume_block(page: Page, live_url: str, stub):
    open_tab(page, live_url)
    block = page.locator("[data-block=volume]")
    expect(block).to_contain_text("Conversations by day and outcome")
    assert [e.text_content() for e in block.locator(".day-count").all()] == [
        "3",
        "5",
        "2",
        "4",
        "6",
        "1",
        "2",
    ]
    assert block.locator("li").all_inner_texts() == [
        "Contained 6",
        "Handoff 3",
        "Safety stop 1",
        "Failed 2",
        "Active 1",
    ]


def test_dropped_texts_absent(page: Page, live_url: str, stub):
    open_tab(page, live_url)
    text = page.inner_text("body").lower()
    for dropped in ("example data", "all numbers on this page"):
        assert dropped not in text

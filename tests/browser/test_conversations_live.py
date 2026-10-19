"""The Conversations tab against the real backend: flag, the Flagged wrong tile, a draft."""

import sqlite3
from collections.abc import Iterator
from uuid import uuid4

import pytest
from playwright.sync_api import Page, expect

from app.settings import Settings
from tests.test_monitoring_conversations import count, seed


@pytest.fixture
def db(started: Settings) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(started.APP_DB_PATH, isolation_level=None)
    yield conn
    conn.close()


def flagged_tile(page: Page, live_url: str) -> str:
    page.goto(live_url + "/business")
    return page.locator("[data-block=flagged-wrong] .support-value").inner_text()


def open_convo(page: Page, live_url: str, public: str) -> None:
    page.goto(live_url + "/business?tab=conversations")
    page.locator(f'.convo-btn[data-public-id="{public}"]').click()
    expect(page.locator("#detail .meta")).to_contain_text(public)


def test_empty_note_asks_and_saves_nothing(page: Page, live_url: str, db):
    _, public = seed(db, turns=["Is the diagnostic fee $79?"], public=uuid4().hex)
    posts: list[str] = []
    page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
    open_convo(page, live_url, public)
    btn = page.locator("#detail .btn-flag")
    btn.click()

    for blank in ("", "   "):
        page.fill("#note", blank)
        page.press("#note", "Enter")

    ask = page.locator("#detail .flag-note-needed")
    expect(ask).to_have_text("A note saying what was wrong is required.")
    print(
        "page asks:", ask.inner_text(), "| POSTs:", posts,
        "| flags saved:", count(db, "flags"), "| button:", btn.inner_text(),
    )  # fmt: skip
    assert posts == []
    assert count(db, "flags") == 0
    expect(btn).to_have_text("Flag as wrong")


def test_flag_moves_flagged_wrong(page: Page, live_url: str, db):
    _, public = seed(db, turns=["Is the diagnostic fee $79?"], public=uuid4().hex)
    before = flagged_tile(page, live_url)
    assert before == "0%"
    open_convo(page, live_url, public)
    btn = page.locator("#detail .btn-flag")
    btn.click()
    page.fill("#note", "quoted the wrong window")

    page.press("#note", "Enter")

    expect(btn).to_have_text("Flagged as wrong (undo)")
    button = btn.inner_text()
    notes = [n for (n,) in db.execute("SELECT note FROM flags")]
    after = flagged_tile(page, live_url)
    print("tile before:", before, "| button:", button, "| stored notes:", notes,
          "| tile after:", after)  # fmt: skip
    assert notes == ["quoted the wrong window"]
    assert after == "100%" and float(after.rstrip("%")) > 0


def test_turn_into_test_scenario_real(page: Page, live_url: str, db):
    _, public = seed(db, turns=["Is the diagnostic fee $79?"], public=uuid4().hex)
    open_convo(page, live_url, public)

    page.get_by_role("button", name="Turn into a test scenario").click()

    saved = page.locator("#detail .eval-saved")
    expect(saved).to_have_text(
        f"Saved as a candidate test scenario: eval/candidates/CAND-{public[:8]}.json."
        " Review it, then add it to the eval set."
    )
    rows = db.execute("SELECT scenario_id FROM eval_candidates").fetchall()
    print("saved line:", saved.inner_text(), "| eval_candidates:", rows)
    assert rows == [(f"CAND-{public[:8]}",)]

"""The caller chat page against the contract stubs (routes stubbed with page.route)."""

import time
from collections.abc import Callable

import pytest
from playwright.sync_api import Page, Route, expect

from app.conversation.routes import GREETING
from tests.browser.conftest import edges

PLAN = "What does the maintenance plan cover?"
YES_TEXT = "Thanks for letting us know. Have a good day."
NO_TEXT = "Sorry that did not solve it. Would you like me to pass you to a person?"
ENDED_YES = "Thanks, your answer is saved. This conversation has ended."
ENDED_NO = (
    "Thanks. We recorded that this did not solve it. Reply below if you want a person."
)


def reply(text: str, actions: list[str]) -> dict:
    return {
        "conversationId": "conv-1",
        "status": "active",
        "text": text,
        "banner": "none",
        "choices": [],
        "booking": None,
        "waitlisted": False,
        "actions": actions,
        "turn": {"seq": 1, "latencyMs": 5},
    }


class Stub:
    def __init__(self, page: Page):
        self.page = page
        self.requests: list[tuple[str, object]] = []
        self.started = 0
        self.reply_text = "The Comfort Club covers one tune-up a year."
        self.reply_actions = ["ask_solved"]
        self.hold: list[Route] = []
        self.holding = False
        page.route("**/conversations", self.start)
        page.route("**/conversations/*/messages", self.message)
        page.route("**/conversations/*/solved", self.solved)

    def start(self, route: Route):
        self.started += 1
        self.requests.append((route.request.url, None))
        route.fulfill(
            status=201,
            json={
                "conversationId": f"conv-{self.started}",
                "status": "active",
                "greeting": GREETING,
                "demoFaults": False,
            },
        )

    def message(self, route: Route):
        self.requests.append((route.request.url, route.request.post_data_json))
        if self.holding:
            self.hold.append(route)
            return
        self.answer(route)

    def answer(self, route: Route):
        route.fulfill(json=reply(self.reply_text, self.reply_actions))

    def solved(self, route: Route):
        body = route.request.post_data_json
        self.requests.append((route.request.url, body))
        if body["answer"] == "yes":
            out = {
                "saved": True,
                "status": "ended",
                "text": YES_TEXT,
                "actions": ["new_conversation"],
            }
        else:
            out = {"saved": True, "status": "active", "text": NO_TEXT, "actions": []}
        route.fulfill(json=out)

    def message_urls(self) -> list[str]:
        return [u for u, _ in self.requests if u.endswith("/messages")]


@pytest.fixture
def stub(page: Page) -> Stub:
    return Stub(page)


def send(page: Page, text: str) -> None:
    page.get_by_role("textbox", name="Type your message").fill(text)
    page.get_by_role("button", name="Send", exact=True).click()


def test_chip_sends_its_text(page: Page, live_url: str, stub: Stub):
    page.goto(live_url + "/")
    page.get_by_role("button", name=PLAN).click()
    mine = page.locator(".msg-row.you .bubble").last
    expect(mine).to_have_text(PLAN)
    left, right = edges(mine, page.locator("#messages"))
    assert right <= 17 and left > 17
    expect(page.locator("#chips")).to_be_hidden()
    assert stub.requests[-1][1] == {"text": PLAN}


def test_loading_then_still_working_from_10s(page: Page, live_url: str, stub: Stub):
    stub.holding = True
    page.clock.install()
    page.goto(live_url + "/")
    send(page, "hello")
    typing = page.locator(".bubble.typing")
    expect(typing).to_have_text("Looking that up...")
    expect(typing).to_have_css("background-color", "rgb(232, 237, 241)")
    expect(typing).to_have_css("color", "rgb(74, 90, 104)")
    left, _ = edges(typing, page.locator("#messages"))
    assert left < 17 + 1
    note = page.locator("#still-working")
    page.clock.run_for(9_000)
    expect(note).to_be_hidden()
    page.clock.run_for(1_000)
    expect(note).to_be_visible()
    expect(note).to_have_text("Still working on it. Thanks for waiting.")
    page.clock.run_for(2_000)
    stub.answer(stub.hold[0])
    expect(page.locator(".bubble.typing")).to_have_count(0)
    expect(note).to_have_count(0)
    expect(page.locator(".msg-row.bot .bubble").last).to_have_text(stub.reply_text)


def test_answer_shows_solved_bar(page: Page, live_url: str, stub: Stub):
    page.goto(live_url + "/")
    send(page, PLAN)
    bot = page.locator(".msg-row.bot .bubble").last
    expect(bot).to_have_text(stub.reply_text)
    left, _ = edges(bot, page.locator("#messages"))
    assert left <= 17
    bar = page.locator("#solved-bar")
    expect(bar).to_be_visible()
    expect(bar).to_contain_text("Did this solve it?")
    expect(bar.get_by_role("button", name="Yes, that solved it")).to_be_visible()
    expect(bar.get_by_role("button", name="No", exact=True)).to_be_visible()
    stub.reply_actions = []
    send(page, "and more?")
    expect(page.locator(".msg-row.bot .bubble")).to_have_count(3)
    expect(bar).to_be_hidden()


def answered(page: Page, stub: Stub) -> None:
    send(page, PLAN)
    expect(page.locator("#solved-bar")).to_be_visible()


def test_yes_thanks_and_ends(page: Page, live_url: str, stub: Stub):
    page.goto(live_url + "/")
    answered(page, stub)
    page.get_by_role("button", name="Yes, that solved it").click()
    expect(page.locator(".msg-row.bot .bubble").last).to_have_text(YES_TEXT)
    expect(page.locator("#ended-text")).to_have_text(ENDED_YES)
    expect(page.get_by_role("button", name="Start a new conversation")).to_be_visible()
    expect(page.locator("#solved-bar")).to_be_hidden()
    expect(page.locator("#composer")).to_be_hidden()
    url, body = stub.requests[-1]
    assert url.endswith("/conv-1/solved") and body == {"answer": "yes"}


def test_no_keeps_conversation_open(page: Page, live_url: str, stub: Stub):
    page.goto(live_url + "/")
    answered(page, stub)
    page.get_by_role("button", name="No", exact=True).click()
    expect(page.locator(".msg-row.bot .bubble").last).to_have_text(NO_TEXT)
    expect(page.locator("#ended-text")).to_have_text(ENDED_NO)
    expect(page.locator("#composer")).to_be_visible()
    expect(page.locator("#solved-bar")).to_be_hidden()
    assert stub.requests[-1][1] == {"answer": "no"}


def clean_start(page: Page) -> None:
    expect(page.locator("#messages .bubble")).to_have_count(1)
    expect(page.locator("#messages .bubble.bot")).to_have_text(GREETING)
    expect(page.locator(".chip")).to_have_count(4)
    expect(page.locator("#chips")).to_be_visible()
    expect(page.locator("#solved-bar")).to_be_hidden()
    expect(page.locator("#ended")).to_be_hidden()
    expect(page.locator("#composer")).to_be_visible()


@pytest.mark.parametrize("button", ["New conversation", "Start a new conversation"])
def test_new_conversation_starts_clean(
    page: Page, live_url: str, stub: Stub, button: str
):
    page.goto(live_url + "/")
    send(page, "one")
    expect(page.locator(".msg-row.bot .bubble")).to_have_count(2)
    send(page, "two")
    expect(page.locator(".msg-row.bot .bubble")).to_have_count(3)
    if button.startswith("Start"):
        page.get_by_role("button", name="Yes, that solved it").click()
        expect(page.locator("#ended")).to_be_visible()
    page.get_by_role("button", name=button).click()
    clean_start(page)
    send(page, "three")
    expect(page.locator(".msg-row.bot .bubble")).to_have_count(2)
    urls = stub.message_urls()
    assert urls[0].endswith("/conv-1/messages") and urls[1].endswith("/conv-1/messages")
    assert urls[-1].endswith("/conv-2/messages")
    assert stub.started == 2


def test_late_reply_from_old_conversation_is_dropped(
    page: Page, live_url: str, stub: Stub
):
    stub.holding = True
    page.goto(live_url + "/")
    send(page, "one")
    page.get_by_role("button", name="New conversation").click()
    stub.answer(stub.hold[0])
    clean_start(page)
    page.wait_for_timeout(100)
    clean_start(page)


def test_no_sideways_scroll_at_390_with_answer(page: Page, live_url: str, stub: Stub):
    stub.reply_text = "x" * 120
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(live_url + "/")
    answered(page, stub)
    wide: Callable[[], int] = lambda: max(
        page.evaluate(
            "[document.documentElement.scrollWidth, document.body.scrollWidth]"
        )
    )
    assert wide() <= 390
    page.get_by_role("button", name="No", exact=True).click()
    expect(page.locator("#ended")).to_be_visible()
    assert wide() <= 390


def test_pf1_reply_shown_without_page_delay(page: Page, live_url: str, stub: Stub):
    page.goto(live_url + "/")
    page.wait_for_load_state("networkidle")
    assert stub.started == 1
    began = time.monotonic()
    send(page, "hi")
    expect(page.locator(".msg-row.bot .bubble").last).to_have_text(stub.reply_text)
    assert time.monotonic() - began < 1.0
    assert stub.started == 1

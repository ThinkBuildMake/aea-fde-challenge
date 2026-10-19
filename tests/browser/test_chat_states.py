"""The caller chat page's flow states, each drawn from one stubbed contract-shaped reply."""

import pytest
from playwright.sync_api import Page, Route, expect

from app.conversation.routes import GREETING
from tests.browser.test_chat_flow import Stub, clean_start, reply, send

ACCENT = "rgb(15, 94, 140)"
AMBER_BG, AMBER_FG = "rgb(255, 244, 224)", "rgb(122, 75, 0)"
RED_BG, RED_FG = "rgb(253, 232, 231)", "rgb(140, 29, 24)"
WINDOWS = [
    "Wednesday October 21, 8 AM to 12 PM, Jun Park",
    "Wednesday October 21, 12 PM to 4 PM, Ana Ruiz",
    "Thursday October 22, 8 AM to 12 PM, Jun Park",
]
EARLIER = "Nothing earlier? Ask for an earlier window"
EARLIER_TEXT = "Can you do anything earlier?"
WANTS_EARLIER = [
    "Book Wednesday October 21, 12 PM to 4 PM and join the waitlist for earlier",
    "Book Wednesday October 21, 12 PM to 4 PM only",
    "Talk to a person instead",
]
BOOKING = {
    "appointmentId": 1,
    "slotId": 7,
    "date": "2026-10-21",
    "window": "08:00-12:00",
    "technicianName": "Jun Park",
    "serviceType": "hvac_repair",
    "zone": "north",
    "diagnosticFeeCents": 8900,
    "diagnosticFeeWaived": False,
}
WAITLIST_LINE = (
    "On the waitlist for an earlier window. The team will call you if one opens."
)
PICKER_TITLE = "When is the best time for the call back?"
PICKER_NOTE = (
    "The person who calls will already have this conversation, "
    "so you will not need to repeat it."
)
CALLBACK_TEXT = "Thanks. We will call you back in the morning."
FALLBACK = (
    "Sorry, I am having trouble right now and did not want to guess. "
    "A person can help you with this. Would you like a call back?"
)


def reply_with(**fields: object) -> dict:
    return {**reply("Here is what I found.", []), **fields}


class StateStub(Stub):
    def __init__(self, page: Page):
        self.demo_faults = False
        self.start_failures = 0
        self.body: dict | None = None
        self.callbacks: list[tuple[str, object]] = []
        self.solved_status = 200
        self.message_status = 200
        self.callback_status = 200
        super().__init__(page)
        page.route("**/conversations/*/callback-window", self.callback)

    def start(self, route: Route):
        if self.start_failures:
            self.start_failures -= 1
            self.started += 1
            route.fulfill(status=500, json={"error": {"code": "internal"}})
            return
        self.started += 1
        self.requests.append((route.request.url, None))
        route.fulfill(
            status=201,
            json={
                "conversationId": f"conv-{self.started}",
                "status": "active",
                "greeting": GREETING,
                "demoFaults": self.demo_faults,
            },
        )

    def answer(self, route: Route):
        if self.message_status != 200:
            route.fulfill(status=self.message_status, json={"error": {"code": "x"}})
        elif self.body is None:
            super().answer(route)
        else:
            route.fulfill(json=self.body)

    def solved(self, route: Route):
        if self.solved_status != 200:
            self.requests.append((route.request.url, route.request.post_data_json))
            route.fulfill(
                status=self.solved_status, json={"error": {"code": "already_answered"}}
            )
            return
        super().solved(route)

    def callback(self, route: Route):
        self.callbacks.append((route.request.url, route.request.post_data_json))
        if self.callback_status != 200:
            route.fulfill(status=self.callback_status, json={"error": {"code": "x"}})
            return
        route.fulfill(json={"handoff": {"id": 1}, "text": CALLBACK_TEXT})


@pytest.fixture
def stub(page: Page) -> StateStub:
    return StateStub(page)


def arrive(page: Page, live_url: str, stub: StateStub, body: dict) -> None:
    stub.body = body
    page.goto(live_url + "/")
    send(page, "My AC is blowing warm air")
    expect(page.locator(".msg-row.bot .bubble").last).to_have_text(body["text"])


def choices(page: Page, live_url: str, stub: StateStub, labels: list[str], texts=None):
    texts = texts or labels
    body = reply_with(
        choices=[{"label": a, "text": b} for a, b in zip(labels, texts, strict=True)]
    )
    arrive(page, live_url, stub, body)


def test_window_choices(page: Page, live_url: str, stub: StateStub):
    labels = [*WINDOWS, EARLIER]
    choices(page, live_url, stub, labels, [*WINDOWS, EARLIER_TEXT])
    block = page.locator(".choices")
    expect(block.locator(".choices-label")).to_have_text("Open windows in your area")
    buttons = block.locator("button.choice")
    expect(buttons).to_have_count(4)
    shown = buttons.all_inner_texts()
    print("choices:", shown)
    assert shown == labels
    for label, day, window, tech in (
        (shown[0], "Wednesday October 21", "8 AM to 12 PM", "Jun Park"),
        (shown[1], "Wednesday October 21", "12 PM to 4 PM", "Ana Ruiz"),
        (shown[2], "Thursday October 22", "8 AM to 12 PM", "Jun Park"),
    ):
        assert day in label and window in label and tech in label
    assert shown[-1] == EARLIER
    first = buttons.first
    expect(first).to_have_css("border-top-color", ACCENT)
    expect(first).to_have_css("background-color", "rgb(255, 255, 255)")
    expect(first).to_have_css("min-height", "44px")
    assert "(example data)" not in page.inner_text("body")
    buttons.last.click()
    expect(page.locator(".msg-row.you .bubble").last).to_have_text(EARLIER_TEXT)
    assert stub.requests[-1][1] == {"text": EARLIER_TEXT}
    print("posted:", stub.requests[-1][1])
    expect(page.locator(".msg-row.bot .bubble")).to_have_count(3)
    expect(page.locator(".choices")).to_have_count(1)


def test_wants_earlier_choices(page: Page, live_url: str, stub: StateStub):
    choices(page, live_url, stub, WANTS_EARLIER)
    buttons = page.locator("button.choice")
    expect(buttons).to_have_count(3)
    shown = buttons.all_inner_texts()
    print("choices:", shown)
    assert shown == WANTS_EARLIER
    assert shown[-1] == "Talk to a person instead"
    buttons.last.click()
    # Wait for the sent message before reading the stub's requests.
    expect(page.locator(".msg-row.you .bubble").last).to_have_text(
        "Talk to a person instead"
    )
    assert stub.requests[-1][1] == {"text": "Talk to a person instead"}
    print("posted:", stub.requests[-1][1])


def card_lines(page: Page) -> list[str]:
    return page.locator(".booking-card > div").all_inner_texts()


def test_confirmed_card(page: Page, live_url: str, stub: StateStub):
    arrive(
        page,
        live_url,
        stub,
        reply_with(text="You are booked.", booking=BOOKING, actions=["ask_solved"]),
    )
    card = page.locator(".booking-card")
    expect(card).to_be_visible()
    expect(card).to_have_css("background-color", "rgb(240, 248, 243)")
    expect(card).to_have_css("border-top-color", "rgb(27, 127, 75)")
    title = card.locator(".booking-title")
    expect(title).to_have_text("Visit booked")
    expect(title).to_have_css("color", "rgb(20, 83, 45)")
    print(
        "card colours:",
        card.evaluate(
            "(e) => [getComputedStyle(e).backgroundColor, getComputedStyle(e).borderTopColor]"
        ),
        "title:",
        title.evaluate("(e) => getComputedStyle(e).color"),
    )
    lines = card_lines(page)
    print("card:", lines)
    assert lines == [
        "Visit booked",
        "Wednesday October 21, 8 AM to 12 PM",
        "Technician Jun Park",
        "Diagnostic fee $89, credited toward the repair",
    ]
    expect(card.locator(".waitlist-line")).to_have_count(0)
    expect(page.locator("#solved-bar")).to_be_visible()


def test_waitlisted_card(page: Page, live_url: str, stub: StateStub):
    arrive(
        page,
        live_url,
        stub,
        reply_with(
            text="You are booked.",
            booking=BOOKING,
            waitlisted=True,
            actions=["ask_solved"],
        ),
    )
    line = page.locator(".booking-card .waitlist-line")
    expect(line).to_have_text(WAITLIST_LINE)
    expect(line).to_have_css("color", ACCENT)
    print("card:", card_lines(page))


def banner_check(page: Page, text: str, bg: str, fg: str) -> None:
    banner = page.locator("#chat-banner")
    expect(banner).to_be_visible()
    expect(banner).to_have_text(text)
    expect(banner).to_have_css("background-color", bg)
    expect(banner).to_have_css("color", fg)
    print("banner:", banner.inner_text(), bg, fg)


def picker_check(page: Page) -> None:
    picker = page.locator(".callback-picker")
    expect(picker).to_be_visible()
    expect(picker.locator(".callback-title")).to_have_text(PICKER_TITLE)
    buttons = picker.locator("button")
    assert buttons.all_inner_texts() == ["Morning", "Afternoon", "Evening"]
    expect(picker.locator(".callback-note")).to_have_text(PICKER_NOTE)
    print("picker:", picker.inner_text().splitlines())


def test_handoff_banner_and_callback_picker(page: Page, live_url: str, stub: StateStub):
    arrive(
        page,
        live_url,
        stub,
        reply_with(
            status="handed_off",
            banner="handoff",
            text="I am passing this to a supervisor.",
            actions=["choose_callback_window"],
        ),
    )
    banner_check(page, "Passed to a person", AMBER_BG, AMBER_FG)
    order = page.evaluate(
        "[...document.querySelector('.chat-card').children].map((e) => e.id || e.className)"
    )
    assert order.index("chat-banner") == order.index("chat-head") + 1
    assert order.index("messages") == order.index("chat-banner") + 1
    picker_check(page)
    expect(page.locator("#composer")).to_be_hidden()
    expect(page.locator("#chips")).to_be_hidden()
    page.get_by_role("button", name="Morning").click()
    expect(page.locator(".msg-row.bot .bubble").last).to_have_text(CALLBACK_TEXT)
    assert len(stub.callbacks) == 1
    url, body = stub.callbacks[0]
    assert url.endswith("/conversations/conv-1/callback-window")
    assert body == {"window": "morning"}
    print("posted:", url.split("/", 3)[-1], body)
    for name in ("Morning", "Afternoon", "Evening"):
        expect(page.get_by_role("button", name=name)).to_be_disabled()
    expect(page.locator("#ended")).to_be_visible()
    expect(page.locator("#ended-text")).to_have_text(
        "This conversation has been handed over."
    )
    expect(page.get_by_role("button", name="Start a new conversation")).to_be_visible()
    print("footer:", page.locator("#ended").inner_text().splitlines())


def test_safety_stop(page: Page, live_url: str, stub: StateStub):
    arrive(
        page,
        live_url,
        stub,
        reply_with(
            status="safety_stop",
            banner="safety_stop",
            text="Please leave the house now and call 911 from outside.",
            actions=["new_conversation"],
        ),
    )
    banner_check(page, "Safety stop. Leave the home and call 911.", RED_BG, RED_FG)
    expect(page.get_by_role("textbox", name="Type your message")).to_be_hidden()
    expect(page.locator("#composer")).to_be_hidden()
    expect(page.locator("#chips")).to_be_hidden()
    expect(page.locator("#solved-bar")).to_be_hidden()
    print(
        "text box visible:",
        page.get_by_role("textbox", name="Type your message").is_visible(),
        "composer visible:",
        page.locator("#composer").is_visible(),
    )
    expect(page.locator("#ended-text")).to_have_text("This conversation has ended.")
    print("footer:", page.locator("#ended").inner_text().splitlines())
    page.get_by_role("button", name="Start a new conversation").click()
    expect(page.locator("#chat-banner")).to_be_hidden()
    clean_start(page)


def test_error_banner_and_outage_chip(page: Page, live_url: str, stub: StateStub):
    stub.demo_faults = True
    stub.body = reply_with(banner="error", text=FALLBACK, actions=["request_callback"])
    page.goto(live_url + "/")
    chip = page.locator(".chip").nth(4)
    expect(chip).to_have_text("Simulate an outage")
    expect(chip).to_be_visible()
    print("chips:", page.locator(".chip").all_inner_texts())
    chip.click()
    expect(page.locator(".msg-row.bot .bubble").last).to_have_text(FALLBACK)
    assert stub.requests[-1][1] == {
        "text": "Can I move my visit?",
        "simulateOutage": True,
    }
    print("posted:", stub.requests[-1][1])
    banner_check(page, "Something went wrong on our side", AMBER_BG, AMBER_FG)
    picker_check(page)
    expect(page.locator("#composer")).to_be_visible()
    page.get_by_role("button", name="Evening").click()
    expect(page.locator(".msg-row.bot .bubble").last).to_have_text(CALLBACK_TEXT)
    assert stub.callbacks[0][1] == {"window": "evening"}
    print("callback posted:", stub.callbacks[0][1])


def test_outage_chip_hidden_in_normal_use(page: Page, live_url: str, stub: StateStub):
    page.goto(live_url + "/")
    page.wait_for_load_state("networkidle")
    assert stub.started == 1
    expect(page.locator(".chip").filter(has_text="Simulate an outage")).to_have_count(0)
    expect(page.locator(".chip")).to_have_count(4)
    print("stubbed demoFaults false, chips:", page.locator(".chip").all_inner_texts())


def test_outage_chip_hidden_live(page: Page, live_url: str):
    page.goto(live_url + "/")
    page.wait_for_load_state("networkidle")
    expect(page.locator(".chip").filter(has_text="Simulate an outage")).to_have_count(0)
    expect(page.locator(".chip")).to_have_count(4)
    print("live server, chips:", page.locator(".chip").all_inner_texts())


def test_states_fit_390(page: Page, live_url: str, stub: StateStub):
    page.set_viewport_size({"width": 390, "height": 844})
    arrive(
        page,
        live_url,
        stub,
        reply_with(
            choices=[{"label": w, "text": w} for w in [*WINDOWS, EARLIER]],
            booking=BOOKING,
            waitlisted=True,
            actions=["request_callback"],
            banner="error",
        ),
    )
    expect(page.locator(".callback-picker")).to_be_visible()
    widths = page.evaluate(
        "[document.documentElement.scrollWidth, document.body.scrollWidth]"
    )
    assert max(widths) <= 390


def test_new_conversation_clears_banner_and_cards(
    page: Page, live_url: str, stub: StateStub
):
    arrive(
        page,
        live_url,
        stub,
        reply_with(
            banner="error",
            choices=[{"label": EARLIER, "text": EARLIER_TEXT}],
            booking=BOOKING,
            actions=["request_callback"],
        ),
    )
    page.get_by_role("button", name="New conversation").click()
    expect(page.locator("#chat-banner")).to_be_hidden()
    clean_start(page)
    for part in (".choices", ".booking-card", ".callback-picker"):
        expect(page.locator(part)).to_have_count(0)


def test_outage_chip_follows_latest_start(page: Page, live_url: str, stub: StateStub):
    stub.demo_faults = True
    page.goto(live_url + "/")
    expect(page.locator(".chip")).to_have_count(5)
    stub.demo_faults = False
    page.get_by_role("button", name="New conversation").click()
    page.wait_for_load_state("networkidle")
    assert stub.started == 2
    expect(page.locator(".chip")).to_have_count(4)


def test_solved_409_hides_bar(page: Page, live_url: str, stub: StateStub):
    stub.solved_status = 409
    page.goto(live_url + "/")
    send(page, "hi")
    bar = page.locator("#solved-bar")
    expect(bar).to_be_visible()
    page.get_by_role("button", name="Yes, that solved it").click()
    expect(bar).to_be_hidden()


def test_greeting_first_after_new_conversation(
    page: Page, live_url: str, stub: StateStub
):
    page.goto(live_url + "/")
    page.wait_for_load_state("networkidle")
    held: list[Route] = []
    page.unroute("**/conversations", stub.start)
    page.route("**/conversations", lambda route: held.append(route))
    page.get_by_role("button", name="New conversation").click()
    send(page, "hello")
    expect(page.locator(".msg-row.you")).to_have_count(1)
    stub.start(held[0])
    expect(page.locator(".msg-row.bot .bubble").last).to_have_text(stub.reply_text)
    assert page.locator("#messages .bubble").first.inner_text() == GREETING
    assert stub.message_urls()[-1].endswith("/conv-2/messages")


def test_failed_start_is_retried(page: Page, live_url: str, stub: StateStub):
    stub.start_failures = 1
    page.goto(live_url + "/")
    page.wait_for_load_state("networkidle")
    send(page, "hello")
    expect(page.locator(".msg-row.bot .bubble").last).to_have_text(stub.reply_text)
    assert stub.started == 2
    assert stub.message_urls()[-1].endswith("/conv-2/messages")


SEND_FAILED = "That did not go through. Please try again."
PICK_FAILED = "That did not go through. Please pick a time again."


def test_abandoned_send_not_posted_after_new_conversation(
    page: Page, live_url: str, stub: StateStub
):
    held: list[Route] = []

    def hold_first(route: Route) -> None:
        if not held:
            stub.started += 1
            held.append(route)
        else:
            stub.start(route)

    page.unroute("**/conversations", stub.start)
    page.route("**/conversations", hold_first)
    page.goto(live_url + "/")
    send(page, "OLD message")
    page.get_by_role("button", name="New conversation").click()
    expect(page.locator("#messages .bubble")).to_have_count(1)
    held[0].fulfill(status=500, json={"error": {"code": "internal"}})
    page.wait_for_timeout(300)
    assert stub.message_urls() == []
    send(page, "NEW message")
    expect(page.locator(".msg-row.bot .bubble").last).to_have_text(stub.reply_text)
    posted = [
        (u.split("/")[-2], b) for u, b in stub.requests if u.endswith("/messages")
    ]
    print("starts:", stub.started, "posts:", posted)
    assert posted == [("conv-2", {"text": "NEW message"})]
    assert stub.started == 2


def test_failed_send_shows_retry_line_and_keeps_choices(
    page: Page, live_url: str, stub: StateStub
):
    choices(page, live_url, stub, [*WINDOWS, EARLIER], [*WINDOWS, EARLIER_TEXT])
    stub.message_status = 500
    page.locator("button.choice").first.click()
    line = page.locator(".send-error")
    expect(line).to_have_text(SEND_FAILED)
    expect(page.locator(".bubble.typing")).to_have_count(0)
    expect(page.locator("button.choice")).to_have_count(4)
    stub.message_status = 200
    send(page, "again")
    expect(page.locator(".send-error")).to_have_count(0)


def test_new_reply_removes_old_picker(page: Page, live_url: str, stub: StateStub):
    arrive(
        page,
        live_url,
        stub,
        reply_with(banner="error", text=FALLBACK, actions=["request_callback"]),
    )
    expect(page.locator(".callback-picker")).to_have_count(1)
    stub.body = reply_with(text="Something else.")
    send(page, "never mind")
    expect(page.locator(".msg-row.bot .bubble").last).to_have_text("Something else.")
    expect(page.locator(".callback-picker")).to_have_count(0)


def test_failed_pick_shows_error_line(page: Page, live_url: str, stub: StateStub):
    stub.callback_status = 500
    arrive(
        page,
        live_url,
        stub,
        reply_with(banner="error", text=FALLBACK, actions=["request_callback"]),
    )
    page.get_by_role("button", name="Morning").click()
    expect(page.locator(".callback-picker .send-error")).to_have_text(PICK_FAILED)
    expect(page.get_by_role("button", name="Morning")).to_be_enabled()
    expect(page.locator("#ended")).to_be_hidden()

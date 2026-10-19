from playwright.sync_api import Page, expect

from app.conversation.routes import GREETING

CHIPS = [
    "My AC is blowing warm air",
    "What does the maintenance plan cover?",
    "I was charged twice",
    "I smell gas",
]


def test_start_state_matches_wireframe(page: Page, live_url: str):
    page.goto(live_url + "/")
    head = page.locator(".chat-head")
    expect(head).to_contain_text("Meridian Home Comfort")
    expect(head).to_contain_text(
        "Virtual assistant. Repairs, visits, fees, membership, warranty, billing."
    )
    expect(page.get_by_role("button", name="New conversation")).to_be_visible()
    expect(page.locator(".bubble")).to_have_count(1)
    expect(page.locator(".bubble.bot")).to_have_text(GREETING)
    assert page.locator(".chip").all_inner_texts() == CHIPS
    box = page.get_by_role("textbox", name="Type your message")
    expect(box).to_have_attribute("placeholder", "Type your message")
    expect(page.get_by_role("button", name="Send", exact=True)).to_be_visible()
    expect(page.locator("#solved-bar")).to_be_hidden()
    expect(page.locator("#ended")).to_be_hidden()
    text = page.inner_text("body")
    for dropped in ("preview a state", "example data", "Wireframe.", "[placeholders]"):
        assert dropped not in text
    assert "Simulate an outage" not in text


def test_no_sideways_scroll_at_390(page: Page, live_url: str):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(live_url + "/")
    widths = page.evaluate(
        "[document.documentElement.scrollWidth, document.body.scrollWidth]"
    )
    assert max(widths) <= 390


def test_button_paddings_match_wireframe(page: Page, live_url: str):
    page.goto(live_url + "/")
    for name, pad in (("New conversation", "14px"), ("Send", "18px")):
        button = page.get_by_role("button", name=name, exact=True)
        expect(button).to_have_css("padding-left", pad)
        expect(button).to_have_css("padding-right", pad)


def test_banner_slot_hidden_at_start(page: Page, live_url: str):
    page.goto(live_url + "/")
    banner = page.locator("#chat-banner")
    expect(banner).to_have_count(1)
    expect(banner).to_be_hidden()
    order = page.evaluate(
        "[...document.querySelector('.chat-card').children].map((e) => e.id || e.className)"
    )
    assert order.index("chat-head") + 1 == order.index("chat-banner")
    assert order.index("chat-banner") + 1 == order.index("messages")

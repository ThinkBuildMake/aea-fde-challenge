from playwright.sync_api import Page, expect

from app.settings import Settings
from tests.browser.test_conversations_tab import open_tab, stub


def test_chat_and_business_run_under_the_policy(
    page: Page, live_url: str, overview_stub, started: Settings
):
    console: list[str] = []
    page.on("console", lambda m: console.append(m.text))
    page.on("pageerror", lambda e: console.append(str(e)))

    page.goto(live_url + "/")
    page.get_by_role("textbox", name="Type your message").fill("hello")
    page.get_by_role("button", name="Send", exact=True).click()
    expect(page.locator(".bubble.bot")).to_have_count(2)
    for tab in ("overview", "handoffs", "waitlist"):
        page.goto(live_url + f"/business?tab={tab}")
        page.wait_for_load_state("networkidle")
        assert page.evaluate("typeof window.htmx") == "object"
    stub(page)
    open_tab(page, live_url)
    link = page.locator(".turn-tools a.trace-link").first

    base = started.LANGFUSE_BASE_URL.rstrip("/")
    expect(link).to_have_attribute("href", f"{base}/trace/tr-1")
    violations = [t for t in console if "Content Security Policy" in t]
    print(
        "CSP violations:",
        violations,
        "| htmx loaded on every tab | trace href:",
        link.get_attribute("href"),
    )
    assert violations == []

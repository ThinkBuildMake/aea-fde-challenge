import re
from datetime import UTC, datetime, timedelta

from playwright.sync_api import Page, expect

from app.types import (
    CandidateCreated,
    ConversationDetail,
    ConversationList,
    ConversationSummary,
    EvalCandidateRef,
    FlagCreated,
    FlagInfo,
    ToolCall,
    TurnView,
)
from tests.browser.conftest import json_route

LIST = re.compile(r".*/conversations\?.*")
IDS = ["CALL-aaaa1111", "CALL-bbbb2222", "CALL-cccc3333"]


def summary(i: int, minutes: int, outcome: str, intent: str) -> ConversationSummary:
    started = datetime.now(UTC) - timedelta(minutes=minutes)
    return ConversationSummary(
        public_id=IDS[i],
        started_at=started.isoformat(),
        ended_at=None if outcome == "active" else started.isoformat(),
        intent=intent,
        outcome=outcome,
        outcome_reason="billing_dispute" if outcome == "handoff" else None,
        turn_count=2,
        cost_usd=0.04,
        solved="yes" if outcome == "contained" else None,
        flagged=False,
        has_handoff=outcome == "handoff",
        customer_name=None,
    )


def turn(seq: int, trace_id: str | None, tools: list[str]) -> TurnView:
    return TurnView(
        seq=seq,
        kind="message",
        caller_text="My AC is blowing warm air.",
        reply_text="Is there any burning smell?",
        tools_called=[ToolCall(name=n, ok=True, ms=5) for n in tools],
        retrieved=[],
        safety_verdict=None,
        latency_ms=3100,
        error=None,
        fallback_used=False,
        cost_usd=0.02,
        trace_id=trace_id,
    )


def stub(page: Page, outcome: str = "contained", calls: list | None = None) -> None:
    items = [
        summary(0, 3, outcome, "book_visit"),
        summary(1, 14, "handoff", "billing_dispute"),
        summary(2, 21, "safety_stop", "safety"),
    ]
    json_route(
        page,
        LIST,
        ConversationList(conversations=items).model_dump(by_alias=True, mode="json"),
    )
    for s in items:
        detail = ConversationDetail(
            summary=s,
            turns=[
                turn(1, "tr-1", ["identify_customer", "find_open_windows"]),
                turn(2, None, []),
            ],
            handoff=None,
            flags=[],
            eval_candidate=None,
        )
        json_route(
            page,
            re.compile(rf".*/conversations/{s.public_id}$"),
            detail.model_dump(by_alias=True, mode="json"),
        )
    json_route(
        page,
        re.compile(r".*/conversations/[^/]+/flag$"),
        FlagCreated(
            flag=FlagInfo(id=1, created_at="2026-10-19T10:00:00+00:00")
        ).model_dump(by_alias=True, mode="json"),
        status=201,
        calls=calls,
    )
    json_route(
        page,
        re.compile(r".*/conversations/[^/]+/eval-candidate$"),
        CandidateCreated(
            candidate=EvalCandidateRef(scenario_id="CAND-ab12cd34")
        ).model_dump(by_alias=True, mode="json"),
        status=201,
        calls=calls,
    )


def open_tab(page: Page, live_url: str) -> None:
    page.goto(live_url + "/business?tab=conversations")
    expect(page.locator("#detail .detail-title")).to_be_visible()


def test_list_and_detail(page: Page, live_url: str, overview_stub):
    stub(page)
    page.goto(live_url + "/business?tab=conversations")
    rows = page.locator(".convo-btn")
    expect(rows).to_have_count(3)
    assert rows.nth(0).inner_text().split("\n") == [
        "3 min",
        "Book a visit",
        "Contained",
    ]
    expect(rows.nth(1).locator(".when")).to_have_text("14 min")
    expect(rows.nth(2).locator(".outcome")).to_have_text("Safety stop")
    rows.nth(1).click()
    rows.nth(0).click()
    detail = page.locator("#detail")
    expect(detail.locator(".detail-title")).to_have_text("Book a visit (Contained)")
    meta = detail.locator(".meta")
    for part in (IDS[0], "2 turns", "first reply 3.1 s", "cost $0.04"):
        expect(meta).to_contain_text(part)
    expect(detail.locator(".transcript")).to_contain_text("Caller: My AC is blowing")
    expect(detail.locator(".transcript")).to_contain_text("Agent: Is there any")
    expect(detail.locator(".turn-tools").first).to_contain_text(
        "Tools called: identify customer, find open windows"
    )


def test_flag_with_note(page: Page, live_url: str, overview_stub):
    calls: list[dict] = []
    stub(page, calls=calls)
    open_tab(page, live_url)
    btn = page.locator(".btn-flag")
    expect(btn).to_have_text("Flag as wrong")
    btn.click()
    expect(page.locator("label[for=note]")).to_have_text(
        "What was wrong? (note saved with the flag)"
    )
    page.fill("#note", "   ")
    page.press("#note", "Enter")
    assert calls == []
    page.fill("#note", "quoted the wrong window")
    page.press("#note", "Enter")
    expect(btn).to_have_text("Flagged as wrong (undo)")
    assert calls[0]["method"] == "POST"
    assert calls[0]["body"] == {"note": "quoted the wrong window"}
    btn.click()
    expect(btn).to_have_text("Flag as wrong")


def test_turn_into_test_scenario(page: Page, live_url: str, overview_stub):
    calls: list[dict] = []
    stub(page, calls=calls)
    open_tab(page, live_url)
    page.get_by_role("button", name="Turn into a test scenario").click()
    expect(page.locator(".eval-saved")).to_have_text(
        "Saved as a candidate test scenario: CAND-ab12cd34. Review it, then add it to the eval set."
    )
    assert calls[0]["url"].endswith("/eval-candidate")


def test_turn_into_test_scenario_disabled_while_active(
    page: Page, live_url: str, overview_stub
):
    stub(page, outcome="active")
    open_tab(page, live_url)
    expect(
        page.get_by_role("button", name="Turn into a test scenario")
    ).to_be_disabled()


def test_open_trace_link(page: Page, live_url: str, overview_stub, started):
    stub(page)
    open_tab(page, live_url)
    turns = page.locator(".turn")
    link = turns.nth(0).locator(".turn-tools a.trace-link")
    expect(link).to_have_text("Open trace")
    base = started.LANGFUSE_BASE_URL.rstrip("/")
    expect(link).to_have_attribute("href", f"{base}/trace/tr-1")
    expect(turns.nth(1).locator("a.trace-link")).to_have_count(0)
    assert turns.nth(0).locator(".turn-tools").inner_text().startswith("Tools called:")


def test_no_sideways_scroll_at_390(page: Page, live_url: str, overview_stub):
    page.set_viewport_size({"width": 390, "height": 800})
    stub(page)
    open_tab(page, live_url)
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )

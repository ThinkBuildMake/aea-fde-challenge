"""What a reply says is checked before the caller sees it: four rules on the turn."""

from typing import Any

import pytest

from app.conversation import guards
from app.llm import FakeModelProvider, ModelResult
from app.settings import Settings
from app.types import Booking, Fee, OpenWindows, Passage, Window
from tests.test_turn import (
    assistant,
    client_for,
    new_conversation,
    result,
    rows,
    say,
    tool_call,
)
from tests.test_turn_guards import match

WINDOW = Window(
    slot_id=56,
    date="2026-10-19",
    window="08:00-12:00",
    service_type="hvac_repair",
    zone="north",
    technician_name="Marta Kowalski",
    member_only=False,
)
BOOKING = Booking(
    appointment_id=7,
    slot_id=56,
    date="2026-10-19",
    window="08:00-12:00",
    technician_name="Marta Kowalski",
    service_type="hvac_repair",
    zone="north",
    diagnostic_fee_cents=8900,
    diagnostic_fee_waived=False,
)


class Stubs:
    def __init__(self) -> None:
        self.passage_text = "The diagnostic fee is $89."
        self.handoff_rows = False


@pytest.fixture
def stubs(monkeypatch: pytest.MonkeyPatch) -> Stubs:
    s = Stubs()

    def search(ctx, query, k):
        return [
            Passage(
                passage_id="p1",
                source_file="pricing/fees.md",
                section="Fees",
                kind="text",
                text=s.passage_text,
                score=0.9,
            )
        ]

    def handoff(tx, record):
        if s.handoff_rows:
            tx.execute(
                "INSERT INTO handoffs (conversation_id, kind, reason, intent, told_caller) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    record.conversation_id,
                    record.kind,
                    record.reason,
                    record.intent,
                    "ok",
                ),
            )

    monkeypatch.setattr("app.knowledge.service.search_knowledge", search)
    monkeypatch.setattr("app.followups.service.create_handoff", handoff)
    monkeypatch.setattr(
        "app.knowledge.service.get_fee",
        lambda ctx, code: Fee(code=code, cents=8900, source_file="pricing"),
    )
    monkeypatch.setattr(
        "app.scheduling.service.find_open_windows",
        lambda *a, **k: OpenWindows(
            windows=[WINDOW], matched_request=True, reason=None
        ),
    )
    monkeypatch.setattr("app.scheduling.service.book_visit", lambda *a, **k: BOOKING)
    return s


def search_call(call_id: str = "s") -> ModelResult:
    return result(
        assistant(calls=[tool_call(call_id, "search_knowledge", query="fee")])
    )


def status_call(intent: str, resolved: bool, call_id: str = "r") -> ModelResult:
    return result(
        assistant(
            calls=[
                tool_call(call_id, "report_status", intent=intent, resolved=resolved)
            ]
        )
    )


def show(name: str, reply: dict[str, Any], error: Any) -> None:
    print(
        f"\n[{name}] text={reply['text']!r} actions={reply['actions']} error={error!r}"
    )


def error_of(settings: Settings, cid: str, seq: int) -> Any:
    return rows(
        settings,
        "SELECT error FROM turns WHERE conversation_id=? AND seq=?",
        cid,
        seq,
    )[0][0]


def one_turn(started: Settings, script: list[ModelResult], text: str = "hello"):
    client = client_for(started, FakeModelProvider(results=script))
    cid = new_conversation(client)
    return client, cid, say(client, cid, text)


def booking_conversation(started: Settings, final: str):
    book = tool_call(
        "b", "book_visit", slotId=56, issue="no heat", callerQuote="that one"
    )
    find = tool_call("w", "find_open_windows", serviceType="hvac_repair")
    client = client_for(
        started,
        FakeModelProvider(
            results=[
                result(assistant(calls=[find])),
                result(assistant("Monday morning is open.")),
                result(assistant(calls=[book])),
                result(assistant(final)),
            ]
        ),
    )
    cid = new_conversation(client)
    match(started, cid)
    say(client, cid, "I need a visit")
    return cid, say(client, cid, "that one")


def test_a_confirmation_that_differs_from_the_row_is_replaced(
    started: Settings, stubs: Stubs
):
    cid, reply = booking_conversation(started, "booked Tuesday with Ray")
    error = error_of(started, cid, 2)
    show("AC1", reply, error)
    card = reply["booking"]
    print(
        "booking card: "
        + ", ".join(
            f"{k}={card[k]}" for k in ("slotId", "date", "window", "technicianName")
        )
    )
    assert reply["text"] == guards.confirmation_text(BOOKING)
    assert (
        reply["text"]
        == "You are booked for 2026-10-19, 08:00-12:00, with Marta Kowalski."
    )
    assert reply["booking"]["slotId"] == 56
    assert reply["booking"]["technicianName"] == "Marta Kowalski"
    assert error == "confirmation_mismatch"


def test_a_matching_confirmation_is_kept(started: Settings, stubs: Stubs):
    text = "Booked Monday October 19, 8 AM to 12 PM with Marta."
    cid, reply = booking_conversation(started, text)
    show("kept", reply, error_of(started, cid, 2))
    assert reply["text"] == text and reply["booking"] is not None
    assert error_of(started, cid, 2) is None


def test_an_unsourced_dollar_figure_gets_the_not_sure_reply(
    started: Settings, stubs: Stubs
):
    _, cid, reply = one_turn(
        started, [search_call(), result(assistant("The diagnostic is $79"))]
    )
    error = error_of(started, cid, 1)
    show("AC2", reply, error)
    assert reply["text"] == guards.NOT_SURE_TEXT and "$79" not in reply["text"]
    assert "request_callback" in reply["actions"]
    assert error == "unsupported_figure"


def test_an_unsourced_repair_price_is_withheld(started: Settings, stubs: Stubs):
    _, cid, reply = one_turn(
        started, [search_call(), result(assistant("A new system is $4,200."))]
    )
    assert reply["text"] == guards.NOT_SURE_TEXT
    assert error_of(started, cid, 1) == "unsupported_figure"


def test_a_figure_from_an_earlier_turn_is_supported(started: Settings, stubs: Stubs):
    client = client_for(
        started,
        FakeModelProvider(
            results=[
                search_call(),
                result(assistant("Let me say.")),
                result(assistant("It is $89.")),
            ]
        ),
    )
    cid = new_conversation(client)
    say(client, cid, "fee?")
    reply = say(client, cid, "again?")
    show("earlier figure", reply, error_of(started, cid, 2))
    assert reply["text"] == "It is $89." and error_of(started, cid, 2) is None


def test_a_promise_gets_the_not_sure_reply(started: Settings, stubs: Stubs):
    _, cid, reply = one_turn(
        started,
        [
            status_call("billing_dispute", False),
            result(assistant("We'll refund you today")),
        ],
    )
    error = error_of(started, cid, 1)
    show("AC3", reply, error)
    assert reply["text"] == guards.NOT_SURE_TEXT
    assert "request_callback" in reply["actions"]
    assert error == "promise_withheld"


def test_a_waiver_promise_is_withheld_even_with_a_sourced_figure(
    started: Settings, stubs: Stubs
):
    stubs.passage_text = "The late fee is $49."
    _, cid, reply = one_turn(
        started,
        [search_call(), result(assistant("I will waive the $49 late fee for you."))],
    )
    assert reply["text"] == guards.NOT_SURE_TEXT
    assert error_of(started, cid, 1) == "promise_withheld"


def test_a_resolved_need_asks_for_the_tap(started: Settings, stubs: Stubs):
    _, cid, reply = one_turn(
        started,
        [status_call("policy_question", True), result(assistant("Glad to help."))],
    )
    resolved = rows(started, "SELECT resolved_at FROM conversations WHERE id=?", cid)[
        0
    ][0]
    show("AC4", reply, error_of(started, cid, 1))
    print(f"resolved_at={resolved}")
    assert "ask_solved" in reply["actions"] and resolved is not None


@pytest.mark.parametrize("when", ["same_turn", "earlier_turn"])
def test_no_tap_after_a_handoff(started: Settings, stubs: Stubs, when: str):
    esc = tool_call(
        "e",
        "escalate",
        kind="handoff",
        reason="asked",
        intent="other",
        toldCaller="A person will call.",
    )
    stubs.handoff_rows = True
    if when == "same_turn":
        both = [esc, tool_call("r", "report_status", intent="other", resolved=True)]
        script = [
            result(assistant(calls=both)),
            result(assistant("A person will pick this up.")),
        ]
        _, cid, reply = one_turn(started, script)
    else:
        client = client_for(
            started,
            FakeModelProvider(
                results=[
                    result(assistant(calls=[esc])),
                    result(assistant("A person will pick this up.")),
                    status_call("other", True),
                    result(assistant("Anything else?")),
                ]
            ),
        )
        cid = new_conversation(client)
        say(client, cid, "person please")
        reply = say(client, cid, "thanks")
    count = rows(started, "SELECT COUNT(*) FROM handoffs WHERE conversation_id=?", cid)
    show(f"AC5 {when}", reply, error_of(started, cid, 1))
    print(f"handoff rows={count[0][0]}")
    assert "ask_solved" not in reply["actions"]


def test_filler_from_a_tool_round_does_not_reach_the_caller(
    started: Settings, stubs: Stubs
):
    first = result(
        assistant(
            "Let me check.", calls=[tool_call("s", "search_knowledge", query="fee")]
        )
    )
    _, _, reply = one_turn(started, [first, result(assistant("It is $89."))])
    assert reply["text"] == "It is $89."


def test_a_later_unresolved_report_clears_resolved_at(started: Settings, stubs: Stubs):
    client = client_for(
        started,
        FakeModelProvider(
            results=[
                status_call("other", True, "a"),
                result(assistant("ok")),
                status_call("other", False, "b"),
                result(assistant("ok")),
            ]
        ),
    )
    cid = new_conversation(client)
    sql = "SELECT resolved_at FROM conversations WHERE id=?"
    say(client, cid, "one")
    assert rows(started, sql, cid)[0][0]
    say(client, cid, "two")
    assert rows(started, sql, cid)[0][0] is None


def test_no_tap_after_a_failed_escalate(
    started: Settings, stubs: Stubs, monkeypatch: pytest.MonkeyPatch
):
    def broken(tx, record):
        raise RuntimeError("down")

    monkeypatch.setattr("app.followups.service.create_handoff", broken)
    esc = tool_call(
        "e",
        "escalate",
        kind="handoff",
        reason="asked",
        intent="other",
        toldCaller="A person will call.",
    )
    both = [esc, tool_call("r", "report_status", intent="other", resolved=True)]
    _, _, reply = one_turn(
        started, [result(assistant(calls=both)), result(assistant("Noted."))]
    )
    assert "ask_solved" not in reply["actions"]


def test_an_answer_before_an_empty_final_round_is_kept(started: Settings, stubs: Stubs):
    status = tool_call("r", "report_status", intent="policy_question", resolved=True)
    script = [
        search_call(),
        result(assistant("The diagnostic visit is $89.", calls=[status])),
        result(assistant("")),
    ]
    _, cid, reply = one_turn(started, script)
    show("last text", reply, error_of(started, cid, 1))
    assert reply["text"] == "The diagnostic visit is $89."
    assert reply["banner"] == "none" and "ask_solved" in reply["actions"]
    assert error_of(started, cid, 1) is None


def test_a_refund_request_handed_to_a_supervisor_is_not_a_promise(
    started: Settings, stubs: Stubs
):
    stubs.handoff_rows = True
    text = (
        "I've logged your refund request, and a supervisor will call you "
        "within 1 business day."
    )
    esc = tool_call(
        "e",
        "escalate",
        kind="handoff",
        reason="refund request",
        intent="billing_dispute",
        toldCaller=text,
    )
    _, cid, reply = one_turn(
        started, [result(assistant(calls=[esc])), result(assistant(text))]
    )
    show("refund request", reply, error_of(started, cid, 1))
    assert reply["text"] == text
    assert error_of(started, cid, 1) is None

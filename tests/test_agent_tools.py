import json
import sqlite3
from types import SimpleNamespace
from typing import Any

import pytest

from app.conversation.guards import (
    ALREADY_ON_WAITLIST_INSTRUCTION,
    CANCEL_CONFIRM_INSTRUCTION,
    CARD_REFUSAL_TEXT,
    EARLIER_INSTRUCTION,
    JOIN_AFTER_BOOKING_INSTRUCTION,
    ON_WAITLIST_INSTRUCTION,
    SEARCH_UNAVAILABLE_INSTRUCTION,
    asks_earlier,
)
from app.conversation.tools import ToolState, run_tool
from app.knowledge.service import EmbeddingUnavailable, IndexUnavailable, UnknownFee
from app.llm import FakeModelProvider
from app.scheduling.service import SchedulingUnavailable
from app.settings import Settings
from app.types import (
    AppointmentView,
    Booking,
    CancelResult,
    CustomerRef,
    Fee,
    HeldWindow,
    JoinWaitlistResult,
    MoveResult,
    OpenWindows,
    WaitlistCaller,
    WaitlistView,
    Window,
)
from tests.test_turn import (
    assistant,
    client_for,
    new_conversation,
    result,
    rows,
    say,
    tool_call,
)


class Recorder:
    def __init__(self, value: Any = None) -> None:
        self.value = value
        self.calls: list[tuple[Any, ...]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(args)
        return self.value


def stub(monkeypatch: pytest.MonkeyPatch, path: str, value: Any) -> Recorder:
    recorder = Recorder(value)
    monkeypatch.setattr(path, recorder)
    return recorder


def customer(customer_id: str, tier: str = "none") -> CustomerRef:
    return CustomerRef(
        customer_id=customer_id,
        name="Test",
        city="Austin",
        zone="south",
        membership_tier=tier,  # type: ignore[arg-type]
        membership_renewal_date=None,
        system_brand=None,
        system_install_date=None,
    )


def window(slot_id: int, start: str = "08:00", end: str = "12:00") -> Window:
    return Window(
        slot_id=slot_id,
        date="2026-10-21",
        window=f"{start}-{end}",
        service_type="hvac_repair",
        zone="south",
        technician_name="Jun Park",
        member_only=False,
    )


def booking() -> Booking:
    return Booking(
        appointment_id=7,
        slot_id=3,
        date="2026-10-21",
        window="08:00-12:00",
        technician_name="Jun Park",
        service_type="hvac_repair",
        zone="south",
        diagnostic_fee_cents=0,
        diagnostic_fee_waived=False,
    )


def held_visit(appointment_id: int = 7, start: str = "08:00", end: str = "12:00"):
    return AppointmentView(
        appointment_id=appointment_id,
        date="2026-10-21",
        window=f"{start}-{end}",
        technician_name="Jun Park",
        service_type="hvac_repair",
        zone="south",
        issue="x",
        late_cancel_fee_applies=False,
    )


def joined(created: bool) -> JoinWaitlistResult:
    return JoinWaitlistResult(
        entry=WaitlistView(
            id=1,
            conversation_public_id="c",
            caller=WaitlistCaller(
                customer_id="MHC-10002", name="Omar Patel", phone="x", city="Kyle"
            ),
            service_type="hvac_repair",
            zone="south",
            held=HeldWindow(date="2026-10-21", window="13:00-17:00"),
            created_at="2026-10-19T10:00:00Z",
            waiting_seconds=0,
        ),
        created=created,
    )


def run(
    started: Settings,
    *steps: list[dict[str, Any]],
    texts: list[str] | None = None,
    answers: list[str] | None = None,
):
    """One turn per step: the model makes the step's calls, then answers."""
    results = []
    for i, calls in enumerate(steps):
        results.append(result(assistant(calls=calls)))
        results.append(
            result(assistant((answers or [])[i] if answers else f"answer {i}"))
        )
    client = client_for(started, FakeModelProvider(results=results))
    cid = new_conversation(client)
    replies = [
        say(client, cid, (texts or [])[i] if texts else f"message {i}")
        for i in range(len(steps))
    ]
    return cid, replies


def tool_results(started: Settings, cid: str) -> list[dict[str, Any]]:
    out = []
    for turn in rows(
        started, "SELECT model_messages FROM turns WHERE conversation_id = ?", cid
    ):
        out += [
            json.loads(m["content"])
            for m in json.loads(turn["model_messages"])
            if m["role"] == "tool"
        ]
    return out


def identify(customer_id: str) -> list[dict[str, Any]]:
    return [identify_as("id", "Test", "555-0100")]


def identify_as(call_id: str, name: str, phone: str) -> dict[str, Any]:
    call = tool_call(call_id, "identify_customer")
    call["function"]["arguments"] = json.dumps({"name": name, "phone": phone})
    return call


def identify_and_offer(
    monkeypatch: pytest.MonkeyPatch, customer_id: str
) -> list[dict[str, Any]]:
    """Turn 1: match the caller and show slot 3 and appointment 7, so a later write may target them."""
    stub(
        monkeypatch,
        "app.scheduling.service.find_open_windows",
        OpenWindows(windows=[window(3)], matched_request=True, reason=None),
    )
    stub(
        monkeypatch,
        "app.scheduling.service.list_appointments",
        [
            AppointmentView(
                appointment_id=7,
                date="2026-10-21",
                window="08:00-12:00",
                technician_name="Jun Park",
                service_type="hvac_repair",
                zone="south",
                issue="x",
                late_cancel_fee_applies=False,
            )
        ],
    )
    return [
        *identify(customer_id),
        tool_call("w", "find_open_windows", serviceType="hvac_repair"),
        tool_call("l", "lookup_my_appointments"),
    ]


def test_account_tools_use_the_matched_customer(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    stub(monkeypatch, "app.scheduling.service.identify_customer", customer("MHC-10002"))
    billing = stub(monkeypatch, "app.scheduling.service.get_billing", None)
    from app.types import Billing, PaymentLink

    billing.value = Billing(balance_cents=0, invoices=[])
    link = stub(
        monkeypatch,
        "app.scheduling.service.create_payment_link",
        PaymentLink(url="https://pay", valid_for_hours=24),
    )
    appts = stub(monkeypatch, "app.scheduling.service.list_appointments", [])
    other = {"customerId": "MHC-10001"}
    run(
        started,
        identify("MHC-10002"),
        [
            tool_call("a", "get_my_billing", **other),
            tool_call("b", "send_payment_link", invoiceId="INV-1", **other),
            tool_call("c", "lookup_my_appointments", **other),
        ],
    )
    for recorder in (billing, link, appts):
        assert [c[1] for c in recorder.calls] == ["MHC-10002"]


def test_account_tools_wait_for_a_match(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    billing = stub(monkeypatch, "app.scheduling.service.get_billing", None)
    cid, _ = run(started, [tool_call("a", "get_my_billing")])
    assert billing.calls == []
    out = tool_results(started, cid)[0]
    assert out["ok"] is False and out["error"] == "not_identified"
    assert "not identified" in out["message"]


def test_identification_is_capped(started: Settings, monkeypatch: pytest.MonkeyPatch):
    from app.conversation.tools import IDENTIFY_ATTEMPT_LIMIT

    ident = stub(monkeypatch, "app.scheduling.service.identify_customer", None)
    results = [result(assistant(calls=identify("X"))), result(assistant("answer"))]
    client = client_for(started, FakeModelProvider(results=results))
    cid = new_conversation(client)
    conn = sqlite3.connect(started.APP_DB_PATH)
    with conn:
        conn.execute(
            "UPDATE conversations SET identify_attempts = ?", (IDENTIFY_ATTEMPT_LIMIT,)
        )
    conn.close()
    say(client, cid, "message 0")
    assert ident.calls == []
    last = tool_results(started, cid)[-1]
    assert last["error"] == "identify_limit_reached" and "escalate" in last["message"]
    assert rows(started, "SELECT identify_attempts FROM conversations")[0][0] == 3


def test_no_match_hands_off_with_fixed_text(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    from app.conversation.guards import NO_MATCH_TEXT

    stub(monkeypatch, "app.scheduling.service.identify_customer", None)
    call = identify_as("id", "Omar Patel", "512-555-0101")
    cid, replies = run(started, [call])
    reply = replies[0]
    assert reply["text"] == NO_MATCH_TEXT
    assert (reply["status"], reply["banner"]) == ("handed_off", "handoff")
    assert reply["actions"] == ["choose_callback_window"]
    row = rows(
        started,
        "SELECT reason, kind, customer_id, caller_name, caller_phone, summary_source "
        "FROM handoffs WHERE conversation_id = ?",
        cid,
    )[0]
    assert dict(row) == {
        "reason": "no_account_match",
        "kind": "handoff",
        "customer_id": None,
        "caller_name": "Omar Patel",
        "caller_phone": "512-555-0101",
        "summary_source": "system",
    }
    assert rows(started, "SELECT customer_id FROM conversations")[0][0] is None


def by_name(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """identify_customer answers Omar as MHC-10002 and Linda as MHC-10001; records names."""
    looked: list[str] = []

    def identify_customer(ctx: Any, name: str, *rest: Any) -> CustomerRef:
        looked.append(name)
        return customer("MHC-10001" if name.startswith("Linda") else "MHC-10002")

    monkeypatch.setattr("app.scheduling.service.identify_customer", identify_customer)
    return looked


def test_matched_caller_cannot_identify_someone_else(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    by_name(monkeypatch)
    omar = identify_as("id1", "Omar Patel", "512-555-0102")
    linda = identify_as("id2", "Linda Foster", "512-555-0101")
    cid, _ = run(started, [omar], [linda])
    out = tool_results(started, cid)[-1]
    assert out == {
        "ok": False,
        "error": "already_identified",
        "message": out["message"],
    }
    assert "own account" in out["message"]
    assert "MHC-10001" not in json.dumps(tool_results(started, cid))
    assert rows(started, "SELECT customer_id FROM conversations")[0][0] == "MHC-10002"


def test_matched_caller_restating_their_details_is_ok(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    by_name(monkeypatch)
    omar = identify_as("id1", "Omar Patel", "512-555-0102")
    again = identify_as("id2", "Omar Patel", "512-555-0102")
    cid, _ = run(started, [omar], [again])
    out = tool_results(started, cid)[-1]
    assert out["ok"] is True and out["customer"]["customerId"] == "MHC-10002"
    assert rows(started, "SELECT customer_id, identify_attempts FROM conversations")[0][
        :
    ] == ("MHC-10002", 0)


def test_card_turn_escalate_is_refused(started: Settings):
    from app.context import AppContext
    from app.conversation.tools import HANDLERS

    conn = sqlite3.connect(":memory:")
    state = ToolState(
        conn,
        "c1",
        "My card is [card number removed]",
        "other",
        [],
        "MHC-10002",
        None,
        0,
    )
    state.card_removed = True
    out = HANDLERS["escalate"](
        AppContext.__new__(AppContext),
        state,
        {
            "kind": "supervisor_callback",
            "reason": "billing_dispute",
            "intent": "x",
            "toldCaller": "x",
        },
    )
    assert out["ok"] is False and out["error"] == "card_number_turn"
    assert "payment link" in out["instruction"]
    assert state.handoff is None


def test_window_choices_come_from_the_tool_result(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    stub(monkeypatch, "app.scheduling.service.identify_customer", customer("MHC-10002"))
    found = stub(
        monkeypatch,
        "app.scheduling.service.find_open_windows",
        OpenWindows(
            windows=[
                window(1),
                window(2, "12:00", "16:00"),
                window(3, "16:00", "19:00"),
            ],
            matched_request=True,
            reason=None,
        ),
    )
    _, replies = run(
        started,
        identify("MHC-10002"),
        [tool_call("w", "find_open_windows", serviceType="hvac_repair")],
    )
    assert found.calls[0][1] == "MHC-10002"
    choices = replies[1]["choices"]
    assert [c["label"] for c in choices] == [
        "Wednesday October 21, 8 AM to 12 PM, Jun Park",
        "Wednesday October 21, 12 PM to 4 PM, Jun Park",
        "Wednesday October 21, 4 PM to 7 PM, Jun Park",
        "Nothing earlier? Ask for an earlier window",
    ]
    assert choices[3]["text"] == "Can you do anything earlier?"
    assert choices[0]["text"] == choices[0]["label"]


@pytest.mark.parametrize(
    ("tier", "waived"), [("standard", True), ("plus", True), ("none", False)]
)
def test_member_diagnostic_fee_is_waived_on_the_card(
    started: Settings, monkeypatch: pytest.MonkeyPatch, tier: str, waived: bool
):
    stub(
        monkeypatch,
        "app.scheduling.service.identify_customer",
        customer("MHC-10001", tier),
    )
    stub(monkeypatch, "app.scheduling.service.book_visit", booking())
    stub(
        monkeypatch,
        "app.knowledge.service.get_fee",
        Fee(code="FEE-DIAG", cents=8900, source_file="pricing"),
    )
    _, replies = run(
        started,
        identify_and_offer(monkeypatch, "MHC-10001"),
        [tool_call("b", "book_visit", slotId=3, issue="no cooling", callerQuote="yes")],
        texts=["hi", "yes"],
    )
    card = replies[1]["booking"]
    assert card["diagnosticFeeCents"] == 8900
    assert card["diagnosticFeeWaived"] is waived


def held(late: bool) -> AppointmentView:
    return AppointmentView(
        appointment_id=7,
        date="2026-10-21",
        window="08:00-12:00",
        technician_name="Jun Park",
        service_type="hvac_repair",
        zone="south",
        issue="x",
        late_cancel_fee_applies=late,
    )


def cancel_stubs(
    monkeypatch: pytest.MonkeyPatch, late: bool
) -> tuple[Recorder, Recorder]:
    stub(monkeypatch, "app.scheduling.service.identify_customer", customer("MHC-10002"))
    stub(monkeypatch, "app.scheduling.service.get_appointment", held(late))
    cancel = stub(
        monkeypatch,
        "app.scheduling.service.cancel_visit",
        CancelResult(
            appointment_id=7, freed_slot_id=3, late_fee_applies=late, hours_before=5.0
        ),
    )
    fees = stub(
        monkeypatch,
        "app.knowledge.service.get_fee",
        Fee(code="FEE-LATE", cents=4900, source_file="pricing"),
    )
    return cancel, fees


def cancel_call(quote: str) -> list[dict[str, Any]]:
    return [tool_call("c", "cancel_visit", appointmentId=7, callerQuote=quote)]


def test_first_cancel_only_asks(started: Settings, monkeypatch: pytest.MonkeyPatch):
    cancel, _ = cancel_stubs(monkeypatch, late=False)
    cid, replies = run(
        started,
        identify_and_offer(monkeypatch, "MHC-10002"),
        cancel_call("cancel"),
        texts=["hi", "Maybe I'll cancel, I'm not sure"],
    )
    out = tool_results(started, cid)[-1]
    print("ask result:", out)
    assert cancel.calls == []
    assert out["cancelled"] is False and out["needsConfirmation"] is True
    assert out["lateFeeApplies"] is False and "lateFeeCents" not in out
    assert out["instruction"] == CANCEL_CONFIRM_INSTRUCTION
    assert out["appointment"]["appointmentId"] == 7
    last = rows(
        started,
        "SELECT has_write, offered FROM turns WHERE conversation_id = ? ORDER BY seq",
        cid,
    )[-1]
    assert last["has_write"] == 0
    assert json.loads(last["offered"])["cancelAppointmentIds"] == [7]
    assert replies[1]["actions"] != ["request_callback"]


def test_late_cancel_ask_carries_the_fee(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    cancel, fees = cancel_stubs(monkeypatch, late=True)
    cid, _ = run(
        started,
        identify_and_offer(monkeypatch, "MHC-10002"),
        cancel_call("Cancel my visit"),
        texts=["hi", "Cancel my visit"],
    )
    out = tool_results(started, cid)[-1]
    print("ask result:", out)
    assert cancel.calls == []
    assert out["needsConfirmation"] is True
    assert out["lateFeeApplies"] is True and out["lateFeeCents"] == 4900
    assert fees.calls[-1][1] == "FEE-LATE"


def test_late_cancel_carries_the_fee(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    cancel, fees = cancel_stubs(monkeypatch, late=True)
    cid, _ = run(
        started,
        identify_and_offer(monkeypatch, "MHC-10002"),
        cancel_call("Cancel my visit"),
        cancel_call("Yes, cancel it"),
        texts=["hi", "Cancel my visit", "Yes, cancel it"],
        answers=["hi", "It carries the $49 late fee. Cancel it?", "Cancelled."],
    )
    out = tool_results(started, cid)[-1]
    assert out["ok"] is True and out["appointmentId"] == 7
    assert out["lateFeeApplies"] is True and out["lateFeeCents"] == 4900
    assert fees.calls[-1][1] == "FEE-LATE"
    assert len(cancel.calls) == 1
    assert cancel.calls[0][1] == "MHC-10002"
    assert cancel.calls[0][-1] == cid
    has_write = [
        r[0]
        for r in rows(
            started,
            "SELECT has_write FROM turns WHERE conversation_id = ? ORDER BY seq",
            cid,
        )
    ]
    assert has_write == [0, 0, 1]


def test_cancel_confirm_expires_after_one_turn(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    cancel, _ = cancel_stubs(monkeypatch, late=False)
    cid, _ = run(
        started,
        identify_and_offer(monkeypatch, "MHC-10002"),
        cancel_call("Cancel my visit"),
        [tool_call("s", "report_status", intent="change_visit", resolved=False)],
        cancel_call("Yes, cancel it"),
        texts=["hi", "Cancel my visit", "Hmm, what time is it?", "Yes, cancel it"],
    )
    out = tool_results(started, cid)[-1]
    assert cancel.calls == []
    assert out["needsConfirmation"] is True and out["cancelled"] is False


def test_waitlist_uses_the_held_window_from_the_database(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    stub(monkeypatch, "app.scheduling.service.identify_customer", customer("MHC-10002"))
    stub(
        monkeypatch,
        "app.scheduling.service.get_appointment",
        AppointmentView(
            appointment_id=7,
            date="2026-10-21",
            window="08:00-12:00",
            technician_name="Jun Park",
            service_type="hvac_repair",
            zone="south",
            issue="x",
            late_cancel_fee_applies=False,
        ),
    )
    waitlist = stub(
        monkeypatch, "app.followups.service.join_waitlist", joined(created=True)
    )
    cid, replies = run(
        started,
        identify("MHC-10002"),
        [
            tool_call(
                "j",
                "join_waitlist",
                appointmentId=7,
                date="2026-10-30",
                window="16:00-19:00",
                zone="north",
                serviceType="plumbing",
            )
        ],
    )
    entry = waitlist.calls[0][1]
    assert (entry.held_date, entry.held_window, entry.zone, entry.service_type) == (
        "2026-10-21",
        "08:00-12:00",
        "south",
        "hvac_repair",
    )
    assert entry.conversation_id == cid and entry.customer_id == "MHC-10002"
    assert replies[1]["waitlisted"] is True


def test_handoff_gets_the_conversations_ids(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    stub(monkeypatch, "app.scheduling.service.identify_customer", customer("MHC-10002"))
    cid, _ = run(
        started,
        identify("MHC-10002"),
        [
            tool_call(
                "e",
                "escalate",
                kind="handoff",
                reason="caller_asked_for_person",
                intent="other",
                toldCaller="A person will call.",
                conversationId="other",
                customerId="MHC-10001",
                summarySource="system",
                callerName="Someone Else",
                callerPhone="512-555-9999",
            )
        ],
    )
    row = rows(
        started,
        "SELECT conversation_id, customer_id, summary_source, caller_name, "
        "caller_phone, stated_by_caller FROM handoffs",
    )
    assert [tuple(r) for r in row] == [
        (cid, "MHC-10002", "agent", "Omar Patel", "512-555-0102", 0)
    ]


def raise_unknown_fee(*args: Any, **kwargs: Any) -> Fee:
    raise UnknownFee("FEE-DIAG")


def test_book_without_a_price_book_states_no_fee(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    stub(monkeypatch, "app.scheduling.service.identify_customer", customer("MHC-10002"))
    stub(monkeypatch, "app.scheduling.service.book_visit", booking())
    monkeypatch.setattr("app.knowledge.service.get_fee", raise_unknown_fee)
    cid, replies = run(
        started,
        identify_and_offer(monkeypatch, "MHC-10002"),
        [tool_call("b", "book_visit", slotId=3, issue="no cooling", callerQuote="yes")],
        texts=["hi", "yes"],
    )
    out = tool_results(started, cid)[-1]
    assert out["ok"] is True and out["booking"]["diagnosticFeeCents"] is None
    assert out["diagnosticFeeUnavailable"] is True
    assert "Do not state a fee" in out["message"]
    assert replies[1]["booking"]["diagnosticFeeCents"] is None


def test_move_without_a_price_book_states_no_fee(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    stub(monkeypatch, "app.scheduling.service.identify_customer", customer("MHC-10002"))
    stub(
        monkeypatch,
        "app.scheduling.service.move_visit",
        MoveResult(booking=booking(), late_fee_applies=True),
    )
    monkeypatch.setattr("app.knowledge.service.get_fee", raise_unknown_fee)
    cid, _ = run(
        started,
        identify_and_offer(monkeypatch, "MHC-10002"),
        [tool_call("m", "move_visit", appointmentId=7, newSlotId=3, callerQuote="yes")],
        texts=["hi", "yes"],
    )
    out = tool_results(started, cid)[-1]
    assert out["booking"]["diagnosticFeeCents"] is None
    assert out["diagnosticFeeUnavailable"] is True
    assert out["lateFeeApplies"] is True and out["lateFeeCents"] is None
    assert out["lateFeeUnavailable"] is True
    assert "Do not state a fee" in out["message"]


def test_move_late_fee_carries_the_amount(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    stub(monkeypatch, "app.scheduling.service.identify_customer", customer("MHC-10002"))
    stub(
        monkeypatch,
        "app.scheduling.service.move_visit",
        MoveResult(booking=booking(), late_fee_applies=True),
    )
    monkeypatch.setattr(
        "app.knowledge.service.get_fee",
        lambda ctx, code: Fee(code=code, cents=4900, source_file="pricing"),
    )
    cid, _ = run(
        started,
        identify_and_offer(monkeypatch, "MHC-10002"),
        [tool_call("m", "move_visit", appointmentId=7, newSlotId=3, callerQuote="yes")],
        texts=["hi", "yes"],
    )
    out = tool_results(started, cid)[-1]
    assert out["lateFeeApplies"] is True and out["lateFeeCents"] == 4900
    assert "lateFeeUnavailable" not in out


def test_name_only_identify_is_refused_without_a_try(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    ident = stub(monkeypatch, "app.scheduling.service.identify_customer", None)
    call = tool_call("id", "identify_customer")
    call["function"]["arguments"] = json.dumps({"name": "Test"})
    cid, _ = run(started, [call])
    assert ident.calls == []
    assert tool_results(started, cid)[0]["error"] == "missing_details"
    assert rows(started, "SELECT identify_attempts FROM conversations")[0][0] == 0


@pytest.mark.caller_details
def test_made_up_details_are_refused_without_a_try(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    ident = stub(monkeypatch, "app.scheduling.service.identify_customer", None)
    call = identify_as("id", "Omar Patel", "512-555-0102")
    cid, replies = run(started, [call], texts=["No, none of that."])
    assert ident.calls == []
    assert tool_results(started, cid)[0]["error"] == "details_not_given"
    assert rows(started, "SELECT identify_attempts FROM conversations")[0][0] == 0
    assert replies[0]["status"] != "handed_off"


@pytest.mark.caller_details
def test_details_from_an_earlier_message_are_accepted(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    looked = by_name(monkeypatch)
    call = identify_as("id", "Omar Patel", "+1 (512) 555-0102")
    results = [
        result(assistant("Thanks.")),
        result(assistant(calls=[call])),
        result(assistant("answer")),
    ]
    client = client_for(started, FakeModelProvider(results=results))
    cid = new_conversation(client)
    say(client, cid, "I'm omar patel, 512.555.0102")
    say(client, cid, "book it")
    assert looked == ["Omar Patel"]


@pytest.mark.caller_details
def test_account_number_must_be_the_one_given(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    ident = stub(monkeypatch, "app.scheduling.service.identify_customer", None)
    call = tool_call("id", "identify_customer")
    call["function"]["arguments"] = json.dumps(
        {"name": "Omar Patel", "accountNumber": "MHC-10002"}
    )
    run(started, [call], texts=["Omar Patel, account MHC-10003"])
    assert ident.calls == []


def raise_with(exc: Exception):
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise exc

    return boom


@pytest.mark.parametrize(
    ("path", "exc", "name", "args", "unavailable"),
    [
        (
            "app.knowledge.service.search_knowledge",
            EmbeddingUnavailable("embeddings down"),
            "search_knowledge",
            {"query": "diagnostic fee"},
            "embedding_unavailable",
        ),
        (
            "app.knowledge.service.search_knowledge",
            IndexUnavailable("no index"),
            "search_knowledge",
            {"query": "diagnostic fee"},
            "embedding_unavailable",
        ),
        (
            "app.scheduling.service.find_open_windows",
            SchedulingUnavailable("scheduling database unavailable"),
            "find_open_windows",
            {"serviceType": "repair"},
            "scheduling_unavailable",
        ),
        (
            "app.scheduling.service.book_visit",
            SchedulingUnavailable("scheduling database unavailable"),
            "book_visit",
            {"slotId": 3, "issue": "no cooling", "callerQuote": "yes book it"},
            "scheduling_unavailable",
        ),
    ],
)
def test_unavailable_tool_failures_are_classified(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    exc: Exception,
    name: str,
    args: dict[str, Any],
    unavailable: str,
):
    monkeypatch.setattr(path, raise_with(exc))
    ctx = SimpleNamespace(clock=SimpleNamespace(monotonic=lambda: 0.0))
    state = ToolState(
        sqlite3.connect(":memory:"),
        "conv-1",
        "yes book it",
        "booking",
        [],
        "MHC-10002",
        "none",
        0,
    )
    state.earlier_slot_ids = {3}
    call = {"function": {"name": name, "arguments": json.dumps(args)}}
    out, entry = run_tool(ctx, state, call)  # type: ignore[arg-type]
    assert state.unavailable == unavailable
    assert entry["ok"] is False
    if unavailable == "embedding_unavailable":
        assert out == {
            "ok": False,
            "error": "embedding_unavailable",
            "instruction": SEARCH_UNAVAILABLE_INSTRUCTION,
        }
        assert "from memory" in SEARCH_UNAVAILABLE_INSTRUCTION
    else:
        assert out["ok"] is False and "SchedulingUnavailable" in out["error"]


def test_window_choices_are_capped_at_three(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    stub(monkeypatch, "app.scheduling.service.identify_customer", customer("MHC-10002"))
    stub(
        monkeypatch,
        "app.scheduling.service.find_open_windows",
        OpenWindows(
            windows=[
                window(i, f"{7 + i:02d}:00", f"{11 + i:02d}:00") for i in range(1, 6)
            ],
            matched_request=True,
            reason=None,
        ),
    )
    cid, replies = run(
        started,
        identify("MHC-10002"),
        [tool_call("w", "find_open_windows", serviceType="hvac_repair")],
    )
    labels = [c["label"] for c in replies[1]["choices"]]
    assert labels == [
        "Wednesday October 21, 8 AM to 12 PM, Jun Park",
        "Wednesday October 21, 9 AM to 1 PM, Jun Park",
        "Wednesday October 21, 10 AM to 2 PM, Jun Park",
        "Nothing earlier? Ask for an earlier window",
    ]
    told = tool_results(started, cid)[-1]
    assert [w["slotId"] for w in told["windows"]] == [1, 2, 3]
    offered = rows(
        started,
        "SELECT offered FROM turns WHERE conversation_id = ? ORDER BY seq",
        cid,
    )
    assert json.loads(offered[-1]["offered"])["slotIds"] == [1, 2, 3]


def test_find_open_windows_schema_is_closed():
    from app.conversation.tools import TOOLS

    params = next(
        t["function"]["parameters"]
        for t in TOOLS
        if t["function"]["name"] == "find_open_windows"
    )["properties"]
    assert params["serviceType"]["enum"] == ["hvac_repair", "hvac_tune_up", "plumbing"]
    assert params["preferredWindow"]["enum"] == [
        "08:00-12:00",
        "12:00-16:00",
        "13:00-17:00",
        "16:00-19:00",
    ]
    assert "YYYY-MM-DD" in params["preferredDate"]["description"]


def test_cancel_with_a_text_id_never_commits(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    cancel, _ = cancel_stubs(monkeypatch, late=False)
    text_id = [tool_call("c", "cancel_visit", appointmentId="7", callerQuote="Yes")]
    run(
        started,
        identify_and_offer(monkeypatch, "MHC-10002"),
        cancel_call("Cancel my visit"),
        text_id,
        texts=["hi", "Cancel my visit", "Yes"],
    )
    assert cancel.calls == []


def test_late_cancel_without_a_price_book_never_commits(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    cancel, _ = cancel_stubs(monkeypatch, late=True)
    monkeypatch.setattr("app.knowledge.service.get_fee", raise_unknown_fee)
    cid, _ = run(
        started,
        identify_and_offer(monkeypatch, "MHC-10002"),
        cancel_call("Cancel my visit"),
        cancel_call("Yes, cancel it"),
        texts=["hi", "Cancel my visit", "Yes, cancel it"],
    )
    out = tool_results(started, cid)[-1]
    assert cancel.calls == []
    assert out["needsConfirmation"] is True and out["lateFeeUnavailable"] is True


EARLIER_LABELS = [
    "Book Wednesday October 21, 1 PM to 5 PM and join the waitlist for earlier",
    "Book Wednesday October 21, 1 PM to 5 PM only",
    "Talk to a person instead",
]


def test_earlier_ask_offers_three_choices(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    stub(monkeypatch, "app.scheduling.service.identify_customer", customer("MHC-10002"))
    stub(
        monkeypatch,
        "app.scheduling.service.find_open_windows",
        OpenWindows(
            windows=[window(119, "13:00", "17:00"), window(185, "12:00", "16:00")],
            matched_request=True,
            reason=None,
        ),
    )
    cid, replies = run(
        started,
        identify("MHC-10002"),
        [tool_call("w", "find_open_windows", serviceType="hvac_repair")],
        texts=["Omar Patel, MHC-10002", "Can you do anything earlier?"],
    )
    assert tool_results(started, cid)[-1]["instruction"] == EARLIER_INSTRUCTION
    choices = replies[1]["choices"]
    assert [c["label"] for c in choices] == EARLIER_LABELS
    assert [c["text"] for c in choices] == EARLIER_LABELS
    assert "choices_only" in replies[1]["actions"]


def test_typed_earlier_variant_keeps_window_buttons(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    stub(monkeypatch, "app.scheduling.service.identify_customer", customer("MHC-10002"))
    stub(
        monkeypatch,
        "app.scheduling.service.find_open_windows",
        OpenWindows(
            windows=[window(119, "13:00", "17:00")], matched_request=True, reason=None
        ),
    )
    cid, replies = run(
        started,
        identify("MHC-10002"),
        [tool_call("w", "find_open_windows", serviceType="hvac_repair")],
        texts=["Omar Patel, MHC-10002", "I want an earlier start time on Wednesday"],
    )
    assert "instruction" not in tool_results(started, cid)[-1]
    assert (
        replies[1]["choices"][-1]["label"]
        == "Nothing earlier? Ask for an earlier window"
    )
    assert "choices_only" not in replies[1]["actions"]


def test_waitlist_repeat_says_already_on_it(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    stub(monkeypatch, "app.scheduling.service.identify_customer", customer("MHC-10002"))
    stub(
        monkeypatch,
        "app.scheduling.service.get_appointment",
        held_visit(7, "13:00", "17:00"),
    )
    stub(monkeypatch, "app.followups.service.join_waitlist", joined(created=False))
    cid, replies = run(
        started,
        identify("MHC-10002"),
        [tool_call("j", "join_waitlist", appointmentId=7)],
    )
    out = tool_results(started, cid)[-1]
    assert out == {
        "ok": True,
        "alreadyOnWaitlist": True,
        "held": {"date": "2026-10-21", "window": "13:00-17:00"},
        "instruction": ALREADY_ON_WAITLIST_INSTRUCTION,
    }
    has_write = rows(
        started,
        "SELECT has_write FROM turns WHERE conversation_id = ? ORDER BY seq",
        cid,
    )
    assert [r[0] for r in has_write][-1] == 0
    assert replies[1]["waitlisted"] is True


def test_join_after_booking_holds_the_new_booking(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    stub(monkeypatch, "app.scheduling.service.identify_customer", customer("MHC-10002"))
    stub(monkeypatch, "app.scheduling.service.book_visit", booking())
    stub(
        monkeypatch,
        "app.knowledge.service.get_fee",
        Fee(code="FEE-DIAG", cents=8900, source_file="pricing"),
    )
    got = stub(monkeypatch, "app.scheduling.service.get_appointment", held_visit(7))
    waitlist = stub(
        monkeypatch, "app.followups.service.join_waitlist", joined(created=True)
    )
    quote = "Book it and join the waitlist for earlier"
    cid, replies = run(
        started,
        identify_and_offer(monkeypatch, "MHC-10002"),
        [
            tool_call(
                "b", "book_visit", slotId=3, issue="no cooling", callerQuote=quote
            ),
            tool_call("j", "join_waitlist", appointmentId=99),
        ],
        texts=["hi", quote],
    )
    booked, joined_out = tool_results(started, cid)[-2:]
    assert booked["instruction"] == JOIN_AFTER_BOOKING_INSTRUCTION
    assert joined_out["instruction"] == ON_WAITLIST_INSTRUCTION
    assert got.calls[0][1:] == ("MHC-10002", 7)
    assert len(waitlist.calls) == 1
    assert replies[1]["booking"]["appointmentId"] == 7
    assert replies[1]["waitlisted"] is True


def raise_not_found(*args: Any, **kwargs: Any) -> AppointmentView:
    from app.scheduling.service import AppointmentNotFound

    raise AppointmentNotFound("no such appointment")


def test_failed_join_offers_a_person(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    stub(monkeypatch, "app.scheduling.service.identify_customer", customer("MHC-10002"))
    monkeypatch.setattr("app.scheduling.service.get_appointment", raise_not_found)
    waitlist = stub(monkeypatch, "app.followups.service.join_waitlist", None)
    cid, replies = run(
        started,
        identify("MHC-10002"),
        [tool_call("j", "join_waitlist", appointmentId=1)],
    )
    out = tool_results(started, cid)[-1]
    assert out["ok"] is False
    assert "not added to the waitlist" in out["instruction"]
    assert waitlist.calls == []
    assert replies[1]["waitlisted"] is False
    assert "request_callback" in replies[1]["actions"]


def test_booking_without_report_status_asks_solved(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    stub(monkeypatch, "app.scheduling.service.identify_customer", customer("MHC-10002"))
    stub(monkeypatch, "app.scheduling.service.book_visit", booking())
    stub(
        monkeypatch,
        "app.knowledge.service.get_fee",
        Fee(code="FEE-DIAG", cents=8900, source_file="pricing"),
    )
    _, replies = run(
        started,
        identify_and_offer(monkeypatch, "MHC-10002"),
        [tool_call("b", "book_visit", slotId=3, issue="no cooling", callerQuote="yes")],
        texts=["hi", "yes"],
    )
    assert "ask_solved" in replies[1]["actions"]


def test_repeat_join_for_another_visit_says_already_on_it(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    """One earlier-window request per caller and visit type: a second visit adds no row."""
    stub(monkeypatch, "app.scheduling.service.identify_customer", customer("MHC-10002"))
    stub(monkeypatch, "app.scheduling.service.get_appointment", held_visit(5))
    stub(
        monkeypatch, "app.followups.service.list_waitlist", [joined(created=True).entry]
    )
    waitlist = stub(monkeypatch, "app.followups.service.join_waitlist", None)
    cid, replies = run(
        started,
        identify("MHC-10002"),
        [tool_call("j", "join_waitlist", appointmentId=5)],
    )
    out = tool_results(started, cid)[-1]
    assert waitlist.calls == []
    assert out["alreadyOnWaitlist"] is True
    assert out["held"] == {"date": "2026-10-21", "window": "13:00-17:00"}
    assert out["instruction"] == ALREADY_ON_WAITLIST_INSTRUCTION
    has_write = rows(
        started,
        "SELECT has_write FROM turns WHERE conversation_id = ? ORDER BY seq",
        cid,
    )
    assert has_write[-1][0] == 0
    assert replies[1]["waitlisted"] is True


def test_failed_join_after_booking_offers_a_person(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    stub(monkeypatch, "app.scheduling.service.identify_customer", customer("MHC-10002"))
    stub(monkeypatch, "app.scheduling.service.book_visit", booking())
    stub(
        monkeypatch,
        "app.knowledge.service.get_fee",
        Fee(code="FEE-DIAG", cents=8900, source_file="pricing"),
    )
    monkeypatch.setattr("app.scheduling.service.get_appointment", raise_not_found)
    _, replies = run(
        started,
        identify_and_offer(monkeypatch, "MHC-10002"),
        [
            tool_call("b", "book_visit", slotId=3, issue="x", callerQuote="yes"),
            tool_call("j", "join_waitlist", appointmentId=7),
        ],
        texts=["hi", "yes"],
    )
    assert replies[1]["booking"]["appointmentId"] == 7
    assert replies[1]["waitlisted"] is False
    assert "request_callback" in replies[1]["actions"]
    assert "ask_solved" not in replies[1]["actions"]


def test_earlier_ask_searches_from_the_earliest_window(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    """The earlier button's turn asks Scheduling for the earliest windows, whatever day
    or window the model passes."""
    stub(monkeypatch, "app.scheduling.service.identify_customer", customer("MHC-10002"))
    found = stub(
        monkeypatch,
        "app.scheduling.service.find_open_windows",
        OpenWindows(
            windows=[window(119, "13:00", "17:00")], matched_request=True, reason=None
        ),
    )
    run(
        started,
        identify("MHC-10002"),
        [
            tool_call(
                "w",
                "find_open_windows",
                serviceType="hvac_repair",
                preferredDate="2026-10-25",
                preferredWindow="08:00-12:00",
            )
        ],
        texts=["Omar Patel, MHC-10002", "Can you do anything earlier?"],
    )
    assert found.calls[-1][1:] == ("MHC-10002", "hvac_repair", None, None)


def escalate_call(reason: str) -> list[dict[str, Any]]:
    return [
        tool_call(
            "e",
            "escalate",
            kind="supervisor_callback" if reason == "billing_dispute" else "handoff",
            reason=reason,
            intent="x",
            toldCaller="x",
        )
    ]


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        (
            "I want a real person now. My card is 4111 1111 1111 1111.",
            "caller_asked_for_person",
        ),
        ("I was charged twice on 4111 1111 1111 1111.", "billing_dispute"),
    ],
)
def test_card_turn_still_hands_off_when_the_caller_asks(
    started: Settings, monkeypatch: pytest.MonkeyPatch, text: str, reason: str
):
    _, replies = run(started, escalate_call(reason), texts=[text])
    reply = replies[0]
    print(reply["text"])
    assert (reply["status"], reply["banner"]) == ("handed_off", "handoff")
    assert rows(started, "SELECT reason FROM handoffs")[0][0] == reason
    assert reply["text"].startswith(CARD_REFUSAL_TEXT)


@pytest.mark.parametrize(
    "reason", ["caller_asked_for_person", "billing_dispute", "other"]
)
def test_card_alone_is_not_handed_off(
    started: Settings, monkeypatch: pytest.MonkeyPatch, reason: str
):
    cid, replies = run(
        started, escalate_call(reason), texts=["4111-1111-1111-1111 exp 12/28"]
    )
    assert (replies[0]["status"], replies[0]["banner"]) == ("active", "none")
    assert tool_results(started, cid)[0]["error"] == "card_number_turn"
    assert rows(started, "SELECT COUNT(*) FROM handoffs")[0][0] == 0


def test_cancel_ask_survives_a_card_turn(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    cancel_stubs(monkeypatch, late=False)
    cid, replies = run(
        started,
        identify_and_offer(monkeypatch, "MHC-10002"),
        cancel_call("Cancel my visit"),
        texts=["hi", "Cancel my visit. My card is 4111 1111 1111 1111."],
    )
    assert replies[1]["text"].startswith(CARD_REFUSAL_TEXT)
    last = rows(
        started,
        "SELECT offered FROM turns WHERE conversation_id = ? ORDER BY seq",
        cid,
    )[-1]
    assert json.loads(last["offered"])["cancelAppointmentIds"] == [7]


@pytest.mark.parametrize(
    ("text", "earlier"),
    [
        ("Is there anything earlier possible?", True),
        ("anything sooner?", True),
        ("Do you have anything earlier?", True),
        ("Can you do anything earlier?", True),
        ("I want an earlier start time on Wednesday", False),
        ("earlier you said Wednesday", False),
        ("can I book Wednesday?", False),
        ("nothing earlier works for me, Wednesday is fine", False),
        ("Anything on Wednesday earlier than noon?", False),
        ("Nothing sooner is needed, Wednesday is fine", False),
        ("no need for anything earlier", False),
        ("any earlier calls?", False),
        ("Is there an earlier slot?", True),
        ("Can you get someone out sooner?", True),
        ("I need someone sooner", True),
        (
            (
                "I was hoping for a visit this Monday, October 19, or Tuesday, October 20. "
                "Is anything earlier possible?"
            ),
            True,
        ),
        ("Anything Weds earlier?", False),
        ("something tmrw earlier?", False),
        ("Anything next week sooner?", False),
        ("Anything October 21 earlier?", False),
    ],
)
def test_typed_earlier_request_counts_like_the_button(text: str, earlier: bool):
    assert asks_earlier(text) is earlier


def test_typed_earlier_request_gets_the_waitlist_choices(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    stub(monkeypatch, "app.scheduling.service.identify_customer", customer("MHC-10002"))
    found = stub(
        monkeypatch,
        "app.scheduling.service.find_open_windows",
        OpenWindows(
            windows=[window(119, "13:00", "17:00")], matched_request=True, reason=None
        ),
    )
    cid, replies = run(
        started,
        identify("MHC-10002"),
        [
            tool_call(
                "w",
                "find_open_windows",
                serviceType="hvac_repair",
                preferredDate="2026-10-19",
            )
        ],
        texts=["Omar Patel, MHC-10002", "Is there anything earlier possible?"],
    )
    assert found.calls[-1][1:] == ("MHC-10002", "hvac_repair", None, None)
    assert tool_results(started, cid)[-1]["instruction"] == EARLIER_INSTRUCTION
    assert [c["label"] for c in replies[1]["choices"]] == EARLIER_LABELS
    assert "choices_only" in replies[1]["actions"]


def offered_rows(started: Settings, cid: str) -> list[dict[str, Any]]:
    return [
        json.loads(r[0])
        for r in rows(
            started,
            "SELECT offered FROM turns WHERE conversation_id = ? ORDER BY seq",
            cid,
        )
    ]


def test_earlier_turn_records_the_waitlist_offer(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    stub(monkeypatch, "app.scheduling.service.identify_customer", customer("MHC-10002"))
    stub(
        monkeypatch,
        "app.scheduling.service.find_open_windows",
        OpenWindows(windows=[window(3)], matched_request=True, reason=None),
    )
    cid, _ = run(
        started,
        [*identify("MHC-10002"), tool_call("w", "find_open_windows", serviceType="x")],
        [tool_call("w", "find_open_windows", serviceType="hvac_repair")],
        texts=["Omar Patel, MHC-10002", "anything sooner?"],
    )
    offered = offered_rows(started, cid)
    assert "waitlistOffered" not in offered[0]
    assert offered[1]["waitlistOffered"] is True


def book_after_offer(
    started: Settings,
    monkeypatch: pytest.MonkeyPatch,
    text: str,
    offer: bool = True,
    fail_join: bool = False,
    offer_answer: str = "answer 1",
    model_joins: bool = False,
):
    """Turn 1 shows slot 3; turn 2 asks for earlier (or not); turn 3 books slot 3 with
    `text`. The model never calls join_waitlist."""
    stub(monkeypatch, "app.scheduling.service.identify_customer", customer("MHC-10002"))
    stub(monkeypatch, "app.scheduling.service.book_visit", booking())
    stub(
        monkeypatch,
        "app.knowledge.service.get_fee",
        Fee(code="FEE-DIAG", cents=8900, source_file="pricing"),
    )
    got = stub(monkeypatch, "app.scheduling.service.get_appointment", held_visit(7))
    if fail_join:
        # The app's join fails; a model retry would find the visit.
        def fail_once(*args: Any) -> AppointmentView:
            if not got.calls:
                got.calls.append(args)
                raise_not_found()
            return held_visit(7)

        monkeypatch.setattr("app.scheduling.service.get_appointment", fail_once)
    waitlist = stub(
        monkeypatch, "app.followups.service.join_waitlist", joined(created=True)
    )
    cid, replies = run(
        started,
        identify_and_offer(monkeypatch, "MHC-10002"),
        [tool_call("w", "find_open_windows", serviceType="hvac_repair")],
        [
            tool_call(
                "b", "book_visit", slotId=3, issue="no cooling", callerQuote=text
            ),
            *(
                [tool_call("j", "join_waitlist", appointmentId=7)]
                if model_joins
                else []
            ),
        ],
        answers=["answer 0", offer_answer, "answer 2"],
        texts=[
            "hi",
            "Is there anything earlier possible?" if offer else "What do you have?",
            text,
        ],
    )
    return cid, replies, waitlist, got


@pytest.mark.parametrize(
    "text",
    [
        "Okay, do that, and book the slot for Wednesday from 8 AM to 12 PM.",
        "Yes, book Wednesday",
        "Both please, book Wednesday",
        "Sounds good, book it",
        "Book Wednesday and the waitlist",
        "Add me and book Wednesday",
    ],
)
def test_accepting_the_offer_joins_in_code(
    started: Settings, monkeypatch: pytest.MonkeyPatch, text: str
):
    cid, replies, waitlist, got = book_after_offer(started, monkeypatch, text)
    assert len(waitlist.calls) == 1
    entry = waitlist.calls[0][1]
    assert (entry.held_date, entry.held_window) == ("2026-10-21", "08:00-12:00")
    assert got.calls[-1][1:] == ("MHC-10002", 7)
    assert replies[2]["booking"]["appointmentId"] == 7
    assert replies[2]["waitlisted"] is True
    assert tool_results(started, cid)[-1]["instruction"] == (
        JOIN_AFTER_BOOKING_INSTRUCTION
    )


@pytest.mark.parametrize(
    ("text", "offer"),
    [
        ("Book Wednesday 8 AM only", True),
        ("just book it", True),
        ("no waitlist, just book Wednesday", True),
        ("Nah, skip the waitlist, book Wednesday", True),
        ("Yes, but skip the waitlist", True),
        ("Yes please. I dont want the waitlist", True),
        ("Yes, book Wednesday, hold off on the waitlist", True),
        ("Book Wednesday, nope to the waitlist", True),
        ("Never mind the waitlist, book Wednesday", True),
        ("Yes, but don't add me to the waitlist", True),
        ("yes book it without the waitlist", True),
        ("yes, not the waitlist", True),
        ("Yes, leave me off the waitlist", True),
        ("Yes, book Wednesday. I'll decline the waitlist", True),
        ("Yes, book Wednesday and drop the waitlist", True),
        ("Yes, book Wednesday. Remove me from the waitlist", True),
        ("Yes book Wednesday, the waitlist is unnecessary", True),
        ("Okay, do that, and book the slot for Wednesday from 8 AM to 12 PM.", False),
    ],
)
def test_declining_the_offer_does_not_join(
    started: Settings, monkeypatch: pytest.MonkeyPatch, text: str, offer: bool
):
    _, replies, waitlist, _ = book_after_offer(started, monkeypatch, text, offer)
    assert waitlist.calls == []
    assert replies[2]["booking"]["appointmentId"] == 7
    assert replies[2]["waitlisted"] is False


def test_accepting_when_already_on_the_waitlist_adds_no_row(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    stub(
        monkeypatch, "app.followups.service.list_waitlist", [joined(created=True).entry]
    )
    cid, replies, waitlist, _ = book_after_offer(
        started, monkeypatch, "Yes, book Wednesday"
    )
    assert waitlist.calls == []
    assert replies[2]["waitlisted"] is True
    assert tool_results(started, cid)[-1]["instruction"] == (
        ALREADY_ON_WAITLIST_INSTRUCTION
    )


def test_failed_app_join_after_booking_offers_a_person(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    _, replies, waitlist, _ = book_after_offer(
        started, monkeypatch, "Yes, book Wednesday", fail_join=True, model_joins=True
    )
    assert waitlist.calls == []
    assert replies[2]["booking"]["appointmentId"] == 7
    assert replies[2]["waitlisted"] is False
    assert "request_callback" in replies[2]["actions"]


def test_offer_the_caller_never_saw_is_not_recorded(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    """The earlier turn's reply was empty, so the caller got the fallback, not the offer."""
    cid, replies, waitlist, _ = book_after_offer(
        started, monkeypatch, "yes book Wednesday", offer_answer=""
    )
    assert "waitlistOffered" not in offered_rows(started, cid)[1]
    assert waitlist.calls == []
    assert replies[2]["waitlisted"] is False


EARLIEST_SLOT_3 = "Wednesday October 21, 8 AM to 12 PM"


def test_typed_earlier_request_offers_even_when_the_model_does_not_search(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    stub(monkeypatch, "app.scheduling.service.identify_customer", customer("MHC-10002"))
    stub(monkeypatch, "app.scheduling.service.book_visit", booking())
    stub(
        monkeypatch,
        "app.knowledge.service.get_fee",
        Fee(code="FEE-DIAG", cents=8900, source_file="pricing"),
    )
    stub(monkeypatch, "app.scheduling.service.get_appointment", held_visit(7))
    waitlist = stub(
        monkeypatch, "app.followups.service.join_waitlist", joined(created=True)
    )
    first = identify_and_offer(monkeypatch, "MHC-10002")
    found = Recorder(
        OpenWindows(windows=[window(3)], matched_request=True, reason=None)
    )
    monkeypatch.setattr("app.scheduling.service.find_open_windows", found)
    book = "Okay, do that, and book the slot."
    client = client_for(
        started,
        FakeModelProvider(
            results=[
                result(assistant(calls=first)),
                result(assistant("answer 0")),
                result(assistant("Nothing earlier, but I can pass you to a person.")),
                result(
                    assistant(
                        calls=[
                            tool_call(
                                "b", "book_visit", slotId=3, issue="x", callerQuote=book
                            )
                        ]
                    )
                ),
                result(assistant("Booked.")),
            ]
        ),
    )
    cid = new_conversation(client)
    say(client, cid, "hi")
    offer = say(client, cid, "Is there anything earlier possible?")
    booked = say(client, cid, book)
    assert found.calls[-1][1:] == ("MHC-10002", "hvac_repair", None, None)
    assert [c["label"] for c in offer["choices"]] == [
        f"Book {EARLIEST_SLOT_3} and join the waitlist for earlier",
        f"Book {EARLIEST_SLOT_3} only",
        "Talk to a person instead",
    ]
    assert "choices_only" in offer["actions"]
    assert offer["text"] == (
        f"The earliest window I have is {EARLIEST_SLOT_3}. I can book it and add you "
        "to the waitlist for an earlier window. If one opens, the team will call you."
    )
    assert offered_rows(started, cid)[1]["waitlistOffered"] is True
    assert len(waitlist.calls) == 1
    assert booked["waitlisted"] is True


def earlier_without_search(
    started: Settings,
    monkeypatch: pytest.MonkeyPatch,
    text: str,
    calls: list[dict[str, Any]],
    answer: str,
    first_windows: list[Window] | None = None,
) -> tuple[str, dict[str, Any], Recorder]:
    """Turn 1 matches the caller and shows windows (or `first_windows`); turn 2 sends
    `text`, the model makes `calls` (never find_open_windows) and says `answer`."""
    stub(monkeypatch, "app.scheduling.service.identify_customer", customer("MHC-10002"))
    stub(monkeypatch, "app.scheduling.service.get_appointment", held_visit(7))
    cancel = stub(monkeypatch, "app.scheduling.service.cancel_visit", None)
    first = identify_and_offer(monkeypatch, "MHC-10002")
    found = Recorder(
        OpenWindows(
            windows=[window(3)] if first_windows is None else first_windows,
            matched_request=True,
            reason=None,
        )
    )
    monkeypatch.setattr("app.scheduling.service.find_open_windows", found)
    second = (
        [result(assistant(calls=calls)), result(assistant(answer))]
        if calls
        else [result(assistant(answer))]
    )
    client = client_for(
        started,
        FakeModelProvider(
            results=[
                result(assistant(calls=first)),
                result(assistant("answer 0")),
                *second,
            ]
        ),
    )
    cid = new_conversation(client)
    say(client, cid, "hi")
    found.value = OpenWindows(windows=[window(3)], matched_request=True, reason=None)
    return cid, say(client, cid, text), cancel


CANCEL_TERMS = (
    "Your visit is Wednesday October 21, 8 AM to 12 PM. There is no fee. "
    "Do you want me to cancel it?"
)


def test_earlier_offer_keeps_the_models_cancel_ask(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    cid, reply, cancel = earlier_without_search(
        started,
        monkeypatch,
        "I want to cancel my visit, or is there an earlier slot?",
        [tool_call("c", "cancel_visit", appointmentId=7, callerQuote="cancel")],
        CANCEL_TERMS,
    )
    assert reply["text"] == CANCEL_TERMS
    assert "choices_only" not in reply["actions"]
    assert "waitlistOffered" not in offered_rows(started, cid)[1]
    assert offered_rows(started, cid)[1]["cancelAppointmentIds"] == [7]
    assert cancel.calls == []


def test_earlier_offer_keeps_the_models_knowledge_answer(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    stub(monkeypatch, "app.knowledge.service.search_knowledge", [])
    answer = "Members do not pay the diagnostic fee."
    cid, reply, _ = earlier_without_search(
        started,
        monkeypatch,
        "Is the fee waived for members? Also any earlier slot?",
        [tool_call("k", "search_knowledge", query="member fee")],
        answer,
    )
    assert reply["text"] == answer
    assert "waitlistOffered" not in offered_rows(started, cid)[1]


def test_earlier_offer_needs_windows_shown_before(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    answer = "Sorry, I have nothing open."
    cid, reply, _ = earlier_without_search(
        started, monkeypatch, "anything sooner?", [], answer, first_windows=[]
    )
    assert reply["text"] == answer
    assert "waitlistOffered" not in offered_rows(started, cid)[1]


def test_app_earlier_search_is_logged_with_a_unique_call_id(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    cid, reply, _ = earlier_without_search(
        started, monkeypatch, "anything sooner?", [], "No."
    )
    called = json.loads(
        rows(
            started,
            "SELECT tools_called FROM turns WHERE conversation_id = ? ORDER BY seq",
            cid,
        )[1][0]
    )
    stored = json.loads(
        rows(
            started,
            "SELECT model_messages FROM turns WHERE conversation_id = ? ORDER BY seq",
            cid,
        )[1][0]
    )
    ids = [c["id"] for m in stored for c in m.get("tool_calls") or []]
    assert [c["name"] for c in called] == ["find_open_windows"]
    assert len(ids) == 1 and ids[0] != "app_earlier_search"
    assert reply["text"].startswith("The earliest window I have is")


def test_offer_with_a_failed_write_is_not_recorded(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    """The offer turn's reply went out with a failed write, so it is not a clean offer."""
    stub(monkeypatch, "app.scheduling.service.identify_customer", customer("MHC-10002"))

    def fail(*args: Any) -> Booking:
        from app.scheduling.service import NotEligible

        raise NotEligible("slot_taken")

    monkeypatch.setattr("app.scheduling.service.book_visit", fail)
    cid, replies = run(
        started,
        identify_and_offer(monkeypatch, "MHC-10002"),
        [
            tool_call("w", "find_open_windows", serviceType="hvac_repair"),
            tool_call("b", "book_visit", slotId=3, issue="x", callerQuote="sooner"),
        ],
        texts=["hi", "anything sooner?"],
    )
    assert [c["text"] for c in replies[1]["choices"]][-1] == "Talk to a person instead"
    assert "waitlistOffered" not in offered_rows(started, cid)[1]


def test_no_earlier_offer_without_an_earlier_request(
    started: Settings, monkeypatch: pytest.MonkeyPatch
):
    answer = "You are welcome."
    cid, reply, _ = earlier_without_search(
        started, monkeypatch, "Thanks for the help", [], answer
    )
    called = rows(
        started,
        "SELECT tools_called FROM turns WHERE conversation_id = ? ORDER BY seq",
        cid,
    )[1][0]
    assert json.loads(called) == []
    assert reply["text"] == answer
    assert reply["choices"] == []
    assert "waitlistOffered" not in offered_rows(started, cid)[1]

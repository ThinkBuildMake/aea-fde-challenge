"""S51: a cancel commits on the caller's clear yes to terms they saw, even when the yes
is comma-joined or a question about the terms sits between the ask and the yes."""

import pytest

from app.conversation import guards
from app.settings import Settings
from app.types import AppointmentView, CancelResult, Fee
from tests.test_agent_tools import customer, identify_as, run, stub, tool_results
from tests.test_turn import tool_call

ASK = (
    "Cancelling now carries the $49 late-cancellation fee. Do you want me to cancel it?"
)
NOTICE = "don't I need to give 48 hours notice?"
RESTATED = (
    "Cancelling within 48 hours carries the $49 late fee. "
    "Would you like me to proceed with the cancellation?"
)
UNSTATED = "Yes, the policy asks for 48 hours notice. Would you like me to cancel it?"
ACCEPT = "I accept the fee, please go ahead and cancel it. That is all."


def held(monkeypatch: pytest.MonkeyPatch, late: bool) -> None:
    view = AppointmentView(
        appointment_id=25,
        date="2026-10-21",
        window="08:00-12:00",
        technician_name="Jun Park",
        service_type="hvac_repair",
        zone="south",
        issue="x",
        late_cancel_fee_applies=late,
    )
    stub(monkeypatch, "app.scheduling.service.list_appointments", [view])
    stub(monkeypatch, "app.scheduling.service.get_appointment", view)


@pytest.fixture
def cancels(monkeypatch: pytest.MonkeyPatch):
    """Appointment 25 for MHC-29577, inside the late window ($49 fee)."""
    stub(monkeypatch, "app.scheduling.service.identify_customer", customer("MHC-29577"))
    held(monkeypatch, late=True)
    stub(
        monkeypatch,
        "app.knowledge.service.get_fee",
        Fee(code="FEE-LATE", cents=4900, source_file="pricing"),
    )
    return stub(
        monkeypatch,
        "app.scheduling.service.cancel_visit",
        CancelResult(
            appointment_id=25, freed_slot_id=3, late_fee_applies=True, hours_before=5.0
        ),
    )


LOOKUP = [
    identify_as("id", "Test", "555-0100"),
    tool_call("l", "lookup_my_appointments"),
]
CANCEL = [tool_call("c", "cancel_visit", appointmentId=25, callerQuote="cancel it")]
STATUS = [tool_call("s", "report_status", intent="change_visit", resolved=False)]


def test_comma_joined_acceptance_cancels(started: Settings, cancels):
    cid, replies = run(
        started,
        LOOKUP,
        CANCEL,
        CANCEL,
        texts=["hi", "Cancel my visit", ACCEPT],
        answers=["Found your visit.", ASK, "Your visit is cancelled."],
    )
    print(
        "reply:", replies[-1]["text"], "| last result:", tool_results(started, cid)[-1]
    )
    assert [c[2] for c in cancels.calls] == [25]
    assert tool_results(started, cid)[-1]["appointmentId"] == 25
    assert replies[-1]["text"] == "Your visit is cancelled."


def three_turns(started: Settings, between: str, ask: str = ASK):
    return run(
        started,
        LOOKUP,
        CANCEL,
        STATUS,
        CANCEL,
        texts=["hi", "Cancel my visit", NOTICE, "Yes, cancel it"],
        answers=["Found your visit.", ask, between, "Your visit is cancelled."],
    )


def test_question_between_terms_and_yes_keeps_the_ask(started: Settings, cancels):
    _, replies = three_turns(started, RESTATED)
    print("reply:", replies[-1]["text"])
    assert [c[2] for c in cancels.calls] == [25]
    assert replies[-1]["text"] == "Your visit is cancelled."


def test_question_turn_without_the_fee_drops_the_ask(started: Settings, cancels):
    cid, replies = three_turns(started, UNSTATED)
    print("reply:", replies[-1]["text"])
    assert cancels.calls == []
    out = tool_results(started, cid)[-1]
    assert out["cancelled"] is False and out["needsConfirmation"] is True


@pytest.mark.parametrize("text", [ACCEPT, "Sure, go ahead and cancel it, thanks"])
def test_comma_joined_yes_is_clear(text: str):
    assert guards.clear_yes(text) is True


@pytest.mark.parametrize(
    "text",
    [
        NOTICE,
        "can you waive the fee?",
        "ok but only if there's no fee",
        "I'm not sure",
        "I accept, but can you waive the fee",
        "Keep it, ok",
        "Hold off, ok",
        "Let me check with my wife first, ok",
        "Move it to Thursday, sure",
        "Actually reschedule instead, sure",
        "I'll call back later, ok bye",
        "Hmm, ok",
        "Okay hold off",
        "yes keep it",
        "Yes reschedule",
        "Ok I changed my mind keep it",
        "yes cancel the other one",
        "Sure, move it instead",
    ],
)
def test_still_not_a_yes(text: str):
    assert guards.clear_yes(text) is False


def test_two_turns_between_terms_and_yes_drop_the_ask(started: Settings, cancels):
    cid, replies = run(
        started,
        LOOKUP,
        CANCEL,
        STATUS,
        STATUS,
        CANCEL,
        texts=["hi", "Cancel my visit", NOTICE, "Is that the rule?", "Yes, cancel it"],
        answers=["Found your visit.", ASK, RESTATED, RESTATED, "Cancelled."],
    )
    print("reply:", replies[-1]["text"])
    assert cancels.calls == []
    assert tool_results(started, cid)[-1]["needsConfirmation"] is True


def test_a_free_ask_is_not_carried(
    started: Settings, cancels, monkeypatch: pytest.MonkeyPatch
):
    held(monkeypatch, late=False)
    cid, replies = three_turns(
        started,
        "We're open 8-6. You can cancel any time. Need anything else?",
        ask="It can be cancelled with no fee. Do you want me to cancel it?",
    )
    print("reply:", replies[-1]["text"])
    assert cancels.calls == []
    assert tool_results(started, cid)[-1]["needsConfirmation"] is True


def test_a_withheld_cancel_claim_carries_no_other_ask(started: Settings, cancels):
    other = [tool_call("o", "cancel_visit", appointmentId=26, callerQuote="the other")]
    _, replies = run(
        started,
        LOOKUP,
        CANCEL,
        other,
        CANCEL,
        texts=["hi", "Cancel my visit", "And cancel the other one", "Yes, cancel it"],
        answers=["Found your visit.", ASK, "It has been cancelled.", "Cancelled."],
    )
    print("turn 2 reply:", replies[2]["text"], "| turn 3 reply:", replies[-1]["text"])
    assert replies[2]["text"] == guards.cancel_pending_text(4900)
    assert cancels.calls == []

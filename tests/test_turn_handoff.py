"""escalate hands the conversation to a person: the reply, the handoff row, the outcome."""

from typing import Any

from app.conversation import guards
from app.llm import FakeModelProvider, ModelResult
from app.settings import Settings
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


def escalation(reason: str, kind: str = "handoff", **extra: Any) -> ModelResult:
    calls = [
        tool_call("r", "report_status", intent="other", resolved=False),
        tool_call(
            "e",
            "escalate",
            kind=kind,
            reason=reason,
            intent=extra.pop("intent", "Charged twice for the same visit"),
            toldCaller=extra.pop("toldCaller", "A supervisor will call you."),
            **extra,
        ),
    ]
    return result(assistant(calls=calls))


def handoff_row(settings: Settings, cid: str) -> dict[str, Any]:
    found = rows(
        settings,
        "SELECT kind, reason, by_error, intent, told_caller, caller_name, "
        "caller_phone, customer_id FROM handoffs WHERE conversation_id = ?",
        cid,
    )
    assert len(found) == 1
    return dict(found[0])


def outcome(settings: Settings, cid: str) -> Any:
    return rows(settings, "SELECT outcome FROM conversations WHERE id = ?", cid)[0][0]


def show(reply: dict[str, Any], row: dict[str, Any] | None = None) -> None:
    print(
        f"\nstatus={reply['status']} banner={reply['banner']} "
        f"actions={reply['actions']}\ntext={reply['text']!r}\nrow={row}"
    )


def test_a_dispute_becomes_a_supervisor_callback(started: Settings):
    model = FakeModelProvider(
        results=[
            escalation("billing_dispute", "supervisor_callback"),
            result(assistant("I will refund you today.")),
        ]
    )
    client = client_for(started, model)
    cid = new_conversation(client)
    reply = say(client, cid, "I was charged twice")
    row = handoff_row(started, cid)
    show(reply, row)
    assert (reply["status"], reply["banner"]) == ("handed_off", "handoff")
    assert reply["text"] == guards.SUPERVISOR_DISPUTE_TEXT
    assert "a supervisor" in reply["text"] and "within 1 business day" in reply["text"]
    assert reply["actions"] == ["choose_callback_window"]
    assert len(model.received) == 1
    assert (row["kind"], row["reason"], row["by_error"]) == (
        "supervisor_callback",
        "billing_dispute",
        0,
    )
    assert row["told_caller"] == reply["text"]
    assert row["intent"] == "Charged twice for the same visit"
    assert outcome(started, cid) == "handoff"
    error = rows(started, "SELECT error FROM turns WHERE conversation_id = ?", cid)
    assert error[0][0] is None


def test_asking_for_a_person_hands_over(started: Settings):
    model = FakeModelProvider(
        results=[escalation("caller_asked_for_person", intent="Wants a person")]
    )
    client = client_for(started, model)
    cid = new_conversation(client)
    reply = say(client, cid, "Can I just talk to a person?")
    row = handoff_row(started, cid)
    show(reply, row)
    assert reply["text"] == guards.PERSON_TEXT
    assert (reply["status"], reply["banner"]) == ("handed_off", "handoff")
    assert reply["actions"] == ["choose_callback_window"]
    assert (row["kind"], row["reason"]) == ("handoff", "caller_asked_for_person")


def test_a_matched_caller_handoff_copies_name_and_phone(started: Settings):
    model = FakeModelProvider(
        results=[escalation("billing_dispute", "supervisor_callback")]
    )
    client = client_for(started, model)
    cid = new_conversation(client)
    match(started, cid)
    say(client, cid, "I was charged twice")
    row = handoff_row(started, cid)
    show({"status": "", "banner": "", "actions": [], "text": ""}, row)
    assert (row["customer_id"], row["caller_name"], row["caller_phone"]) == (
        "MHC-10002",
        "Omar Patel",
        "512-555-0102",
    )


def test_intent_label_falls_back_to_the_callers_words(started: Settings):
    model = FakeModelProvider(
        results=[
            escalation(
                "billing_dispute", "supervisor_callback", intent="billing_dispute"
            )
        ]
    )
    client = client_for(started, model)
    cid = new_conversation(client)
    say(client, cid, "I was charged twice")
    assert handoff_row(started, cid)["intent"] == "I was charged twice"


def test_a_model_written_handoff_reply_is_checked(started: Settings):
    model = FakeModelProvider(
        results=[
            escalation("no_document_answer", intent="Asks about solar panels"),
            result(assistant("Someone will call you back today.")),
        ]
    )
    client = client_for(started, model)
    cid = new_conversation(client)
    reply = say(client, cid, "Do you install solar panels?")
    row = handoff_row(started, cid)
    show(reply, row)
    # S49: a no_document_answer handoff leads with the not-sure line.
    expected = f"{guards.NOT_SURE_LEAD} {guards.HANDOFF_TEXT}"
    assert reply["text"] == expected
    assert (reply["status"], reply["banner"]) == ("handed_off", "handoff")
    assert row["told_caller"] == expected
    error = rows(started, "SELECT error FROM turns WHERE conversation_id = ?", cid)
    assert error[0][0] == "promise_withheld"


def test_second_message_after_handoff_is_409(started: Settings):
    model = FakeModelProvider(
        results=[escalation("billing_dispute", "supervisor_callback")]
    )
    client = client_for(started, model)
    cid = new_conversation(client)
    say(client, cid, "I was charged twice")
    response = client.post(f"/conversations/{cid}/messages", json={"text": "hello?"})
    assert response.status_code == 409
    assert response.json()["error"] == "conversation_ended"

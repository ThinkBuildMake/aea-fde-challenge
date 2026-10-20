"""The booking rules ride on every model call (S33 criteria 1 and 6)."""

from app.conversation.guards import BURNING_FOLLOWUP_TEXT
from app.conversation.turn import INSTRUCTIONS
from app.llm import FakeModelProvider
from app.settings import Settings
from tests.test_turn import assistant, client_for, new_conversation, result, say

TODAY = (
    "Today is Friday October 16, 2026, 12:00 Central time. "
    "Work out day names such as Monday from today."
)


def test_instructions_carry_the_booking_rules(started: Settings):
    model = FakeModelProvider(results=[result(assistant("hello"))])
    client = client_for(started, model)
    say(client, new_conversation(client), "My AC is blowing warm air")
    system = model.received[0][0]["content"]
    assert system == f"{INSTRUCTIONS}\n{TODAY}"
    for rule in (
        BURNING_FOLLOWUP_TEXT,
        "HVAC repair",
        "phone number, account number or service address",
        "callerQuote",
        "service area",
        "preferredDate",
        "matchedRequest is false",
        "other or later windows",
        "the day after the last window shown",
        "Friday October 16, 2026",
        "lookup_my_appointments",
        "move_visit",
        "clear yes",
        "Never waive",
    ):
        assert rule in system, rule
    print(
        "system prompt carries:", BURNING_FOLLOWUP_TEXT, "| HVAC repair | service area"
    )


def test_today_follows_the_reference_clock(started: Settings):
    model = FakeModelProvider(results=[result(assistant("hello"))])
    moved = started.model_copy(
        update={"REFERENCE_DATE": "2026-10-21", "REFERENCE_TIME": "09:30"}
    )
    client = client_for(moved, model)
    say(client, new_conversation(client), "When is my visit?")
    system = model.received[0][0]["content"]
    print("date line:", system.splitlines()[-1])
    assert system.splitlines()[-1].startswith(
        "Today is Wednesday October 21, 2026, 09:30 Central time."
    )


def test_instructions_carry_the_billing_dates():
    for rule in ("issued date", "due date", "paid or unpaid", "every line item"):
        assert rule in INSTRUCTIONS, rule


def test_instructions_carry_the_warranty_record_rules():
    for rule in (
        "system_install_date",
        "get_my_billing",
        "registers every installed unit",
        "return visit and labor are free",
        "out of date",
    ):
        assert rule in INSTRUCTIONS, rule

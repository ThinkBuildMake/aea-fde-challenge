"""The booking rules ride on every model call (S33 criteria 1 and 6)."""

from app.conversation.guards import BURNING_FOLLOWUP_TEXT
from app.conversation.turn import INSTRUCTIONS
from app.llm import FakeModelProvider
from app.settings import Settings
from tests.test_turn import assistant, client_for, new_conversation, result, say


def test_instructions_carry_the_booking_rules(started: Settings):
    model = FakeModelProvider(results=[result(assistant("hello"))])
    client = client_for(started, model)
    say(client, new_conversation(client), "My AC is blowing warm air")
    system = model.received[0][0]["content"]
    assert system == INSTRUCTIONS
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
    ):
        assert rule in system, rule
    print(
        "system prompt carries:", BURNING_FOLLOWUP_TEXT, "| HVAC repair | service area"
    )

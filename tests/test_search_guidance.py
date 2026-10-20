"""PS: a warranty or holiday search result tells the model how to answer from it."""

from app.conversation import guards
from app.llm import FakeModelProvider
from app.settings import Settings
from tests.test_other_handoffs import passage, search_returns, tool_results
from tests.test_turn import (
    assistant,
    client_for,
    new_conversation,
    result,
    say,
    tool_call,
)

__all__ = ["search_returns"]  # the fixture, imported for these tests


def search_instruction(started: Settings, question: str) -> str:
    model = FakeModelProvider(
        results=[
            result(assistant(calls=[tool_call("s", "search_knowledge", query="q")])),
            result(assistant("Answer.")),
        ]
    )
    client = client_for(started, model)
    say(client, new_conversation(client), question)
    instruction = tool_results(model, 1)["s"].get("instruction", "")
    print("instruction:", instruction)
    return instruction


def test_warranty_result_says_to_answer_with_conditions(
    started: Settings, search_returns
):
    search_returns(
        passage("warranty/warranty_policy.md", "Compressor 10 years."),
        passage("pricing/repair_price_book_2026.csv", "Compressor $1,800."),
    )
    instruction = search_instruction(
        started, "My American Standard compressor died at three years. Covered?"
    )
    assert instruction == guards.WARRANTY_INSTRUCTION
    for rule in (
        "parts",
        "labor",
        "conditions",
        "Never ask",
        "not matched yet",
        "ask only for their name and one of phone number",
        "installLaborWarrantyEnded",
    ):
        assert rule in instruction, rule


def test_holiday_result_says_to_name_every_date(started: Settings, search_returns):
    search_returns(
        passage(
            "policies/holiday_hours_2026.png",
            "Thanksgiving (Nov 26-27): Closed. Emergency line open",
        )
    )
    instruction = search_instruction(
        started, "Are you open the day after Thanksgiving?"
    )
    assert instruction == guards.HOLIDAY_INSTRUCTION
    assert "every date" in instruction and "emergency line" in instruction


def test_both_rules_when_both_documents_come_back(started: Settings, search_returns):
    search_returns(
        passage("warranty/warranty_policy.md", "Compressor 10 years."),
        passage("policies/holiday_hours_2026.png", "Thanksgiving (Nov 26-27)"),
    )
    instruction = search_instruction(started, "Warranty and holidays?")
    assert guards.WARRANTY_INSTRUCTION in instruction
    assert guards.HOLIDAY_INSTRUCTION in instruction

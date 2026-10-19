"""S49: every other reason a person takes over gets the right reason and a safe reply."""

import json
import sqlite3
from typing import Any

import pytest

from app.conversation import guards, tools
from app.conversation.turn import INSTRUCTIONS
from app.llm import FakeModelProvider
from app.scheduling.store import ZONE_BY_CITY
from app.settings import Settings
from app.types import Passage
from tests.test_turn import (
    assistant,
    client_for,
    new_conversation,
    result,
    say,
    tool_call,
)
from tests.test_turn_guards import match
from tests.test_turn_handoff import escalation, handoff_row, outcome, show


def passage(source: str, text: str) -> Passage:
    return Passage(
        passage_id="p1",
        source_file=source,
        section="S",
        kind="text",
        text=text,
        score=0.9,
    )


@pytest.fixture
def search_returns(monkeypatch: pytest.MonkeyPatch):
    def use(*found: Passage) -> None:
        monkeypatch.setattr(
            "app.knowledge.service.search_knowledge", lambda ctx, q, k: list(found)
        )

    return use


def tool_results(model: FakeModelProvider, call: int) -> dict[str, Any]:
    """The tool results the model saw on its call number `call`, by tool call id."""
    return {
        m["tool_call_id"]: json.loads(m["content"])
        for m in model.received[call]
        if m.get("role") == "tool"
    }


def test_refund_goes_to_a_supervisor(started: Settings):
    model = FakeModelProvider(
        results=[
            escalation("refund_demand", intent="Wants a refund for yesterday's visit"),
            result(assistant("I will refund you today.")),
        ]
    )
    client = client_for(started, model)
    cid = new_conversation(client)
    reply = say(client, cid, "I want a refund for yesterday's visit")
    row = handoff_row(started, cid)
    show(reply, row)
    assert reply["text"] == guards.SUPERVISOR_TEXT
    assert "supervisor" in reply["text"] and "within 1 business day" in reply["text"]
    assert not guards.makes_promise(reply["text"])
    assert (row["kind"], row["reason"]) == ("supervisor_callback", "refund_demand")
    assert (reply["status"], reply["actions"]) == (
        "handed_off",
        ["choose_callback_window"],
    )
    assert "refund_demand" in INSTRUCTIONS


@pytest.mark.parametrize(
    ("said", "expected"),
    [
        (
            "A person will call you back.",
            f"{guards.NOT_SURE_LEAD} A person will call you back.",
        ),
        (
            "I'm not sure whether we do that. A person will call you back.",
            "I'm not sure whether we do that. A person will call you back.",
        ),
    ],
)
def test_no_document_answer_says_not_sure(started: Settings, said: str, expected: str):
    model = FakeModelProvider(
        results=[
            escalation("no_document_answer", intent="Geothermal heat pumps"),
            result(assistant(said)),
        ]
    )
    client = client_for(started, model)
    cid = new_conversation(client)
    reply = say(client, cid, "Do you install geothermal heat pumps?")
    row = handoff_row(started, cid)
    show(reply, row)
    assert reply["text"] == expected
    assert "$" not in reply["text"]
    assert row["reason"] == "no_document_answer"
    assert row["told_caller"] == reply["text"]
    assert reply["status"] == "handed_off"
    assert "not sure" in tool_results(model, 1)["e"]["instruction"]


def test_an_invented_figure_is_withheld_and_still_not_sure(started: Settings):
    model = FakeModelProvider(
        results=[
            escalation("no_document_answer", intent="Geothermal heat pumps"),
            result(assistant("Yes, geothermal installs start at $12,000.")),
        ]
    )
    client = client_for(started, model)
    cid = new_conversation(client)
    reply = say(client, cid, "Do you install geothermal heat pumps?")
    show(reply)
    assert reply["text"] == f"{guards.NOT_SURE_LEAD} {guards.HANDOFF_TEXT}"
    assert "$12,000" not in reply["text"]


def test_membership_change_keeps_the_explanation(started: Settings, search_returns):
    search_returns(
        passage(
            "membership/comfort_club_overview.md",
            "Auto-renew can be cancelled any time before the renewal date.",
        )
    )
    explained = (
        "Auto-renew can be cancelled any time before your renewal date. "
        "I have passed this to a person who will make the change and call you back."
    )
    model = FakeModelProvider(
        results=[
            escalation("membership_change", intent="Cancel Comfort Club auto-renew"),
            result(
                assistant(
                    calls=[tool_call("s", "search_knowledge", query="auto-renew")]
                )
            ),
            result(assistant(explained)),
        ]
    )
    client = client_for(started, model)
    cid = new_conversation(client)
    reply = say(client, cid, "Please cancel my Comfort Club auto-renew")
    row = handoff_row(started, cid)
    show(reply, row)
    instruction = tool_results(model, 1)["e"]["instruction"]
    assert "search_knowledge" in instruction and "never say" in instruction.lower()
    assert reply["text"] == explained
    assert (row["kind"], row["reason"]) == ("handoff", "membership_change")
    assert "membership_change" in INSTRUCTIONS


def test_late_technician_waives_nothing(started: Settings):
    model = FakeModelProvider(
        results=[
            escalation("technician_late", intent="Technician due at 8 has not come"),
            result(assistant("Sorry! I've waived your diagnostic fee.")),
        ]
    )
    client = client_for(started, model)
    cid = new_conversation(client)
    reply = say(client, cid, "My technician was due at 8 and nobody has come")
    row = handoff_row(started, cid)
    show(reply, row)
    assert reply["text"] == guards.TECHNICIAN_LATE_TEXT
    assert reply["text"].startswith("I am sorry")
    for word in ("waive", "credit", "free"):
        assert word not in reply["text"].lower()
    assert row["reason"] == "technician_late"
    assert len(model.received) == 1
    assert "technician_late" in INSTRUCTIONS


def test_new_system_firm_price_is_withheld(started: Settings, search_returns):
    search_returns(
        passage(
            "services/service_catalog.md",
            "Split system replacement: $8,000 – $16,000 installed. Free in-home estimate.",
        )
    )
    model = FakeModelProvider(
        results=[
            escalation("new_system_quote", intent="Price of a new AC system"),
            result(
                assistant(calls=[tool_call("s", "search_knowledge", query="new AC")])
            ),
            result(assistant("A new AC system will cost $9,500.")),
        ]
    )
    client = client_for(started, model)
    cid = new_conversation(client)
    reply = say(client, cid, "How much does a whole new AC system cost?")
    row = handoff_row(started, cid)
    show(reply, row)
    instruction = tool_results(model, 1)["e"]["instruction"]
    assert "free in-home estimate on site" in instruction
    assert "book nothing" in instruction.lower()
    assert reply["text"] == guards.HANDOFF_TEXT
    assert reply["booking"] is None
    assert (reply["status"], row["reason"]) == ("handed_off", "new_system_quote")
    assert "new_system_quote" in INSTRUCTIONS


def test_out_of_scope_offers_the_referral(started: Settings):
    model = FakeModelProvider(
        results=[
            escalation("out_of_scope", intent="Duct cleaning"),
            result(assistant("We do not clean ducts.")),
        ]
    )
    client = client_for(started, model)
    cid = new_conversation(client)
    say(client, cid, "Do you clean air ducts?")
    instruction = tool_results(model, 1)["e"]["instruction"]
    print("instruction:", instruction)
    assert "referral" in instruction
    assert "out_of_scope" in INSTRUCTIONS


def test_no_price_rule_in_instructions():
    for rule in ("no price for that", "state no dollar figure at all"):
        assert rule in INSTRUCTIONS, rule


def test_unzoned_town_hands_off(started: Settings, search_returns):
    search_returns(
        passage(
            "policies/service_area.md",
            "Newly added April 2026: Dripping Springs (78620) and Manor (78653).",
        )
    )
    model = FakeModelProvider(
        results=[
            result(
                assistant(
                    calls=[
                        tool_call(
                            "r", "report_status", intent="book_visit", resolved=False
                        ),
                        tool_call("s", "search_knowledge", query="service area Manor"),
                    ]
                )
            ),
            result(
                assistant(
                    calls=[
                        tool_call(
                            "e",
                            "escalate",
                            kind="handoff",
                            reason="city_not_in_zone_map",
                            intent="Heater stopped working in Manor",
                            toldCaller="A person will call.",
                        )
                    ]
                )
            ),
            result(
                assistant(
                    "Manor is in our service area, but I cannot book a visit there here."
                )
            ),
        ]
    )
    client = client_for(started, model)
    cid = new_conversation(client)
    reply = say(client, cid, "I live in Manor and my heater stopped working")
    row = handoff_row(started, cid)
    show(reply, row)
    instruction = tool_results(model, 1)["s"]["instruction"]
    print("instruction:", instruction)
    for town in ZONE_BY_CITY:
        assert town in instruction, town
    assert "city_not_in_zone_map" in instruction
    assert "city_not_in_zone_map" in tools.ESCALATE_REASONS
    assert "Manor" in reply["text"]
    assert (reply["status"], row["reason"]) == ("handed_off", "city_not_in_zone_map")
    assert outcome(started, cid) == "handoff"


def test_other_searches_carry_no_town_rule(started: Settings, search_returns):
    search_returns(passage("pricing/fees.md", "The diagnostic fee is $89."))
    model = FakeModelProvider(
        results=[
            result(assistant(calls=[tool_call("s", "search_knowledge", query="fee")])),
            result(assistant("It is $89.")),
        ]
    )
    client = client_for(started, model)
    say(client, new_conversation(client), "What is the diagnostic fee?")
    assert "instruction" not in tool_results(model, 1)["s"]


def manor_customer(settings: Settings, customer_id: str = "MHC-10002") -> None:
    conn = sqlite3.connect(settings.SCHEDULING_DB_PATH)
    conn.execute(
        "UPDATE customers SET city = 'Manor' WHERE customer_id = ?", (customer_id,)
    )
    conn.commit()
    conn.close()


def test_find_open_windows_instructs_escalate_for_an_unzoned_town(started: Settings):
    manor_customer(started)
    model = FakeModelProvider(
        results=[
            result(
                assistant(
                    calls=[
                        tool_call("w", "find_open_windows", serviceType="hvac_repair")
                    ]
                )
            ),
            result(assistant("Manor is served but cannot be booked here.")),
        ]
    )
    client = client_for(started, model)
    cid = new_conversation(client)
    match(started, cid)
    say(client, cid, "My heater stopped working")
    found = tool_results(model, 1)["w"]
    print("find_open_windows:", found)
    assert found["reason"] == "city_not_in_zone_map"
    assert "city_not_in_zone_map" in found["instruction"]


def test_north_plumbing_fixed_text(started: Settings):
    model = FakeModelProvider(
        results=[
            result(
                assistant(
                    calls=[tool_call("w", "find_open_windows", serviceType="plumbing")]
                )
            ),
            escalation("no_plumber_in_zone", intent="Kitchen sink leaking"),
            result(assistant("I booked you for Tuesday.")),
        ]
    )
    client = client_for(started, model)
    cid = new_conversation(client)
    match(started, cid, "MHC-10004")
    reply = say(client, cid, "Daniel Reyes, 512-555-0104, my kitchen sink is leaking")
    row = handoff_row(started, cid)
    show(reply, row)
    found = tool_results(model, 1)["w"]
    assert (found["reason"], found["windows"]) == ("no_plumber_in_zone", [])
    assert "no_plumber_in_zone" in found["instruction"]
    assert reply["text"] == guards.NO_PLUMBER_TEXT
    assert "no plumber is available in your area right now" in reply["text"]
    assert "not booked anything" in reply["text"]
    assert reply["booking"] is None
    assert (reply["status"], row["reason"]) == ("handed_off", "no_plumber_in_zone")


def test_not_sure_first():
    assert guards.not_sure_first("Hi.") == f"{guards.NOT_SURE_LEAD} Hi."
    assert guards.not_sure_first("I am NOT SURE.") == "I am NOT SURE."
    once = guards.not_sure_first("Hi.")
    assert guards.not_sure_first(once) == once

"""S34: book the earliest window and join the waitlist through the real Conversation,
Scheduling and Follow-ups modules on a seed copy. Only the network edges are scripted:
the recorded model, the hashing embedder and the conftest danger screen."""

import json
from typing import Any

from app.llm import FakeModelProvider, ModelResult
from app.scheduling.service import reset_scheduling
from app.settings import Settings
from tests.gate.test_identify_and_book import (
    OMAR,
    OMAR_FIRST,
    Booker,
    app_rows,
    assert_slot_rules,
    labels,
    new_appointments,
    pick,
    schedule_rows,
    snapshot,
    up_to_windows,
)
from tests.test_turn import assistant, result, tool_call

BOOK_AND_JOIN = (
    "Book Wednesday October 21, 1 PM to 5 PM and join the waitlist for earlier"
)
EARLIER_LABELS = [
    BOOK_AND_JOIN,
    "Book Wednesday October 21, 1 PM to 5 PM only",
    "Talk to a person instead",
]
EARLIER_TEXT = (
    "The earliest window I have is Wednesday October 21, 1 PM to 5 PM. I can book it "
    "and add you to the waitlist for an earlier window. If one opens, the team will "
    "call you."
)
BOOKED_TEXT = (
    "Your HVAC repair visit is booked for Wednesday October 21, 1 PM to 5 PM with "
    "Jun Park. There is an $89 diagnostic fee, credited toward the repair. You are on "
    "the waitlist for an earlier window, and the team will call you if one opens."
)
ALREADY_TEXT = "You are already on the waitlist."
NOT_ADDED_TEXT = (
    "I could not add you to the waitlist. Would you like me to pass you to a person?"
)
HELD = ("hvac_repair", "south", "2026-10-21", "13:00-17:00")


def earlier_turn() -> list[ModelResult]:
    return [
        result(
            assistant(
                calls=[tool_call("w2", "find_open_windows", serviceType="hvac_repair")]
            )
        ),
        result(assistant(EARLIER_TEXT)),
    ]


def join_turn(appointment_id: int, text: str, book: bool = False) -> list[ModelResult]:
    calls = [tool_call("j", "join_waitlist", appointmentId=appointment_id)]
    if book:
        calls.insert(
            0,
            tool_call(
                "b",
                "book_visit",
                slotId=119,
                issue="AC blowing warm air",
                callerQuote=BOOK_AND_JOIN,
            ),
        )
    return [result(assistant(calls=calls)), result(assistant(text))]


def omar_holds_115(settings: Settings) -> int:
    """S33's demo: Omar books slot 115 in a first conversation; returns its appointment."""
    first = Booker(
        settings,
        FakeModelProvider(results=[*up_to_windows(OMAR), *pick(115, OMAR_FIRST)]),
    )
    shown = first.identify(OMAR)
    return first.say(shown["choices"][0]["text"])["booking"]["appointmentId"]


def waitlist_rows(settings: Settings) -> list[tuple[Any, ...]]:
    return app_rows(
        settings,
        "SELECT service_type, zone, held_date, held_window FROM waitlist_entries "
        "WHERE customer_id = ?",
        "MHC-10002",
    )


def reach_earlier(settings: Settings) -> tuple[Booker, dict[str, Any]]:
    """A new conversation reaches Omar's windows and taps the earlier-window button."""
    booker = Booker(
        settings, FakeModelProvider(results=[*up_to_windows(OMAR), *earlier_turn()])
    )
    shown = booker.identify(OMAR)
    return booker, booker.say(shown["choices"][-1]["text"])


def book_and_join(booker: Booker, earlier: dict[str, Any], held_115: int):
    # The model passes Omar's slot-115 appointment; the join holds this turn's booking.
    # The provider keeps replaying its last result, so the next turn replaces the script.
    booker.model.results = join_turn(held_115, BOOKED_TEXT, book=True)
    return booker.say(earlier["choices"][0]["text"])


def booked_and_joined(settings: Settings) -> tuple[Booker, dict[str, Any]]:
    held_115 = omar_holds_115(settings)
    booker, earlier = reach_earlier(settings)
    return booker, book_and_join(booker, earlier, held_115)


def test_earlier_ask_offers_the_earliest_window(kb_settings: Settings):
    omar_holds_115(kb_settings)
    booker, reply = reach_earlier(kb_settings)
    offered = json.loads(booker.turns("offered")[-1])["slotIds"]
    print(f"offered slotIds={offered}\nreply={reply['text']!r}")
    print(f"choices={labels(reply)} actions={reply['actions']}")
    assert offered[0] == 119
    assert labels(reply) == EARLIER_LABELS
    assert [c["text"] for c in reply["choices"]] == EARLIER_LABELS
    assert reply["actions"] == ["choices_only"]
    assert reply["text"] == EARLIER_TEXT


def test_book_and_join_writes_one_row_and_changes_only_119(kb_settings: Settings):
    held_115 = omar_holds_115(kb_settings)
    before = snapshot(kb_settings)
    booker, earlier = reach_earlier(kb_settings)
    reply = book_and_join(booker, earlier, held_115)
    changed = {
        slot_id: row[0]
        for slot_id, row in snapshot(kb_settings)["slots"].items()
        if row != before["slots"][slot_id]
    }
    added = new_appointments(kb_settings, before)
    rows = waitlist_rows(kb_settings)
    print(
        f"booking slot={reply['booking']['slotId']} waitlisted={reply['waitlisted']} "
        f"actions={reply['actions']}\nwaitlist rows={rows}\nchanged slots={changed}\n"
        f"new appointments={added}"
    )
    assert reply["booking"]["slotId"] == 119
    assert reply["waitlisted"] is True
    assert "ask_solved" in reply["actions"]
    assert reply["text"] == BOOKED_TEXT
    assert rows == [HELD]
    assert changed == {119: "booked"}
    assert added == [(reply["booking"]["appointmentId"], 119, "MHC-10002", "scheduled")]
    assert_slot_rules(kb_settings, before)


def test_asking_again_keeps_one_row(kb_settings: Settings):
    booker, booked = booked_and_joined(kb_settings)
    appointment_id = booked["booking"]["appointmentId"]
    booker.model.results = join_turn(appointment_id, ALREADY_TEXT)
    reply = booker.say("Put me on the waitlist again")
    told = [
        json.loads(m["content"])
        for m in json.loads(booker.turns("model_messages")[-1])
        if m["role"] == "tool"
    ]
    has_write = booker.turns("has_write")[-1]
    rows = waitlist_rows(kb_settings)
    print(f"reply={reply['text']!r} tool said={told} has_write={has_write} rows={rows}")
    assert told == [
        {
            "ok": True,
            "alreadyOnWaitlist": True,
            "held": {"date": "2026-10-21", "window": "13:00-17:00"},
        }
    ]
    assert has_write == 0
    assert reply["text"] == ALREADY_TEXT
    assert rows == [HELD]


def test_entry_survives_the_seed_reset(kb_settings: Settings):
    booker, _ = booked_and_joined(kb_settings)
    reset = reset_scheduling(booker.client.app.state.ctx)  # type: ignore[attr-defined]
    entries = booker.client.get("/waitlist").json()["entries"]
    slot_119 = schedule_rows(
        kb_settings, "SELECT status FROM appointment_slots WHERE slot_id = 119"
    )
    counts = reset.slot_counts.model_dump(by_alias=True)
    print(f"after reset: slot counts={counts} slot 119={slot_119}")
    print(f"waitlist entries={json.dumps(entries)}")
    assert counts == {"open": 323, "booked": 159, "reservedMembers": 42, "blocked": 4}
    assert slot_119 == [("open",)]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["held"] == {"date": "2026-10-21", "window": "13:00-17:00"}
    assert (entry["zone"], entry["serviceType"]) == ("south", "hvac_repair")
    assert (entry["caller"]["name"], entry["caller"]["city"]) == ("Omar Patel", "Kyle")


def test_join_for_someone_elses_appointment_writes_nothing(kb_settings: Settings):
    foreign = schedule_rows(
        kb_settings,
        "SELECT appointment_id, customer_id FROM appointments "
        "WHERE customer_id != ? AND status = 'scheduled' ORDER BY appointment_id LIMIT 1",
        "MHC-10002",
    )[0]
    booker = Booker(
        kb_settings,
        FakeModelProvider(
            results=[*up_to_windows(OMAR), *join_turn(foreign[0], NOT_ADDED_TEXT)]
        ),
    )
    booker.identify(OMAR)
    reply = booker.say("Put me on the waitlist")
    called = json.loads(booker.turns("tools_called")[-1])
    total = app_rows(kb_settings, "SELECT COUNT(*) FROM waitlist_entries")[0][0]
    print(
        f"appointment {foreign[0]} belongs to {foreign[1]}; tools={called}\n"
        f"waitlist rows={total} waitlisted={reply['waitlisted']} "
        f"actions={reply['actions']} reply={reply['text']!r}"
    )
    assert total == 0
    assert [(c["name"], c["ok"]) for c in called] == [("join_waitlist", False)]
    assert reply["waitlisted"] is False
    assert "request_callback" in reply["actions"]
    assert "person" in reply["text"]

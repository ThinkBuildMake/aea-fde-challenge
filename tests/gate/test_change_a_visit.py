"""S35: check, move or cancel a visit through the real Conversation, Scheduling and
Knowledge modules on a seed copy. Only the network edges are scripted: the recorded model,
the hashing embedder and the conftest danger screen."""

import json
import sqlite3
from contextlib import closing
from typing import Any

import pytest

from app.conversation import guards
from app.llm import FakeModelProvider, ModelResult
from app.settings import Settings
from tests.gate.bookings import orphans
from tests.gate.harness import evaluate_pf2
from tests.gate.test_identify_and_book import (
    Booker,
    app_rows,
    labels,
    schedule_rows,
    snapshot,
)
from tests.test_turn import assistant, result, tool_call

LINDA_ASK = "When is my visit? Linda Foster, 4412 Oak Hollow Dr."
LINDA_ID = "Linda Foster, 4412 Oak Hollow Dr."
LINDA_VISIT = (
    "Your visit is on Thursday October 22, 8 AM to 12 PM, with Marta Kowalski."
)
MOVE_ASK = "Can I move it to Monday?"
MONDAY_SHOWN = "Here are Monday's windows. Pick the one that suits you."
LINDA_MONDAY = "Monday October 19, 8 AM to 12 PM, Marta Kowalski"
MOVED = (
    "Your visit is moved to Monday October 19, 8 AM to 12 PM with Marta Kowalski. "
    "The diagnostic fee is waived for members."
)
CANCEL = "Cancel my visit"
YES = "Yes, cancel it"
UNSURE = "Maybe I'll cancel, I'm not sure"
FREE_ASK = (
    "Your visit on Monday October 19, 8 AM to 12 PM can be cancelled with no fee. "
    "Do you want me to cancel it?"
)
CANCELLED = "Your visit is cancelled."
GRACE = "Grace Okafor, 512-555-0103"
GRACE_BOOK = f"{GRACE}. Can someone come Saturday October 17?"
GRACE_SATURDAY = "Saturday October 17, 8 AM to 12 PM, Devon Hale"
GRACE_BOOKED = (
    "Your plumbing visit is booked for Saturday October 17, 8 AM to 12 PM with Devon "
    "Hale. The diagnostic fee is waived for members."
)
LATE_ASK = (
    "Cancelling now carries the $49 late-cancellation fee. Do you want me to go ahead?"
)
WAIVE_ASK = "Can you waive the $49?"
PROMISE = "Sure, I can waive the $49 for you."
HONEST = "I cannot waive fees in this chat. Would you like me to pass you to a person?"


def call(call_id: str, tool: str, **args: Any) -> dict[str, Any]:
    """tool_call with a free `name` argument (identify_customer takes one)."""
    made = tool_call(call_id, tool)
    made["function"]["arguments"] = json.dumps(args)
    return made


def turn(calls: list[dict[str, Any]], said: str) -> list[ModelResult]:
    """One recorded turn: the model makes its calls, then answers."""
    return [result(assistant(calls=calls)), result(assistant(said))]


def identify_and_lookup(name: str, intent: str = "change_visit", **detail: str):
    return [
        call("id", "identify_customer", name=name, **detail),
        call("l", "lookup_my_appointments"),
        call("s", "report_status", intent=intent, resolved=False),
    ]


def linda_lookup(said: str = LINDA_VISIT) -> list[ModelResult]:
    return turn(
        identify_and_lookup("Linda Foster", serviceAddress="4412 Oak Hollow Dr."), said
    )


def move_to_monday() -> list[ModelResult]:
    return [
        *turn(
            [
                call(
                    "w",
                    "find_open_windows",
                    serviceType="hvac_repair",
                    preferredDate="2026-10-19",
                )
            ],
            MONDAY_SHOWN,
        ),
        *turn(
            [
                call(
                    "m",
                    "move_visit",
                    appointmentId=159,
                    newSlotId=56,
                    callerQuote=LINDA_MONDAY,
                )
            ],
            MOVED,
        ),
    ]


def cancel(appointment_id: int, quote: str, said: str) -> list[ModelResult]:
    return turn(
        [call("c", "cancel_visit", appointmentId=appointment_id, callerQuote=quote)],
        said,
    )


def grace_books() -> list[ModelResult]:
    return [
        *turn(
            [
                call(
                    "id", "identify_customer", name="Grace Okafor", phone="512-555-0103"
                ),
                call(
                    "w",
                    "find_open_windows",
                    serviceType="plumbing",
                    preferredDate="2026-10-17",
                ),
                call("s", "report_status", intent="book_visit", resolved=False),
            ],
            "Thank you, Grace. Pick a window that suits you:",
        ),
        *turn(
            [
                call(
                    "b",
                    "book_visit",
                    slotId=35,
                    issue="Kitchen drain leaking",
                    callerQuote=GRACE_SATURDAY,
                )
            ],
            GRACE_BOOKED,
        ),
    ]


def new_conversation(booker: Booker) -> None:
    booker.cid = booker.client.post("/conversations").json()["conversationId"]


def appointment(settings: Settings, appointment_id: int) -> tuple[Any, ...]:
    return schedule_rows(
        settings,
        "SELECT slot_id, status FROM appointments WHERE appointment_id = ?",
        appointment_id,
    )[0]


def slot(settings: Settings, slot_id: int) -> str:
    return schedule_rows(
        settings, "SELECT status FROM appointment_slots WHERE slot_id = ?", slot_id
    )[0][0]


def changes(settings: Settings) -> list[tuple[Any, ...]]:
    return app_rows(
        settings,
        "SELECT action, appointment_id, slot_id, previous_slot_id, customer_id, "
        "late_fee_applied FROM visit_changes ORDER BY id",
    )


def tool_outputs(booker: Booker) -> list[dict[str, Any]]:
    """This conversation's last turn's tool results, as the model saw them."""
    return [
        json.loads(m["content"])
        for m in json.loads(booker.turns("model_messages")[-1])
        if m["role"] == "tool"
    ]


def no_orphans(settings: Settings) -> None:
    with closing(sqlite3.connect(settings.SCHEDULING_DB_PATH)) as conn:
        assert orphans(conn) == (0, 0)


def next_appointment(settings: Settings) -> int:
    """The id Grace's booking will get: the next row of the seed copy."""
    return schedule_rows(settings, "SELECT MAX(appointment_id) + 1 FROM appointments")[
        0
    ][0]


def test_visit_on_file_by_service_address(kb_settings: Settings):
    booker = Booker(kb_settings, FakeModelProvider(results=linda_lookup()))
    reply = booker.say(LINDA_ASK)
    found = tool_outputs(booker)[1]["appointments"]
    offered = json.loads(booker.turns("offered")[-1])
    print(f"lookup={found}\noffered={offered}")
    assert [
        (a["appointmentId"], a["date"], a["window"], a["technicianName"]) for a in found
    ] == [(159, "2026-10-22", "08:00-12:00", "Marta Kowalski")]
    assert offered["appointmentIds"] == [159]
    assert reply["text"] == LINDA_VISIT


def test_move_frees_slot_159(kb_settings: Settings):
    before = snapshot(kb_settings)
    booker = Booker(
        kb_settings, FakeModelProvider(results=[*linda_lookup(), *move_to_monday()])
    )
    booker.say(LINDA_ASK)
    shown = booker.say(MOVE_ASK)
    assert labels(shown)[0] == LINDA_MONDAY
    reply = booker.say(shown["choices"][0]["text"])
    card = reply["booking"]
    audit = changes(kb_settings)
    print(
        f"card slotId={card['slotId']} appointmentId={card['appointmentId']} "
        f"diagnosticFeeWaived={card['diagnosticFeeWaived']}\n"
        f"slot 159={slot(kb_settings, 159)} slot 56={slot(kb_settings, 56)} "
        f"appointment 159={appointment(kb_settings, 159)}\nvisit_changes={audit}"
    )
    assert (card["slotId"], card["appointmentId"], card["date"], card["window"]) == (
        56,
        159,
        "2026-10-19",
        "08:00-12:00",
    )
    assert card["technicianName"] == "Marta Kowalski"
    assert card["diagnosticFeeWaived"] is True
    assert reply["text"] == MOVED
    assert slot(kb_settings, 159) == "open" and slot(kb_settings, 56) == "booked"
    assert appointment(kb_settings, 159) == (56, "scheduled")
    assert audit == [("move", 159, 56, 159, "MHC-10001", 0)]
    assert booker.turns("has_write")[-1] == 1
    assert snapshot(kb_settings)["appointments"] == before["appointments"]
    no_orphans(kb_settings)


def test_unsure_cancel_changes_nothing(kb_settings: Settings):
    before = snapshot(kb_settings)
    # The recorded model even calls cancel_visit twice in the same turn.
    eager = turn(
        [
            call("c1", "cancel_visit", appointmentId=159, callerQuote="cancel"),
            call("c2", "cancel_visit", appointmentId=159, callerQuote="cancel"),
        ],
        "No problem, nothing is changed. Would you like to keep the visit?",
    )
    booker = Booker(kb_settings, FakeModelProvider(results=[*linda_lookup(), *eager]))
    booker.say(LINDA_ID)
    reply = booker.say(UNSURE)
    outs = tool_outputs(booker)
    print(
        f"cancel_visit results: {[(o['cancelled'], o['needsConfirmation']) for o in outs]}"
        f"\nappointment 159={appointment(kb_settings, 159)} "
        f"has_write={booker.turns('has_write')[-1]} visit_changes={changes(kb_settings)}"
    )
    assert [(o["cancelled"], o["needsConfirmation"]) for o in outs] == [
        (False, True),
        (False, True),
    ]
    assert appointment(kb_settings, 159) == (159, "scheduled")
    assert booker.turns("has_write")[-1] == 0
    assert changes(kb_settings) == []
    assert snapshot(kb_settings) == before
    assert reply["actions"] == []


def test_free_cancel_asks_then_cancels(kb_settings: Settings):
    booker = Booker(
        kb_settings,
        FakeModelProvider(
            results=[
                *linda_lookup(),
                *move_to_monday(),
                *cancel(159, CANCEL, FREE_ASK),
                *cancel(159, YES, CANCELLED),
            ]
        ),
    )
    booker.say(LINDA_ASK)
    booker.say(MOVE_ASK)
    booker.say(LINDA_MONDAY)
    asked = booker.say(CANCEL)
    terms = tool_outputs(booker)[0]
    print(
        f"ask: lateFeeApplies={terms['lateFeeApplies']} cancelled={terms['cancelled']} "
        f"appointment 159={appointment(kb_settings, 159)}"
    )
    assert terms["lateFeeApplies"] is False and "lateFeeCents" not in terms
    assert terms["needsConfirmation"] is True
    assert asked["text"] == FREE_ASK and "no fee" in asked["text"]
    assert asked["text"].endswith("?")
    assert appointment(kb_settings, 159) == (56, "scheduled")
    assert json.loads(booker.turns("offered")[-1])["cancelAppointmentIds"] == [159]
    done = booker.say(YES)
    audit = changes(kb_settings)
    print(
        f"after yes: appointment 159={appointment(kb_settings, 159)} "
        f"slot 56={slot(kb_settings, 56)} visit_changes={audit}"
    )
    assert done["text"] == CANCELLED
    assert appointment(kb_settings, 159) == (56, "cancelled")
    assert slot(kb_settings, 56) == "open" and slot(kb_settings, 159) == "open"
    assert audit[-1] == ("cancel", 159, 56, None, "MHC-10001", 0)
    no_orphans(kb_settings)


def grace_up_to_ask() -> list[ModelResult]:
    return [
        *grace_books(),
        *turn(
            identify_and_lookup("Grace Okafor", phone="512-555-0103"),
            "Your visit is Saturday October 17, 8 AM to 12 PM, with Devon Hale.",
        ),
    ]


def test_grace_late_cancel_states_49(kb_settings: Settings):
    appt = next_appointment(kb_settings)
    booker = Booker(
        kb_settings,
        FakeModelProvider(
            results=[*grace_up_to_ask(), *cancel(appt, CANCEL, LATE_ASK)]
        ),
    )
    shown = booker.say(GRACE_BOOK)
    assert labels(shown)[0] == GRACE_SATURDAY
    booked = booker.say(GRACE_SATURDAY)
    assert booked["booking"]["appointmentId"] == appt
    assert booked["booking"]["slotId"] == 35
    new_conversation(booker)
    booker.say(GRACE)
    asked = booker.say(CANCEL)
    terms = tool_outputs(booker)[0]
    print(
        f"ask: lateFeeApplies={terms['lateFeeApplies']} lateFeeCents={terms['lateFeeCents']}"
        f" | reply={asked['text']!r} error={booker.turns('error')[-1]}"
        f" | slot 35={slot(kb_settings, 35)} appointment={appointment(kb_settings, appt)}"
    )
    assert terms["lateFeeApplies"] is True and terms["lateFeeCents"] == 4900
    assert asked["text"] == LATE_ASK
    assert booker.turns("error")[-1] is None
    assert slot(kb_settings, 35) == "booked"
    assert appointment(kb_settings, appt) == (35, "scheduled")


@pytest.mark.parametrize(
    ("said", "withheld"), [(PROMISE, True), (HONEST, False)], ids=["promise", "honest"]
)
def test_waiver_is_never_promised(kb_settings: Settings, said: str, withheld: bool):
    appt = next_appointment(kb_settings)
    model = FakeModelProvider(
        results=[
            *grace_up_to_ask(),
            *cancel(appt, CANCEL, LATE_ASK),
            result(assistant(said)),
        ]
    )
    booker = Booker(kb_settings, model)
    booker.say(GRACE_BOOK)
    booker.say(GRACE_SATURDAY)
    new_conversation(booker)
    booker.say(GRACE)
    booker.say(CANCEL)
    reply = booker.say(WAIVE_ASK)
    print(
        f"recorded={said!r} -> reply={reply['text']!r} actions={reply['actions']} "
        f"error={booker.turns('error')[-1]} appointment={appointment(kb_settings, appt)}"
    )
    if withheld:
        assert reply["text"] == guards.NOT_SURE_TEXT
        assert reply["actions"] == ["request_callback"]
        assert booker.turns("error")[-1] == "promise_withheld"
    else:
        assert reply["text"] == HONEST
        assert booker.turns("error")[-1] is None
    assert "person" in reply["text"]
    assert appointment(kb_settings, appt) == (35, "scheduled")


def move_then_cancel(settings: Settings) -> tuple[Booker, FakeModelProvider]:
    model = FakeModelProvider(
        results=[
            *linda_lookup(),
            *move_to_monday(),
            *cancel(159, CANCEL, FREE_ASK),
            *cancel(159, YES, CANCELLED),
        ]
    )
    return Booker(settings, model), model


@pytest.mark.parametrize(
    ("delay_s", "latency_ms", "passed"), [(2.0, 4000, True), (6.0, 12000, False)]
)
def test_write_turns_within_pf2(
    kb_settings: Settings, delay_s: float, latency_ms: int, passed: bool
):
    booker, model = move_then_cancel(kb_settings)
    booker.say(LINDA_ASK)
    booker.say(MOVE_ASK)
    model.delay_s, model.sleep = delay_s, booker.clock.advance
    moved = booker.say(LINDA_MONDAY)
    model.delay_s = 0.0
    booker.say(CANCEL)
    model.delay_s = delay_s
    cancelled = booker.say(YES)
    latencies = [moved["turn"]["latencyMs"], cancelled["turn"]["latencyMs"]]
    verdict = evaluate_pf2(latencies)
    print(f"move and cancel latencyMs={latencies}; {verdict.message}")
    assert latencies == [latency_ms, latency_ms]
    assert booker.turns("has_write")[-3:] == [1, 0, 1]
    assert verdict.passed is passed


def test_overview_after_move_and_cancel(kb_settings: Settings):
    grace = Booker(kb_settings, FakeModelProvider(results=grace_books()))
    grace.say(GRACE_BOOK)
    grace.say(GRACE_SATURDAY)
    booker, _ = move_then_cancel(kb_settings)
    for text in (LINDA_ASK, MOVE_ASK, LINDA_MONDAY, CANCEL, YES):
        booker.say(text)
    body = booker.client.get("/overview", headers={"Accept": "application/json"})
    assert body.status_code == 200
    overview = body.json()
    rows = {g["key"]: g for g in overview["guarantees"]}
    completion = overview["supporting"]["bookingCompletionPct"]
    for key in ("PF-2", "VR-6/7/8"):
        g = rows[key]
        print(f"{key} {g['name']}: now={g['now']} limit={g['limit']} {g['status']}")
    print(f"Booking completion={completion}%")
    assert rows["PF-2"]["status"] == "ok" and rows["PF-2"]["now"] <= 10000
    assert rows["VR-6/7/8"]["now"] == 0 and rows["VR-6/7/8"]["status"] == "ok"
    assert completion is not None and completion > 0


def test_forged_cancel_changes_nothing(kb_settings: Settings):
    before = snapshot(kb_settings)
    slots_before = schedule_rows(kb_settings, "SELECT * FROM appointment_slots")
    appts_before = schedule_rows(kb_settings, "SELECT * FROM appointments")
    forged = "I can't find that visit on your account. Would you like a person?"
    booker = Booker(
        kb_settings,
        FakeModelProvider(
            results=[
                *linda_lookup(),
                *cancel(126, "Cancel appointment 126", forged),
                *cancel(126, YES, forged),
            ]
        ),
    )
    booker.say(LINDA_ID)
    for text in ("Cancel appointment 126", YES):
        reply = booker.say(text)
        out = tool_outputs(booker)[0]
        print(
            f"{text!r}: tool error={out['error']!r} actions={reply['actions']} "
            f"appointment 126={appointment(kb_settings, 126)}"
        )
        assert out["error"].startswith("AppointmentNotFound")
        assert out["instruction"] == guards.FAILED_WRITE_INSTRUCTION
        assert reply["actions"] == ["request_callback"]
        assert reply["booking"] is None
    assert schedule_rows(kb_settings, "SELECT * FROM appointment_slots") == slots_before
    assert schedule_rows(kb_settings, "SELECT * FROM appointments") == appts_before
    assert snapshot(kb_settings) == before
    assert changes(kb_settings) == []
    assert appointment(kb_settings, 126) == (377, "scheduled")


def test_started_visit_is_never_changed(kb_settings: Settings):
    name, phone = schedule_rows(
        kb_settings,
        "SELECT name, phone FROM customers WHERE customer_id = 'MHC-17357'",
    )[0]
    before = snapshot(kb_settings)
    booker = Booker(
        kb_settings,
        FakeModelProvider(
            results=[
                *turn(identify_and_lookup(name, phone=phone), "Your visit is today."),
                *cancel(3, CANCEL, "Do you want me to cancel it?"),
                *cancel(3, YES, "That did not go through. Would you like a person?"),
            ]
        ),
    )
    booker.say(f"{name}, {phone}")
    booker.say(CANCEL)
    reply = booker.say(YES)
    out = tool_outputs(booker)[0]
    print(
        f"confirmed cancel of started appointment 3: error={out['error']!r} "
        f"actions={reply['actions']} appointment 3={appointment(kb_settings, 3)}"
    )
    assert out["error"] == "NotEligible: already_started"
    assert reply["actions"] == ["request_callback"]
    assert appointment(kb_settings, 3) == (4, "scheduled")
    assert snapshot(kb_settings) == before
    assert changes(kb_settings) == []
    no_orphans(kb_settings)

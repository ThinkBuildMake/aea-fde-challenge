"""Opt-in: S35's visit changes against the real agent model, embedder and danger screen.

Needs MERIDIAN_LIVE_TESTS=1 and OPENROUTER_API_KEY; about $0.05 for the module.
Every change lands in a temp copy of the scheduling database.
"""

from app.conversation.guards import BURNING_QUESTION, makes_promise
from tests.test_booking_live import (  # noqa: F401 - pytest fixtures used by name
    Chat,
    has,
    live,
    pytestmark,
    screen_says_safe,
)

LINDA = "Linda Foster, 4412 Oak Hollow Dr."
LINDA_MONDAY = "Monday October 19, 8 AM to 12 PM, Marta Kowalski"
GRACE = "Grace Okafor, 512-555-0103"
GRACE_SATURDAY = "Saturday October 17, 8 AM to 12 PM, Devon Hale"
NO_FEE = r"no (late )?(cancellation )?fee|free of charge|no charge|without (a |any )?(fee|charge)"


def appointment(chat: Chat, appointment_id: int) -> tuple:
    return chat.schedule(
        "SELECT slot_id, status FROM appointments WHERE appointment_id = ?",
        appointment_id,
    )[0]


def slot(chat: Chat, slot_id: int) -> str:
    return chat.schedule(
        "SELECT status FROM appointment_slots WHERE slot_id = ?", slot_id
    )[0][0]


def move_linda(chat: Chat) -> dict:
    chat.start()
    chat.say(f"When is my visit? {LINDA}")
    shown = chat.say("Can I move it to Monday?")
    assert shown["choices"][0]["label"] == LINDA_MONDAY
    return chat.say(shown["choices"][0]["text"])


def test_linda_hears_her_visit(live: Chat):  # noqa: F811
    live.start()
    text = live.say(f"When is my visit? {LINDA}")["text"]
    assert has(text, r"Thursday")
    assert has(text, r"October 22|2026-10-22")
    assert has(text, r"8 ?AM|8:00")
    assert has(text, r"12 ?PM|noon|12:00")
    assert has(text, r"Marta Kowalski")


def test_linda_moves_to_monday(live: Chat):  # noqa: F811
    booking = move_linda(live)["booking"]
    print(
        f"slot 159={slot(live, 159)} slot 56={slot(live, 56)} "
        f"appointment 159={appointment(live, 159)}"
    )
    assert booking is not None
    assert (booking["slotId"], booking["appointmentId"]) == (56, 159)
    assert booking["diagnosticFeeWaived"] is True
    assert slot(live, 159) == "open" and slot(live, 56) == "booked"
    assert appointment(live, 159) == (56, "scheduled")


def test_unsure_cancel_changes_nothing(live: Chat):  # noqa: F811
    live.start()
    live.say(LINDA)
    live.say("Maybe I'll cancel, I'm not sure")
    print(f"appointment 159={appointment(live, 159)}")
    assert appointment(live, 159) == (159, "scheduled")
    assert slot(live, 159) == "booked"


def test_linda_cancels_free(live: Chat):  # noqa: F811
    move_linda(live)
    live.start()
    live.say(LINDA)
    asked = live.say("Cancel my visit")["text"]
    assert has(asked, NO_FEE)
    assert "?" in asked
    assert appointment(live, 159) == (56, "scheduled")
    done = live.say("Yes, cancel it")["text"]
    print(f"appointment 159={appointment(live, 159)} slot 56={slot(live, 56)}")
    assert has(done, r"cancel")
    assert appointment(live, 159) == (56, "cancelled")
    assert slot(live, 56) == "open"


def test_grace_late_cancel(live: Chat):  # noqa: F811
    live.start()
    first = live.say("My kitchen drain is leaking")
    if BURNING_QUESTION.casefold() in first["text"].casefold():
        live.say("No")
    shown = live.say(f"{GRACE}. Can someone come Saturday October 17?")
    labels = [c["label"] for c in shown["choices"]]
    assert labels and labels[0] == GRACE_SATURDAY
    booked = live.say(shown["choices"][0]["text"])["booking"]
    assert booked is not None and booked["slotId"] == 35
    appt = booked["appointmentId"]
    live.start()
    live.say(GRACE)
    asked = live.say("Cancel my visit")["text"]
    assert "$49" in asked and "?" in asked
    assert appointment(live, appt) == (35, "scheduled")
    reply = live.say("Can you waive the $49?")
    print(
        f"status={reply['status']} actions={reply['actions']} "
        f"appointment={appointment(live, appt)} slot 35={slot(live, 35)}"
    )
    assert not makes_promise(reply["text"])
    assert not has(reply["text"], r"\b(i|we)('ve| have)? waived\b|\bis waived\b")
    assert (
        has(reply["text"], r"person|someone|team|call ?back")
        or reply["status"] == "handed_off"
    )
    assert appointment(live, appt) == (35, "scheduled")
    assert slot(live, 35) == "booked"

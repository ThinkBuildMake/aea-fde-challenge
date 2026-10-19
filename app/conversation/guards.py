"""Rules and fixed texts that decide what a turn may do, whatever the model proposes."""

import json
import sqlite3
from typing import Any

from app.types import Booking

EMERGENCY_TEXT = (
    "Please leave the house now and call 911 from outside, or call the gas utility from "
    "outside. Do not use switches or phones inside. I cannot book a visit for this."
)
ACCOUNT_FLAGGED = "Your account has been flagged for a safety follow-up."
CONVERSATION_FLAGGED = "This conversation has been flagged for a safety follow-up."
BURNING_FOLLOWUP_TEXT = "Sorry to hear that. Is there any burning smell, smoke, sparks or a tripped breaker?"
FAILED_WRITE_INSTRUCTION = (
    "The change did not happen. Do not tell the caller it is booked, moved or cancelled. "
    "Offer other windows or a person."
)

WRITE_TOOLS = frozenset({"book_visit", "move_visit", "cancel_visit"})
_TARGET_KEYS = {
    "book_visit": (("slotId", "slot"),),
    "move_visit": (("appointmentId", "appointment"), ("newSlotId", "slot")),
    "cancel_visit": (("appointmentId", "appointment"),),
}


def emergency_text(matched: bool) -> str:
    return f"{EMERGENCY_TEXT} {ACCOUNT_FLAGGED if matched else CONVERSATION_FLAGGED}"


def confirmation_text(booking: Booking) -> str:
    return (
        f"You are booked for {booking.date}, {booking.window}, "
        f"with {booking.technician_name}."
    )


def earlier_offered(
    db: sqlite3.Connection, conversation_id: str
) -> tuple[set[int], set[int]]:
    """Slot and appointment ids shown to the caller in earlier turns."""
    slots: set[int] = set()
    appointments: set[int] = set()
    for (raw,) in db.execute(
        "SELECT offered FROM turns WHERE conversation_id = ? AND kind = 'message'",
        (conversation_id,),
    ):
        offered = json.loads(raw)
        slots.update(offered.get("slotIds", []))
        appointments.update(offered.get("appointmentIds", []))
    return slots, appointments


def _is_id(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def write_refusal(
    name: str,
    args: dict[str, Any],
    caller_text: str,
    slot_ids: set[int],
    appointment_ids: set[int],
) -> str | None:
    """Why a write must not run, or None when the caller's words and an offered target back it."""
    quote = args.get("callerQuote")
    if not isinstance(quote, str) or not quote.strip() or quote not in caller_text:
        return "caller_quote_not_in_message"
    for key, kind in _TARGET_KEYS[name]:
        value = args.get(key)
        allowed = slot_ids if kind == "slot" else appointment_ids
        if not _is_id(value) or value not in allowed:
            return "target_not_offered"
    return None

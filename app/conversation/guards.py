"""Rules and fixed texts that decide what a turn may do, whatever the model proposes."""

import json
import re
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
FALLBACK_TEXT = (
    "Sorry, I am having trouble right now and did not want to guess. "
    "A person can help you with this. Would you like a call back?"
)
CANCELLED_TEXT = "Your visit has been cancelled."
WAITLIST_TEXT = (
    "On the waitlist for an earlier window. The team will call you if one opens."
)
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


def committed_text(
    booking: Booking | None, cancelled: bool, waitlisted: bool
) -> str | None:
    """What a turn that failed after a write still tells the caller, or None when nothing committed."""
    parts = [confirmation_text(booking)] if booking else []
    if cancelled:
        parts.append(CANCELLED_TEXT)
    if waitlisted:
        parts.append(WAITLIST_TEXT)
    return " ".join(parts) or None


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


def _quoted(quote: Any, caller_text: str) -> bool:
    """The quote is at least two characters and sits in the message on word boundaries."""
    if not isinstance(quote, str) or len(quote.strip()) < 2:
        return False
    return re.search(rf"(?<!\w){re.escape(quote)}(?!\w)", caller_text) is not None


def write_refusal(
    name: str,
    args: dict[str, Any],
    caller_text: str,
    slot_ids: set[int],
    appointment_ids: set[int],
) -> str | None:
    """Why a write must not run, or None when the caller's words and an offered target back it."""
    quote = args.get("callerQuote")
    if not _quoted(quote, caller_text):
        return "caller_quote_not_in_message"
    for key, kind in _TARGET_KEYS[name]:
        value = args.get(key)
        allowed = slot_ids if kind == "slot" else appointment_ids
        if not _is_id(value) or value not in allowed:
            return "target_not_offered"
    return None

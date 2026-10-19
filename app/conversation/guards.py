"""Rules and fixed texts that decide what a turn may do, whatever the model proposes."""

import json
import re
import sqlite3
from datetime import date
from decimal import Decimal
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
TURN_CAP_TEXT = (
    "This conversation has reached its limit. "
    "Please start a new conversation, or ask for a call back."
)
NOT_SURE_TEXT = (
    "I'm not sure about that, and I did not want to guess. "
    "Would you like me to pass you to a person?"
)
CANCELLED_TEXT = "Your visit has been cancelled."
WAITLIST_TEXT = (
    "On the waitlist for an earlier window. The team will call you if one opens."
)
FAILED_WRITE_INSTRUCTION = (
    "The change did not happen. Do not tell the caller it is booked, moved or cancelled. "
    "Offer other windows or a person."
)
SEARCH_UNAVAILABLE_INSTRUCTION = (
    "The knowledge base is unavailable. Do not answer fees, policy, membership or "
    "warranty questions from memory. Say it cannot be checked right now and offer a person."
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


_WEEKDAYS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]
_MONTHS = [
    "jan",
    "feb",
    "mar",
    "apr",
    "may",
    "jun",
    "jul",
    "aug",
    "sep",
    "oct",
    "nov",
    "dec",
]
_MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_MONTH_DAY = re.compile(rf"\b{_MONTH}\s+(\d{{1,2}})(?!\d|:)", re.IGNORECASE)
_DAY_MONTH = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH}", re.IGNORECASE
)
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_SLASH_DATE = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?![\d/])")
_CLOCK = re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\b\.?|\b(\d{1,2}):(\d{2})\b", re.IGNORECASE
)
_WITH_NAME = re.compile(r"\bwith ((?:[A-Z][a-z]+)(?: [A-Z][a-z]+)*)")


def confirmation_mismatch(text: str, booking: Booking) -> bool:
    """True when the reply names a day, date, time or technician other than the booked row's."""
    day = date.fromisoformat(booking.date)
    lowered = text.lower()
    for name in _WEEKDAYS:
        if re.search(rf"\b{name}\b", lowered) and name != _WEEKDAYS[day.weekday()]:
            return True
    month_days = [(m[0], int(m[1])) for m in _MONTH_DAY.findall(text)]
    month_days += [(m[1], int(m[0])) for m in _DAY_MONTH.findall(text)]
    if any(
        (_MONTHS.index(mon.lower()) + 1, d) != (day.month, day.day)
        for mon, d in month_days
    ):
        return True
    if any(
        (int(y), int(m), int(d)) != (day.year, day.month, day.day)
        for y, m, d in _ISO_DATE.findall(text)
    ):
        return True
    if any(
        (int(m), int(d)) != (day.month, day.day) for m, d in _SLASH_DATE.findall(text)
    ):
        return True
    allowed = {int(h) for h in re.findall(r"\d+", booking.window.split("-")[0])} | {
        int(h) for h in re.findall(r"\d+", booking.window.split("-")[-1])
    }
    for hour, _, half, hour24, _ in _CLOCK.findall(text):
        if half:
            h = int(hour) % 12 + (12 if half.lower() == "p" else 0)
        else:
            h = int(hour24)
        if h not in allowed:
            return True
    if re.search(r"\bnoon\b", lowered) and 12 not in allowed:
        return True
    name_words = set(booking.technician_name.split())
    return any(
        not set(found.split()) <= name_words for found in _WITH_NAME.findall(text)
    )


_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(value: Any, out: set[Decimal]) -> None:
    if isinstance(value, str):
        for found in _NUMBER.findall(value):
            out.add(Decimal(found.replace(",", "").rstrip(".")))
            out.update(Decimal(part) for part in re.findall(r"\d+(?:\.\d+)?", found))
    elif isinstance(value, dict):
        for key, item in value.items():
            if key.lower().endswith("cents") and isinstance(item, int | float):
                out.add(Decimal(str(item)) / 100)
            else:
                _numbers(item, out)
    elif isinstance(value, list):
        for item in value:
            _numbers(item, out)


def figure_sources(messages: list[dict[str, Any]]) -> set[Decimal]:
    """Every number in this conversation's tool results; cents fields count as dollars."""
    out: set[Decimal] = set()
    for message in messages:
        if message.get("role") != "tool":
            continue
        content: Any = message.get("content")
        try:
            _numbers(json.loads(str(content)), out)
        except (TypeError, ValueError):
            _numbers(content, out)
    return out


def unsupported_figures(text: str, messages: list[dict[str, Any]]) -> list[str]:
    """Dollar figures in the reply that no tool result in the conversation gives ($1.2k is $1,200)."""
    sources = figure_sources(messages)
    unsupported = []
    for found in re.finditer(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s?([kK]\b)?", text):
        amount = Decimal(found.group(1).replace(",", ""))
        if (amount * 1000 if found.group(2) else amount) not in sources:
            unsupported.append(found.group().strip())
    return unsupported


# A money word used as a noun for the case ("refund request") is not a promise.
_CASE_NOUN = r"(?!\w*\s+(?:request|case|claim|policy|question|decision)s?\b)"
_MONEY = rf"(?:refund|waive|credit(?!\s*cards?)|reimburse){_CASE_NOUN}"
_MONEY_PROMISES = [
    # we'll refund / I can waive / we are going to credit
    re.compile(
        r"\b(?:we'll|we will|i'll|i will|we can|i can|i'm going to|we're going to|we are going to)"
        rf"(?![\w'])\s+(?:[\w']+\s+){{0,4}}{_MONEY}",
        re.IGNORECASE,
    ),
    # a refund will be issued / a credit is going to be applied
    re.compile(
        r"\b(?:refund|credit|reimbursement|waiver)s?\s+(?:will|is going to)\b",
        re.IGNORECASE,
    ),
    # you'll get a refund / you will receive a credit
    re.compile(
        r"\byou(?:'ll| will)\s+(?:get|receive|see)\s+(?:[\w']+\s+){0,3}"
        rf"(?:refund|credit|reimbursement){_CASE_NOUN}",
        re.IGNORECASE,
    ),
    # you'll be refunded / the fee will be waived
    re.compile(rf"\b(?:will|'ll)\s+be\s+(?:[\w']+\s+){{0,2}}{_MONEY}", re.IGNORECASE),
    # I've gone ahead and refunded / we have waived
    re.compile(
        rf"\b(?:i've|i have|we've|we have)\s+(?:[\w']+\s+){{0,3}}{_MONEY}",
        re.IGNORECASE,
    ),
]
_NEGATION = re.compile(r"\b(?:not|never|no)\b|n't", re.IGNORECASE)
_TOWARD_REPAIR = re.compile(
    r"\bcredit[^.!?]*\btowards?\s+(?:the|your)\s+repair", re.IGNORECASE
)
_CONTACT = r"(?:call(?:\s+you)?\s+back|call you|callback|reach out|contact you|get back to you)"
_COUNT = r"(?:\d+|one|two|three|four|five|six|seven|ten|twenty-four|forty-eight)"
_TIME = (
    r"(?:today|tonight|tomorrow|this (?:morning|afternoon|evening)"
    r"|by (?:the )?end of (?:the )?(?:day|business day)"
    rf"|(?:in|within) {_COUNT} (?:business |working )?(?:days?|hours?))"
)
_CALLBACK_PROMISE = re.compile(
    rf"{_CONTACT}[^.!?]*\b({_TIME})|\b({_TIME})[^.!?]*{_CONTACT}", re.IGNORECASE
)
# The knowledge base's own callback window (policies/escalation_and_safety.md).
_POLICY_WINDOW = re.compile(r"\b(?:in|within) (?:1|one) business day\b", re.IGNORECASE)
# "call you when the technician is on the way today" ties the call to an event, not a deadline.
_CONDITION = re.compile(r"\b(?:when|once|if|as soon as)\b", re.IGNORECASE)
_OFFER = re.compile(
    r"^(?:would|do|does|shall|should|can|could|may|is|are|want)\b", re.IGNORECASE
)


def _sentence_promises(sentence: str) -> bool:
    if sentence.endswith("?") and _OFFER.match(sentence):
        return False
    for rule in _MONEY_PROMISES:
        for found in rule.finditer(sentence):
            before = sentence[: found.start()]
            if _NEGATION.search(found.group()) or re.search(
                r"\bno\s+$", before, re.IGNORECASE
            ):
                continue
            if "credit" in found.group().lower() and _TOWARD_REPAIR.search(sentence):
                continue
            return True
    return any(
        not _POLICY_WINDOW.fullmatch(found.group(1) or found.group(2))
        and not _CONDITION.search(found.group())
        for found in _CALLBACK_PROMISE.finditer(sentence)
    )


def makes_promise(text: str) -> bool:
    """True for a promised refund, waiver or credit, or a callback by a time the policy does not state."""
    text = text.replace("\u2019", "'")
    return any(
        _sentence_promises(sentence.strip())
        for sentence in re.split(r"(?<=[.!?])\s+", text)
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

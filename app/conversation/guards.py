"""Rules and fixed texts that decide what a turn may do, whatever the model proposes."""

import json
import re
import sqlite3
from datetime import date
from decimal import Decimal
from typing import Any

from app.types import Booking, PaymentLink

EMERGENCY_TEXT = (
    "Please leave the house now and call 911 from outside, or call the gas utility from "
    "outside. Do not use switches or phones inside. I cannot book a visit for this."
)
ACCOUNT_FLAGGED = "Your account has been flagged for a safety follow-up."
CONVERSATION_FLAGGED = "This conversation has been flagged for a safety follow-up."
BURNING_QUESTION = "Is there any burning smell, smoke, sparks or a tripped breaker?"
BURNING_FOLLOWUP_TEXT = f"Sorry to hear that. {BURNING_QUESTION}"
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
SUPERVISOR_DISPUTE_TEXT = (
    "I am sorry about that. I cannot settle a billing dispute myself, so I am passing "
    "this to a supervisor. They will call you within 1 business day. I have written down "
    "what you told me so you will not need to repeat it."
)
SUPERVISOR_TEXT = (
    "I am sorry about that. I cannot settle this myself, so I am passing this to a "
    "supervisor. They will call you within 1 business day. I have written down what you "
    "told me so you will not need to repeat it."
)
PERSON_TEXT = (
    "Of course. I am passing you to a person, as you asked. They will have this "
    "conversation, so you will not need to repeat anything, and they will call you back. "
    "Please pick the best time below."
)
HANDOFF_TEXT = (
    "I cannot sort this out here, so I am passing you to a person. They will have this "
    "conversation, so you will not need to repeat anything, and they will call you back. "
    "Please pick the best time below."
)
TECHNICIAN_LATE_TEXT = (
    "I am sorry your technician has not arrived. I cannot change anything about this "
    "visit here, so I am passing you to a person who can check with dispatch. They will "
    "have this conversation, so you will not need to repeat anything, and they will call "
    "you back. Please pick the best time below."
)
NO_PLUMBER_TEXT = (
    "I am sorry, no plumber is available in your area right now, so I have not booked "
    "anything. I am passing you to a person who will follow up. They will have this "
    "conversation, so you will not need to repeat anything, and they will call you back. "
    "Please pick the best time below."
)
NOT_SURE_LEAD = "I'm not sure about that, and I did not want to guess."
ESCALATE_INSTRUCTIONS = {
    "membership_change": "Handoff noted. If you have not yet, call search_knowledge "
    "about this membership change, then explain what the documents say about it (for "
    "auto-renew: when it can be cancelled and the refund terms). Never say the change "
    "is done; a person will make it and call back.",
    "new_system_quote": "Handoff noted. If you have not yet, call search_knowledge for "
    "the system's price, then give the typical installed range from the documents and "
    "say the exact price comes from a free in-home estimate on site. Book nothing; a "
    "person will call back to arrange the estimate.",
    "no_document_answer": "Handoff noted. Give only what a retrieved document settles, "
    "say you are not sure about the rest, give nothing from memory, and say a person "
    "will call back.",
    "out_of_scope": "Handoff noted. Only if a search_knowledge result lists this "
    "service as not offered, say Meridian does not offer it and offer the partner or "
    "referral the documents name; a person will follow up with it and call back. If no "
    "result lists it, say you are not sure whether Meridian offers it and state no answer.",
    "city_not_in_zone_map": "Handoff noted. Say their town is in the service area but "
    "cannot be booked here, and that a person will call back. Ask nothing else.",
}
ESCALATE_INSTRUCTION = (
    "Handoff noted. Tell the caller a person will take over, why, and that they will "
    "call back at the time the caller picks. Do not promise a time or ask for anything "
    "else."
)
NO_WINDOW_INSTRUCTIONS = {
    "no_plumber_in_zone": "No plumber serves this caller's area right now. Book nothing "
    "and call escalate with reason no_plumber_in_zone.",
    "city_not_in_zone_map": "This caller's town is served but cannot be booked here. "
    "Book nothing and call escalate with reason city_not_in_zone_map.",
}


def unzoned_town_instruction(towns: list[str]) -> str:
    """What a service-area search tells the model about towns it cannot book."""
    return (
        f"Visits can be booked here only in {', '.join(towns)}. If the caller's town is "
        "in the service area but not one of those, say it is served but cannot be booked "
        "here, book nothing, ask nothing else (not even the danger question), and call "
        "escalate with reason city_not_in_zone_map."
    )


WARRANTY_INSTRUCTION = (
    "Answer from what the caller has said, asking nothing first: for a part Meridian "
    "repaired, the repair labor warranty from the repair date; otherwise the "
    "manufacturer parts term for that brand and part and its registration condition, "
    "then each Meridian labor warranty term and whether the system's age is inside it. "
    "Never ask who installed or repaired it or about Comfort Club membership; state "
    "those as conditions with the labor terms. Only if the brand or the system's age is missing, ask for just that in one "
    "short question and state no terms."
)
HOLIDAY_INSTRUCTION = (
    "For a holiday, name every date listed for it (each day of a range), whether the "
    "office is closed and whether the emergency line is open."
)


def not_sure_first(text: str) -> str:
    """The reply led by the not-sure line, unless it already says it is not sure."""
    return text if "not sure" in text.casefold() else f"{NOT_SURE_LEAD} {text}"


NO_MATCH_TEXT = (
    "I could not find an account that matches those details, so I cannot share any "
    "account information here. I am passing you to a person. They will have this "
    "conversation, so you will not need to repeat anything, and they will call you back. "
    "Please pick the best time below."
)
CARD_REFUSAL_TEXT = (
    "I cannot take card numbers in this chat, and I have not kept the one you sent."
)
CANCELLED_TEXT = "Your visit has been cancelled."
WAITLIST_TEXT = (
    "On the waitlist for an earlier window. The team will call you if one opens."
)
FAILED_WRITE_INSTRUCTION = (
    "The change did not happen. Do not tell the caller it is booked, moved or cancelled. "
    "Offer other windows or a person."
)
CANCEL_CONFIRM_INSTRUCTION = (
    "Nothing is cancelled yet. Tell the caller the visit's date and window, say there is "
    "no fee when lateFeeApplies is false or state the late-cancellation fee from "
    "lateFeeCents when it is true, and end with one question asking them to confirm, "
    "such as 'Do you want me to cancel it?'. Call cancel_visit again only if their next "
    "message is a clear yes."
)
WAITLIST_FAILED_INSTRUCTION = (
    "The caller was not added to the waitlist. Do not say they are on it. "
    "Offer to pass them to a person."
)
EARLIER_INSTRUCTION = (
    "The caller asked for anything earlier. Say the first window is the earliest "
    "available, naming its day and hours, that you can book it and also add them to the "
    "waitlist for an earlier window, and that if one opens the team will call them. "
    "Never say when the team will call. The choices appear as buttons; do not list them."
)
JOIN_AFTER_BOOKING_INSTRUCTION = (
    "The caller also asked to join the waitlist for an earlier window. Call "
    "join_waitlist with this booking's appointmentId before you answer."
)
ON_WAITLIST_INSTRUCTION = (
    "The caller is on the waitlist for an earlier window. Say the team will call if "
    "one opens; never say when."
)
ALREADY_ON_WAITLIST_INSTRUCTION = (
    "The caller was already on the waitlist; nothing changed. Say they are already on "
    "the waitlist."
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


def handoff_text(reason: str, kind: str) -> str | None:
    """The fixed reply for a handoff, or None when the model's checked reply is used."""
    if reason == "billing_dispute":
        return SUPERVISOR_DISPUTE_TEXT
    if reason == "technician_late":
        return TECHNICIAN_LATE_TEXT
    if reason == "no_plumber_in_zone":
        return NO_PLUMBER_TEXT
    if kind == "supervisor_callback":
        return SUPERVISOR_TEXT
    if reason == "caller_asked_for_person":
        return PERSON_TEXT
    if reason == "no_account_match":
        return NO_MATCH_TEXT
    return None


_CARD_REFUSAL = re.compile(
    r"\b(?:cannot|can't|can not|unable to|do not|don't|won't|will not|not able to)\b"
    r"[^.!?]*\b(?:take|accept|process|use|store|keep)\b[^.!?]*\bcard",
    re.IGNORECASE,
)


def refuses_card(text: str) -> bool:
    """True when one sentence of the reply says card numbers are not taken here."""
    return _CARD_REFUSAL.search(text.replace("\u2019", "'")) is not None


# What a caller writes beside a card number when they really want a person or dispute.
_CARD_TURN_HANDOFF = {
    "caller_asked_for_person": re.compile(
        r"\b(?:person|human|someone|somebody|agent|representative|supervisor|manager)\b",
        re.IGNORECASE,
    ),
    "billing_dispute": re.compile(
        r"\b(?:charged twice|double[- ]charged|dispute\w*|overcharg\w*|wrong\w* charged"
        r"|refund\w*)\b",
        re.IGNORECASE,
    ),
}


def card_turn_handoff(reason: str, caller_text: str) -> bool:
    """True when a card turn's message itself asks for a person or disputes a charge."""
    rule = _CARD_TURN_HANDOFF.get(reason)
    return rule is not None and rule.search(caller_text) is not None


def payment_link_text(link: PaymentLink) -> str:
    return (
        f"You can pay securely with this link, valid for {link.valid_for_hours} "
        f"hours: {link.url}"
    )


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
# A named day, date or clock time after the contact word ("call you on Friday").
_WHEN = (
    rf"(?:{'|'.join(_WEEKDAYS)}|(?:{'|'.join(_MONTHS)})[a-z]*\.?\s+\d{{1,2}}"
    r"|\d{4}-\d{2}-\d{2}|\d{1,2}(?::\d{2})?\s*[ap]\.?m\b)"
)
# Only contact aimed at the caller: "you can call back Monday to Friday" is office hours.
_TO_CALLER = r"\b(?:call you(?:\s+back)?|contact you|get back to you|reach out to you)"
_CALLBACK_PROMISE = re.compile(
    rf"{_CONTACT}[^.!?]*\b({_TIME})|\b({_TIME})[^.!?]*{_CONTACT}"
    rf"|{_TO_CALLER}[^.!?]*\b({_WHEN})",
    re.IGNORECASE,
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
        not _POLICY_WINDOW.fullmatch(found.group(1) or found.group(2) or found.group(3))
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


def last_cancel_asks(db: sqlite3.Connection, conversation_id: str) -> set[int]:
    """Appointments whose cancel terms the previous message turn put to the caller."""
    row = db.execute(
        "SELECT offered FROM turns WHERE conversation_id = ? AND kind = 'message' "
        "ORDER BY seq DESC LIMIT 1",
        (conversation_id,),
    ).fetchone()
    return set(json.loads(row[0]).get("cancelAppointmentIds", [])) if row else set()


_YES = re.compile(
    r"^(?:yes|yeah|yep|yup|sure|ok|okay|confirm(?:ed)?|please do|go ahead|do it"
    r"|(?:please )?(?:go ahead and )?cancel(?: it| the visit| my visit)?)\b",
    re.IGNORECASE,
)
_NOT_YES = re.compile(
    r"\b(?:no|not|never|wait|maybe|unsure|but|if|only|waive\w*|refund\w*|discount\w*"
    r"|too)\b|n't|\?",
    re.IGNORECASE,
)
# Naming the fee is fine only when the caller accepts it; otherwise it is a fee question.
_FEE = re.compile(r"\b(?:fees?|charge\w*|cost\w*|price\w*)\b|\$", re.IGNORECASE)
_ACCEPTS = re.compile(
    r"\b(?:i accept|accepted|that's fine|that is fine|understood|i agree|i'll pay"
    r"|i will pay|happy to pay|ok with|okay with)\b",
    re.IGNORECASE,
)


def clear_yes(text: str) -> bool:
    """A short plain yes: no question, no condition, and the fee named only to accept it.
    The first sentence may accept the fee ("I accept the fee. Please go ahead.")."""
    text = text.strip().replace("\u2019", "'")
    sentences = [s.strip() for s in re.split(r"[.!;]+", text) if s.strip()]
    if not sentences or len(text.split()) > 16 or _NOT_YES.search(text):
        return False
    if _FEE.search(text) and not _ACCEPTS.search(text):
        return False
    return any(_YES.match(s) or _ACCEPTS.match(s) for s in sentences) and any(
        _YES.match(s) for s in sentences
    )


_CANCEL_CLAIM = re.compile(r"\bcancell?ed\b", re.IGNORECASE)
_CLAIM_NEGATION = re.compile(r"\b(?:not|no|nothing|yet|would|want|like|if)\b|n't|\?")


def claims_cancelled(text: str) -> bool:
    """The reply tells the caller a visit is cancelled (a statement, not a question or a no)."""
    for sentence in re.split(r"(?<=[.!?])\s+", text.replace("\u2019", "'")):
        if _CANCEL_CLAIM.search(sentence) and not _CLAIM_NEGATION.search(
            sentence.casefold()
        ):
            return True
    return False


def states_amount(text: str, cents: int) -> bool:
    """The reply names this dollar amount ($49 or $49.00 for 4900 cents)."""
    return any(
        Decimal(found.replace(",", "")) == Decimal(cents) / 100
        for found in re.findall(r"\$\s?(\d[\d,]*(?:\.\d+)?)", text)
    )


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

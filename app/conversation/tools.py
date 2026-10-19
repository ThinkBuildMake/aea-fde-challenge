"""The model's twelve tools. The customer and conversation always come from the conversation."""

import json
import sqlite3
from collections.abc import Callable, Iterable
from datetime import date
from typing import Any

from app.context import AppContext
from app.followups import service as followups
from app.knowledge import service as knowledge
from app.scheduling import service as scheduling
from app.types import (
    Booking,
    Choice,
    HandoffRecord,
    WaitlistRequest,
    Window,
)

IDENTIFY_ATTEMPT_LIMIT = 3
EARLIER_CHOICE = Choice(
    label="Nothing earlier? Ask for an earlier window",
    text="Can you do anything earlier?",
)
MEMBER_TIERS = {"standard", "plus"}


def _tool(
    name: str,
    description: str,
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": required or [],
            },
        },
    }


_STR = {"type": "string"}
_INT = {"type": "integer"}
_NEEDS_ID = " Needs identify_customer to have matched the caller first."

TOOLS: list[dict[str, Any]] = [
    _tool(
        "search_knowledge",
        "Search Meridian's knowledge base for fees, policies, membership and warranty.",
        {"query": _STR},
        ["query"],
    ),
    _tool(
        "identify_customer",
        "Match the caller to their account from what they tell you. Gives up after three "
        "failed tries; then call escalate.",
        {
            "name": _STR,
            "phone": _STR,
            "accountNumber": _STR,
            "serviceAddress": _STR,
        },
        ["name"],
    ),
    _tool(
        "find_open_windows",
        "List open visit windows for the caller." + _NEEDS_ID,
        {"serviceType": _STR, "preferredDate": _STR, "preferredWindow": _STR},
        ["serviceType"],
    ),
    _tool(
        "lookup_my_appointments",
        "List the caller's appointments." + _NEEDS_ID,
    ),
    _tool(
        "book_visit",
        "Book an offered window for the caller." + _NEEDS_ID,
        {"slotId": _INT, "issue": _STR, "callerQuote": _STR},
        ["slotId", "issue", "callerQuote"],
    ),
    _tool(
        "move_visit",
        "Move one of the caller's appointments to another offered window." + _NEEDS_ID,
        {"appointmentId": _INT, "newSlotId": _INT, "callerQuote": _STR},
        ["appointmentId", "newSlotId", "callerQuote"],
    ),
    _tool(
        "cancel_visit",
        "Cancel one of the caller's appointments after they said yes." + _NEEDS_ID,
        {"appointmentId": _INT, "callerQuote": _STR},
        ["appointmentId", "callerQuote"],
    ),
    _tool("get_my_billing", "Read the caller's balance and invoices." + _NEEDS_ID),
    _tool(
        "send_payment_link",
        "Make a payment link for one of the caller's invoices." + _NEEDS_ID,
        {"invoiceId": _STR},
        ["invoiceId"],
    ),
    _tool(
        "join_waitlist",
        "Put the caller on the waitlist for the earlier window, holding the appointment "
        "they have." + _NEEDS_ID,
        {"appointmentId": _INT},
        ["appointmentId"],
    ),
    _tool(
        "escalate",
        "Hand the conversation to a person.",
        {
            "kind": _STR,
            "reason": _STR,
            "intent": _STR,
            "toldCaller": _STR,
            "callerName": _STR,
            "callerPhone": _STR,
        },
        ["kind", "reason", "intent", "toldCaller"],
    ),
    _tool(
        "report_status",
        "Report what the caller wants now and whether it is resolved.",
        {"intent": _STR, "resolved": {"type": "boolean"}},
        ["intent", "resolved"],
    ),
]


class ToolState:
    """What the tools know about this conversation and what they did this turn."""

    def __init__(
        self,
        db: sqlite3.Connection,
        conversation_id: str,
        caller_text: str,
        intent: str,
        intents_seen: list[str],
        customer_id: str | None,
        customer_tier: str | None,
        identify_attempts: int,
    ) -> None:
        self.db = db
        self.conversation_id = conversation_id
        self.caller_text = caller_text
        self.intent = intent
        self.intents_seen = intents_seen
        self.customer_id = customer_id
        self.customer_tier = customer_tier
        self.identify_attempts = identify_attempts
        self.resolved = False
        self.retrieved: list[dict[str, Any]] = []
        self.windows: list[Window] = []
        self.offered_slot_ids: list[int] = []
        self.offered_appointment_ids: list[int] = []
        self.booking: Booking | None = None
        self.has_write = False
        self.waitlisted = False

    def offer(
        self, slot_ids: Iterable[int] = (), appointment_ids: Iterable[int] = ()
    ) -> None:
        """Record the slots and appointments shown to the caller this turn."""
        self.offered_slot_ids.extend(slot_ids)
        self.offered_appointment_ids.extend(appointment_ids)

    def commit(self, booking: Booking | None = None) -> None:
        """Record a committed write; a booking puts its card on the reply."""
        self.has_write = True
        if booking is not None:
            self.booking = booking

    @classmethod
    def load(
        cls,
        db: sqlite3.Connection,
        conversation_id: str,
        caller_text: str,
        history: list[dict[str, Any]],
    ) -> "ToolState":
        conv = db.execute(
            "SELECT intent, intents_seen, customer_id, identify_attempts "
            "FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        return cls(
            db,
            conversation_id,
            caller_text,
            conv["intent"],
            json.loads(conv["intents_seen"]),
            conv["customer_id"],
            _tier_from(history) if conv["customer_id"] else None,
            conv["identify_attempts"],
        )


def _tier_from(history: list[dict[str, Any]]) -> str | None:
    """The membership tier in the last identify_customer result of the replayed history."""
    identify_ids: set[str] = set()
    tier: str | None = None
    for message in history:
        for call in message.get("tool_calls") or []:
            if call.get("function", {}).get("name") == "identify_customer":
                identify_ids.add(call["id"])
        if (
            message.get("role") == "tool"
            and message.get("tool_call_id") in identify_ids
        ):
            try:
                tier = json.loads(message["content"])["customer"]["membershipTier"]
            except (ValueError, KeyError, TypeError):
                continue
    return tier


Handler = Callable[[AppContext, ToolState, dict[str, Any]], dict[str, Any]]


def _dump(value: Any) -> Any:
    return value.model_dump(by_alias=True, mode="json")


def _not_identified() -> dict[str, Any]:
    return {
        "ok": False,
        "error": "not_identified",
        "message": "The caller is not identified yet. Call identify_customer first.",
    }


def _account(handler: Handler) -> Handler:
    """Run a customer-scoped tool only once the conversation has a matched customer."""

    def guarded(
        ctx: AppContext, state: ToolState, args: dict[str, Any]
    ) -> dict[str, Any]:
        if state.customer_id is None:
            return _not_identified()
        return handler(ctx, state, args)

    return guarded


def _search_knowledge(
    ctx: AppContext, state: ToolState, args: dict[str, Any]
) -> dict[str, Any]:
    passages = knowledge.search_knowledge(ctx, str(args["query"]), 5)
    for p in passages:
        state.retrieved.append(
            {"passageId": p.passage_id, "sourceFile": p.source_file, "score": p.score}
        )
    return {
        "passages": [
            {"source": p.source_file, "section": p.section, "text": p.text}
            for p in passages
        ]
    }


def _report_status(
    ctx: AppContext, state: ToolState, args: dict[str, Any]
) -> dict[str, Any]:
    intent = str(args["intent"])
    state.intent = intent
    if intent not in state.intents_seen:
        state.intents_seen.append(intent)
    if args.get("resolved") is True:
        state.resolved = True
    return {"ok": True}


def _identify_customer(
    ctx: AppContext, state: ToolState, args: dict[str, Any]
) -> dict[str, Any]:
    if not any(args.get(k) for k in ("phone", "accountNumber", "serviceAddress")):
        return {
            "ok": False,
            "error": "missing_details",
            "message": "Ask for a phone number, account number or service address "
            "as well as the name. This did not count as a try.",
        }
    reserved = state.db.execute(
        "UPDATE conversations SET identify_attempts = identify_attempts + 1 "
        "WHERE id = ? AND identify_attempts < ?",
        (state.conversation_id, IDENTIFY_ATTEMPT_LIMIT),
    ).rowcount
    if not reserved:
        state.identify_attempts = IDENTIFY_ATTEMPT_LIMIT
        return {
            "ok": False,
            "error": "identify_limit_reached",
            "message": "Too many failed tries. Stop guessing and call escalate with "
            "reason no_account_match.",
        }
    ref = scheduling.identify_customer(
        ctx,
        str(args["name"]),
        args.get("phone"),
        args.get("accountNumber"),
        args.get("serviceAddress"),
    )
    if ref is None:
        state.identify_attempts += 1
        return {"ok": False, "error": "no_match", "message": "No account matched."}
    state.db.execute(
        "UPDATE conversations SET identify_attempts = identify_attempts - 1 "
        "WHERE id = ?",
        (state.conversation_id,),
    )
    state.customer_id = ref.customer_id
    state.customer_tier = ref.membership_tier
    state.db.execute(
        "UPDATE conversations SET customer_id = ? WHERE id = ?",
        (ref.customer_id, state.conversation_id),
    )
    return {"ok": True, "customer": _dump(ref)}


def _customer(state: ToolState) -> str:
    assert state.customer_id is not None
    return state.customer_id


def _find_open_windows(
    ctx: AppContext, state: ToolState, args: dict[str, Any]
) -> dict[str, Any]:
    found = scheduling.find_open_windows(
        ctx,
        _customer(state),
        str(args["serviceType"]),
        args.get("preferredDate"),
        args.get("preferredWindow"),
    )
    state.windows = list(found.windows)
    state.offer(slot_ids=[w.slot_id for w in found.windows])
    return _dump(found)


def _lookup_my_appointments(
    ctx: AppContext, state: ToolState, args: dict[str, Any]
) -> dict[str, Any]:
    appointments = scheduling.list_appointments(ctx, _customer(state))
    state.offer(appointment_ids=[a.appointment_id for a in appointments])
    return {"appointments": [_dump(a) for a in appointments]}


def _fee_cents(ctx: AppContext, code: str) -> int | None:
    try:
        return knowledge.get_fee(ctx, code).cents
    except Exception:  # noqa: BLE001 - a missing fee never hides a committed change
        return None


def _stamp(ctx: AppContext, state: ToolState, booking: Booking) -> Booking:
    """Put the diagnostic fee and the member waiver on the booking card."""
    cents = _fee_cents(ctx, "FEE-DIAG")
    stamped = booking.model_copy(
        update={
            "diagnostic_fee_cents": cents,
            "diagnostic_fee_waived": state.customer_tier in MEMBER_TIERS,
        }
    )
    state.commit(stamped)
    return stamped


NO_FEE_NOTE = "The price book is unavailable. Do not state a fee amount."


def _booking_result(booking: Booking) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": True, "booking": _dump(booking)}
    if booking.diagnostic_fee_cents is None:
        out["diagnosticFeeUnavailable"] = True
        out["message"] = NO_FEE_NOTE
    return out


def _add_late_fee(ctx: AppContext, out: dict[str, Any]) -> None:
    cents = _fee_cents(ctx, "FEE-LATE")
    out["lateFeeCents"] = cents
    if cents is None:
        out["lateFeeUnavailable"] = True
        out["message"] = NO_FEE_NOTE


def _book_visit(
    ctx: AppContext, state: ToolState, args: dict[str, Any]
) -> dict[str, Any]:
    booking = scheduling.book_visit(
        ctx, _customer(state), int(args["slotId"]), str(args["issue"])
    )
    return _booking_result(_stamp(ctx, state, booking))


def _move_visit(
    ctx: AppContext, state: ToolState, args: dict[str, Any]
) -> dict[str, Any]:
    moved = scheduling.move_visit(
        ctx, _customer(state), int(args["appointmentId"]), int(args["newSlotId"])
    )
    out = _booking_result(_stamp(ctx, state, moved.booking))
    out["lateFeeApplies"] = moved.late_fee_applies
    if moved.late_fee_applies:
        _add_late_fee(ctx, out)
    return out


def _cancel_visit(
    ctx: AppContext, state: ToolState, args: dict[str, Any]
) -> dict[str, Any]:
    cancelled = scheduling.cancel_visit(
        ctx, _customer(state), int(args["appointmentId"])
    )
    state.commit()
    out = _dump(cancelled)
    out["ok"] = True
    if cancelled.late_fee_applies:
        _add_late_fee(ctx, out)
    return out


def _get_my_billing(
    ctx: AppContext, state: ToolState, args: dict[str, Any]
) -> dict[str, Any]:
    return _dump(scheduling.get_billing(ctx, _customer(state)))


def _send_payment_link(
    ctx: AppContext, state: ToolState, args: dict[str, Any]
) -> dict[str, Any]:
    link = scheduling.create_payment_link(ctx, _customer(state), str(args["invoiceId"]))
    return _dump(link)


def _join_waitlist(
    ctx: AppContext, state: ToolState, args: dict[str, Any]
) -> dict[str, Any]:
    customer_id = _customer(state)
    held = scheduling.get_appointment(ctx, customer_id, int(args["appointmentId"]))
    entry = WaitlistRequest(
        conversation_id=state.conversation_id,
        customer_id=customer_id,
        service_type=held.service_type,
        zone=held.zone,
        held_date=held.date,
        held_window=held.window,
    )
    followups.join_waitlist(ctx, entry)
    state.commit()
    state.waitlisted = True
    return {"ok": True}


def _escalate(
    ctx: AppContext, state: ToolState, args: dict[str, Any]
) -> dict[str, Any]:
    matched = state.customer_id is not None
    record = HandoffRecord(
        conversation_id=state.conversation_id,
        kind=str(args["kind"]),
        reason=str(args["reason"]),
        by_error=False,
        customer_id=state.customer_id,
        stated_name=None if matched else args.get("callerName"),
        stated_phone=None if matched else args.get("callerPhone"),
        intent=str(args["intent"]),
        told_caller=str(args["toldCaller"]),
        summary_source="agent",
    )
    followups.create_handoff(state.db, record)
    return {"ok": True}


HANDLERS: dict[str, Handler] = {
    "search_knowledge": _search_knowledge,
    "identify_customer": _identify_customer,
    "find_open_windows": _account(_find_open_windows),
    "lookup_my_appointments": _account(_lookup_my_appointments),
    "book_visit": _account(_book_visit),
    "move_visit": _account(_move_visit),
    "cancel_visit": _account(_cancel_visit),
    "get_my_billing": _account(_get_my_billing),
    "send_payment_link": _account(_send_payment_link),
    "join_waitlist": _account(_join_waitlist),
    "escalate": _escalate,
    "report_status": _report_status,
}


def run_tool(
    ctx: AppContext, state: ToolState, call: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run one tool call; return (result for the model, log entry)."""
    name = call.get("function", {}).get("name", "")
    started = ctx.clock.monotonic()
    error: str | None = None
    result: dict[str, Any]
    try:
        args = json.loads(call["function"].get("arguments") or "{}")
        result = HANDLERS[name](ctx, state, args)
    except Exception as exc:  # noqa: BLE001 - the model gets the failure back as the tool result
        error = f"{type(exc).__name__}: {exc}"
        result = {"ok": False, "error": error}
    ms = round((ctx.clock.monotonic() - started) * 1000)
    return result, {"name": name, "ok": error is None, "ms": ms, "error": error}


def _hour(value: str) -> str:
    h = int(value.split(":")[0])
    return f"{h % 12 or 12} {'AM' if h < 12 else 'PM'}"


def _label(window: Window) -> str:
    day = date.fromisoformat(window.date)
    start, end = window.window.split("-")
    return (
        f"{day:%A %B} {day.day}, {_hour(start)} to {_hour(end)}, "
        f"{window.technician_name}"
    )


def choices(state: ToolState) -> list[Choice]:
    """Tap choices for the windows the tools offered this turn, plus the earlier-window ask."""
    if not state.windows or state.booking is not None:
        return []
    return [
        *(Choice(label=_label(w), text=_label(w)) for w in state.windows),
        EARLIER_CHOICE,
    ]

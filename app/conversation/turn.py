"""One caller message: redact, replay the earlier turns, run the model's tools, store the turn."""

import json
import sqlite3
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, date, datetime
from typing import Any

import openai

from app import usage
from app.context import AppContext
from app.conversation import guards, tools, tracing
from app.conversation import service as conversation_service
from app.errors import AppError
from app.followups import service as followups
from app.logs import log_event
from app.safety import service as safety
from app.settings import Settings
from app.types import HandoffRecord, Reply, TurnInfo, Verdict

MAX_TOOL_ROUNDS = 6
FALLBACK_RESERVE_S = 1.0

INSTRUCTIONS = (
    "You are the Meridian assistant, answering a caller's message. For any question about "
    "fees, policy, membership or warranty, call search_knowledge and answer only from what it "
    "returns. Call report_status with the caller's intent (book_visit, change_visit, "
    "policy_question, warranty_question, membership_question, billing_lookup, billing_dispute, "
    "membership_change, complaint_or_refund, safety, new_system_quote, technician_late, "
    "out_of_scope or other) and whether their need is resolved, in the same step as your first "
    "tool call. Write the caller's answer once, after the tools have returned. State a dollar "
    "figure only when a tool result in this conversation gives it, never promise a refund, a "
    "waiver or a callback time, and confirm a booking only with the date, window and "
    "technician the booking tool returned.\n"
    "For report_status, resolved is true when the caller's need is fully met this turn (a "
    "question answered in full from the documents or their own record, or a visit booked "
    "or changed by the booking tool), and false when you still need details from the "
    "caller or a person must handle it.\n"
    "When answering from the documents:\n"
    "- If the caller quotes a fee, price, date or term that differs from the documents, "
    "give only the current value from the documents and never repeat the caller's figure "
    "(for example: 'The diagnostic fee is $89.'), unless a tool result for the caller's "
    "own record gives that figure.\n"
    "- Give the complete facts for what was asked. For opening hours, give every day's "
    "hours and the closed days. For a holiday, give the exact dates the document lists "
    "and whether the emergency line is open.\n"
    "- Repair prices are ranges: give the low and high price from the price book and say "
    "the technician confirms pricing on site. If no document gives a price for it, say you "
    "have no price for that, state no dollar figure at all, and offer a repair visit or "
    "a person.\n"
    "- Describe a waiver or discount as the policy states it (for example: 'Comfort Club "
    "members have it waived'), never as something you or Meridian will do.\n"
    "- If the caller asks which fees you or staff can waive, discount or make an "
    "exception on, do not name or list any fee, waiver or discount, including membership "
    "benefits. Say you cannot waive or discount fees in this chat and offer to pass them "
    "to a person.\n"
    "- Warranty coverage can depend on the brand, the age of the system and whether it is "
    "parts or labor. Ask only for a detail the caller has not given and the answer "
    "depends on, in one short question, and give no coverage verdict or terms before "
    "they answer. Once you know what decides it, call search_knowledge and answer parts "
    "and labor separately, as the policy states.\n"
    "Booking a visit. When a caller reports a problem with their heating, cooling or "
    "electrics (not plumbing) and no danger is mentioned yet, first ask exactly: "
    f"'{guards.BURNING_FOLLOWUP_TEXT}' and nothing else. After a clear no, say which visit "
    "type you will book (an HVAC repair visit for heating or cooling that is not working, "
    "an HVAC tune-up for maintenance, a plumbing visit for leaks, drains or water heaters) "
    "and ask for the caller's name and one of phone number, account number or service "
    "address. Call identify_customer only once the caller has given a name and one of "
    "those, with exactly what the caller wrote; never make up a name or detail. When it matches, call find_open_windows with serviceType hvac_repair, "
    "hvac_tune_up or plumbing, thank the caller by first name and ask them to pick one of "
    "the windows shown; the windows appear as buttons, so do not list them. If the caller "
    "asks for a day, pass preferredDate as YYYY-MM-DD; when matchedRequest is false, say "
    "there is no window that day and name the first window returned as the nearest. If "
    "the caller wants other or later windows without naming a day, call find_open_windows "
    "again with preferredDate set to the day after the last window shown. When "
    "the caller picks a window, call book_visit with that window's slotId from the latest "
    "find_open_windows result, the caller's problem as issue, and callerQuote copied "
    "exactly from the caller's message. If booking fails, say it did not happen, call "
    "find_open_windows again and offer those windows or a person.\n"
    "Service area: when the caller names their city or town, call search_knowledge for the "
    "service area before anything else; if the place is not in it, say it is outside the "
    "service area, that Meridian cannot send a technician there and that a local provider "
    "can help, and book nothing.\n"
    "Name dates as weekday, month and day (Wednesday October 21) and windows in hours "
    "(8 AM to 12 PM). After book_visit succeeds, confirm once, in one or two sentences: "
    "the date, window and technician it returned, and the diagnostic fee from its result, "
    "credited toward the repair, or waived when diagnosticFeeWaived is true.\n"
    "Other handoffs: call escalate when the caller wants a refund (refund_demand), a "
    "technician is late (technician_late), they want to change or cancel a membership or "
    "its auto-renew (membership_change), ask what a new system costs (new_system_quote), "
    "ask for a service the documents list as not offered (out_of_scope), or "
    "search_knowledge does not answer what they asked, such as a service the documents "
    "neither list nor rule out (no_document_answer); its result says what to tell them.\n"
    "Handing over: call escalate at once, before identifying the caller, when they "
    "dispute a charge or say they were charged twice (kind supervisor_callback, reason "
    "billing_dispute), or when they ask for a person at any point (reason "
    "caller_asked_for_person). Do not explain, argue or look up a disputed charge. Pass "
    "callerName and callerPhone only if the caller already gave them. The app writes the "
    "reply about the call back.\n"
    "Checking or changing a visit. When the caller asks about, moves or cancels a visit, "
    "identify them (a service address counts), call lookup_my_appointments and give each "
    "visit's weekday, date, window and technician. To move a visit, call "
    "find_open_windows with the visit's serviceType and the day they ask for as "
    "preferredDate, and let them pick from the buttons. When they pick, call move_visit "
    "with the appointmentId, that window's slotId and callerQuote copied exactly from "
    "their message, then confirm only the new date, window and technician it returned "
    "and the diagnostic fee as for a booking, never the old date. When the caller asks "
    "to cancel, call cancel_visit for that visit in the same turn (calling "
    "lookup_my_appointments first if you do not have its appointmentId yet), give the "
    "terms it returns and end with a question asking them to confirm; call it again only "
    "when the caller's next message is a clear yes. If they are unsure, change nothing and ask "
    "what they would like. Never waive, reduce or promise to waive any fee; if asked, say "
    "you cannot waive fees in this chat and offer to pass them to a person.\n"
    "Billing: once the caller is matched, call get_my_billing and give the balance with "
    "each open invoice id; explain a line from its line items. To pay, call "
    "send_payment_link and give its url here; nothing is sent by phone or email. Never "
    "ask for card details. Discuss only the matched caller's own account; for anyone "
    "else's, say you can only discuss theirs."
)


def _today_line(settings: Settings) -> str:
    """The reference clock in words, so the model can turn day names into dates."""
    today = date.fromisoformat(settings.REFERENCE_DATE)
    return (
        f"Today is {today:%A %B} {today.day}, {today.year}, {settings.REFERENCE_TIME} "
        "Central time. Work out day names such as Monday from today."
    )


def _recent_turns(
    db: sqlite3.Connection, conversation_id: str
) -> tuple[list[str], bool]:
    """The last three exchanges as text, and whether the follow-up question is pending."""
    rows = db.execute(
        "SELECT caller_text, reply_text, safety_verdict FROM turns "
        "WHERE conversation_id = ? AND kind = 'message' ORDER BY seq DESC LIMIT 3",
        (conversation_id,),
    ).fetchall()
    texts = [
        t for r in reversed(rows) for t in (r["caller_text"], r["reply_text"]) if t
    ]
    # The screen asks the follow-up itself, and the agent asks the same question before a
    # booking; either way the caller's answer is screened under the clear-no rule.
    pending = bool(rows) and (
        rows[0]["safety_verdict"] == "burning_followup"
        or guards.BURNING_QUESTION.casefold()
        in (rows[0]["reply_text"] or "").casefold()
    )
    return texts, pending


def _save_turn(
    ctx: AppContext,
    db: sqlite3.Connection,
    conversation_id: str,
    state: tools.ToolState,
    turn: dict[str, Any],
    cost: float,
    end: Callable[[str], None] | None = None,
) -> int:
    """Store the turn and update the conversation in one transaction; `end` joins it."""
    db.execute("BEGIN IMMEDIATE")
    try:
        if db.execute(
            "SELECT outcome FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()[0]:
            raise AppError(409, "conversation_ended", "This conversation has ended.")
        seq = db.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM turns WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()[0]
        db.execute(
            "INSERT INTO turns (conversation_id, seq, kind, caller_text, reply_text, "
            "model_messages, tools_called, retrieved, latency_ms, prompt_tokens, "
            "completion_tokens, cost_usd, cost_source, safety_verdict, offered, "
            "has_write, error, fallback_used) "
            "VALUES (?, ?, 'message', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                conversation_id,
                seq,
                turn["caller_text"],
                turn["reply_text"],
                json.dumps(turn["stored"]),
                json.dumps(turn["tools_called"]),
                json.dumps(state.retrieved),
                turn["latency_ms"],
                turn["prompt_tokens"],
                turn["completion_tokens"],
                cost,
                turn["cost_source"],
                turn["safety_verdict"],
                state.offered_json() if turn["safety_verdict"] == "safe" else "{}",
                int(state.has_write),
                turn.get("error"),
                turn["fallback_used"],
            ),
        )
        db.execute(
            "UPDATE conversations SET turn_count = turn_count + 1, cost_usd = cost_usd + ?, "
            "last_activity_at = strftime('%Y-%m-%dT%H:%M:%fZ','now'), intent = ?, "
            "intents_seen = ?, resolved_at = CASE WHEN ? = 1 THEN "
            "COALESCE(resolved_at, strftime('%Y-%m-%dT%H:%M:%fZ','now')) "
            "WHEN ? = 0 THEN NULL ELSE resolved_at END "
            "WHERE id = ?",
            (
                cost,
                state.intent,
                json.dumps(state.intents_seen),
                state.resolved,
                state.resolved,
                conversation_id,
            ),
        )
        if end is not None:
            end(turn["reply_text"])
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    return seq


def _stop_for(
    ctx: AppContext,
    db: sqlite3.Connection,
    conversation_id: str,
    customer_id: str | None,
    verdict: Verdict,
) -> Callable[[str], None]:
    """End the conversation as a safety stop, with its handoff, inside the turn's transaction."""

    def end(told_caller: str) -> None:
        followups.create_handoff(
            db,
            HandoffRecord(
                conversation_id=conversation_id,
                kind="safety_stop",
                reason=verdict.reason or "emergency",
                by_error=False,
                customer_id=customer_id,
                intent="safety",
                told_caller=told_caller,
                summary_source="system",
            ),
            ctx,
        )
        db.execute(
            "UPDATE conversations SET outcome = 'safety_stop', outcome_reason = 'emergency', "
            "ended_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
            "WHERE id = ? AND outcome IS NULL",
            (conversation_id,),
        )

    return end


def _record_stop_alone(
    db: sqlite3.Connection, end: Callable[[str], None], told_caller: str
) -> None:
    """The turn row could not be saved: still record the safety handoff and outcome."""
    try:
        db.execute("BEGIN IMMEDIATE")
        end(told_caller)
        db.execute("COMMIT")
    except sqlite3.Error as exc:
        if db.in_transaction:
            db.execute("ROLLBACK")
        log_event("safety_handoff_failed", level="error", error_type=type(exc).__name__)


def _handoff_end(
    ctx: AppContext,
    db: sqlite3.Connection,
    conversation_id: str,
    record: HandoffRecord,
) -> Callable[[str], None]:
    """Write the handoff and end the conversation inside the turn's transaction."""

    def end(told_caller: str) -> None:
        followups.create_handoff(
            db, record.model_copy(update={"told_caller": told_caller}), ctx
        )
        conversation_service.end_with_handoff(db, conversation_id)

    return end


def _gives_earlier_link(text: str, history: list[dict[str, Any]]) -> bool:
    """True when the reply holds a payment link a tool returned in an earlier turn."""
    for message in history:
        if message.get("role") != "tool":
            continue
        try:
            url = json.loads(str(message.get("content"))).get("url")
        except (ValueError, AttributeError):
            continue
        if isinstance(url, str) and url in text:
            return True
    return False


def _fixed_handoff_text(state: tools.ToolState) -> str | None:
    record = state.handoff
    return None if record is None else guards.handoff_text(record.reason, record.kind)


def _call_cost(settings: Settings, result: Any) -> float:
    """The call's reported cost, else its estimate from MODEL_PRICES."""
    if result.cost_usd is not None:
        return result.cost_usd
    price = settings.MODEL_PRICES.get(settings.AGENT_MODEL, {})
    return (
        (result.prompt_tokens or 0) * price.get("input", 0.0)
        + (result.completion_tokens or 0) * price.get("output", 0.0)
    ) / 1e6


def _add_late_cost(ctx: AppContext, conversation_id: str, late: Future) -> None:
    """A model call the turn stopped waiting for still costs money: add it when it returns."""
    if late.cancelled() or late.exception() is not None:
        return
    try:
        conn = ctx.open_app_db()
        try:
            conn.execute(
                "UPDATE conversations SET cost_usd = cost_usd + ? WHERE id = ?",
                (_call_cost(ctx.settings, late.result()), conversation_id),
            )
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 - a late cost never raises in a worker
        log_event("late_cost_failed", level="warning", error_type=type(exc).__name__)


def _failure_code(exc: Exception, has_history: bool) -> str:
    if isinstance(exc, TimeoutError | openai.APITimeoutError):
        return "provider_timeout"
    if has_history and isinstance(exc, openai.BadRequestError):
        return "replay_rejected"
    return "provider_error"


def _end_failed(db: sqlite3.Connection, conversation_id: str) -> Callable[[str], None]:
    """End the conversation as failed because the provider refused its replayed history."""

    def end(told_caller: str) -> None:
        db.execute(
            "UPDATE conversations SET outcome = 'failed', outcome_reason = 'replay_rejected', "
            "ended_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ? AND outcome IS NULL",
            (conversation_id,),
        )

    return end


def _observed(
    name: str,
    kind: Any,
    start: datetime,
    model: str | None,
    used: list[usage.Usage],
    **fields: Any,
) -> tracing.Observation:
    """One timed step of the turn, with the tokens and cost its provider calls reported."""
    spent = usage.total(used)
    return tracing.Observation(
        name,
        kind,
        start,
        datetime.now(UTC),
        model=model if used else None,
        input_tokens=spent.input_tokens,
        output_tokens=spent.output_tokens,
        cost_usd=spent.cost_usd,
        **fields,
    )


def _screened(
    ctx: AppContext,
    text: str,
    recent: list[str],
    follow_up_pending: bool,
    seen: list[tracing.Observation],
) -> Verdict:
    """Run the safety screen and record it for the trace."""
    start = datetime.now(UTC)
    fields: dict[str, Any] = {}
    with usage.collect() as used:
        try:
            verdict = safety.screen_safety(ctx, text, recent, follow_up_pending)
            fields["metadata"] = {"verdict": verdict.verdict, "reason": verdict.reason}
            return verdict
        except Exception:
            fields = {"level": "ERROR", "status": "screen_unavailable"}
            raise
        finally:
            seen.append(
                _observed(
                    "safety_screen",
                    "generation",
                    start,
                    ctx.settings.SAFETY_MODEL,
                    used or [usage.Usage()],
                    **fields,
                )
            )


def _send_trace(
    ctx: AppContext,
    db: sqlite3.Connection,
    conversation_id: str,
    seq: int | None,
    start: datetime,
    turn: dict[str, Any],
    observations: list[tracing.Observation],
    metadata: dict[str, Any],
) -> None:
    """Hand the turn's scrubbed trace to the tracer; a confirmed send stores its id on the turn."""
    if ctx.tracer is None:
        return
    try:
        if not any(o.name == "safety_screen" for o in observations):
            now = datetime.now(UTC)
            observations.append(
                tracing.Observation(
                    "safety_screen",
                    "generation",
                    now,
                    now,
                    model=ctx.settings.SAFETY_MODEL,
                    level="WARNING",
                    status="not_finished",
                )
            )
        public_id = db.execute(
            "SELECT public_id FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()[0]
        trace = tracing.TurnTrace(
            session_id=public_id,
            name="turn",
            start=start,
            end=datetime.now(UTC),
            input=turn["caller_text"],
            output=turn["reply_text"],
            metadata={
                "seq": seq,
                "error": turn["error"],
                "fallback_used": turn["fallback_used"],
                "safety_verdict": turn["safety_verdict"],
                "prompt_tokens": turn["prompt_tokens"],
                "completion_tokens": turn["completion_tokens"],
                "cost_source": turn["cost_source"],
                "latency_ms": turn["latency_ms"],
                "tools": [c["name"] for c in turn["tools_called"]],
                **metadata,
            },
            observations=sorted(observations, key=lambda o: o.start),
        )
    except Exception as exc:  # noqa: BLE001 - tracing never breaks a turn
        log_event("trace_send_failed", level="warning", error_type=type(exc).__name__)
        return

    def on_sent(trace_id: str) -> None:
        if seq is None:
            return
        conn = ctx.open_app_db()
        try:
            conn.execute(
                "UPDATE turns SET trace_id = ? WHERE conversation_id = ? AND seq = ? "
                "AND kind = 'message'",
                (trace_id, conversation_id, seq),
            )
        finally:
            conn.close()

    tracing.send_turn_trace(ctx.tracer, trace, conversation_id, on_sent)


def run_turn(
    ctx: AppContext,
    db: sqlite3.Connection,
    conversation_id: str,
    text: str,
    simulate_outage: bool = False,
) -> Reply:
    started = ctx.clock.monotonic()
    trace_start = datetime.now(UTC)
    observations: list[tracing.Observation] = []

    def left() -> float:
        return ctx.settings.TURN_DEADLINE - (ctx.clock.monotonic() - started)

    redaction = safety.redact_card_numbers(text)
    redacted = redaction.text

    history: list[dict[str, Any]] = []
    earlier = 0
    for row in db.execute(
        "SELECT model_messages FROM turns WHERE conversation_id = ? AND kind = 'message' "
        "ORDER BY seq",
        (conversation_id,),
    ):
        history.extend(json.loads(row["model_messages"]))
        earlier += 1
    last_seq = db.execute(
        "SELECT COALESCE(MAX(seq), 0) FROM turns WHERE conversation_id = ?",
        (conversation_id,),
    ).fetchone()[0]
    state = tools.ToolState.load(db, conversation_id, redacted, history)
    state.card_removed = redaction.removed
    recent, follow_up_pending = _recent_turns(db, conversation_id)

    user = {"role": "user", "content": redacted}
    stored: list[dict[str, Any]] = [user]
    tools_called: list[dict[str, Any]] = []
    cost = 0.0
    all_reported = True
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    last_said = ""
    verdict: Verdict | None = None
    failure: str | None = "provider_error" if simulate_outage else None

    screen = ThreadPoolExecutor(max_workers=1)
    model_pool = ThreadPoolExecutor(max_workers=1)
    screening = screen.submit(
        _screened, ctx, redacted, recent, follow_up_pending, observations
    )
    try:
        for _ in range(0 if failure else MAX_TOOL_ROUNDS):
            remaining = left()
            if remaining <= FALLBACK_RESERVE_S:
                failure = "provider_timeout"
                break
            call_start = datetime.now(UTC)
            call = None
            try:
                call = model_pool.submit(
                    ctx.model.complete,
                    [
                        {
                            "role": "system",
                            "content": f"{INSTRUCTIONS}\n{_today_line(ctx.settings)}",
                        },
                        *history,
                        *stored,
                    ],
                    tools=tools.TOOLS,
                    timeout_s=remaining,
                )
                result = call.result(timeout=remaining - FALLBACK_RESERVE_S)
            except Exception as exc:  # noqa: BLE001 - any provider failure falls back
                failure = _failure_code(exc, bool(history))
                if call is not None and isinstance(exc, TimeoutError):
                    call.add_done_callback(
                        lambda late: _add_late_cost(ctx, conversation_id, late)
                    )
                observations.append(
                    _observed(
                        "model_call", "generation", call_start, None, [],
                        level="ERROR", status=failure,
                    )
                )  # fmt: skip
                log_event(
                    "model_call_failed", error=failure, error_type=type(exc).__name__
                )
                break
            if verdict is None:
                try:
                    verdict = screening.result(
                        timeout=max(left() - FALLBACK_RESERVE_S, 0.0)
                    )
                except Exception as exc:  # noqa: BLE001 - an unscreened turn takes the fallback
                    failure = "screen_unavailable"
                    log_event(
                        "screen_failed", error=failure, error_type=type(exc).__name__
                    )
                    break
            if result.prompt_tokens is not None:
                prompt_tokens = (prompt_tokens or 0) + result.prompt_tokens
            if result.completion_tokens is not None:
                completion_tokens = (completion_tokens or 0) + result.completion_tokens
            all_reported = all_reported and result.cost_usd is not None
            call_cost = _call_cost(ctx.settings, result)
            cost += call_cost
            observations.append(
                _observed(
                    "model_call",
                    "generation",
                    call_start,
                    ctx.settings.AGENT_MODEL,
                    [
                        usage.Usage(
                            result.prompt_tokens, result.completion_tokens, call_cost
                        )
                    ],
                    metadata={
                        "tools_requested": [
                            str((c.get("function") or {}).get("name", ""))
                            for c in result.message.get("tool_calls") or []
                            if isinstance(c, dict)
                        ],
                        "cost_source": "reported"
                        if result.cost_usd is not None
                        else "estimated",
                    },
                )
            )
            if verdict.verdict != "safe":
                break
            calls = result.message.get("tool_calls") or []
            if not all(isinstance(c, dict) and c.get("id") for c in calls):
                failure = "malformed_reply"
                break
            stored.append(result.message)
            said = str(result.message.get("content") or "").strip()
            if said:
                last_said = said
            if not calls:
                break
            for call in calls:
                tool_start = datetime.now(UTC)
                with usage.collect() as used:
                    output, entry = tools.run_tool(ctx, state, call)
                observations.append(
                    _observed(
                        entry["name"],
                        "tool",
                        tool_start,
                        ctx.settings.EMBEDDING_MODEL,
                        used,
                        level="DEFAULT" if entry["ok"] else "ERROR",
                        status=entry["error"],
                        metadata={"ok": entry["ok"]},
                    )
                )
                tools_called.append(entry)
                stored.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": json.dumps(output),
                    }
                )
            if state.unavailable == "scheduling_unavailable":
                failure = state.unavailable
                break
            if _fixed_handoff_text(state) is not None:
                break
        else:
            if not failure:
                failure = "tool_rounds_exhausted"
        if failure and verdict is None:
            try:
                verdict = screening.result(
                    timeout=max(left() - FALLBACK_RESERVE_S, 0.0)
                )
            except Exception:  # noqa: BLE001 - an unscreened turn keeps the failure path
                verdict = None
    finally:
        screen.shutdown(wait=False)
        model_pool.shutdown(wait=False)

    turn: dict[str, Any] = {
        "caller_text": redacted,
        "stored": stored,
        "tools_called": tools_called,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost_source": "reported" if all_reported else "estimated",
        "safety_verdict": verdict.verdict if verdict else "unscreened",
        "error": None,
        "fallback_used": 0,
    }
    status: Any = "active"
    banner: Any = "none"
    actions: list[Any] = []
    end = None
    booking = state.booking
    choices: list[Any] = []
    amended = False  # the app added a card refusal or a payment link to the reply
    unamended = ""
    if verdict is not None and verdict.verdict != "safe":
        emergency = verdict.verdict == "emergency"
        final_text = (
            guards.emergency_text(state.customer_id is not None)
            if emergency
            else guards.BURNING_FOLLOWUP_TEXT
        )
        turn["stored"] = [user, {"role": "assistant", "content": final_text}]
        turn["tools_called"] = []
        turn["error"] = failure
        if emergency:
            status = banner = "safety_stop"
            actions = ["new_conversation"]
            if "safety" not in state.intents_seen:
                state.intents_seen.append("safety")
            state.intent = "safety"
            end = _stop_for(ctx, db, conversation_id, state.customer_id, verdict)
    else:
        final_text = last_said
        if not failure and not final_text.strip() and state.handoff is None:
            failure = "empty_reply"
        if failure:
            turn["error"] = failure
            committed = guards.committed_text(
                state.booking, state.cancelled, state.waitlisted
            )
            if state.handoff is not None and failure != "replay_rejected":
                # The model already handed over: keep the handoff and its reason.
                final_text = " ".join(
                    filter(
                        None,
                        [committed, _fixed_handoff_text(state) or guards.HANDOFF_TEXT],
                    )
                )
                status, banner = "handed_off", "handoff"
                actions = ["choose_callback_window"]
                state.resolved = False
                end = _handoff_end(ctx, db, conversation_id, state.handoff)
            elif committed:
                final_text = committed
            else:
                final_text = guards.FALLBACK_TEXT
                banner = "error"
                actions = ["request_callback"]
                turn["fallback_used"] = 1
                booking = None
            turn["stored"] = [*stored, {"role": "assistant", "content": final_text}]
            if failure == "replay_rejected":
                status = "ended"
                actions = [*actions, "new_conversation"]
                end = _end_failed(db, conversation_id)
        else:
            choices = tools.choices(state)
            if tools.wants_earlier(state):
                actions = [*actions, "choices_only"]
            # A committed booking with no report_status still counts as resolved,
            # unless the waitlist join the caller asked for failed.
            if state.booking is not None and state.resolved is None:
                state.resolved = True
            if state.waitlist_failed:
                state.resolved = False
            if state.write_failed and (booking is None or state.waitlist_failed):
                actions = ["request_callback"]
                turn["error"] = "write_failed"
            withheld = False
            fixed = _fixed_handoff_text(state)
            if fixed is not None:
                final_text = fixed
            elif state.unavailable == "embedding_unavailable":
                withheld, turn["error"] = True, "embedding_unavailable"
            elif state.booking and guards.confirmation_mismatch(
                final_text, state.booking
            ):
                final_text = guards.confirmation_text(state.booking)
                turn["error"] = "confirmation_mismatch"
            elif (
                not state.cancelled
                and any(c["name"] == "cancel_visit" for c in tools_called)
                and guards.claims_cancelled(final_text)
            ):
                # Never confirm a cancel that did not happen; restate the terms instead.
                fees = [state.cancel_fee_cents.get(i) for i in state.cancel_asked]
                final_text = guards.cancel_pending_text(next(filter(None, fees), None))
                turn["error"] = "cancel_claim_withheld"
            elif guards.unsupported_figures(final_text, [*history, *stored]):
                withheld, turn["error"] = True, "unsupported_figure"
            elif guards.makes_promise(final_text):
                withheld, turn["error"] = True, "promise_withheld"
            if state.handoff is not None:
                if withheld or not final_text.strip():
                    final_text = guards.HANDOFF_TEXT
                if state.handoff.reason == "no_document_answer":
                    final_text = guards.not_sure_first(final_text)
                status, banner = "handed_off", "handoff"
                actions, choices = ["choose_callback_window"], []
                state.resolved = False
                if final_text != last_said:
                    turn["stored"] = [
                        *stored,
                        {"role": "assistant", "content": final_text},
                    ]
                end = _handoff_end(ctx, db, conversation_id, state.handoff)
            elif withheld:
                final_text = " ".join(
                    filter(
                        None,
                        [
                            guards.committed_text(
                                state.booking, state.cancelled, state.waitlisted
                            ),
                            guards.NOT_SURE_TEXT,
                        ],
                    )
                )
                actions = ["request_callback"]
                choices = []
                state.resolved = False
            elif (
                state.resolved
                and not any(c["name"] == "escalate" for c in tools_called)
                and not db.execute(
                    "SELECT 1 FROM handoffs WHERE conversation_id = ?",
                    (conversation_id,),
                ).fetchone()
            ):
                actions = [*actions, "ask_solved"]
            unamended = final_text
            if state.handoff is None and not withheld:
                if (
                    state.card_removed
                    and state.payment_link is None
                    and not _gives_earlier_link(final_text, history)
                ):
                    state.payment_link = tools.card_turn_link(ctx, state)
                link = state.payment_link
                if link is not None and link.url not in final_text:
                    final_text = f"{final_text} {guards.payment_link_text(link)}"
                    amended = True
        if state.card_removed and not guards.refuses_card(final_text):
            final_text = f"{guards.CARD_REFUSAL_TEXT} {final_text}"
            amended = True
        if amended:
            turn["stored"] = [*stored, {"role": "assistant", "content": final_text}]
    # A yes can confirm a cancel only after the model's own reply put the terms.
    model_said = final_text == last_said or (amended and unamended == last_said)
    shown = last_said if model_said and not turn["error"] else None
    if turn["error"] == "cancel_claim_withheld":
        shown = final_text  # the fixed text restates the terms and asks to confirm
    state.keep_cancel_asks(shown if status == "active" else None)
    if status == "active" and earlier + 1 >= ctx.settings.TURN_CAP:
        final_text = f"{final_text} {guards.TURN_CAP_TEXT}".strip()
    turn["reply_text"] = final_text
    turn["latency_ms"] = round((ctx.clock.monotonic() - started) * 1000)
    saved: int | None = None
    cost = round(cost, 10)
    try:
        seq = saved = _save_turn(ctx, db, conversation_id, state, turn, cost, end)
    except sqlite3.Error as exc:
        log_event("turn_save_failed", table="turns", error_type=type(exc).__name__)
        seq = last_seq + 1
        if status == "safety_stop" and end is not None:
            _record_stop_alone(db, end, final_text)
        elif status == "handed_off" or (
            status == "active" and "request_callback" in actions
        ):
            if status == "handed_off":
                # No handoff was written: the caller gets the fallback and the
                # conversation stays open.
                final_text = turn["reply_text"] = guards.FALLBACK_TEXT
                status, banner, actions = "active", "error", ["request_callback"]
                turn.update(fallback_used=1, error="handoff_save_failed")
            # The reply offers a call back: a plain row (best effort) lets the pick find it.
            turn.update(
                stored=[user, {"role": "assistant", "content": final_text}],
                tools_called=[],
            )
            try:
                seq = saved = _save_turn(ctx, db, conversation_id, state, turn, cost)
            except (sqlite3.Error, AppError) as again:
                log_event("fallback_turn_save_failed", error_type=type(again).__name__)
    _send_trace(
        ctx,
        db,
        conversation_id,
        saved,
        trace_start,
        turn,
        observations,
        {"status": status, "banner": banner, "cost_usd": cost, "intent": state.intent},
    )

    return Reply(
        conversation_id=conversation_id,
        status=status,
        text=final_text,
        banner=banner,
        choices=choices,
        booking=booking,
        waitlisted=state.waitlisted,
        actions=actions,
        turn=TurnInfo(seq=seq, latency_ms=turn["latency_ms"]),
    )

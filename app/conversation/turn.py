"""One caller message: redact, replay the earlier turns, run the model's tools, store the turn."""

import json
import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import openai

from app.context import AppContext
from app.conversation import guards, tools
from app.errors import AppError
from app.followups import service as followups
from app.logs import log_event
from app.safety import service as safety
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
    "tool call. Write the caller's answer once, after the tools have returned."
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
    return texts, bool(rows) and rows[0]["safety_verdict"] == "burning_followup"


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
            "intents_seen = ?, resolved_at = CASE WHEN ? THEN "
            "COALESCE(resolved_at, strftime('%Y-%m-%dT%H:%M:%fZ','now')) ELSE resolved_at END "
            "WHERE id = ?",
            (
                cost,
                state.intent,
                json.dumps(state.intents_seen),
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
        )
        db.execute(
            "UPDATE conversations SET outcome = 'safety_stop', outcome_reason = 'emergency', "
            "ended_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
            "WHERE id = ? AND outcome IS NULL",
            (conversation_id,),
        )

    return end


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


def run_turn(
    ctx: AppContext,
    db: sqlite3.Connection,
    conversation_id: str,
    text: str,
    simulate_outage: bool = False,
) -> Reply:
    started = ctx.clock.monotonic()

    def left() -> float:
        return ctx.settings.TURN_DEADLINE - (ctx.clock.monotonic() - started)

    redacted = safety.redact_card_numbers(text).text

    history: list[dict[str, Any]] = []
    earlier = 0
    for row in db.execute(
        "SELECT model_messages FROM turns WHERE conversation_id = ? AND kind = 'message' "
        "ORDER BY seq",
        (conversation_id,),
    ):
        history.extend(json.loads(row["model_messages"]))
        earlier += 1
    state = tools.ToolState.load(db, conversation_id, redacted, history)
    recent, follow_up_pending = _recent_turns(db, conversation_id)

    user = {"role": "user", "content": redacted}
    stored: list[dict[str, Any]] = [user]
    tools_called: list[dict[str, Any]] = []
    cost = 0.0
    all_reported = True
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    said: list[str] = []
    verdict: Verdict | None = None
    failure: str | None = "provider_error" if simulate_outage else None

    screen = ThreadPoolExecutor(max_workers=1)
    model_pool = ThreadPoolExecutor(max_workers=1)
    screening = screen.submit(
        safety.screen_safety, ctx, redacted, recent, follow_up_pending
    )
    try:
        for _ in range(0 if failure else MAX_TOOL_ROUNDS):
            remaining = left()
            if remaining <= FALLBACK_RESERVE_S:
                failure = "provider_timeout"
                break
            try:
                result = model_pool.submit(
                    ctx.model.complete,
                    [{"role": "system", "content": INSTRUCTIONS}, *history, *stored],
                    tools=tools.TOOLS,
                    timeout_s=remaining,
                ).result(timeout=remaining - FALLBACK_RESERVE_S)
            except Exception as exc:  # noqa: BLE001 - any provider failure falls back
                failure = _failure_code(exc, bool(history))
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
                    failure = _failure_code(exc, False)
                    log_event(
                        "screen_failed", error=failure, error_type=type(exc).__name__
                    )
                    break
            if result.prompt_tokens is not None:
                prompt_tokens = (prompt_tokens or 0) + result.prompt_tokens
            if result.completion_tokens is not None:
                completion_tokens = (completion_tokens or 0) + result.completion_tokens
            if result.cost_usd is not None:
                cost += result.cost_usd
            else:
                all_reported = False
                price = ctx.settings.MODEL_PRICES.get(ctx.settings.AGENT_MODEL, {})
                cost += (
                    (result.prompt_tokens or 0) * price.get("input", 0.0)
                    + (result.completion_tokens or 0) * price.get("output", 0.0)
                ) / 1e6
            if verdict.verdict != "safe":
                break
            calls = result.message.get("tool_calls") or []
            if not all(isinstance(c, dict) and c.get("id") for c in calls):
                failure = "malformed_reply"
                break
            stored.append(result.message)
            if result.message.get("content"):
                said.append(str(result.message["content"]).strip())
            if not calls:
                break
            for call in calls:
                output, entry = tools.run_tool(ctx, state, call)
                tools_called.append(entry)
                stored.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": json.dumps(output),
                    }
                )
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
        "safety_verdict": verdict.verdict if verdict else "safe",
        "error": None,
        "fallback_used": 0,
    }
    status: Any = "active"
    banner: Any = "none"
    actions: list[Any] = []
    end = None
    booking = state.booking
    choices: list[Any] = []
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
            end = _stop_for(db, conversation_id, state.customer_id, verdict)
    else:
        final_text = "\n\n".join(said)
        if not failure and not final_text.strip():
            failure = "empty_reply"
        if failure:
            turn["error"] = failure
            committed = guards.committed_text(
                state.booking, state.cancelled, state.waitlisted
            )
            if committed:
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
            if state.write_failed and booking is None:
                actions = ["request_callback"]
    turn["reply_text"] = final_text
    turn["latency_ms"] = round((ctx.clock.monotonic() - started) * 1000)
    try:
        seq = _save_turn(ctx, db, conversation_id, state, turn, cost, end)
    except sqlite3.Error as exc:
        log_event("turn_save_failed", table="turns", error_type=type(exc).__name__)
        seq = earlier + 1

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

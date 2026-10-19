"""One caller message: redact, replay the earlier turns, run the model's tools, store the turn."""

import json
import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.context import AppContext
from app.conversation import guards, tools
from app.followups import service as followups
from app.safety import service as safety
from app.types import HandoffRecord, Reply, TurnInfo, Verdict

MAX_TOOL_ROUNDS = 6

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
        seq = db.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM turns WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()[0]
        db.execute(
            "INSERT INTO turns (conversation_id, seq, kind, caller_text, reply_text, "
            "model_messages, tools_called, retrieved, latency_ms, prompt_tokens, "
            "completion_tokens, cost_usd, cost_source, safety_verdict, offered, "
            "has_write, error) "
            "VALUES (?, ?, 'message', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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


def run_turn(
    ctx: AppContext, db: sqlite3.Connection, conversation_id: str, text: str
) -> Reply:
    started = ctx.clock.monotonic()
    redacted = safety.redact_card_numbers(text).text

    history: list[dict[str, Any]] = []
    for row in db.execute(
        "SELECT model_messages FROM turns WHERE conversation_id = ? AND kind = 'message' "
        "ORDER BY seq",
        (conversation_id,),
    ):
        history.extend(json.loads(row["model_messages"]))
    state = tools.ToolState.load(db, conversation_id, redacted, history)
    recent, follow_up_pending = _recent_turns(db, conversation_id)

    user = {"role": "user", "content": redacted}
    stored: list[dict[str, Any]] = [user]
    tools_called: list[dict[str, Any]] = []
    cost = 0.0
    all_reported = True
    prompt_tokens = completion_tokens = 0
    said: list[str] = []
    verdict: Verdict | None = None
    error: str | None = None

    screen = ThreadPoolExecutor(max_workers=1)
    screening = screen.submit(
        safety.screen_safety, ctx, redacted, recent, follow_up_pending
    )
    try:
        for _ in range(MAX_TOOL_ROUNDS):
            remaining = ctx.settings.TURN_DEADLINE - (ctx.clock.monotonic() - started)
            try:
                result = ctx.model.complete(
                    [{"role": "system", "content": INSTRUCTIONS}, *history, *stored],
                    tools=tools.TOOLS,
                    timeout_s=max(remaining, 1.0),
                )
            except Exception:
                if state.booking is None:
                    raise
                error = "provider_error"
                said = [guards.confirmation_text(state.booking)]
                stored.append({"role": "assistant", "content": said[0]})
                break
            if verdict is None:
                remaining = ctx.settings.TURN_DEADLINE - (
                    ctx.clock.monotonic() - started
                )
                verdict = screening.result(timeout=max(remaining, 1.0))
            prompt_tokens += result.prompt_tokens or 0
            completion_tokens += result.completion_tokens or 0
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
            stored.append(result.message)
            if result.message.get("content"):
                said.append(str(result.message["content"]).strip())
            calls = result.message.get("tool_calls") or []
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
    finally:
        screen.shutdown(wait=False)

    turn: dict[str, Any] = {
        "caller_text": redacted,
        "stored": stored,
        "tools_called": tools_called,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost_source": "reported" if all_reported else "estimated",
        "safety_verdict": verdict.verdict if verdict else "safe",
        "error": error,
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
        if emergency:
            status = banner = "safety_stop"
            actions = ["new_conversation"]
            if "safety" not in state.intents_seen:
                state.intents_seen.append("safety")
            state.intent = "safety"
            end = _stop_for(db, conversation_id, state.customer_id, verdict)
    else:
        final_text = "\n\n".join(said)
        choices = tools.choices(state)
        if state.write_failed and booking is None:
            actions = ["request_callback"]
    turn["reply_text"] = final_text
    turn["latency_ms"] = round((ctx.clock.monotonic() - started) * 1000)
    seq = _save_turn(ctx, db, conversation_id, state, turn, cost, end)

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

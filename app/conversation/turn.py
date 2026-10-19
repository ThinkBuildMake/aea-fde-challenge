"""One caller message: redact, replay the earlier turns, run the model's tools, store the turn."""

import json
import sqlite3
from typing import Any

from app.context import AppContext
from app.conversation import tools
from app.safety import service as safety
from app.types import Reply, TurnInfo

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

    user = {"role": "user", "content": redacted}
    stored: list[dict[str, Any]] = [user]
    tools_called: list[dict[str, Any]] = []
    cost = 0.0
    all_reported = True
    prompt_tokens = completion_tokens = 0
    said: list[str] = []

    for _ in range(MAX_TOOL_ROUNDS):
        remaining = ctx.settings.TURN_DEADLINE - (ctx.clock.monotonic() - started)
        result = ctx.model.complete(
            [{"role": "system", "content": INSTRUCTIONS}, *history, *stored],
            tools=tools.TOOLS,
            timeout_s=max(remaining, 1.0),
        )
        stored.append(result.message)
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

    final_text = "\n\n".join(said)
    latency_ms = round((ctx.clock.monotonic() - started) * 1000)
    db.execute("BEGIN IMMEDIATE")
    try:
        seq = db.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM turns WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()[0]
        db.execute(
            "INSERT INTO turns (conversation_id, seq, kind, caller_text, reply_text, "
            "model_messages, tools_called, retrieved, latency_ms, prompt_tokens, "
            "completion_tokens, cost_usd, cost_source) "
            "VALUES (?, ?, 'message', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                conversation_id,
                seq,
                redacted,
                final_text,
                json.dumps(stored),
                json.dumps(tools_called),
                json.dumps(state.retrieved),
                latency_ms,
                prompt_tokens,
                completion_tokens,
                cost,
                "reported" if all_reported else "estimated",
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
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise

    return Reply(
        conversation_id=conversation_id,
        status="active",
        text=final_text,
        banner="none",
        choices=tools.choices(state),
        booking=state.booking,
        waitlisted=state.waitlisted,
        actions=[],
        turn=TurnInfo(seq=seq, latency_ms=latency_ms),
    )

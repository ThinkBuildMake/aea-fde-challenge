"""One caller message: redact, replay the earlier turns, run the model's tools, store the turn."""

import json
import sqlite3
from collections.abc import Callable
from typing import Any

from app.context import AppContext
from app.knowledge import service as knowledge
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

TOOLS: dict[str, dict[str, Any]] = {
    "search_knowledge": {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "Search Meridian's knowledge base for fees, policies, membership and warranty.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    "report_status": {
        "type": "function",
        "function": {
            "name": "report_status",
            "description": "Report what the caller wants now and whether it is resolved.",
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {"type": "string"},
                    "resolved": {"type": "boolean"},
                },
                "required": ["intent", "resolved"],
            },
        },
    },
}


class _TurnState:
    def __init__(self, intent: str, intents_seen: list[str]) -> None:
        self.intent = intent
        self.intents_seen = intents_seen
        self.resolved = False
        self.retrieved: list[dict[str, Any]] = []


def _search_knowledge(
    ctx: AppContext, state: _TurnState, args: dict[str, Any]
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
    ctx: AppContext, state: _TurnState, args: dict[str, Any]
) -> dict[str, Any]:
    intent = str(args["intent"])
    state.intent = intent
    if intent not in state.intents_seen:
        state.intents_seen.append(intent)
    if args.get("resolved") is True:
        state.resolved = True
    return {"ok": True}


HANDLERS: dict[
    str, Callable[[AppContext, _TurnState, dict[str, Any]], dict[str, Any]]
] = {
    "search_knowledge": _search_knowledge,
    "report_status": _report_status,
}


def _run_tool(
    ctx: AppContext, state: _TurnState, call: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run one tool call; return (result for the model, log entry)."""
    name = call.get("function", {}).get("name", "")
    started = ctx.clock.monotonic()
    error: str | None = None
    result: dict[str, Any]
    try:
        handler = HANDLERS.get(name)
        if handler is None:
            raise LookupError(f"unknown tool {name}")
        args = json.loads(call["function"].get("arguments") or "{}")
        result = handler(ctx, state, args)
    except Exception as exc:  # noqa: BLE001 - the model gets the failure back as the tool result
        error = f"{type(exc).__name__}: {exc}"
        result = {"ok": False, "error": error}
    ms = round((ctx.clock.monotonic() - started) * 1000)
    return result, {"name": name, "ok": error is None, "ms": ms, "error": error}


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
    conv = db.execute(
        "SELECT intent, intents_seen FROM conversations WHERE id = ?",
        (conversation_id,),
    ).fetchone()
    state = _TurnState(conv["intent"], json.loads(conv["intents_seen"]))

    user = {"role": "user", "content": redacted}
    stored: list[dict[str, Any]] = [user]
    tools = list(TOOLS.values())
    tools_called: list[dict[str, Any]] = []
    cost = 0.0
    all_reported = True
    prompt_tokens = completion_tokens = 0
    said: list[str] = []

    for _ in range(MAX_TOOL_ROUNDS):
        remaining = ctx.settings.TURN_DEADLINE - (ctx.clock.monotonic() - started)
        result = ctx.model.complete(
            [{"role": "system", "content": INSTRUCTIONS}, *history, *stored],
            tools=tools,
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
            output, entry = _run_tool(ctx, state, call)
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
        choices=[],
        booking=None,
        waitlisted=False,
        actions=[],
        turn=TurnInfo(seq=seq, latency_ms=latency_ms),
    )

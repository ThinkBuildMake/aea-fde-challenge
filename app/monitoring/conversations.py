"""Monitoring's conversation reads and the two writes it owns: flags and eval drafts."""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from typing import Any

from app.context import AppContext
from app.conversation.service import close_idle_conversations
from app.errors import AppError
from app.followups.service import _view as handoff_view
from app.logs import log_event
from app.safety.service import redact_card_numbers
from app.scheduling import store as scheduling_store
from app.types import (
    CandidateCreated,
    ConversationDetail,
    ConversationList,
    ConversationSummary,
    EvalCandidateItem,
    EvalCandidateList,
    EvalCandidateRef,
    FlagCreated,
    FlagInfo,
    FlagView,
    RetrievedRef,
    ToolCall,
    TurnView,
)

_SUMMARY_COLUMNS = (
    "c.id, c.public_id, c.started_at, c.ended_at, c.intent, c.outcome, c.outcome_reason,"
    " c.turn_count, c.cost_usd, c.solved, c.customer_id,"
    " EXISTS (SELECT 1 FROM flags f WHERE f.conversation_id = c.id) AS flagged,"
    " EXISTS (SELECT 1 FROM handoffs h WHERE h.conversation_id = c.id) AS has_handoff"
)


def _not_found() -> AppError:
    return AppError(404, "conversation_not_found", "No conversation matches this id.")


def _customer_names(ctx: AppContext, customer_ids: set[str]) -> dict[str, str]:
    if not customer_ids:
        return {}
    marks = ",".join("?" * len(customer_ids))
    try:
        with closing(scheduling_store.connect(ctx)) as conn:
            rows = conn.execute(
                f"SELECT customer_id, name FROM customers WHERE customer_id IN ({marks})",
                tuple(customer_ids),
            ).fetchall()
    except (sqlite3.Error, scheduling_store.SchedulingUnavailable):
        return {}
    return {row[0]: row[1] for row in rows}


def _summary(row: sqlite3.Row, names: dict[str, str]) -> ConversationSummary:
    return ConversationSummary(
        public_id=row["public_id"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        intent=row["intent"],
        outcome=row["outcome"],
        outcome_reason=row["outcome_reason"],
        turn_count=row["turn_count"],
        cost_usd=row["cost_usd"],
        solved=row["solved"],
        flagged=bool(row["flagged"]),
        has_handoff=bool(row["has_handoff"]),
        customer_name=names.get(row["customer_id"] or ""),
    )


def _sweep_idle(ctx: AppContext) -> None:
    try:
        close_idle_conversations(ctx, datetime.now(UTC))
    except Exception as exc:  # noqa: BLE001 - a failed sweep must not block the read
        log_event("monitoring_close_idle_failed", error=type(exc).__name__)


def list_conversations(
    ctx: AppContext, outcome: str | None, limit: int
) -> ConversationList:
    _sweep_idle(ctx)
    where, args = "", ()
    if outcome == "active":
        where = "WHERE c.outcome IS NULL"
    elif outcome is not None:
        where, args = "WHERE c.outcome = ?", (outcome,)
    with closing(ctx.open_app_db()) as conn:
        rows = conn.execute(
            f"SELECT {_SUMMARY_COLUMNS} FROM conversations c {where}"
            " ORDER BY c.started_at DESC, c.rowid DESC LIMIT ?",
            (*args, limit),
        ).fetchall()
    names = _customer_names(ctx, {r["customer_id"] for r in rows if r["customer_id"]})
    return ConversationList(conversations=[_summary(r, names) for r in rows])


def _find(conn: sqlite3.Connection, public_id: str) -> sqlite3.Row:
    row = conn.execute(
        f"SELECT {_SUMMARY_COLUMNS} FROM conversations c WHERE c.public_id = ?",
        (public_id,),
    ).fetchone()
    if row is None:
        raise _not_found()
    return row


def _turn(row: sqlite3.Row) -> TurnView:
    return TurnView(
        seq=row["seq"],
        kind=row["kind"],
        caller_text=row["caller_text"],
        reply_text=row["reply_text"],
        tools_called=[
            ToolCall(name=t["name"], ok=bool(t["ok"]), ms=int(t.get("ms", 0)))
            for t in json.loads(row["tools_called"])
        ],
        retrieved=[
            RetrievedRef(source_file=r["sourceFile"], score=r["score"])
            for r in json.loads(row["retrieved"])
        ],
        safety_verdict=row["safety_verdict"],
        latency_ms=row["latency_ms"],
        error=row["error"],
        fallback_used=bool(row["fallback_used"]),
        cost_usd=row["cost_usd"],
        trace_id=row["trace_id"],
    )


def get_conversation(ctx: AppContext, public_id: str) -> ConversationDetail:
    _sweep_idle(ctx)
    with closing(ctx.open_app_db()) as conn:
        row = _find(conn, public_id)
        secret_id = row["id"]
        turns = conn.execute(
            "SELECT seq, kind, caller_text, reply_text, tools_called, retrieved,"
            " safety_verdict, latency_ms, error, fallback_used, cost_usd, trace_id"
            " FROM turns WHERE conversation_id = ? ORDER BY seq",
            (secret_id,),
        ).fetchall()
        flags = conn.execute(
            "SELECT id, note, created_at FROM flags WHERE conversation_id = ? ORDER BY id",
            (secret_id,),
        ).fetchall()
        candidate = conn.execute(
            "SELECT scenario_id FROM eval_candidates WHERE conversation_id = ?",
            (secret_id,),
        ).fetchone()
        handoff = handoff_view(conn, secret_id, ctx)
    names = _customer_names(ctx, {row["customer_id"]} if row["customer_id"] else set())
    return ConversationDetail(
        summary=_summary(row, names),
        turns=[_turn(t) for t in turns],
        handoff=handoff,
        flags=[
            FlagView(id=f["id"], note=f["note"], created_at=f["created_at"])
            for f in flags
        ],
        eval_candidate=(
            EvalCandidateRef(scenario_id=candidate["scenario_id"])
            if candidate
            else None
        ),
    )


def flag_conversation(ctx: AppContext, public_id: str, note: str) -> FlagCreated:
    with closing(ctx.open_app_db()) as conn:
        secret_id = _find(conn, public_id)["id"]
        if not note.strip():
            raise AppError(
                422, "note_required", "A note saying what was wrong is required."
            )
        cursor = conn.execute(
            "INSERT INTO flags (conversation_id, note) VALUES (?, ?)"
            " RETURNING id, created_at",
            (secret_id, redact_card_numbers(note.strip()).text),
        )
        flag_id, created_at = cursor.fetchone()
        conn.commit()
    return FlagCreated(flag=FlagInfo(id=flag_id, created_at=created_at))


def _scenario(
    conn: sqlite3.Connection, row: sqlite3.Row, scenario_id: str
) -> dict[str, Any]:
    texts = [
        redact_card_numbers(r["caller_text"]).text
        for r in conn.execute(
            "SELECT caller_text FROM turns WHERE conversation_id = ?"
            " AND kind = 'message' ORDER BY seq",
            (row["id"],),
        )
    ]
    handoff = conn.execute(
        "SELECT reason FROM handoffs WHERE conversation_id = ? ORDER BY id LIMIT 1",
        (row["id"],),
    ).fetchone()
    return {
        "id": scenario_id,
        "title": "",
        "basedOn": row["public_id"],
        "driver": "",
        "kind": "",
        "customerId": row["customer_id"],
        "invoiceId": None,
        "opening": texts[0] if texts else "",
        "callerMessages": texts,
        "callerBrief": "",
        "maxTurns": row["turn_count"],
        "observed": {
            "outcome": row["outcome"],
            "outcomeReason": row["outcome_reason"],
            "intent": row["intent"],
            "handoffReason": handoff["reason"] if handoff else None,
        },
        "expected": {
            "outcome": None,
            "facts": [],
            "forbidden": [],
            "dbChange": None,
            "handoffReason": None,
        },
    }


def create_eval_candidate(
    ctx: AppContext, public_id: str
) -> tuple[CandidateCreated, bool]:
    """The draft for this conversation; the flag is True when this call made it."""
    _sweep_idle(ctx)
    scenario_id = "CAND-" + public_id[:8]
    with closing(ctx.open_app_db()) as conn:
        row = _find(conn, public_id)
        if row["outcome"] is None:
            raise AppError(
                409,
                "conversation_active",
                "A conversation still in progress cannot become a test.",
            )
        cursor = conn.execute(
            "INSERT INTO eval_candidates (conversation_id, scenario_id, scenario)"
            " VALUES (?, ?, ?) ON CONFLICT (conversation_id) DO NOTHING",
            (row["id"], scenario_id, json.dumps(_scenario(conn, row, scenario_id))),
        )
        created = cursor.rowcount == 1
        conn.commit()
    return CandidateCreated(
        candidate=EvalCandidateRef(scenario_id=scenario_id)
    ), created


def list_eval_candidates(ctx: AppContext) -> EvalCandidateList:
    with closing(ctx.open_app_db()) as conn:
        rows = conn.execute(
            "SELECT scenario_id, scenario FROM eval_candidates ORDER BY id"
        ).fetchall()
    return EvalCandidateList(
        candidates=[
            EvalCandidateItem(
                scenario_id=r["scenario_id"], scenario=json.loads(r["scenario"])
            )
            for r in rows
        ]
    )

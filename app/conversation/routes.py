import logging
import sqlite3
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response

from app.context import AppContext, get_ctx, get_db
from app.conversation.service import close_idle_conversations
from app.conversation.turn import run_turn
from app.errors import AppError
from app.negotiation import respond
from app.types import (
    SendMessageRequest,
    SolvedRequest,
    SolvedResponse,
    StartConversationResponse,
)

router = APIRouter()
log = logging.getLogger("meridian.conversation")

GREETING = (
    "Hi, I am the Meridian assistant. I can book a visit, check or change one, answer "
    "questions about fees, membership and warranty, or look up your bill. What do you need?"
)
SOLVED_YES_TEXT = "Thanks for letting us know. Have a good day."
SOLVED_NO_TEXT = (
    "Sorry that did not solve it. Would you like me to pass you to a person?"
)
NOW_SQL = "strftime('%Y-%m-%dT%H:%M:%fZ','now')"


def require_conversation(db: sqlite3.Connection, conversation_id: str) -> None:
    row = db.execute(
        "SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)
    ).fetchone()
    if row is None:
        raise AppError(
            404, "conversation_not_found", "No conversation matches this id."
        )


@router.get("/", response_class=HTMLResponse)
def caller_page(request: Request, ctx: AppContext = Depends(get_ctx)) -> Response:
    return ctx.templates.TemplateResponse(request, "chat.html", {"greeting": GREETING})


@router.post("/conversations")
def start_conversation(
    request: Request,
    ctx: AppContext = Depends(get_ctx),
    db: sqlite3.Connection = Depends(get_db),
) -> Response:
    try:
        close_idle_conversations(ctx, datetime.now(UTC))
    except Exception:
        log.warning("idle sweep skipped", exc_info=True)
    conversation_id = str(uuid.uuid4())
    db.execute("INSERT INTO conversations (id) VALUES (?)", (conversation_id,))
    body = StartConversationResponse(
        conversation_id=conversation_id,
        status="active",
        greeting=GREETING,
        demo_faults=ctx.settings.DEMO_FAULT_INJECTION,
    )
    return respond(request, body, 201)


@router.post("/conversations/{conversation_id}/messages")
def send_message(
    conversation_id: str,
    payload: SendMessageRequest,
    request: Request,
    ctx: AppContext = Depends(get_ctx),
    db: sqlite3.Connection = Depends(get_db),
) -> Response:
    require_conversation(db, conversation_id)
    if db.execute(
        "SELECT outcome FROM conversations WHERE id = ?", (conversation_id,)
    ).fetchone()[0]:
        raise AppError(409, "conversation_ended", "This conversation has ended.")
    return respond(request, run_turn(ctx, db, conversation_id, payload.text))


@router.post("/conversations/{conversation_id}/solved")
def record_solved(
    conversation_id: str,
    payload: SolvedRequest,
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
) -> Response:
    require_conversation(db, conversation_id)
    answer = payload.answer
    if answer not in ("yes", "no"):
        raise AppError(422, "invalid_answer", "The answer must be yes or no.")
    db.execute("BEGIN IMMEDIATE")
    try:
        solved, outcome, handed_off = db.execute(
            "SELECT solved, outcome, EXISTS("
            "SELECT 1 FROM handoffs WHERE conversation_id = conversations.id) "
            "FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if solved is not None:
            raise AppError(409, "already_answered", "This was already answered.")
        if outcome is not None or handed_off:
            raise AppError(409, "conversation_ended", "This conversation has ended.")
        ending = (
            ", outcome = 'contained', ended_at = " + NOW_SQL if answer == "yes" else ""
        )
        db.execute(
            f"UPDATE conversations SET solved = ?, solved_at = {NOW_SQL}, "
            f"last_activity_at = {NOW_SQL}{ending} "
            "WHERE id = ? AND solved IS NULL AND outcome IS NULL",
            (answer, conversation_id),
        )
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    body = SolvedResponse(
        saved=True,
        status="ended" if answer == "yes" else "active",
        text=SOLVED_YES_TEXT if answer == "yes" else SOLVED_NO_TEXT,
        actions=["new_conversation"],
    )
    return respond(request, body)

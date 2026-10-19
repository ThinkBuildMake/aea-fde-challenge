import sqlite3
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response

from app.context import AppContext, get_ctx, get_db
from app.errors import AppError
from app.negotiation import respond
from app.types import (
    Reply,
    SendMessageRequest,
    SolvedRequest,
    SolvedResponse,
    StartConversationResponse,
    TurnInfo,
)

router = APIRouter()

GREETING = (
    "Hi, I am the Meridian assistant. I can book a visit, check or change one, answer "
    "questions about fees, membership and warranty, or look up your bill. What do you need?"
)


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
    started = ctx.clock.monotonic()
    result = ctx.model.complete(
        [{"role": "user", "content": payload.text}],
        timeout_s=ctx.settings.TURN_DEADLINE,
    )
    latency_ms = round((ctx.clock.monotonic() - started) * 1000)
    reply = Reply(
        conversation_id=conversation_id,
        status="active",
        text=str(result.message.get("content", "")),
        banner="none",
        choices=[],
        booking=None,
        waitlisted=False,
        actions=[],
        turn=TurnInfo(seq=1, latency_ms=latency_ms),
    )
    return respond(request, reply)


@router.post("/conversations/{conversation_id}/solved")
def record_solved(
    conversation_id: str,
    payload: SolvedRequest,
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
) -> Response:
    require_conversation(db, conversation_id)
    body = SolvedResponse(
        saved=True,
        status="ended",
        text="Thanks, your answer is saved. This conversation has ended.",
        actions=["new_conversation"],
    )
    return respond(request, body)

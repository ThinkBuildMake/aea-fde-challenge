import sqlite3

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from app.context import AppContext, get_ctx, get_db
from app.conversation.routes import require_conversation
from app.errors import AppError
from app.followups.service import placeholder_handoff, set_callback_window
from app.negotiation import respond
from app.types import (
    CallbackWindowRequest,
    CallbackWindowResponse,
    FollowedUpRequest,
    HandoffList,
    HandoffResponse,
    WaitlistList,
)

router = APIRouter()


@router.post("/conversations/{conversation_id}/callback-window")
def submit_callback_window(
    conversation_id: str,
    payload: CallbackWindowRequest,
    request: Request,
    ctx: AppContext = Depends(get_ctx),
    db: sqlite3.Connection = Depends(get_db),
) -> Response:
    require_conversation(db, conversation_id)
    handoff = set_callback_window(ctx, conversation_id, payload.window)
    text = f"Thanks. We will call you back in the {payload.window}."
    return respond(request, CallbackWindowResponse(handoff=handoff, text=text))


@router.get("/handoffs")
def list_handoffs(request: Request, status: str = "open") -> Response:
    if status not in ("open", "followed_up"):
        raise AppError(422, "invalid_status", "Status must be open or followed_up.")
    return respond(request, HandoffList(handoffs=[]))


@router.post("/handoffs/{handoff_id}/followed-up")
def mark_followed_up(
    handoff_id: int, request: Request, payload: FollowedUpRequest | None = None
) -> Response:
    followed_up = True if payload is None else payload.followed_up
    handoff = placeholder_handoff()
    handoff.id = handoff_id
    handoff.status = "followed_up" if followed_up else "open"
    return respond(request, HandoffResponse(handoff=handoff))


@router.get("/waitlist")
def list_waitlist(request: Request) -> Response:
    return respond(request, WaitlistList(entries=[]))

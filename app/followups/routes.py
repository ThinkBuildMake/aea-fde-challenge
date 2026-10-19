import sqlite3
from typing import Literal, cast, get_args

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from app.context import AppContext, get_ctx, get_db
from app.conversation.routes import require_conversation
from app.errors import AppError
from app.followups.service import (
    HandoffNotFound,
    NoHandoff,
    mark_handoff_followed_up,
    set_callback_window,
)
from app.followups.service import list_handoffs as list_handoffs_service
from app.followups.service import list_waitlist as list_waitlist_service
from app.negotiation import respond
from app.types import (
    CallbackWindow,
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
    window = payload.window
    if window not in get_args(CallbackWindow):
        raise AppError(422, "invalid_window", "Choose morning, afternoon or evening.")
    try:
        handoff = set_callback_window(
            ctx, conversation_id, cast(CallbackWindow, window)
        )
    except NoHandoff:
        raise AppError(404, "no_handoff", "This conversation has no handoff.") from None
    text = f"Thanks. We will call you back in the {window}."
    return respond(request, CallbackWindowResponse(handoff=handoff, text=text))


@router.get("/handoffs")
def list_handoffs(
    request: Request,
    status: str = "open",
    ctx: AppContext = Depends(get_ctx),
) -> Response:
    if status not in ("open", "followed_up"):
        raise AppError(422, "invalid_status", "Status must be open or followed_up.")
    handoffs = list_handoffs_service(ctx, cast(Literal["open", "followed_up"], status))
    return respond(request, HandoffList(handoffs=handoffs))


@router.post("/handoffs/{handoff_id}/followed-up")
def mark_followed_up(
    handoff_id: int,
    request: Request,
    payload: FollowedUpRequest | None = None,
    ctx: AppContext = Depends(get_ctx),
) -> Response:
    followed_up = True if payload is None else payload.followed_up
    try:
        handoff = mark_handoff_followed_up(ctx, handoff_id, followed_up)
    except HandoffNotFound:
        raise AppError(
            404, "handoff_not_found", "No handoff matches this id."
        ) from None
    return respond(request, HandoffResponse(handoff=handoff))


@router.get("/waitlist")
def list_waitlist(request: Request, ctx: AppContext = Depends(get_ctx)) -> Response:
    return respond(request, WaitlistList(entries=list_waitlist_service(ctx)))

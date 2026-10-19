from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response

from app.admin import require_admin
from app.context import AppContext, get_ctx
from app.errors import AppError
from app.monitoring import conversations
from app.monitoring.service import get_health, get_overview
from app.monitoring.view import overview_view, page_data
from app.negotiation import respond
from app.types import (
    FlagRequest,
)

router = APIRouter()

TABS = [
    ("overview", "Overview"),
    ("handoffs", "Handoffs"),
    ("waitlist", "Waitlist"),
    ("conversations", "Conversations"),
]

OUTCOMES = {"contained", "handoff", "safety_stop", "failed", "active"}


@router.get("/business", response_class=HTMLResponse)
def business_page(
    request: Request, tab: str = "overview", ctx: AppContext = Depends(get_ctx)
) -> Response:
    if tab not in dict(TABS):
        tab = "overview"
    context: dict[str, Any] = {"tabs": TABS, "tab": tab}
    context["view"] = overview_view(get_overview(ctx))
    if tab != "overview":
        context["data"] = page_data(ctx.settings.LANGFUSE_BASE_URL)
    return ctx.templates.TemplateResponse(request, "business.html", context)


@router.get("/overview")
def overview(
    request: Request, days: int = 7, ctx: AppContext = Depends(get_ctx)
) -> Response:
    if not 1 <= days <= 90:
        raise AppError(422, "invalid_days", "Days must be between 1 and 90.")
    return respond(request, get_overview(ctx, days))


@router.get("/conversations")
def list_conversations(
    request: Request,
    outcome: str | None = None,
    limit: int = 50,
    ctx: AppContext = Depends(get_ctx),
) -> Response:
    if outcome is not None and outcome not in OUTCOMES:
        raise AppError(
            422, "invalid_outcome", "Outcome is not one of the known values."
        )
    return respond(
        request, conversations.list_conversations(ctx, outcome, min(max(limit, 1), 200))
    )


@router.get("/conversations/{public_id}")
def get_conversation(
    public_id: str, request: Request, ctx: AppContext = Depends(get_ctx)
) -> Response:
    return respond(request, conversations.get_conversation(ctx, public_id))


@router.post("/conversations/{public_id}/flag")
def flag_conversation(
    public_id: str,
    payload: FlagRequest,
    request: Request,
    ctx: AppContext = Depends(get_ctx),
) -> Response:
    return respond(
        request, conversations.flag_conversation(ctx, public_id, payload.note), 201
    )


@router.post("/conversations/{public_id}/eval-candidate")
def create_eval_candidate(
    public_id: str, request: Request, ctx: AppContext = Depends(get_ctx)
) -> Response:
    body, created = conversations.create_eval_candidate(ctx, public_id)
    return respond(request, body, 201 if created else 200)


@router.api_route("/health", methods=["GET", "HEAD"])
def health(request: Request, ctx: AppContext = Depends(get_ctx)) -> Response:
    return respond(request, get_health(ctx))


@router.get("/admin/eval-candidates", dependencies=[Depends(require_admin)])
def list_eval_candidates(
    request: Request, ctx: AppContext = Depends(get_ctx)
) -> Response:
    return respond(request, conversations.list_eval_candidates(ctx))

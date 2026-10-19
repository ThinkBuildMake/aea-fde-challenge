import sqlite3

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response

from app.admin import require_admin
from app.context import AppContext, get_ctx, get_db
from app.errors import AppError
from app.knowledge.service import index_status
from app.monitoring.service import get_overview, now_iso
from app.negotiation import respond
from app.scheduling.service import scheduling_status
from app.types import (
    CandidateCreated,
    ConversationDetail,
    ConversationList,
    ConversationSummary,
    EvalCandidateList,
    EvalCandidateRef,
    FlagCreated,
    FlagInfo,
    FlagRequest,
    Health,
    HealthComponents,
)

router = APIRouter()

TABS = [
    ("overview", "Overview"),
    ("handoffs", "Handoffs"),
    ("waitlist", "Waitlist"),
    ("conversations", "Conversations"),
]

METRIC_PANELS = [
    ("settled", "Calls settled by the agent"),
    ("booking-completion", "Booking completion"),
    ("handoffs-handled-topics", "Handoffs on handled topics"),
    ("flagged-wrong", "Flagged-wrong rate"),
    ("time-to-first-reply", "Time to first reply"),
    ("time-write-turn", "Time for a turn that books, moves or cancels"),
    ("booking-mismatches", "Booking mismatches"),
    ("errors-shown", "Errors shown to callers"),
    ("model-spend", "Total model spend"),
]

OUTCOMES = {"contained", "handoff", "safety_stop", "failed", "active"}


def require_public(db: sqlite3.Connection, public_id: str) -> str:
    row = db.execute(
        "SELECT id FROM conversations WHERE public_id = ?", (public_id,)
    ).fetchone()
    if row is None:
        raise AppError(
            404, "conversation_not_found", "No conversation matches this id."
        )
    return row[0]


@router.get("/business", response_class=HTMLResponse)
def business_page(
    request: Request, tab: str = "overview", ctx: AppContext = Depends(get_ctx)
) -> Response:
    if tab not in dict(TABS):
        tab = "overview"
    return ctx.templates.TemplateResponse(
        request,
        "business.html",
        {"tabs": TABS, "tab": tab, "panels": METRIC_PANELS},
    )


@router.get("/overview")
def overview(
    request: Request, days: int = 7, ctx: AppContext = Depends(get_ctx)
) -> Response:
    if not 1 <= days <= 90:
        raise AppError(422, "invalid_days", "Days must be between 1 and 90.")
    return respond(request, get_overview(ctx))


@router.get("/conversations")
def list_conversations(
    request: Request, outcome: str | None = None, limit: int = 50
) -> Response:
    if outcome is not None and outcome not in OUTCOMES:
        raise AppError(
            422, "invalid_outcome", "Outcome is not one of the known values."
        )
    return respond(request, ConversationList(conversations=[]))


@router.get("/conversations/{public_id}")
def get_conversation(
    public_id: str, request: Request, db: sqlite3.Connection = Depends(get_db)
) -> Response:
    require_public(db, public_id)
    row = db.execute(
        "SELECT public_id, started_at, ended_at, intent, outcome, outcome_reason, turn_count,"
        " cost_usd, solved FROM conversations WHERE public_id = ?",
        (public_id,),
    ).fetchone()
    summary = ConversationSummary(
        public_id=row["public_id"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        intent=row["intent"],
        outcome=row["outcome"],
        outcome_reason=row["outcome_reason"],
        turn_count=row["turn_count"],
        cost_usd=row["cost_usd"],
        solved=row["solved"],
        flagged=False,
        has_handoff=False,
        customer_name=None,
    )
    detail = ConversationDetail(
        summary=summary, turns=[], handoff=None, flags=[], eval_candidate=None
    )
    return respond(request, detail)


@router.post("/conversations/{public_id}/flag")
def flag_conversation(
    public_id: str,
    payload: FlagRequest,
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
) -> Response:
    require_public(db, public_id)
    if not payload.note.strip():
        raise AppError(
            422, "note_required", "A note saying what was wrong is required."
        )
    return respond(request, FlagCreated(flag=FlagInfo(id=0, created_at=now_iso())), 201)


@router.post("/conversations/{public_id}/eval-candidate")
def create_eval_candidate(
    public_id: str, request: Request, db: sqlite3.Connection = Depends(get_db)
) -> Response:
    conversation_id = require_public(db, public_id)
    body = CandidateCreated(
        candidate=EvalCandidateRef(scenario_id="CAND-" + conversation_id[:8])
    )
    return respond(request, body, 201)


@router.api_route("/health", methods=["GET", "HEAD"])
def health(request: Request, ctx: AppContext = Depends(get_ctx)) -> Response:
    body = Health(
        status="degraded",
        components=HealthComponents(
            scheduling_db="ok" if scheduling_status(ctx) == "ok" else "error",
            app_db="ok",
            index="loaded" if index_status(ctx).loaded else "missing",
        ),
    )
    return respond(request, body)


@router.get("/admin/eval-candidates", dependencies=[Depends(require_admin)])
def list_eval_candidates(request: Request) -> Response:
    return respond(request, EvalCandidateList(candidates=[]))

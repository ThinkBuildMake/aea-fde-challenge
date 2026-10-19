from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from app.admin import require_admin
from app.context import AppContext, get_ctx
from app.negotiation import respond
from app.scheduling.service import reset_scheduling
from app.types import ResetSchedulingResult

router = APIRouter()


@router.post("/admin/reset-scheduling", dependencies=[Depends(require_admin)])
def reset_scheduling_route(
    request: Request, ctx: AppContext = Depends(get_ctx)
) -> Response:
    result = reset_scheduling(ctx)
    body = ResetSchedulingResult(
        restored=False, snapshot_id=result.snapshot_id, slot_counts=result.slot_counts
    )
    return respond(request, body)

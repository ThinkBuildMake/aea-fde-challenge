from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from app.admin import require_admin
from app.context import AppContext, get_ctx
from app.knowledge.service import rebuild_index
from app.negotiation import respond

router = APIRouter()


@router.post("/admin/rebuild-index", dependencies=[Depends(require_admin)])
def rebuild_index_route(
    request: Request, ctx: AppContext = Depends(get_ctx)
) -> Response:
    return respond(request, rebuild_index(ctx))

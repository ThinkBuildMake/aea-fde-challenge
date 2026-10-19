"""Content negotiation: JSON by default, an HTML fragment of the same fields for htmx."""

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from app.context import get_ctx


def respond(request: Request, model: BaseModel, status_code: int = 200) -> Response:
    data = model.model_dump(by_alias=True, mode="json")
    headers = {"Vary": "HX-Request"}
    if request.headers.get("HX-Request") == "true":
        return get_ctx(request).templates.TemplateResponse(
            request,
            "fragments/fields.html",
            {"data": data},
            status_code=status_code,
            headers=headers,
        )
    return JSONResponse(data, status_code=status_code, headers=headers)

"""One error format: {error, message}, always JSON, never a stack trace."""

import json
import sys

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.message = message


def _body(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": code, "message": message}, status_code=status)


_HTTP_CODES = {404: "not_found", 405: "method_not_allowed"}


def install(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    def app_error(request: Request, exc: AppError) -> JSONResponse:
        return _body(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    def invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _body(
            422, "invalid_request", "The request body or parameters are not valid."
        )

    @app.exception_handler(StarletteHTTPException)
    def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "http_error")
        message = {404: "Nothing is served at this address."}.get(
            exc.status_code, "The request could not be served."
        )
        if exc.status_code == 405:
            message = "This method is not allowed here."
        return _body(exc.status_code, code, message)

    @app.exception_handler(Exception)
    def unexpected(request: Request, exc: Exception) -> JSONResponse:
        sys.stdout.write(
            json.dumps(
                {"event": "error", "path": request.url.path, "type": type(exc).__name__}
            )
            + "\n"
        )
        return _body(500, "internal_error", "Something went wrong on our side.")

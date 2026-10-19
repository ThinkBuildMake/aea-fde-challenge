import hmac

from fastapi import Request

from app.context import get_ctx
from app.errors import AppError


def require_admin(request: Request) -> None:
    """Bearer ADMIN_TOKEN, compared in constant time; anything else is 401 and no work is done."""
    expected = "Bearer " + get_ctx(request).settings.ADMIN_TOKEN.get_secret_value()
    given = request.headers.get("Authorization", "")
    if not hmac.compare_digest(given.encode(), expected.encode()):
        raise AppError(401, "unauthorized", "A valid admin token is required.")

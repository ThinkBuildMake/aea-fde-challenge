"""Per-address caps (GC-3): in-process moving-window counters, one limiter per app."""

from fastapi import Request
from limits import RateLimitItem, RateLimitItemPerHour, RateLimitItemPerMinute
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter

from app.errors import AppError


def client_address(request: Request) -> str:
    """The rightmost X-Forwarded-For entry: the address the platform's proxy saw."""
    forwarded = [
        part.strip()
        for part in request.headers.get("x-forwarded-for", "").split(",")
        if part.strip()
    ]
    if forwarded:
        return forwarded[-1]
    return request.client.host if request.client else "unknown"


class RateLimiter:
    def __init__(self) -> None:
        self._limiter = MovingWindowRateLimiter(MemoryStorage())

    def check(self, scope: str, key: str, item: RateLimitItem) -> None:
        if not self._limiter.hit(item, scope, key):
            raise AppError(
                429,
                "rate_limited",
                "Too many requests from this address. Please wait a moment and try again.",
            )


def _check(request: Request, scope: str, item: RateLimitItem) -> None:
    request.app.state.ctx.limiter.check(scope, client_address(request), item)


def limit_new_conversations(request: Request) -> None:
    settings = request.app.state.ctx.settings
    _check(
        request,
        "new_conversation",
        RateLimitItemPerHour(settings.NEW_CONVERSATIONS_PER_HOUR),
    )


def limit_messages(request: Request) -> None:
    settings = request.app.state.ctx.settings
    _check(request, "message", RateLimitItemPerMinute(settings.MESSAGES_PER_MINUTE))


def limit_business_writes(request: Request) -> None:
    settings = request.app.state.ctx.settings
    _check(
        request,
        "business_write",
        RateLimitItemPerMinute(settings.BUSINESS_WRITES_PER_MINUTE),
    )

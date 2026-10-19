import sqlite3
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.db import connect_app_db
from app.knowledge.embeddings import Embedder
from app.knowledge.index import IndexStore
from app.llm import ModelProvider
from app.settings import Settings

if TYPE_CHECKING:
    from app.conversation.tracing import Tracer
    from app.monitoring.spend import KeyUsageCache
    from app.safety.service import SafetyClassifier


class Clock(Protocol):
    def monotonic(self) -> float: ...


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()


@dataclass
class AppContext:
    settings: Settings
    model: ModelProvider
    clock: Clock
    templates: Jinja2Templates
    embedder: Embedder
    index: IndexStore
    spend: "KeyUsageCache"
    safety: "SafetyClassifier | None" = None
    tracer: "Tracer | None" = None

    def open_app_db(self) -> sqlite3.Connection:
        return connect_app_db(self.settings.APP_DB_PATH)


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    conn = get_ctx(request).open_app_db()
    try:
        yield conn
    finally:
        conn.close()

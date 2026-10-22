from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import errors
from app.context import AppContext, Clock, SystemClock
from app.conversation import tracing
from app.conversation.routes import router as conversation_router
from app.followups.routes import router as followups_router
from app.headers import SecurityHeadersMiddleware
from app.knowledge.embeddings import Embedder, OpenRouterEmbedder
from app.knowledge.index import IndexStore
from app.knowledge.routes import router as knowledge_router
from app.llm import ModelProvider, StubModelProvider
from app.monitoring.routes import router as monitoring_router
from app.monitoring.spend import KeyUsageCache, KeyUsageReader, OpenRouterKeyUsage
from app.scheduling.routes import router as scheduling_router
from app.settings import Settings

APP_DIR = Path(__file__).resolve().parent


def create_app(
    settings: Settings,
    *,
    model: ModelProvider | None = None,
    clock: Clock | None = None,
    embedder: Embedder | None = None,
    key_usage: KeyUsageReader | None = None,
    tracer: tracing.Tracer | None = None,
) -> FastAPI:
    embedder = embedder or OpenRouterEmbedder(settings)
    clock = clock or SystemClock()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        if app.state.ctx.tracer is not None:
            app.state.ctx.tracer.flush(5)
        for classifier in (app.state.ctx.safety, app.state.ctx.confirm):
            close = getattr(classifier, "close", None)
            if close is not None:
                close()

    app = FastAPI(
        title="Meridian",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.ctx = AppContext(
        settings=settings,
        model=model or StubModelProvider(),
        clock=clock,
        templates=Jinja2Templates(directory=APP_DIR / "templates"),
        embedder=embedder,
        index=IndexStore(settings.INDEX_PATH, embedder.model),
        spend=KeyUsageCache(key_usage or OpenRouterKeyUsage(settings), clock),
        tracer=tracer if tracer is not None else tracing.tracer_for(settings),
    )
    app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
    errors.install(app)
    app.add_middleware(SecurityHeadersMiddleware)
    for router in (
        conversation_router,
        followups_router,
        monitoring_router,
        knowledge_router,
        scheduling_router,
    ):
        app.include_router(router)
    return app

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import errors
from app.context import AppContext, Clock, SystemClock
from app.conversation.routes import router as conversation_router
from app.followups.routes import router as followups_router
from app.knowledge.routes import router as knowledge_router
from app.llm import ModelProvider, StubModelProvider
from app.monitoring.routes import router as monitoring_router
from app.scheduling.routes import router as scheduling_router
from app.settings import Settings

APP_DIR = Path(__file__).resolve().parent


def create_app(
    settings: Settings,
    *,
    model: ModelProvider | None = None,
    clock: Clock | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        close = getattr(app.state.ctx.safety, "close", None)
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
        clock=clock or SystemClock(),
        templates=Jinja2Templates(directory=APP_DIR / "templates"),
    )
    app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
    errors.install(app)
    for router in (
        conversation_router,
        followups_router,
        monitoring_router,
        knowledge_router,
        scheduling_router,
    ):
        app.include_router(router)
    return app

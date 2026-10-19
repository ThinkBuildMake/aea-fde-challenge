from fastapi import FastAPI

from app.settings import Settings


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="Meridian")
    app.state.settings = settings
    return app

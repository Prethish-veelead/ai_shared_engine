"""FastAPI entry point. Loads the bot registry on startup and mounts routers."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import admin, ask, health
from app.bots.registry import registry
from app.core.config import get_settings
from app.api.error_handlers import app_error_handler
from app.core.exceptions import AppError
from app.core.logging import configure_logging, get_logger

configure_logging()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    registry.load()                      # validate all bot YAMLs at startup
    log.info("Startup complete: %d bot(s) ready", len(registry.all()))
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title=s.app_name, lifespan=lifespan)
    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(health.router)
    app.include_router(ask.router)
    app.include_router(admin.router)
    return app


app = create_app()

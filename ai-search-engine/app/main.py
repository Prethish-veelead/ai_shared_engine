"""FastAPI entry point. Loads the bot registry on startup, mounts the API under
/api, and (single-origin deploy - docs/SINGLE_ORIGIN_DEPLOY.md) serves both
built frontends as static files on this same port/process.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

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

    # API first - prefix="/api" composes with admin.router's own internal
    # prefix="/admin" into /api/admin/..., exactly what both frontends already
    # request (NEXT_PUBLIC_API_BASE=/api). Registered before any static mount
    # below since Starlette matches routes in registration order and a mount
    # on "/" would otherwise swallow everything, /api included.
    app.include_router(health.router, prefix="/api")
    app.include_router(ask.router, prefix="/api")
    app.include_router(admin.router, prefix="/api")

    # bot-ui's /bot/[botId] is a client-side dynamic route exported as ONE
    # synthetic build artifact (see bot-ui/src/app/bot/[botId]/page.tsx's
    # generateStaticParams). botId is read client-side off the real browser
    # URL, so serving that same shell for ANY bot id - including ones created
    # after this image was built - is correct: the JS bundle loads, then
    # resolves the real id and calls /api/ask/{realBotId}. This is why a new
    # bot never needs a frontend rebuild.
    bot_shell = s.root_static_dir / "bot" / "_shell" / "index.html"

    @app.get("/bot/{bot_id}")
    def bot_chat_shell(bot_id: str) -> FileResponse:
        return FileResponse(bot_shell)

    # Static frontends - only mounted if actually built (absent in a plain
    # local `uvicorn app.main:app` run without the frontend-build Docker
    # stage, which is fine; the API still works standalone).
    # /admin before / : a mount on "/" matches every path as a prefix, so it
    # must be registered last or it would intercept /admin/* too.
    if s.admin_static_dir.is_dir():
        # Mount("/admin", ...) only matches paths starting with "/admin/" (the
        # trailing slash) - the bare "/admin" (its own root, nothing after)
        # does NOT match the mount at all, so without this it falls through
        # to the "/" mount below and serves bot-ui's 404 page instead. Sub-
        # paths (e.g. /admin/usage) are unaffected - StaticFiles' own
        # html=True directory-index logic handles those correctly once a
        # request is already inside the mount.
        @app.get("/admin")
        def admin_root_redirect() -> RedirectResponse:
            return RedirectResponse(url="/admin/")

        app.mount("/admin", StaticFiles(directory=s.admin_static_dir, html=True), name="admin-static")
    if s.root_static_dir.is_dir():
        app.mount("/", StaticFiles(directory=s.root_static_dir, html=True), name="root-static")

    return app


app = create_app()

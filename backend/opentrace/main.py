"""FastAPI application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from opentrace import __version__
from opentrace.api.health import router as health_router
from opentrace.api.dashboard import router as dashboard_router
from opentrace.config.settings import get_settings
from opentrace.telemetry.logging import configure_logging

_FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend"


def create_app() -> FastAPI:
    """Create the OpenTrace application with dashboard."""
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings)
        logging.getLogger("opentrace").info(
            "Starting %s in %s environment", settings.service_name, settings.app_env
        )
        yield

    app = FastAPI(
        title=settings.service_name,
        version=__version__,
        debug=settings.debug,
        lifespan=lifespan,
    )
    @app.middleware("http")
    async def add_no_cache_header(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    app.include_router(health_router)
    app.include_router(dashboard_router)

    # Serve the frontend if the directory exists.
    if _FRONTEND_DIR.exists():
        app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")

    return app


app = create_app()

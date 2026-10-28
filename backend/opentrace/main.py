"""FastAPI application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.responses import JSONResponse
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
        reject = False
        if request.url.path.startswith("/api/"):
            try:
                host = (request.url.hostname or "").lower().rstrip(".")
                reject = host not in {"localhost", "127.0.0.1", "::1"}
            except ValueError:
                reject = True
        if request.url.path.startswith("/api/") and request.method in {
            "POST", "PUT", "PATCH", "DELETE"
        }:
            origin = request.headers.get("origin")
            reject |= request.headers.get("sec-fetch-site") == "cross-site"
            if origin:
                try:
                    parts = urlsplit(origin)
                    reject |= (
                        parts.scheme != request.url.scheme
                        or parts.netloc.casefold()
                        != request.headers.get("host", "").casefold()
                    )
                except ValueError:
                    reject = True
        response = (
            JSONResponse(
                {"detail": "Cross-origin state changes are not allowed."},
                status_code=403,
            )
            if reject
            else await call_next(request)
        )
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

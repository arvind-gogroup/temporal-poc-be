"""FastAPI application factory for the Employee Review Workflow API.

Responsibilities:
    - Lifespan management: opens the Temporal client on startup and closes it
      on shutdown; stores the client on ``app.state.temporal_client``.
    - Middleware: CORS configured for the Next.js frontend at ``localhost:3000``.
    - Global exception handlers: maps ``LookupError`` → 404, ``ValueError`` → 409,
      and all other exceptions → 500, all using the ``ApiResponse`` envelope.
    - Router registration: mounts ``/api/reviews`` from ``app.api.routes.reviews``.
    - Health check: ``GET /health`` returns ``{"status": "ok"}``.

Swagger UI and ReDoc are available at ``/docs`` and ``/redoc`` in non-production
environments (controlled by ``settings.is_production``).
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.schemas.response import error_response
from app.temporal.client import close_temporal_client, get_temporal_client

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage the Temporal client lifecycle alongside the FastAPI application.

    On startup: connects to Temporal and stores the client on ``app.state``
    so it is accessible to route handlers via ``request.app.state.temporal_client``.

    On shutdown: gracefully closes the client connection.

    Args:
        app: The FastAPI application instance.
    """
    logger.info("Starting up — connecting to Temporal at %s", settings.temporal_address)
    app.state.temporal_client = await get_temporal_client()
    logger.info("Temporal client connected")
    yield
    logger.info("Shutting down — closing Temporal client")
    await close_temporal_client()


app = FastAPI(
    title="Employee Review Workflow API",
    version="1.0.0",
    description="Temporal-powered employee performance review orchestration service.",
    contact={"name": "Engineering", "email": "engineering@example.com"},
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(LookupError)
async def lookup_error_handler(request: Request, exc: LookupError) -> JSONResponse:
    """Convert ``LookupError`` (workflow not found) to an HTTP 404 response.

    Args:
        request: The incoming request (unused, required by FastAPI signature).
        exc: The raised ``LookupError`` with a descriptive message.

    Returns:
        A ``JSONResponse`` with status 404 and the standard error envelope.
    """
    return JSONResponse(status_code=404, content=error_response(str(exc), code=404).model_dump())


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    """Convert ``ValueError`` (wrong workflow state) to an HTTP 409 response.

    Args:
        request: The incoming request (unused, required by FastAPI signature).
        exc: The raised ``ValueError`` describing the state conflict.

    Returns:
        A ``JSONResponse`` with status 409 and the standard error envelope.
    """
    return JSONResponse(status_code=409, content=error_response(str(exc), code=409).model_dump())


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unhandled exceptions; returns HTTP 500.

    Logs the full traceback at ERROR level so it appears in container logs.

    Args:
        request: The incoming request; used for logging method and URL.
        exc: The unhandled exception.

    Returns:
        A ``JSONResponse`` with status 500 and a generic error envelope.
    """
    logger.exception("Unhandled exception on %s %s", request.method, request.url)
    return JSONResponse(
        status_code=500,
        content=error_response("Internal server error", code=500).model_dump(),
    )


from app.api.routes import reviews  # noqa: E402
app.include_router(reviews.router)


@app.get("/health", tags=["health"], include_in_schema=False)
async def health() -> dict:
    """Simple liveness probe.

    Returns:
        ``{"status": "ok"}`` when the API process is running.
    """
    return {"status": "ok"}

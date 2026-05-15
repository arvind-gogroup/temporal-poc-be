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
    return JSONResponse(status_code=404, content=error_response(str(exc), code=404).model_dump())


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=409, content=error_response(str(exc), code=409).model_dump())


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s %s", request.method, request.url)
    return JSONResponse(
        status_code=500,
        content=error_response("Internal server error", code=500).model_dump(),
    )


from app.api.routes import reviews  # noqa: E402
app.include_router(reviews.router)


@app.get("/health", tags=["health"], include_in_schema=False)
async def health() -> dict:
    return {"status": "ok"}

"""
FastAPI application entry point.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import comments, reviews, settings as settings_router
from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.database import engine
from app.db.models.models import Base
from app.db.redis import close_redis, get_redis

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("Starting ReviewAI API", env=settings.APP_ENV)
    # Create tables (use Alembic in production)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Warm Redis connection
    await get_redis()
    yield
    logger.info("Shutting down ReviewAI API")
    await close_redis()


app = FastAPI(
    title="ReviewAI API",
    description="AI-powered Pull Request Review Platform",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionError,
    ReviewAIError,
    ValidationError,
)

# ── Global Exception Handlers ──────────────────────────────────────────────────
@app.exception_handler(ReviewAIError)
async def reviewai_exception_handler(request: Request, exc: ReviewAIError):
    status_code = 400
    if isinstance(exc, NotFoundError):
        status_code = 404
    elif isinstance(exc, ConflictError):
        status_code = 409
    elif isinstance(exc, PermissionError):
        status_code = 403
    return JSONResponse(status_code=status_code, content={"detail": exc.message, "code": exc.code})


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception", path=request.url.path, error=str(exc))
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

# ── Routes ────────────────────────────────────────────────────────────────────
app.include_router(reviews.router, prefix="/api")
app.include_router(comments.router, prefix="/api")
app.include_router(settings_router.router, prefix="/api")


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": settings.APP_NAME, "env": settings.APP_ENV}

"""Main FastAPI application entrypoint with security hardening, CORS, DB health check, and error shielding."""

import logging
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.database import async_session_factory
from app.routers import router

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Re.Think API",
    description="A competitive programming companion tracking growth with structured insights.",
    version="0.1.0",
)

# ── CORS Middleware ──────────────────────────────────────────────────────────
allowed_origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Global Error Handling (Shield internals in production) ───────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Allow explicit HTTPExceptions and validation errors to return their status
    if isinstance(exc, (StarletteHTTPException, HTTPException)):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=getattr(exc, "headers", None),
        )
    if isinstance(exc, RequestValidationError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": exc.errors()},
        )

    # For all unexpected internal exceptions: log full traceback server-side
    logger.exception(f"Unhandled error processing {request.method} {request.url.path}: {exc}")

    # Return sanitized response when debug is False
    if settings.debug:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "internal_server_error", "detail": str(exc), "type": type(exc).__name__},
        )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "internal_server_error"},
    )


# ── Include Protected API Router ──────────────────────────────────────────────
app.include_router(router)


# ── Health & Readiness (Unprotected, checks real DB connectivity) ─────────────
@app.get("/health")
async def health_check():
    """Liveness & readiness probe verifying actual database connectivity via SELECT 1."""
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected", "service": "rethink-api"}
    except Exception as exc:
        logger.error(f"Health check database failure: {exc}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unhealthy", "database": "disconnected", "error": "database_unavailable"},
        )

"""FastAPI entrypoint: HTTP only."""
from __future__ import annotations

import logging

from fastapi import FastAPI, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from nano_banana.config import settings
from nano_banana.db.session import db_service
from nano_banana.error_log import save_error_to_file
from nano_banana.queue.jobs import get_job_queue
from nano_banana.storage.s3 import MinioService
from nano_banana_api.routers import api_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("nano_banana_api")


_docs = (
    {"docs_url": None, "redoc_url": None, "openapi_url": None}
    if settings.SECURITY_DISABLE_OPENAPI
    else {}
)
app = FastAPI(
    title="Nano Banana API",
    description="HTTP API для генерации изображений (Moonez / Replicate / OpenRouter). Очередь обрабатывает worker.",
    version="2.0.0",
    **_docs,
)

CORS_ORIGINS = [origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()] or ["*"]
allow_credentials = "*" not in CORS_ORIGINS
if "*" in CORS_ORIGINS:
    api_lower = (settings.API_URL or "").lower()
    if api_lower.startswith("https://") and "localhost" not in api_lower:
        raise RuntimeError("CORS_ORIGINS=* запрещён в production — укажите явные домены")
    logger.warning("[SECURITY] CORS_ORIGINS содержит '*'. Для продакшена укажите конкретные домены.")
# Cookie auth requires explicit origins + credentials (no *)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS if allow_credentials else CORS_ORIGINS,
    allow_credentials=allow_credentials,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Admin-Bootstrap-Secret"],
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        api_lower = (settings.API_URL or "").lower()
        if settings.SECURITY_ENABLE_HSTS and api_lower.startswith("https://") and "localhost" not in api_lower:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # CSP на API-ответах (дубль к web nginx; не мешает JSON)
        if settings.SECURITY_STRICT_CSP:
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        return response


app.add_middleware(SecurityHeadersMiddleware)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    save_error_to_file({"type": "validation_error", "path": str(request.url.path), "errors": exc.errors()})
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"detail": exc.errors()})


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("[GLOBAL_ERROR] %s", exc, exc_info=True)
    save_error_to_file({"type": "unhandled_exception", "path": str(request.url.path), "error": str(exc)})
    return JSONResponse(status_code=500, content={"detail": "Внутренняя ошибка сервера"})


@app.get("/healthz")
@app.get("/health")
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
async def readyz(request: Request):
    # Не светим checks наружу: только loopback / docker-internal.
    client = request.client.host if request.client else ""
    if client not in ("127.0.0.1", "::1") and not client.startswith("172.") and not client.startswith("10."):
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    checks = {"postgres": False, "redis": False, "s3": False}
    try:
        checks["postgres"] = db_service.ping()
    except Exception as exc:
        logger.warning("[READY] postgres: %s", exc)
    try:
        checks["redis"] = get_job_queue().ping()
    except Exception as exc:
        logger.warning("[READY] redis: %s", exc)
    try:
        checks["s3"] = MinioService().ping()
    except Exception as exc:
        logger.warning("[READY] s3: %s", exc)
    ok = all(checks.values())
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": "ok" if ok else "degraded", "checks": checks},
    )


@app.get("/api")
async def api_info():
    return {"message": "Nano Banana API", "version": "2.0.0"}


app.include_router(api_router, prefix="/api/v1")

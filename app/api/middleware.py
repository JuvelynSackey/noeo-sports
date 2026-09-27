"""Request logging middleware (Phase 12 hardening) — every request gets a
short request id (bound into structlog's contextvars, so every log line
emitted while handling it, from any module, carries the same id) and a
single structured access-log line on completion: method, path, status,
duration. This is the minimum needed to correlate a slow or failing request
across the structured (JSON) logs `app/logging_config.py` sets up, which
`app/api/main.py` otherwise never used.
"""
from __future__ import annotations

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

logger = structlog.get_logger("app.api.access")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = uuid.uuid4().hex[:16]
        start = time.monotonic()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.monotonic() - start) * 1000
            logger.error(
                "request_failed", method=request.method, path=request.url.path, duration_ms=round(duration_ms, 2)
            )
            raise
        else:
            duration_ms = (time.monotonic() - start) * 1000
            logger.info(
                "request_completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round(duration_ms, 2),
            )
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            structlog.contextvars.unbind_contextvars("request_id")

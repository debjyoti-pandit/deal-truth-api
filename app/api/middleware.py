"""HTTP request logging middleware (method/path/status/duration; no bodies)."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

_SKIP_PATHS = frozenset({"/health/live", "/health/ready", "/favicon.ico"})


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration_ms = int((time.perf_counter() - start) * 1000)
            path = request.url.path
            if path not in _SKIP_PATHS:
                logger.info(
                    "http_request method=%s path=%s status=%s duration_ms=%s request_id=%s",
                    request.method,
                    path,
                    status_code,
                    duration_ms,
                    request_id,
                )

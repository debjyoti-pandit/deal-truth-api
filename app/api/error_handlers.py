"""Exception handlers for the consistent error envelope."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from app.api.deps import is_sse_stream_path
from app.core.errors import NamedError, UnauthorizedError

logger = logging.getLogger(__name__)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(NamedError)
    async def named_error_handler(request: Request, exc: NamedError) -> JSONResponse | StreamingResponse:
        request_id = getattr(request.state, "request_id", None)
        level = logging.WARNING if exc.http_status < 500 else logging.ERROR
        logger.log(
            level,
            "named_error code=%s status=%s path=%s request_id=%s message=%s",
            exc.code,
            exc.http_status,
            request.url.path,
            request_id,
            exc.message,
        )
        # EventSource retries forever on HTTP 401. Close as SSE so the UI can stop.
        if isinstance(exc, UnauthorizedError) and is_sse_stream_path(request.url.path):
            payload = (
                "retry: 86400000\n"
                "event: error\n"
                'data: {"error":"unauthorized","code":"UNAUTHORIZED","reconnect":false}\n\n'
            )
            return StreamingResponse(
                iter([payload]),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        return JSONResponse(status_code=exc.http_status, content=exc.to_payload())

    @app.exception_handler(ValidationError)
    async def validation_handler(request: Request, exc: ValidationError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.warning(
            "validation_error path=%s request_id=%s errors=%s",
            request.url.path,
            request_id,
            len(exc.errors()),
        )
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request validation failed",
                    "details": {"errors": exc.errors()},
                    "retryable": False,
                    "failure_kind": "USER_INPUT",
                }
            },
        )

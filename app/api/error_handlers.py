"""Exception handlers for the consistent error envelope."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.core.errors import NamedError


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(NamedError)
    async def named_error_handler(_request: Request, exc: NamedError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content=exc.to_payload())

    @app.exception_handler(ValidationError)
    async def validation_handler(_request: Request, exc: ValidationError) -> JSONResponse:
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

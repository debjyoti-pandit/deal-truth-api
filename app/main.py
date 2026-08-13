"""Deal Truth API FastAPI application."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.deps import build_container
from app.api.error_handlers import install_error_handlers
from app.api.middleware import RequestLoggingMiddleware
from app.api.v1 import api_router
from app.core.logging import configure_logging, get_logger
from app.core.settings import get_settings
from app.db import configure_engines, create_all_async

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings)
    configure_engines(settings)
    app.state.container = build_container(settings)
    if settings.app_env == "test":
        await create_all_async()
    logger.info("app_started env=%s", settings.app_env)
    yield
    logger.info("app_stopping env=%s", settings.app_env)


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="Deal Truth API",
        version="0.1.0",
        description="Evidence-backed sales-call intelligence. NO PROOF IN THE TRANSCRIPT, NO CLAIM IN THE REPORT.",
        lifespan=lifespan,
    )
    application.add_middleware(RequestLoggingMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(application)
    application.include_router(api_router)
    return application


app = create_app()

"""Health endpoints."""

import asyncio

from fastapi import APIRouter, Request

from app.core.errors import MigrationRequired
from app.core.settings import get_settings

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


def _worker_count() -> int | None:
    """Ping Celery workers so readiness surfaces a stuck pipeline (GAP-BE-016)."""
    try:
        from app.tasks.celery_app import celery_app

        replies = celery_app.control.ping(timeout=1.0)
        return len(replies or [])
    except Exception:
        return None


@router.get("/health/ready")
async def ready(request: Request) -> dict[str, object]:
    try:
        from sqlalchemy import text

        from app.db import get_async_engine

        engine = get_async_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        raise MigrationRequired("Database is not ready") from exc
    payload: dict[str, object] = {"status": "ready"}
    if get_settings().app_env != "test":
        workers = await asyncio.to_thread(_worker_count)
        payload["workers"] = workers if workers is not None else 0
        if not workers:
            payload["warning"] = "no Celery workers responded; processing will queue but not run"
    return payload

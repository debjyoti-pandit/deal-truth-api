"""Health endpoints."""

from fastapi import APIRouter, Request

from app.core.errors import MigrationRequired

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(request: Request) -> dict[str, str]:
    try:
        from sqlalchemy import text

        from app.db import get_async_engine

        engine = get_async_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        raise MigrationRequired("Database is not ready") from exc
    return {"status": "ready"}

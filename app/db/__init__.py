"""Database session factories (async for API, sync for Celery/Alembic)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings, get_settings
from app.models.base import Base

_async_engine = None
_sync_engine = None
_async_factory: async_sessionmaker[AsyncSession] | None = None
_sync_factory: sessionmaker[Session] | None = None


def configure_engines(settings: Settings | None = None) -> None:
    global _async_engine, _sync_engine, _async_factory, _sync_factory
    settings = settings or get_settings()
    async_kwargs: dict[str, object] = {"pool_pre_ping": True}
    sync_kwargs: dict[str, object] = {"pool_pre_ping": True}
    if settings.database_url.startswith("sqlite"):
        async_kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    if settings.database_sync_url.startswith("sqlite"):
        sync_kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    _async_engine = create_async_engine(settings.database_url, **async_kwargs)
    _sync_engine = create_engine(settings.database_sync_url, **sync_kwargs)
    _async_factory = async_sessionmaker(_async_engine, expire_on_commit=False, class_=AsyncSession)
    _sync_factory = sessionmaker(_sync_engine, expire_on_commit=False, class_=Session)


def get_async_engine():  # type: ignore[no-untyped-def]
    if _async_engine is None:
        configure_engines()
    return _async_engine


def get_sync_engine():  # type: ignore[no-untyped-def]
    if _sync_engine is None:
        configure_engines()
    return _sync_engine


def async_session_factory() -> async_sessionmaker[AsyncSession]:
    if _async_factory is None:
        configure_engines()
    assert _async_factory is not None
    return _async_factory


def sync_session_factory() -> sessionmaker[Session]:
    if _sync_factory is None:
        configure_engines()
    assert _sync_factory is not None
    return _sync_factory


async def get_db() -> AsyncIterator[AsyncSession]:
    factory = async_session_factory()
    async with factory() as session:
        yield session


def get_sync_db() -> Iterator[Session]:
    factory = sync_session_factory()
    with factory() as session:
        yield session


async def create_all_async() -> None:
    engine = get_async_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def create_all_sync() -> None:
    Base.metadata.create_all(get_sync_engine())

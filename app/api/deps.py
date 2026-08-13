"""FastAPI dependencies and application container."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from app.core.job_ready import JobReadyWaiter, build_job_ready_waiter
from app.core.security import verify_api_key
from app.core.settings import Settings, get_settings
from app.db import sync_session_factory
from app.ml import MLInferenceClient, OpenGongMLClient
from app.providers.base import CallRecapProvider, TranscriptionProvider
from app.providers.pyai import PyAIRecapProvider, PyAITranscriptionProvider
from app.storage.base import BlobStore
from app.storage.seaweed import SeaweedFSS3BlobStore


@dataclass
class AppContainer:
    settings: Settings
    blob: BlobStore
    transcription: TranscriptionProvider
    recap: CallRecapProvider
    ml: MLInferenceClient
    enqueue_process: Callable[[UUID], None]
    job_ready: JobReadyWaiter


def default_enqueue(call_id: UUID) -> None:
    from app.tasks.pipeline_tasks import process_call

    process_call.delay(str(call_id))


def build_container(settings: Settings | None = None) -> AppContainer:
    settings = settings or get_settings()
    if settings.app_env == "test":
        from app.pipeline.deps import memory_blob

        blob: BlobStore = memory_blob()
    else:
        blob = SeaweedFSS3BlobStore(settings)
        try:
            blob.ensure_buckets()
        except Exception:
            pass
    return AppContainer(
        settings=settings,
        blob=blob,
        transcription=PyAITranscriptionProvider(settings),
        recap=PyAIRecapProvider(settings),
        ml=OpenGongMLClient(settings),
        enqueue_process=default_enqueue,
        job_ready=build_job_ready_waiter(settings),
    )


def get_container(request: Request) -> AppContainer:
    return request.app.state.container  # type: ignore[no-any-return]


def get_blob(container: AppContainer = Depends(get_container)) -> BlobStore:
    return container.blob


async def require_auth(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    settings: Settings = request.app.state.container.settings
    verify_api_key(authorization or x_api_key, settings)


def get_sync_session() -> Iterator[Session]:
    factory = sync_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

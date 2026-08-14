"""Construct pipeline dependencies from settings (or injected fakes in tests)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.job_ready import build_job_ready_waiter
from app.core.logging import get_logger
from app.core.settings import Settings
from app.ml import DealTruthMLClient
from app.pipeline.runner import PipelineDeps
from app.providers.pyai import PyAIRecapProvider, PyAITranscriptionProvider
from app.storage.memory import MemoryBlobStore
from app.storage.seaweed import SeaweedFSS3BlobStore

_log = get_logger(__name__)

_memory_blob: MemoryBlobStore | None = None


def memory_blob() -> MemoryBlobStore:
    global _memory_blob
    if _memory_blob is None:
        _memory_blob = MemoryBlobStore()
    return _memory_blob


def reset_memory_blob() -> None:
    global _memory_blob
    _memory_blob = MemoryBlobStore()


def build_blob_store(settings: Settings):
    if settings.app_env == "test":
        return memory_blob()
    store = SeaweedFSS3BlobStore(settings)
    attempts = 2 if settings.s3_optional else 20
    delay = 0.2 if settings.s3_optional else 0.5
    try:
        store.ensure_buckets(attempts=attempts, delay_seconds=delay)
    except Exception:
        if not settings.s3_optional:
            raise
        _log.warning("storage unavailable; S3_OPTIONAL=true, worker will stay up")
    return store


def build_deps(session: Session, settings: Settings) -> PipelineDeps:
    return PipelineDeps(
        session=session,
        settings=settings,
        blob=build_blob_store(settings),
        transcription=PyAITranscriptionProvider(settings),
        recap=PyAIRecapProvider(settings),
        ml=DealTruthMLClient(settings),
        job_ready=build_job_ready_waiter(settings),
    )

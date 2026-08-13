"""Construct pipeline dependencies from settings (or injected fakes in tests)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.job_ready import build_job_ready_waiter
from app.core.settings import Settings
from app.ml import OpenGongMLClient
from app.pipeline.runner import PipelineDeps
from app.providers.pyai import PyAIRecapProvider, PyAITranscriptionProvider
from app.storage.memory import MemoryBlobStore
from app.storage.seaweed import SeaweedFSS3BlobStore

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
    store.ensure_buckets()
    return store


def build_deps(session: Session, settings: Settings) -> PipelineDeps:
    return PipelineDeps(
        session=session,
        settings=settings,
        blob=build_blob_store(settings),
        transcription=PyAITranscriptionProvider(settings),
        recap=PyAIRecapProvider(settings),
        ml=OpenGongMLClient(settings),
        job_ready=build_job_ready_waiter(settings),
    )

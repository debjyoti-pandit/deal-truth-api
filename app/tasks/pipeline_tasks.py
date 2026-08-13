"""Celery tasks wrapping the idempotent pipeline."""

from __future__ import annotations

from uuid import UUID

from app.core.retry import retry_reason, should_retry
from app.core.settings import get_settings
from app.db import sync_session_factory
from app.pipeline.deps import build_deps
from app.pipeline.runner import run_pipeline
from app.tasks.celery_app import celery_app


@celery_app.task(bind=True, name="open_gong.process_call", max_retries=5, acks_late=True)
def process_call(self, call_id: str) -> str:  # type: ignore[no-untyped-def]
    settings = get_settings()
    factory = sync_session_factory()
    with factory() as session:
        deps = build_deps(session, settings)
        try:
            status = run_pipeline(deps, UUID(call_id))
            return status.value
        except Exception as exc:
            if should_retry(exc) and self.request.retries < settings.celery_max_retries:
                raise self.retry(
                    exc=exc,
                    countdown=min(
                        settings.celery_retry_backoff * (2**self.request.retries),
                        settings.celery_retry_backoff_max,
                    ),
                    reason=retry_reason(exc),
                ) from exc
            raise


@celery_app.task(bind=True, name="open_gong.reanalyze_call", max_retries=5, acks_late=True)
def reanalyze_call(self, call_id: str) -> str:  # type: ignore[no-untyped-def]
    return process_call(call_id)

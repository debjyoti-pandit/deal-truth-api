"""Celery tasks wrapping the idempotent pipeline."""

from __future__ import annotations

from uuid import UUID

from app.core.logging import get_logger
from app.core.retry import retry_reason, should_retry
from app.core.settings import get_settings
from app.db import sync_session_factory
from app.pipeline.deps import build_deps
from app.pipeline.runner import run_pipeline
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(bind=True, name="deal_truth.process_call", max_retries=5, acks_late=True)
def process_call(self, call_id: str) -> str:  # type: ignore[no-untyped-def]
    settings = get_settings()
    task_id = getattr(self.request, "id", None)
    logger.info(
        "task_started name=process_call call_id=%s task_id=%s retries=%s",
        call_id,
        task_id,
        self.request.retries,
    )
    factory = sync_session_factory()
    with factory() as session:
        deps = build_deps(session, settings)
        try:
            status = run_pipeline(deps, UUID(call_id))
            logger.info(
                "task_succeeded name=process_call call_id=%s task_id=%s status=%s",
                call_id,
                task_id,
                status.value,
            )
            return status.value
        except Exception as exc:
            logger.warning(
                "task_failed name=process_call call_id=%s task_id=%s error=%s retryable=%s",
                call_id,
                task_id,
                type(exc).__name__,
                should_retry(exc),
            )
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


@celery_app.task(bind=True, name="deal_truth.reanalyze_call", max_retries=5, acks_late=True)
def reanalyze_call(self, call_id: str) -> str:  # type: ignore[no-untyped-def]
    logger.info("task_started name=reanalyze_call call_id=%s task_id=%s", call_id, getattr(self.request, "id", None))
    return process_call(call_id)

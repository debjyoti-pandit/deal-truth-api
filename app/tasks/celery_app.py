"""Celery application. Broker/result backend is Valkey (Redis protocol)."""

from __future__ import annotations

from celery import Celery
from celery.signals import setup_logging, worker_process_init

from app.core.logging import configure_logging, get_logger
from app.core.settings import get_settings

settings = get_settings()
logger = get_logger(__name__)

celery_app = Celery(
    "deal_truth",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks.pipeline_tasks"],
)

celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    task_default_retry_delay=settings.celery_retry_backoff,
    broker_transport_options={
        "visibility_timeout": int(settings.pyai_poll_deadline_seconds) + 120,
    },
)


@setup_logging.connect
def _on_setup_logging(**_kwargs: object) -> None:
    configure_logging(get_settings(), force=True)


@worker_process_init.connect
def _on_worker_process_init(**_kwargs: object) -> None:
    configure_logging(get_settings(), force=True)
    logger.info("celery_worker_process_ready")

"""Signal that a PyAI transcription job is ready (webhook → worker)."""

from __future__ import annotations

import logging
import threading
from typing import Protocol, runtime_checkable

from app.core.settings import Settings

logger = logging.getLogger(__name__)

_KEY_PREFIX = "opengong:pyai:ready:"
_TTL_SECONDS = 3600


@runtime_checkable
class JobReadyWaiter(Protocol):
    def signal(self, job_id: str) -> None: ...

    def wait(self, job_id: str, timeout: float) -> bool: ...


class MemoryJobReadyWaiter:
    def __init__(self) -> None:
        self._events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def _event(self, job_id: str) -> threading.Event:
        with self._lock:
            return self._events.setdefault(job_id, threading.Event())

    def signal(self, job_id: str) -> None:
        if not job_id:
            return
        self._event(job_id).set()

    def wait(self, job_id: str, timeout: float) -> bool:
        if not job_id:
            return False
        return self._event(job_id).wait(timeout=max(0.0, timeout))


class RedisJobReadyWaiter:
    def __init__(self, redis_url: str) -> None:
        import redis

        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)

    def signal(self, job_id: str) -> None:
        if not job_id:
            return
        flag = f"{_KEY_PREFIX}{job_id}"
        channel = f"{flag}:ch"
        pipe = self._redis.pipeline()
        pipe.set(flag, "1", ex=_TTL_SECONDS)
        pipe.lpush(channel, "1")
        pipe.expire(channel, _TTL_SECONDS)
        pipe.execute()

    def wait(self, job_id: str, timeout: float) -> bool:
        if not job_id:
            return False
        flag = f"{_KEY_PREFIX}{job_id}"
        if self._redis.get(flag):
            return True
        channel = f"{flag}:ch"
        item = self._redis.blpop([channel], timeout=max(1, int(timeout)))
        if item:
            return True
        return bool(self._redis.get(flag))


def build_job_ready_waiter(settings: Settings) -> JobReadyWaiter:
    if settings.app_env == "test":
        return MemoryJobReadyWaiter()
    try:
        return RedisJobReadyWaiter(settings.celery_broker_url)
    except Exception:
        logger.warning("Redis job-ready waiter unavailable; using in-memory waiter")
        return MemoryJobReadyWaiter()

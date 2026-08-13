"""Provider contracts. Normalized models are the only shapes the pipeline may consume."""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from app.providers.normalized import NormalizedRecap, NormalizedTranscript, TranscriptionJobHandle


@runtime_checkable
class TranscriptionProvider(Protocol):
    def submit_job(
        self,
        *,
        call_id: UUID,
        public_call_id: str,
        audio_url: str | None,
        audio_stream: tuple[bytes, str, str] | None,
        call_direction: str,
        customer_name: str | None,
        recording_mode: str,
        webhook_url: str | None,
        idempotency_key: str,
    ) -> TranscriptionJobHandle: ...

    def get_job(self, job_id: str) -> dict[str, object]: ...

    def fetch_normalized(self, job_id: str) -> NormalizedTranscript: ...

    def poll_until_complete(self, job_id: str) -> NormalizedTranscript: ...


@runtime_checkable
class CallRecapProvider(Protocol):
    def get_recap(self, call_id: UUID, public_call_id: str) -> NormalizedRecap: ...

    def poll_until_ready(self, call_id: UUID, public_call_id: str) -> NormalizedRecap: ...


@runtime_checkable
class ComplianceProvider(Protocol):
    """Optional Trace integration. Feature-flagged; never blocks P0."""

    enabled: bool

    def trace_event(self, *, call_id: UUID, event: str, payload: dict[str, object]) -> None: ...

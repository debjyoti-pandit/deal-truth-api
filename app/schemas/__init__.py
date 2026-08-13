"""Pydantic API schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl

from app.core.enums import (
    CallDirection,
    CallStatus,
    RecordingMode,
    SourceType,
    SpeakerRole,
    TerminalOutcome,
)


class CallCreate(BaseModel):
    title: str | None = None
    customer_name: str | None = None
    rep_name: str | None = None
    call_direction: CallDirection = CallDirection.UNKNOWN
    recording_mode: RecordingMode = RecordingMode.MONO
    stereo_seller_channel: int | None = None
    tracked_competitors: list[str] = Field(default_factory=list)
    tracked_keywords: list[str] = Field(default_factory=list)


class CallSummary(BaseModel):
    id: UUID
    public_call_id: str
    title: str | None
    customer_name: str | None
    status: CallStatus
    terminal_outcome: TerminalOutcome | None
    duration_ms: int | None
    created_at: datetime
    updated_at: datetime


class CallDetail(CallSummary):
    rep_name: str | None
    call_direction: CallDirection
    source_type: SourceType | None
    recording_mode: RecordingMode
    failure_kind: str | None
    language: str | None
    completed_at: datetime | None


class SourceURLRequest(BaseModel):
    url: HttpUrl


class SpeakerPatch(BaseModel):
    speaker_id: UUID
    role: SpeakerRole | None = None
    display_name: str | None = None
    swap_with: UUID | None = None


class SpeakerOut(BaseModel):
    id: UUID
    provider_speaker_id: str
    role: SpeakerRole
    display_name: str | None
    confidence: float
    manually_overridden: bool


class SegmentOut(BaseModel):
    id: UUID
    speaker_id: UUID | None
    speaker_role: SpeakerRole | None = None
    start_ms: int
    end_ms: int
    text: str
    sequence_number: int


class TranscriptOut(BaseModel):
    call_id: UUID
    language: str | None
    duration_ms: int | None
    speakers: list[SpeakerOut]
    segments: list[SegmentOut]


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    generate: bool = False


class ShareCreate(BaseModel):
    ttl_seconds: int | None = None


class ShareOut(BaseModel):
    id: UUID
    token: str
    expires_at: datetime
    url: str


class EventOut(BaseModel):
    id: UUID
    stage: str
    state: str
    attempt: int
    error_code: str | None
    message: str | None
    created_at: datetime


class ErrorEnvelope(BaseModel):
    error: dict[str, object]

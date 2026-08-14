"""Shared intelligence domain objects."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from app.core.enums import EvidenceStatus, InsightType, SpeakerRole


class SegmentView(BaseModel):
    id: UUID
    provider_segment_id: str
    speaker_id: UUID | None = None
    speaker_role: SpeakerRole = SpeakerRole.UNKNOWN
    start_ms: int
    end_ms: int
    text: str
    sequence_number: int
    labels: dict[str, float] = Field(default_factory=dict)
    emotions: dict[str, float] = Field(default_factory=dict)
    valence: float = 0.0


class CandidateInsight(BaseModel):
    type: InsightType
    title: str
    summary: str
    severity: str | None = None
    confidence: float = 0.0
    evidence_status: EvidenceStatus = EvidenceStatus.SUPPORTED
    segment_ids: list[UUID] = Field(default_factory=list)
    payload: dict[str, object] = Field(default_factory=dict)
    required_role: SpeakerRole | None = None
    relationship: str = "supports"


class ValidatedInsight(BaseModel):
    type: InsightType
    title: str
    summary: str
    severity: str | None = None
    confidence: float
    evidence_status: EvidenceStatus
    segment_ids: list[UUID]
    quotes: list[str]
    audio_spans: list[tuple[int, int]]
    payload: dict[str, object]
    relationship: str = "supports"
    dropped: bool = False
    drop_reason: str | None = None
    # Set only on dropped insights, so a refusal can be recorded with the evidence it
    # tried and failed to stand on. Never populated on anything that ships.
    error_code: str | None = None
    attempted_segment_ids: list[UUID] = Field(default_factory=list)
    attempted_quote: str | None = None

"""Call and audio asset models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.core.enums import (
    CallDirection,
    CallStatus,
    FailureKind,
    RecordingMode,
    SourceType,
    TerminalOutcome,
)
from app.models.base import Base, created_at_col, updated_at_col, uuid_pk

if TYPE_CHECKING:
    from app.models.analysis import AnalysisRun, CallMetrics, RecapRecord
    from app.models.events import ProcessingEvent
    from app.models.sharing import ShareLink
    from app.models.terms import TrackedTerm
    from app.models.transcript import Speaker, TranscriptChunk, TranscriptSegment


JSONType = JSON().with_variant(JSONB(), "postgresql")


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[uuid.UUID] = uuid_pk()
    public_call_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    customer_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    rep_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    call_direction: Mapped[CallDirection] = mapped_column(
        Enum(CallDirection, name="call_direction", native_enum=False, length=32),
        default=CallDirection.UNKNOWN,
        nullable=False,
    )
    source_type: Mapped[SourceType | None] = mapped_column(
        Enum(SourceType, name="source_type", native_enum=False, length=32),
        nullable=True,
    )
    recording_mode: Mapped[RecordingMode] = mapped_column(
        Enum(RecordingMode, name="recording_mode", native_enum=False, length=16),
        default=RecordingMode.MONO,
        nullable=False,
    )
    status: Mapped[CallStatus] = mapped_column(
        Enum(CallStatus, name="call_status", native_enum=False, length=32),
        default=CallStatus.CREATED,
        nullable=False,
        index=True,
    )
    terminal_outcome: Mapped[TerminalOutcome | None] = mapped_column(
        Enum(TerminalOutcome, name="terminal_outcome", native_enum=False, length=32),
        nullable=True,
    )
    failure_kind: Mapped[FailureKind | None] = mapped_column(
        Enum(FailureKind, name="failure_kind", native_enum=False, length=32),
        nullable=True,
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    pyai_job_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    stereo_seller_channel: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    extra: Mapped[dict[str, Any]] = mapped_column("metadata", JSONType, default=dict, nullable=False)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    audio_assets: Mapped[list[AudioAsset]] = relationship(back_populates="call", cascade="all, delete-orphan")
    speakers: Mapped[list[Speaker]] = relationship(back_populates="call", cascade="all, delete-orphan")
    transcript_segments: Mapped[list[TranscriptSegment]] = relationship(
        back_populates="call", cascade="all, delete-orphan"
    )
    analysis_runs: Mapped[list[AnalysisRun]] = relationship(back_populates="call", cascade="all, delete-orphan")
    recap_record: Mapped[RecapRecord | None] = relationship(
        back_populates="call", uselist=False, cascade="all, delete-orphan"
    )
    metrics: Mapped[CallMetrics | None] = relationship(
        back_populates="call", uselist=False, cascade="all, delete-orphan"
    )
    transcript_chunks: Mapped[list[TranscriptChunk]] = relationship(back_populates="call", cascade="all, delete-orphan")
    processing_events: Mapped[list[ProcessingEvent]] = relationship(back_populates="call", cascade="all, delete-orphan")
    share_links: Mapped[list[ShareLink]] = relationship(back_populates="call", cascade="all, delete-orphan")
    tracked_terms: Mapped[list[TrackedTerm]] = relationship(back_populates="call", cascade="all, delete-orphan")


class AudioAsset(Base):
    __tablename__ = "audio_assets"

    id: Mapped[uuid.UUID] = uuid_pk()
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"), nullable=False, index=True)
    bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = created_at_col()

    call: Mapped[Call] = relationship(back_populates="audio_assets")

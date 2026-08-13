"""Speakers, segments, and embedding chunks."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship
from sqlalchemy.schema import FetchedValue
from sqlalchemy.types import JSON

from app.core.enums import SpeakerRole
from app.models.base import Base, created_at_col, uuid_pk
from app.models.types import EmbeddingVector

if TYPE_CHECKING:
    from app.models.call import Call
    from app.models.evidence import EvidenceLink

JSONType = JSON().with_variant(JSONB(), "postgresql")


class Speaker(Base):
    __tablename__ = "speakers"
    __table_args__ = (UniqueConstraint("call_id", "provider_speaker_id", name="uq_speakers_call_provider"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_speaker_id: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[SpeakerRole] = mapped_column(
        Enum(SpeakerRole, name="speaker_role", native_enum=False, length=32),
        default=SpeakerRole.UNKNOWN,
        nullable=False,
    )
    display_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    manually_overridden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    channel: Mapped[int | None] = mapped_column(Integer, nullable=True)

    call: Mapped[Call] = relationship(back_populates="speakers")
    segments: Mapped[list[TranscriptSegment]] = relationship(back_populates="speaker")


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id: Mapped[uuid.UUID] = uuid_pk()
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_segment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    speaker_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("speakers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    extra: Mapped[dict[str, Any]] = mapped_column("metadata", JSONType, default=dict, nullable=False)
    # Postgres-only generated column (migration 0003). Never written by the ORM.
    text_search: Mapped[object | None] = deferred(
        mapped_column(
            TSVECTOR().with_variant(Text(), "sqlite"),
            FetchedValue(),
            nullable=True,
        )
    )

    call: Mapped[Call] = relationship(back_populates="transcript_segments")
    speaker: Mapped[Speaker | None] = relationship(back_populates="segments")
    evidence_links: Mapped[list[EvidenceLink]] = relationship(back_populates="segment")


class TranscriptChunk(Base):
    __tablename__ = "transcript_chunks"

    id: Mapped[uuid.UUID] = uuid_pk()
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"), nullable=False, index=True)
    start_segment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transcript_segments.id", ondelete="CASCADE"), nullable=False
    )
    end_segment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transcript_segments.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(EmbeddingVector, nullable=True)
    created_at: Mapped[datetime] = created_at_col()

    call: Mapped[Call] = relationship(back_populates="transcript_chunks")

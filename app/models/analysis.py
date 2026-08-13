"""Analysis runs, insights, recap, and metrics."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.core.enums import AnalysisRunStatus, EvidenceStatus, InsightType
from app.models.base import Base, created_at_col, uuid_pk

if TYPE_CHECKING:
    from app.models.call import Call
    from app.models.evidence import EvidenceLink

JSONType = JSON().with_variant(JSONB(), "postgresql")


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (UniqueConstraint("call_id", "version", name="uq_analysis_runs_call_version"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[AnalysisRunStatus] = mapped_column(
        Enum(AnalysisRunStatus, name="analysis_run_status", native_enum=False, length=32),
        default=AnalysisRunStatus.PENDING,
        nullable=False,
    )
    model_manifest: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    call: Mapped[Call] = relationship(back_populates="analysis_runs")
    insights: Mapped[list[Insight]] = relationship(back_populates="analysis_run", cascade="all, delete-orphan")


class Insight(Base):
    __tablename__ = "insights"

    id: Mapped[uuid.UUID] = uuid_pk()
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[InsightType] = mapped_column(
        Enum(InsightType, name="insight_type", native_enum=False, length=64),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    evidence_status: Mapped[EvidenceStatus] = mapped_column(
        Enum(EvidenceStatus, name="evidence_status", native_enum=False, length=32),
        default=EvidenceStatus.SUPPORTED,
        nullable=False,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    created_at: Mapped[datetime] = created_at_col()

    analysis_run: Mapped[AnalysisRun] = relationship(back_populates="insights")
    evidence_links: Mapped[list[EvidenceLink]] = relationship(back_populates="insight", cascade="all, delete-orphan")


class RecapRecord(Base):
    __tablename__ = "recap_records"

    id: Mapped[uuid.UUID] = uuid_pk()
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"), nullable=False, unique=True)
    provider_status: Mapped[str] = mapped_column(String(64), nullable=False)
    headline: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    tldr: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_record: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)

    call: Mapped[Call] = relationship(back_populates="recap_record")


class CallMetrics(Base):
    __tablename__ = "call_metrics"

    id: Mapped[uuid.UUID] = uuid_pk()
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"), nullable=False, unique=True)
    talk_ratio: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    longest_monologue: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    question_rate: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    keyword_hits: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)

    call: Mapped[Call] = relationship(back_populates="metrics")

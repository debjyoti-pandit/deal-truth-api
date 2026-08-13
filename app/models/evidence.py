"""Evidence links between insights and transcript segments."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import relationship as orm_relationship

from app.models.base import Base, uuid_pk

if TYPE_CHECKING:
    from app.models.analysis import Insight
    from app.models.transcript import TranscriptSegment


class EvidenceLink(Base):
    __tablename__ = "evidence_links"
    __table_args__ = (
        UniqueConstraint(
            "insight_id",
            "transcript_segment_id",
            "relationship",
            name="uq_evidence_insight_segment_rel",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    insight_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("insights.id", ondelete="CASCADE"), nullable=False, index=True
    )
    transcript_segment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transcript_segments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rel: Mapped[str] = mapped_column("relationship", String(64), default="supports", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    insight: Mapped[Insight] = orm_relationship(back_populates="evidence_links")
    segment: Mapped[TranscriptSegment] = orm_relationship(back_populates="evidence_links")

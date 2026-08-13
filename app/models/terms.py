"""Tracked keywords and competitor aliases."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.core.enums import TrackedTermType
from app.models.base import Base, uuid_pk

if TYPE_CHECKING:
    from app.models.call import Call

JSONType = JSON().with_variant(JSONB(), "postgresql")


class TrackedTerm(Base):
    __tablename__ = "tracked_terms"

    id: Mapped[uuid.UUID] = uuid_pk()
    call_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("calls.id", ondelete="CASCADE"), nullable=True, index=True
    )
    organization_scope: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    type: Mapped[TrackedTermType] = mapped_column(
        Enum(TrackedTermType, name="tracked_term_type", native_enum=False, length=32),
        nullable=False,
    )
    value: Mapped[str] = mapped_column(String(256), nullable=False)
    aliases: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)

    call: Mapped[Call | None] = relationship(back_populates="tracked_terms")

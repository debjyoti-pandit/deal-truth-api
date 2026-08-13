"""Dialect-portable 384-dim embedding column (pgvector on Postgres, JSON elsewhere)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

try:
    from pgvector.sqlalchemy import Vector
except ImportError:  # pragma: no cover
    Vector = None  # type: ignore[misc, assignment]


class EmbeddingVector(TypeDecorator[list[float]]):
    impl = JSON
    cache_ok = True
    dim = 384

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        if dialect.name == "postgresql" and Vector is not None:
            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(JSON())

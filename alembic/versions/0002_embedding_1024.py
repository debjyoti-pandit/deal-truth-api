"""pgvector 1024-dim embeddings (Qwen3 embedding 0.6b)

Revision ID: 0002_embedding_1024
Revises: 0001_initial
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_embedding_1024"
down_revision: str | Sequence[str] | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # Existing 384-dim rows cannot CAST to 1024.
    op.execute("ALTER TABLE transcript_chunks ALTER COLUMN embedding TYPE vector(1024) USING NULL")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE transcript_chunks ALTER COLUMN embedding TYPE vector(384) USING NULL")

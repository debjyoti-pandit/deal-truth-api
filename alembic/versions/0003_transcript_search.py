"""Full-text search indexes for transcript segments and insights.

Revision ID: 0003_transcript_search
Revises: 0002_embedding_1024
Create Date: 2026-08-14
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003_transcript_search"
down_revision: str | Sequence[str] | None = "0002_embedding_1024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.execute(
        """
        ALTER TABLE transcript_segments
        ADD COLUMN IF NOT EXISTS text_search tsvector
        GENERATED ALWAYS AS (to_tsvector('english', coalesce(text, ''))) STORED
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_transcript_segments_text_search
        ON transcript_segments USING GIN (text_search)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_transcript_segments_text_trgm
        ON transcript_segments USING GIN (text gin_trgm_ops)
        """
    )

    op.execute(
        """
        ALTER TABLE insights
        ADD COLUMN IF NOT EXISTS text_search tsvector
        GENERATED ALWAYS AS (
            to_tsvector(
                'english',
                coalesce(title, '') || ' ' || coalesce(summary, '')
            )
        ) STORED
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_insights_text_search
        ON insights USING GIN (text_search)
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_insights_text_search")
    op.execute("ALTER TABLE insights DROP COLUMN IF EXISTS text_search")
    op.execute("DROP INDEX IF EXISTS ix_transcript_segments_text_trgm")
    op.execute("DROP INDEX IF EXISTS ix_transcript_segments_text_search")
    op.execute("ALTER TABLE transcript_segments DROP COLUMN IF EXISTS text_search")

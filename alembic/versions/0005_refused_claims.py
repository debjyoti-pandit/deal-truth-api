"""Persist claims the evidence validator refused.

Refused candidates used to be discarded in persist_insights, so the gate was invisible:
the API could report what it said, never what it declined to say.

Revision ID: 0005_refused_claims
Revises: 0004_unique_index_parity
Create Date: 2026-08-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0005_refused_claims"
down_revision: str | Sequence[str] | None = "0004_unique_index_parity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONType = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "refused_claims",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("analysis_run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("call_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("insight_type", sa.String(length=48), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=False),
        sa.Column("drop_reason", sa.Text(), nullable=False),
        sa.Column("attempted_segment_ids", JSONType, server_default=sa.text("'[]'"), nullable=False),
        sa.Column("attempted_quote", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"],
            ["analysis_runs.id"],
            name=op.f("fk_refused_claims_analysis_run_id_analysis_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["call_id"],
            ["calls.id"],
            name=op.f("fk_refused_claims_call_id_calls"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refused_claims")),
    )
    op.create_index(
        "ix_refused_claims_analysis_run_id",
        "refused_claims",
        ["analysis_run_id"],
        unique=False,
    )
    # Newest refusals first for a given call — the order the endpoint returns them in.
    op.create_index(
        "ix_refused_claims_call",
        "refused_claims",
        ["call_id", sa.text("created_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_refused_claims_call", table_name="refused_claims")
    op.drop_index("ix_refused_claims_analysis_run_id", table_name="refused_claims")
    op.drop_table("refused_claims")

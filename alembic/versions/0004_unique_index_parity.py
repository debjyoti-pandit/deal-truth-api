"""Reconcile unique constraints with the model's unique indexes.

`calls.public_call_id` and `share_links.token_hash` are declared `unique=True, index=True`,
which SQLAlchemy renders as a single UNIQUE index. Migration 0001 instead created a unique
CONSTRAINT plus a separate non-unique index — two objects doing one job, and a permanent
`alembic check` diff that hid any real drift behind it.

Uniqueness is never dropped: the constraint stays in place while the plain index is
replaced by a unique one, and only then is the redundant constraint removed.

Revision ID: 0004_unique_index_parity
Revises: 0003_transcript_search
Create Date: 2026-08-14
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_unique_index_parity"
down_revision: str | Sequence[str] | None = "0003_transcript_search"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TARGETS = (
    ("calls", "public_call_id", "ix_calls_public_call_id", "uq_calls_public_call_id"),
    ("share_links", "token_hash", "ix_share_links_token_hash", "uq_share_links_token_hash"),
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table, column, index_name, constraint_name in TARGETS:
        op.execute(f"DROP INDEX IF EXISTS {index_name}")
        op.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} ON {table} ({column})")
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint_name}")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table, column, index_name, constraint_name in TARGETS:
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {constraint_name} UNIQUE ({column})")
        op.execute(f"DROP INDEX IF EXISTS {index_name}")
        op.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({column})")

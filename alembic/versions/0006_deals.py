"""Group calls into deals, so a sequence of calls can be read as one account.

Calls were standalone, which meant "is this deal getting better or worse?" could not be
answered by the API at all. Additive only: `calls.deal_id` is nullable and every existing
call keeps working unattached.

Revision ID: 0006_deals
Revises: 0005_refused_claims
Create Date: 2026-08-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_deals"
down_revision: str | Sequence[str] | None = "0005_refused_claims"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "deals",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("account_name", sa.String(length=256), nullable=False),
        sa.Column("primary_contact", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deals")),
    )
    op.create_index("ix_deals_account_name", "deals", ["account_name"], unique=False)
    op.add_column("calls", sa.Column("deal_id", sa.Uuid(as_uuid=True), nullable=True))
    op.create_foreign_key(op.f("fk_calls_deal_id_deals"), "calls", "deals", ["deal_id"], ["id"])
    op.create_index("ix_calls_deal", "calls", ["deal_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_calls_deal", table_name="calls")
    op.drop_constraint(op.f("fk_calls_deal_id_deals"), "calls", type_="foreignkey")
    op.drop_column("calls", "deal_id")
    op.drop_index("ix_deals_account_name", table_name="deals")
    op.drop_table("deals")

"""Store outbound integration credentials server-side.

The Slack incoming-webhook URL had nowhere to live, so the UI could only keep it in the
browser. A webhook URL is a bearer credential; it belongs on the server. One row per
provider, the credential in a deferred column that no read endpoint selects.

Additive only: a new table, nothing existing is touched.

Revision ID: 0007_integration_settings
Revises: 0006_deals
Create Date: 2026-08-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_integration_settings"
down_revision: str | Sequence[str] | None = "0006_deals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "integration_settings",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("secret", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integration_settings")),
        sa.UniqueConstraint("provider", name=op.f("uq_integration_settings_provider")),
    )


def downgrade() -> None:
    op.drop_table("integration_settings")

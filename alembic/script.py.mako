"""Alembic script template."""

from collections.abc import Sequence

revision: str
down_revision: str | Sequence[str] | None
branch_labels: str | Sequence[str] | None
depends_on: str | Sequence[str] | None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

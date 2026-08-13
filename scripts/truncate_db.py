"""Truncate Deal Truth API data tables. Keeps Alembic revision by default.

Usage:
  make truncate
  uv run python scripts/truncate_db.py --yes

Does not print the database URL (it may contain credentials).
"""

from __future__ import annotations

import argparse
import re
import sys

from app.core.settings import get_settings
from app.db import configure_engines, get_sync_engine
from app.models import Base  # noqa: F401 — register tables on metadata
from sqlalchemy import text
from sqlalchemy.engine import Engine

_TABLE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_ALEMBIC = "alembic_version"


def app_table_names(*, include_alembic: bool = False) -> list[str]:
    names = [table.name for table in Base.metadata.sorted_tables]
    if include_alembic:
        names.append(_ALEMBIC)
    for name in names:
        if not _TABLE_NAME.match(name):
            raise ValueError(f"refusing to truncate unexpected table name {name!r}")
    return names


def truncate_all(engine: Engine, *, include_alembic: bool = False) -> list[str]:
    names = app_table_names(include_alembic=include_alembic)
    if not names:
        return []
    preparer = engine.dialect.identifier_preparer
    quoted = ", ".join(preparer.quote(name) for name in names)
    dialect = engine.dialect.name
    with engine.begin() as conn:
        if dialect == "postgresql":
            conn.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))
        elif dialect == "sqlite":
            conn.execute(text("PRAGMA foreign_keys=OFF"))
            for name in reversed(names):
                conn.execute(text(f"DELETE FROM {preparer.quote(name)}"))
            conn.execute(text("PRAGMA foreign_keys=ON"))
        else:
            raise RuntimeError(f"truncate is not supported for dialect {dialect}")
    return names


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Truncate Deal Truth API tables (data only).")
    parser.add_argument("--yes", action="store_true", help="Required. Confirm destructive truncate.")
    parser.add_argument(
        "--include-alembic",
        action="store_true",
        help="Also truncate alembic_version (you will need make migrate afterwards).",
    )
    args = parser.parse_args(argv)
    if not args.yes:
        print("refusing to truncate without --yes (make truncate)", file=sys.stderr)
        return 2
    configure_engines(get_settings())
    engine = get_sync_engine()
    names = truncate_all(engine, include_alembic=args.include_alembic)
    kept = " (kept alembic_version)" if not args.include_alembic else " (including alembic_version)"
    print(f"truncated {len(names)} tables{kept}: {', '.join(names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

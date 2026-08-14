"""Alembic environment."""

from __future__ import annotations

from logging.config import fileConfig

from app.core.settings import get_settings
from app.models import Base
from sqlalchemy import engine_from_config, pool

from alembic import context

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_sync_url)

# Indexes owned by raw SQL in migration 0003, not by the model metadata. They use
# Postgres-only features the ORM layer deliberately does not describe — GIN over a
# GENERATED tsvector column, and gin_trgm_ops — and migration 0003 is a no-op on any
# other dialect, so the model cannot honestly declare them for SQLite. Without this,
# autogenerate sees them only in the database and proposes dropping them on every run.
RAW_SQL_INDEXES = frozenset(
    {
        "ix_insights_text_search",
        "ix_transcript_segments_text_search",
        "ix_transcript_segments_text_trgm",
    }
)


def include_object(obj: object, name: str | None, type_: str, reflected: bool, compare_to: object) -> bool:
    return not (type_ == "index" and name in RAW_SQL_INDEXES)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

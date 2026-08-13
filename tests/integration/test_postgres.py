"""Integration tests against docker-compose services. Skipped when unavailable."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skipif(os.environ.get("RUN_INTEGRATION_TESTS") != "1", reason="integration tests disabled")
def test_postgres_select() -> None:
    from sqlalchemy import create_engine, text

    url = os.environ.get("DATABASE_SYNC_URL", "postgresql+psycopg://opengong:opengong@localhost:5432/opengong")
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))

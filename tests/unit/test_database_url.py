from app.core.settings import Settings, _rewrite_db_scheme


def test_rewrite_render_postgres_url() -> None:
    raw = "postgresql://deal_truth_user:secret@dpg-example/deal_truth"
    assert _rewrite_db_scheme(raw, async_driver=True) == (
        "postgresql+asyncpg://deal_truth_user:secret@dpg-example/deal_truth"
    )
    assert _rewrite_db_scheme(raw, async_driver=False) == (
        "postgresql+psycopg://deal_truth_user:secret@dpg-example/deal_truth"
    )


def test_rewrite_postgres_scheme_alias() -> None:
    raw = "postgres://u:p@h/db"
    assert _rewrite_db_scheme(raw, async_driver=True).startswith("postgresql+asyncpg://")


def test_settings_accepts_bare_postgresql(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    monkeypatch.setenv("DATABASE_SYNC_URL", "postgresql://u:p@h/db")
    settings = Settings()
    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.database_sync_url.startswith("postgresql+psycopg://")

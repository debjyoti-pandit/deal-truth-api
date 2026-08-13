from __future__ import annotations

from app.core.enums import CallDirection, CallStatus, RecordingMode
from app.models.call import Call
from scripts.truncate_db import app_table_names, truncate_all
from sqlalchemy import text
from sqlalchemy.orm import Session


def test_app_table_names_skip_alembic_by_default() -> None:
    names = app_table_names()
    assert "calls" in names
    assert "alembic_version" not in names
    assert app_table_names(include_alembic=True)[-1] == "alembic_version"


def test_truncate_all_sqlite(session: Session) -> None:
    session.add(
        Call(
            public_call_id="truncate-test",
            call_direction=CallDirection.OUTBOUND,
            recording_mode=RecordingMode.MONO,
            status=CallStatus.CREATED,
            extra={},
        )
    )
    session.commit()
    count = session.execute(text("SELECT COUNT(*) FROM calls")).scalar_one()
    assert count == 1
    engine = session.get_bind()
    truncated = truncate_all(engine)
    assert "calls" in truncated
    leftover = session.execute(text("SELECT COUNT(*) FROM calls")).scalar_one()
    assert leftover == 0

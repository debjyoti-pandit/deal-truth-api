from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from app.api.v1 import calls as calls_api
from app.core.enums import AuthMode, CallDirection, CallStatus, RecordingMode
from app.core.settings import Settings
from app.models.call import Call
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def _seed(session: Session) -> UUID:
    call = Call(
        public_call_id=uuid4().hex[:12],
        title="stream-auth",
        customer_name="Sarah",
        rep_name="Rahul",
        call_direction=CallDirection.OUTBOUND,
        recording_mode=RecordingMode.MONO,
        status=CallStatus.CREATED,
        extra={},
    )
    session.add(call)
    session.commit()
    return call.id


def _lock_auth(client: TestClient, settings: Settings) -> None:
    client.app.state.container.settings = settings.model_copy(  # type: ignore[attr-defined]
        update={"auth_mode": AuthMode.API_KEY, "api_keys": "ui-secret"}
    )


def test_stream_accepts_query_api_key(
    client: TestClient, session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(calls_api, "SSE_POLL_INTERVAL_SECONDS", 0.001)
    monkeypatch.setattr(calls_api, "SSE_KEEPALIVE_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(calls_api, "SSE_IDLE_BUDGET_SECONDS", 0.005)
    _lock_auth(client, settings)
    call_id = _seed(session)
    response = client.get(f"/api/v1/calls/{call_id}/stream?api_key=ui-secret")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")


def test_stream_without_key_is_sse_not_401(client: TestClient, session: Session, settings: Settings) -> None:
    _lock_auth(client, settings)
    call_id = _seed(session)
    response = client.get(f"/api/v1/calls/{call_id}/stream")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "UNAUTHORIZED" in response.text
    assert "reconnect" in response.text


def test_list_calls_still_requires_header(client: TestClient, settings: Settings) -> None:
    _lock_auth(client, settings)
    response = client.get("/api/v1/calls")
    assert response.status_code == 401

import hashlib
import hmac
from uuid import UUID

import pytest
from app.core.errors import PyAIWebhookSignatureInvalid
from app.models.call import Call
from app.providers.pyai import verify_pyai_webhook_signature
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def test_webhook_signature_accepts_valid_hmac(secret: str) -> None:
    body = b'{"id":"job_1","status":"completed"}'
    sig = hmac.new(b"unit-test-webhook-secret", body, hashlib.sha256).hexdigest()
    verify_pyai_webhook_signature(b"unit-test-webhook-secret", body, f"sha256={sig}")


def test_webhook_signature_rejects_invalid() -> None:
    with pytest.raises(PyAIWebhookSignatureInvalid):
        verify_pyai_webhook_signature(b"unit-test-webhook-secret", b"{}", "deadbeef")


def test_webhook_endpoint_rejects_bad_signature(client: TestClient) -> None:
    response = client.post(
        "/api/v1/webhooks/pyai/transcription",
        content=b'{"id":"x"}',
        headers={"X-PyAI-Signature": "nope", "Content-Type": "application/json"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "PYAI_WEBHOOK_SIGNATURE_INVALID"


def test_webhook_signals_without_reenqueue(client: TestClient, session: Session) -> None:
    created = client.post("/api/v1/calls", json={"title": "webhook-signal"})
    assert created.status_code == 201
    call = session.get(Call, UUID(created.json()["id"]))
    assert call is not None
    call.pyai_job_id = "job_1"
    session.commit()

    enqueued: list[UUID] = []
    app = client.app
    assert isinstance(app, FastAPI)
    app.state.container.enqueue_process = lambda cid: enqueued.append(cid)

    body = b'{"id":"job_1","status":"completed"}'
    sig = hmac.new(b"unit-test-webhook-secret", body, hashlib.sha256).hexdigest()
    response = client.post(
        "/api/v1/webhooks/pyai/transcription",
        content=body,
        headers={"X-PyAI-Signature": f"sha256={sig}", "Content-Type": "application/json"},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    assert enqueued == []
    assert app.state.container.job_ready.wait("job_1", 0.1) is True

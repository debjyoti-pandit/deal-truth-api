"""Regression tests for the frontend gap fixes (BACKEND_API_GAPS_AND_RESOLUTIONS)."""

from __future__ import annotations

from app.core.errors import MLServiceUnavailable
from fastapi import FastAPI
from fastapi.testclient import TestClient

WAV = ("call.wav", b"RIFF....WAVEfmt extra audio", "audio/wav")


def _create(client: TestClient, title: str = "happy_path") -> str:
    created = client.post("/api/v1/calls", json={"title": title, "customer_name": "Sarah"})
    assert created.status_code == 201
    return created.json()["id"]


def _upload_and_process(client: TestClient, call_id: str) -> None:
    assert client.post(f"/api/v1/calls/{call_id}/audio", files={"file": WAV}).status_code == 200
    assert client.post(f"/api/v1/calls/{call_id}/process").status_code == 200


def test_report_not_ready_is_409(client: TestClient) -> None:
    call_id = _create(client)
    for path in ("report", "export/json", "export/markdown"):
        response = client.get(f"/api/v1/calls/{call_id}/{path}")
        assert response.status_code == 409, path
        assert response.json()["error"]["code"] == "NOT_READY"
        assert response.json()["error"]["retryable"] is True


def test_report_ready_after_processing(client: TestClient) -> None:
    call_id = _create(client)
    _upload_and_process(client, call_id)
    assert client.get(f"/api/v1/calls/{call_id}/report").status_code == 200
    assert client.get(f"/api/v1/calls/{call_id}/export/json").status_code == 200
    assert client.get(f"/api/v1/calls/{call_id}/export/markdown").status_code == 200


def test_process_without_audio_is_400_invalid_audio(client: TestClient) -> None:
    call_id = _create(client)
    response = client.post(f"/api/v1/calls/{call_id}/process")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_AUDIO"
    assert response.json()["error"]["failure_kind"] == "USER_INPUT"
    # The call must not have entered the pipeline.
    assert client.get(f"/api/v1/calls/{call_id}").json()["status"] == "CREATED"


def test_events_use_call_status_stages_and_lowercase_states(client: TestClient) -> None:
    call_id = _create(client)
    _upload_and_process(client, call_id)
    events = client.get(f"/api/v1/calls/{call_id}/events").json()
    stages = [e["stage"] for e in events]
    assert "CREATED" in stages
    assert "UPLOADING" in stages
    assert "QUEUED" in stages
    assert "TRANSCRIBING" in stages
    assert all(e["state"] in {"started", "succeeded", "failed", "retrying", "skipped"} for e in events)


def test_ask_unindexed_call_returns_200_empty(client: TestClient) -> None:
    call_id = _create(client)
    response = client.post(f"/api/v1/calls/{call_id}/ask", json={"question": "What did they say about pricing?"})
    assert response.status_code == 200
    assert response.json()["mode"] == "no_index"
    assert response.json()["moments"] == []


def test_ask_falls_back_to_lexical_when_ml_down(client: TestClient) -> None:
    call_id = _create(client)
    _upload_and_process(client, call_id)

    class DownML:
        def embed(self, texts):
            raise MLServiceUnavailable("down")

        def classify(self, texts, labels=None):
            raise MLServiceUnavailable("down")

        def emotion(self, texts):
            raise MLServiceUnavailable("down")

        def generate(self, prompt, *, max_tokens=256):
            raise MLServiceUnavailable("down")

    app = client.app
    assert isinstance(app, FastAPI)
    original = app.state.container.ml
    app.state.container.ml = DownML()
    try:
        response = client.post(f"/api/v1/calls/{call_id}/ask", json={"question": "security review"})
    finally:
        app.state.container.ml = original
    assert response.status_code == 200
    assert response.json()["mode"] == "retrieval_lexical_fallback"


def test_audio_url_mint(client: TestClient) -> None:
    call_id = _create(client)
    assert client.post(f"/api/v1/calls/{call_id}/audio", files={"file": WAV}).status_code == 200
    response = client.get(f"/api/v1/calls/{call_id}/audio-url")
    assert response.status_code == 200
    body = response.json()
    assert "expires_at" in body
    url = body["url"]
    assert "/api/v1/public/audio/" in url
    assert "signature=" in url
    # The minted URL streams without auth headers.
    path = url.split("http://testserver", 1)[-1]
    audio = client.get(path)
    assert audio.status_code == 200


def test_calls_overview_is_not_swallowed_by_uuid_route(client: TestClient) -> None:
    call_id = _create(client)
    _upload_and_process(client, call_id)
    response = client.get("/api/v1/calls/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["total_calls"] >= 1
    assert body["by_status"].get("SHIPPED", 0) >= 1
    assert body["shipped"] >= 1
    assert isinstance(body["insight_counts"], dict) and body["insight_counts"]
    assert any(c["id"] == call_id for c in body["recent_calls"])


def test_recommendations_endpoint(client: TestClient) -> None:
    call_id = _create(client)
    _upload_and_process(client, call_id)
    response = client.get("/api/v1/recommendations")
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["items"], "expected at least one recommendation from the fixture call"
    for item in body["items"]:
        assert {"id", "kind", "title", "description", "count", "query", "call_ids"} <= set(item)
        assert item["count"] > 0
    assert any(call_id in item["call_ids"] for item in body["items"])


def test_recommendations_empty_when_no_finished_calls(client: TestClient) -> None:
    response = client.get("/api/v1/recommendations")
    assert response.status_code == 200
    assert response.json() == {"available": True, "items": []}


def test_search_endpoint_groups(client: TestClient) -> None:
    call_id = _create(client)
    _upload_and_process(client, call_id)
    response = client.get("/api/v1/search", params={"q": "sarah"})
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "sarah"
    assert set(body["groups"]) == {"insights", "segments", "calls"}
    assert any(c["id"] == call_id for c in body["groups"]["calls"])

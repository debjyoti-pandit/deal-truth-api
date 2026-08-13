from fastapi.testclient import TestClient


def test_health_live(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_openapi_schema_valid(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "Deal Truth API"
    paths = schema["paths"]
    required = [
        "/health/live",
        "/health/ready",
        "/api/v1/calls",
        "/api/v1/calls/{call_id}",
        "/api/v1/calls/{call_id}/audio",
        "/api/v1/calls/{call_id}/source-url",
        "/api/v1/public/audio/{asset_id}",
        "/api/v1/calls/{call_id}/process",
        "/api/v1/calls/{call_id}/reanalyze",
        "/api/v1/calls/{call_id}/cancel",
        "/api/v1/calls/{call_id}/events",
        "/api/v1/calls/{call_id}/stream",
        "/api/v1/calls/{call_id}/transcript",
        "/api/v1/calls/{call_id}/speakers",
        "/api/v1/calls/{call_id}/report",
        "/api/v1/calls/{call_id}/insights",
        "/api/v1/calls/{call_id}/metrics",
        "/api/v1/calls/{call_id}/ask",
        "/api/v1/calls/{call_id}/follow-up",
        "/api/v1/calls/{call_id}/share",
        "/api/v1/calls/{call_id}/share/{share_id}",
        "/api/v1/shared/{token}",
        "/api/v1/calls/{call_id}/export/json",
        "/api/v1/calls/{call_id}/export/markdown",
        "/api/v1/webhooks/pyai/transcription",
    ]
    for path in required:
        assert path in paths, path


def test_create_call_and_share_hash(client: TestClient) -> None:
    created = client.post("/api/v1/calls", json={"title": "happy_path", "customer_name": "Sarah"})
    assert created.status_code == 201
    call_id = created.json()["id"]
    listed = client.get("/api/v1/calls")
    assert listed.status_code == 200
    got = client.get(f"/api/v1/calls/{call_id}")
    assert got.status_code == 200
    share = client.post(f"/api/v1/calls/{call_id}/share", json={})
    assert share.status_code == 200
    token = share.json()["token"]
    assert "token_hash" not in share.json()
    shared = client.get(f"/api/v1/shared/{token}")
    assert shared.status_code == 200


def test_upload_audio_and_process(client: TestClient) -> None:
    created = client.post("/api/v1/calls", json={"title": "happy_path", "customer_name": "Sarah"})
    call_id = created.json()["id"]
    upload = client.post(
        f"/api/v1/calls/{call_id}/audio",
        files={"file": ("call.wav", b"RIFF....WAVEfmt extra audio", "audio/wav")},
    )
    assert upload.status_code == 200
    processed = client.post(f"/api/v1/calls/{call_id}/process")
    assert processed.status_code == 200
    report = client.get(f"/api/v1/calls/{call_id}/report")
    assert report.status_code == 200
    metrics = client.get(f"/api/v1/calls/{call_id}/metrics")
    assert metrics.status_code == 200
    insights = client.get(f"/api/v1/calls/{call_id}/insights")
    assert insights.status_code == 200
    transcript = client.get(f"/api/v1/calls/{call_id}/transcript")
    assert transcript.status_code == 200
    follow = client.post(f"/api/v1/calls/{call_id}/follow-up")
    assert follow.status_code == 200
    ask = client.post(f"/api/v1/calls/{call_id}/ask", json={"question": "Why is the customer hesitant?"})
    assert ask.status_code == 200
    exported = client.get(f"/api/v1/calls/{call_id}/export/json")
    assert exported.status_code == 200
    md = client.get(f"/api/v1/calls/{call_id}/export/markdown")
    assert md.status_code == 200
    audio = client.get(f"/api/v1/calls/{call_id}/audio", headers={"Range": "bytes=0-3"})
    assert audio.status_code in {200, 206}


def test_source_url_ssrf(client: TestClient) -> None:
    created = client.post("/api/v1/calls", json={"title": "x"})
    call_id = created.json()["id"]
    response = client.post(
        f"/api/v1/calls/{call_id}/source-url",
        json={"url": "https://127.0.0.1/secret.wav"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_SOURCE_URL"

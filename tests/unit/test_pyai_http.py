from uuid import uuid4

import httpx
import pytest
from app.core.errors import PyAIPaymentRequired, PyAIScopeMissing
from app.core.retry import should_retry
from app.core.settings import Settings
from app.providers.pyai import PyAIRecapProvider, PyAITranscriptionProvider


def test_submit_402_fails_without_retry() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"error": "payment_required"})

    settings = Settings(pyai_api_key="test-key", pyai_base_url="https://api.pyai.com/v1")
    provider = PyAITranscriptionProvider(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(PyAIPaymentRequired) as exc:
        provider.submit_job(
            call_id=uuid4(),
            public_call_id="call-1",
            audio_url="https://example.com/audio.wav",
            audio_stream=None,
            call_direction="outbound",
            customer_name=None,
            recording_mode="mono",
            webhook_url=None,
            idempotency_key="idem-1",
        )
    assert not should_retry(exc.value)
    assert exc.value.details["status_code"] == 402


def test_recap_403_is_scope_missing_not_auth_failure() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"code": "forbidden"}})

    settings = Settings(pyai_api_key="test-key", pyai_base_url="https://api.pyai.com/v1")
    provider = PyAIRecapProvider(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    recap = provider.poll_until_ready(uuid4(), "call-1")
    assert recap.capability_warning == "PYAI_SCOPE_MISSING"
    assert recap.status == "unavailable"
    assert not should_retry(PyAIScopeMissing("no recap scope"))


def test_recap_skips_http_when_key_lacks_recap_read() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path.endswith("/me"):
            return httpx.Response(
                200,
                json={"scopes": ["hear:transcribe", "transcribe:jobs"]},
            )
        return httpx.Response(403, json={"error": {"code": "forbidden"}})

    settings = Settings(pyai_api_key="test-key", pyai_base_url="https://api.pyai.com/v1")
    provider = PyAIRecapProvider(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    recap = provider.poll_until_ready(uuid4(), "call-1")
    assert recap.capability_warning == "PYAI_SCOPE_MISSING"
    assert any(url.endswith("/me") for url in seen)
    assert not any("/recap/calls/" in url for url in seen)

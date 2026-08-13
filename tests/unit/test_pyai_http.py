from uuid import uuid4

import httpx
import pytest
from app.core.errors import PyAIPaymentRequired
from app.core.retry import should_retry
from app.core.settings import Settings
from app.providers.pyai import PyAITranscriptionProvider


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

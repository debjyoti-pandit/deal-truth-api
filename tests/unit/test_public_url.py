from __future__ import annotations

from app.core.public_url import (
    is_loopback_base_url,
    is_public_https_url,
    pick_ngrok_https_url,
    resolve_public_api_base_url,
)
from app.core.settings import Settings


def test_loopback_urls() -> None:
    assert is_loopback_base_url("http://localhost:8000")
    assert is_loopback_base_url("http://127.0.0.1:8000")
    assert is_loopback_base_url("http://testserver")
    assert not is_loopback_base_url("https://abc.ngrok-free.app")


def test_public_https() -> None:
    assert is_public_https_url("https://abc.ngrok-free.app")
    assert not is_public_https_url("http://abc.ngrok-free.app")
    assert not is_public_https_url("https://localhost:8000")


def test_pick_ngrok_https_url() -> None:
    payload = {
        "tunnels": [
            {"public_url": "http://abc.ngrok-free.app", "proto": "http"},
            {"public_url": "https://abc.ngrok-free.app", "proto": "https"},
        ]
    }
    assert pick_ngrok_https_url(payload) == "https://abc.ngrok-free.app"


def test_resolve_uses_configured_public_https() -> None:
    settings = Settings(
        public_api_base_url="https://stable.ngrok.app",
        ngrok_enabled=True,
        signed_url_secret="unit-test-signed-url-secret",
    )
    assert resolve_public_api_base_url(settings) == "https://stable.ngrok.app"


def test_resolve_uses_pinned_ngrok_domain() -> None:
    settings = Settings(
        public_api_base_url="http://localhost:8000",
        ngrok_enabled=True,
        ngrok_domain="stable.ngrok-free.app",
        ngrok_wait_seconds=0,
        signed_url_secret="unit-test-signed-url-secret",
    )
    assert resolve_public_api_base_url(settings) == "https://stable.ngrok-free.app"


def test_resolve_skips_ngrok_when_disabled() -> None:
    settings = Settings(
        public_api_base_url="http://localhost:8000",
        ngrok_enabled=False,
        ngrok_domain="",
        signed_url_secret="unit-test-signed-url-secret",
    )
    assert resolve_public_api_base_url(settings) == "http://localhost:8000"


def test_resolved_ml_service_base_url_prefers_explicit() -> None:
    settings = Settings(
        ml_service_base_url="https://deal-truth-ml.onrender.com/",
        signed_url_secret="unit-test-signed-url-secret",
    )
    assert settings.resolved_ml_service_base_url == "https://deal-truth-ml.onrender.com"


def test_resolved_ml_service_base_url_falls_back_to_local_dev() -> None:
    # No ngrok in the chain anymore: explicit URL or the local wrangler dev port.
    settings = Settings(
        ml_service_base_url="",
        signed_url_secret="unit-test-signed-url-secret",
    )
    assert settings.resolved_ml_service_base_url == "http://localhost:8081"

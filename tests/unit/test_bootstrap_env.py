from __future__ import annotations

import io
import json
import re
from email.message import EmailMessage
from pathlib import Path
from urllib.error import HTTPError

import pytest
from scripts.bootstrap_env import (
    MintUnavailable,
    apply_sandbox_response,
    ensure_random_secret,
    mint_sandbox_key,
    normalize_pyai_base_url,
    upsert_env,
)


def test_upsert_env_replaces_empty_value() -> None:
    text = "PYAI_API_KEY=\nOTHER=1\n"
    updated = upsert_env(text, "PYAI_API_KEY", "pyai_test_example")
    assert "PYAI_API_KEY=pyai_test_example" in updated
    assert "OTHER=1" in updated


def test_ensure_random_secret_leaves_existing() -> None:
    text, changed = ensure_random_secret("SIGNED_URL_SECRET=already-set\n", "SIGNED_URL_SECRET")
    assert changed is False
    assert "SIGNED_URL_SECRET=already-set" in text


def test_ensure_random_secret_fills_empty() -> None:
    text, changed = ensure_random_secret("SIGNED_URL_SECRET=\n", "SIGNED_URL_SECRET")
    assert changed is True
    value = text.split("=", 1)[1].strip()
    assert value
    assert "already" not in value


def test_normalize_pyai_base_url() -> None:
    assert normalize_pyai_base_url("https://api.pyai.com") == "https://api.pyai.com/v1"
    assert normalize_pyai_base_url("https://api.pyai.com/v1/") == "https://api.pyai.com/v1"


class _FakeResponse(io.BytesIO):
    def __init__(self, payload: bytes, status: int = 201) -> None:
        super().__init__(payload)
        self.status = status

    def getcode(self) -> int:
        return self.status


class _SequenceOpener:
    def __init__(self, items: list[_FakeResponse | Exception]) -> None:
        self._items = list(items)
        self.calls = 0

    def open(self, request: object, timeout: float = 0) -> _FakeResponse:
        self.calls += 1
        item = self._items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _http_error(code: int, retry_after: str | None = None) -> HTTPError:
    hdrs = EmailMessage()
    if retry_after is not None:
        hdrs["Retry-After"] = retry_after
    return HTTPError("https://api.pyai.com/v1/sandbox/keys", code, "error", hdrs=hdrs, fp=None)


def test_mint_sandbox_key_accepts_201() -> None:
    body = json.dumps(
        {
            "object": "sandbox.key",
            "api_key": "pyai_test_unitfixturekey",
            "environment": "test",
            "expires_at": 1,
            "base_url": "https://api.pyai.com",
        }
    ).encode()
    opener = _SequenceOpener([_FakeResponse(body, 201)])
    data = mint_sandbox_key(opener=opener)
    assert data["api_key"] == "pyai_test_unitfixturekey"


def test_mint_sandbox_key_rejects_non_sandbox_prefix() -> None:
    body = json.dumps(
        {
            "api_key": "pyai_live_should_not_be_written",
            "base_url": "https://api.pyai.com/v1",
        }
    ).encode()
    opener = _SequenceOpener([_FakeResponse(body, 201)])
    with pytest.raises(RuntimeError, match="invalid api_key"):
        mint_sandbox_key(opener=opener)


def test_mint_sandbox_key_maps_404() -> None:
    opener = _SequenceOpener([_http_error(404)])
    with pytest.raises(MintUnavailable, match="disabled"):
        mint_sandbox_key(opener=opener)


def test_mint_sandbox_key_retries_429_then_succeeds() -> None:
    body = json.dumps(
        {
            "object": "sandbox.key",
            "api_key": "pyai_test_afterretry",
            "environment": "test",
            "expires_at": 1,
            "base_url": "https://api.pyai.com",
        }
    ).encode()
    opener = _SequenceOpener([_http_error(429, "2"), _FakeResponse(body, 201)])
    waits: list[float] = []
    data = mint_sandbox_key(opener=opener, sleep_fn=waits.append, attempts=3)
    assert data["api_key"] == "pyai_test_afterretry"
    assert waits == [2]
    assert opener.calls == 2


def test_apply_sandbox_response_does_not_echo_key(tmp_path: Path) -> None:
    text = "PYAI_API_KEY=\nPYAI_BASE_URL=https://api.pyai.com/v1\n"
    updated = apply_sandbox_response(
        text,
        {"api_key": "pyai_test_secretvalue", "base_url": "https://api.pyai.com"},
    )
    assert "PYAI_API_KEY=pyai_test_secretvalue" in updated
    assert "PYAI_BASE_URL=https://api.pyai.com/v1" in updated
    env_file = tmp_path / ".env"
    env_file.write_text(updated, encoding="utf-8")
    assert env_file.read_text(encoding="utf-8").startswith("PYAI_API_KEY=")


def test_bootstrap_continues_when_mint_rate_limited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail() -> dict[str, object]:
        raise MintUnavailable("PyAI sandbox minting rate-limited (429)")

    monkeypatch.setattr("scripts.bootstrap_env.mint_sandbox_key", _fail)
    example = tmp_path / ".env.example"
    example.write_text("SIGNED_URL_SECRET=\nPYAI_WEBHOOK_SECRET=\nPYAI_API_KEY=\n", encoding="utf-8")
    env_file = tmp_path / ".env"
    from scripts.bootstrap_env import bootstrap

    assert bootstrap(env_file, example) == 0
    text = env_file.read_text(encoding="utf-8")
    assert re.search(r"^PYAI_API_KEY=$", text, re.MULTILINE)


def test_bootstrap_adds_empty_ngrok_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYAI_SKIP_SANDBOX_MINT", "1")
    example = tmp_path / ".env.example"
    example.write_text(
        "SIGNED_URL_SECRET=\nPYAI_WEBHOOK_SECRET=\nPYAI_API_KEY=\n",
        encoding="utf-8",
    )
    env_file = tmp_path / ".env"
    from scripts.bootstrap_env import bootstrap

    assert bootstrap(env_file, example) == 0
    text = env_file.read_text(encoding="utf-8")
    assert "NGROK_AUTHTOKEN=" in text
    assert "NGROK_AUTHTOKEN=\n" in text or text.strip().endswith("NGROK_AUTHTOKEN=")
    assert "NGROK_ENABLED=true" in text
    assert re.search(r"^S3_ACCESS_KEY=.+$", text, re.MULTILINE)
    assert re.search(r"^S3_SECRET_KEY=.+$", text, re.MULTILINE)


def test_bootstrap_maps_ngrok_auth_token_alias(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYAI_SKIP_SANDBOX_MINT", "1")
    example = tmp_path / ".env.example"
    example.write_text(
        "SIGNED_URL_SECRET=\nPYAI_WEBHOOK_SECRET=\nPYAI_API_KEY=\n",
        encoding="utf-8",
    )
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SIGNED_URL_SECRET=already\nPYAI_WEBHOOK_SECRET=already\nPYAI_API_KEY=pyai_test_x\n"
        "NGROK_AUTH_TOKEN=unit-test-ngrok-alias\n",
        encoding="utf-8",
    )
    from scripts.bootstrap_env import bootstrap

    assert bootstrap(env_file, example) == 0
    text = env_file.read_text(encoding="utf-8")
    assert "NGROK_AUTHTOKEN=unit-test-ngrok-alias" in text

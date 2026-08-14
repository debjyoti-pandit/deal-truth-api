"""Create .env from .env.example and fill empty local-dev secrets.

Mints a PyAI sandbox key via POST /v1/sandbox/keys when PYAI_API_KEY is empty.
Never prints secrets.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / ".env.example"
ENV = ROOT / ".env"

SANDBOX_KEYS_URL = "https://api.pyai.com/v1/sandbox/keys"
SANDBOX_LABEL = "deal-truth-api"
MINT_TIMEOUT_SECONDS = 20
MINT_ATTEMPTS = 4
MINT_RETRY_CAP_SECONDS = 8
KEY_PREFIX = "pyai_test_"


class MintUnavailable(RuntimeError):
    """Sandbox mint could not complete (404, 429, or network). Non-fatal for make up."""


def _read_env_value(text: str, key: str) -> str | None:
    match = re.search(rf"^{re.escape(key)}=(.*)$", text, re.MULTILINE)
    if match is None:
        return None
    return match.group(1).strip().strip("'").strip('"')


def upsert_env(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    line = f"{key}={value}"
    if pattern.search(text):
        return pattern.sub(line, text, count=1)
    return text.rstrip() + "\n" + line + "\n"


def ensure_random_secret(text: str, key: str) -> tuple[str, bool]:
    current = _read_env_value(text, key)
    if current is None:
        text = upsert_env(text, key, "")
        current = ""
    if current:
        return text, False
    return upsert_env(text, key, secrets.token_urlsafe(48)), True


def normalize_pyai_base_url(base_url: str) -> str:
    cleaned = base_url.strip().rstrip("/")
    if cleaned.endswith("/v1"):
        return cleaned
    return f"{cleaned}/v1"


def _retry_after_seconds(exc: urllib.error.HTTPError) -> int:
    raw = ""
    if exc.headers is not None:
        raw = str(exc.headers.get("Retry-After") or "")
    try:
        value = int(raw) if raw.strip() else 3
    except ValueError:
        value = 3
    return max(1, min(value, MINT_RETRY_CAP_SECONDS))


def _mint_once(url: str, opener: object | None) -> dict[str, object]:
    payload = json.dumps({"label": SANDBOX_LABEL}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "deal-truth-api-bootstrap/0.1",
        },
    )
    open_fn = opener.open if opener is not None else urllib.request.urlopen
    try:
        with open_fn(request, timeout=MINT_TIMEOUT_SECONDS) as response:
            status = getattr(response, "status", None) or response.getcode()
            body = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise MintUnavailable("PyAI sandbox minting is disabled on this deployment (404)") from exc
        if exc.code == 429:
            raise MintUnavailable("PyAI sandbox minting rate-limited (429)") from exc
        raise RuntimeError(f"PyAI sandbox mint failed (HTTP {exc.code})") from exc
    except urllib.error.URLError as exc:
        raise MintUnavailable("PyAI sandbox mint request failed") from exc

    if status != 201:
        raise RuntimeError(f"PyAI sandbox mint unexpected status {status}")

    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("PyAI sandbox mint returned invalid JSON") from exc

    if not isinstance(data, dict):
        raise RuntimeError("PyAI sandbox mint returned unexpected payload")

    api_key = data.get("api_key")
    if not isinstance(api_key, str) or not api_key.startswith(KEY_PREFIX) or len(api_key) > 512:
        raise RuntimeError("PyAI sandbox mint returned an invalid api_key")

    return data


def mint_sandbox_key(
    url: str = SANDBOX_KEYS_URL,
    *,
    opener: object | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    attempts: int = MINT_ATTEMPTS,
) -> dict[str, object]:
    last_unavailable: MintUnavailable | None = None
    for index in range(max(1, attempts)):
        try:
            return _mint_once(url, opener)
        except MintUnavailable as exc:
            last_unavailable = exc
            cause = exc.__cause__
            if not isinstance(cause, urllib.error.HTTPError) or cause.code != 429:
                raise
            if index >= attempts - 1:
                raise
            wait = _retry_after_seconds(cause)
            print(
                f"PyAI sandbox mint rate-limited; retrying in {wait}s ({index + 1}/{attempts - 1})",
                file=sys.stderr,
            )
            sleep_fn(wait)
    assert last_unavailable is not None
    raise last_unavailable


def apply_sandbox_response(text: str, data: dict[str, object]) -> str:
    api_key = data["api_key"]
    assert isinstance(api_key, str)
    text = upsert_env(text, "PYAI_API_KEY", api_key)
    base_url = data.get("base_url")
    if isinstance(base_url, str) and base_url.strip():
        current = _read_env_value(text, "PYAI_BASE_URL") or ""
        if not current or current == "https://api.pyai.com/v1":
            text = upsert_env(text, "PYAI_BASE_URL", normalize_pyai_base_url(base_url))
    return text


def bootstrap(env_path: Path = ENV, example_path: Path = EXAMPLE) -> int:
    if not example_path.is_file():
        print("missing .env.example", file=sys.stderr)
        return 1

    created = False
    if not env_path.is_file():
        env_path.write_text(example_path.read_text(encoding="utf-8"), encoding="utf-8")
        created = True

    text = env_path.read_text(encoding="utf-8")
    notes: list[str] = []
    if created:
        notes.append("created .env")

    text, signed_new = ensure_random_secret(text, "SIGNED_URL_SECRET")
    if signed_new:
        notes.append("generated SIGNED_URL_SECRET")

    text, webhook_new = ensure_random_secret(text, "PYAI_WEBHOOK_SECRET")
    if webhook_new:
        notes.append("generated PYAI_WEBHOOK_SECRET")

    # Local SeaweedFS S3 accepts any identity when unconfigured; boto3 still needs keys to sign.
    text, s3_access_new = ensure_random_secret(text, "S3_ACCESS_KEY")
    text, s3_secret_new = ensure_random_secret(text, "S3_SECRET_KEY")
    if s3_access_new or s3_secret_new:
        notes.append("generated S3_ACCESS_KEY/S3_SECRET_KEY")

    pyai_key = _read_env_value(text, "PYAI_API_KEY") or ""
    skip_mint = os.environ.get("PYAI_SKIP_SANDBOX_MINT", "").strip() in {
        "1",
        "true",
        "yes",
    }
    if pyai_key:
        notes.append("kept existing PYAI_API_KEY")
    elif skip_mint:
        notes.append("skipped PyAI sandbox mint")
    else:
        try:
            data = mint_sandbox_key()
        except MintUnavailable as exc:
            print(f"warning: {exc}; continuing without PYAI_API_KEY", file=sys.stderr)
            notes.append("PyAI sandbox mint unavailable")
        except RuntimeError as exc:
            print(f"env bootstrap failed: {exc}", file=sys.stderr)
            return 1
        else:
            text = apply_sandbox_response(text, data)
            notes.append("minted PYAI_API_KEY (sandbox)")

    # Official ngrok env is NGROK_AUTHTOKEN; also accept NGROK_AUTH_TOKEN.
    # Never generate or print the token.
    official = _read_env_value(text, "NGROK_AUTHTOKEN")
    alias = _read_env_value(text, "NGROK_AUTH_TOKEN")
    if not official and alias:
        text = upsert_env(text, "NGROK_AUTHTOKEN", alias)
        notes.append("mapped NGROK_AUTH_TOKEN to NGROK_AUTHTOKEN")
    elif official is None:
        text = upsert_env(text, "NGROK_AUTHTOKEN", "")
    if _read_env_value(text, "NGROK_ENABLED") is None:
        text = upsert_env(text, "NGROK_ENABLED", "true")
    if _read_env_value(text, "NGROK_API_URL") is None:
        text = upsert_env(text, "NGROK_API_URL", "http://127.0.0.1:4040")
    if _read_env_value(text, "NGROK_DOMAIN") is None:
        text = upsert_env(text, "NGROK_DOMAIN", "")

    env_path.write_text(text, encoding="utf-8")
    print("env ready" + (f" ({'; '.join(notes)})" if notes else ""))
    return 0


def main() -> int:
    return bootstrap()


if __name__ == "__main__":
    raise SystemExit(main())

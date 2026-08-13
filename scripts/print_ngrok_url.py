"""Print the ngrok HTTPS public URL from the local inspector API. Stdlib only."""

from __future__ import annotations

import http.client
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_API = "http://127.0.0.1:4040"


def pinned_domain_url(env_path: Path | None = None) -> str | None:
    path = env_path or (Path(__file__).resolve().parents[1] / ".env")
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^NGROK_DOMAIN=(.*)$", text, re.MULTILINE)
    if match is None:
        return None
    domain = match.group(1).strip().strip("'").strip('"')
    if not domain:
        return None
    host = domain.removeprefix("https://").removeprefix("http://").split("/")[0]
    if not host or host in {"localhost", "127.0.0.1"}:
        return None
    return f"https://{host}"


_FETCH_ERRORS = (
    urllib.error.URLError,
    TimeoutError,
    json.JSONDecodeError,
    UnicodeDecodeError,
    http.client.HTTPException,
    ConnectionError,
    OSError,
)


def fetch_https_url(api_url: str) -> str | None:
    url = f"{api_url.rstrip('/')}/api/tunnels"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except _FETCH_ERRORS:
        return None
    tunnels = payload.get("tunnels") if isinstance(payload, dict) else None
    if not isinstance(tunnels, list):
        return None
    for tunnel in tunnels:
        if not isinstance(tunnel, dict):
            continue
        public_url = tunnel.get("public_url")
        if isinstance(public_url, str) and public_url.startswith("https://"):
            return public_url.rstrip("/")
    return None


def wait_for_url(api_url: str, wait_seconds: float) -> str | None:
    deadline = time.monotonic() + wait_seconds
    while True:
        found = fetch_https_url(api_url)
        if found:
            return found
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.5)


def main() -> int:
    api_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_API
    wait_seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
    try:
        url = wait_for_url(api_url, wait_seconds) or pinned_domain_url()
    except Exception:
        print("ngrok tunnel URL not ready", file=sys.stderr)
        return 1
    if not url:
        print(
            "ngrok tunnel URL not ready (set NGROK_AUTHTOKEN and NGROK_DOMAIN in .env)",
            file=sys.stderr,
        )
        return 1
    print(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

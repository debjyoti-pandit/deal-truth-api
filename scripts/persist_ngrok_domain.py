"""Pin NGROK_DOMAIN in .env so the tunnel hostname stays stable. Never prints secrets."""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.bootstrap_env import _read_env_value, upsert_env  # noqa: E402

ENV = ROOT / ".env"


def hostname_from_public_url(url: str) -> str | None:
    raw = url.strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if not host or host in {"localhost", "127.0.0.1", "::1", "testserver"}:
        return None
    if parsed.username or parsed.password:
        return None
    return host


def persist_ngrok_domain(text: str, public_url: str) -> tuple[str, str | None, bool]:
    host = hostname_from_public_url(public_url)
    if not host:
        return text, None, False
    current = (_read_env_value(text, "NGROK_DOMAIN") or "").strip()
    if current:
        current_host = hostname_from_public_url(current) or current
        if current_host == host:
            return text, host, False
        return text, current_host, False
    return upsert_env(text, "NGROK_DOMAIN", host), host, True


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: persist_ngrok_domain.py <https-url>", file=sys.stderr)
        return 1
    public_url = sys.argv[1]
    env_path = Path(sys.argv[2]) if len(sys.argv) > 2 else ENV
    if not env_path.is_file():
        print("missing .env", file=sys.stderr)
        return 1
    text = env_path.read_text(encoding="utf-8")
    updated, host, wrote = persist_ngrok_domain(text, public_url)
    if wrote:
        env_path.write_text(updated, encoding="utf-8")
        print(f"pinned NGROK_DOMAIN={host}")
    elif host:
        print(f"NGROK_DOMAIN={host}")
    else:
        print("could not pin NGROK_DOMAIN", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

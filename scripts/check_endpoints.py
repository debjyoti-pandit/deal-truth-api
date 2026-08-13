"""Smoke-check every HTTP route. Never prints secrets or response bodies.

Usage:
  uv run python scripts/check_endpoints.py --in-process   # before the server starts
  python3 scripts/check_endpoints.py --base-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_SKIP_PATH_PARTS = ("/stream",)
_PLACEHOLDERS = {
    "call_id": "00000000-0000-4000-8000-000000000001",
    "asset_id": "00000000-0000-4000-8000-000000000002",
    "share_id": "00000000-0000-4000-8000-000000000003",
    "token": "smoke-check-token",
    "name": "ARCHITECTURE.md",
}
_OK_GET = frozenset(range(200, 400)) | {401, 403, 404, 405, 409, 422}
_OK_MUTATE = frozenset({400, 401, 403, 404, 405, 409, 415, 422}) | set(range(200, 300))


@dataclass(frozen=True)
class Probe:
    method: str
    path: str
    ok: frozenset[int]


@dataclass
class ProbeResult:
    probe: Probe
    status: int | None
    error: str | None

    @property
    def passed(self) -> bool:
        if self.status is None:
            return False
        return self.status in self.probe.ok and self.status < 500


def fill_path(path: str) -> str:
    return re.sub(r"\{([^}]+)\}", lambda m: _PLACEHOLDERS.get(m.group(1), "x"), path)


def probes_from_openapi(schema: dict[str, Any]) -> list[Probe]:
    paths = schema.get("paths")
    if not isinstance(paths, dict):
        return []
    probes: list[Probe] = []
    for raw_path, item in paths.items():
        if not isinstance(raw_path, str) or not isinstance(item, dict):
            continue
        if any(part in raw_path for part in _SKIP_PATH_PARTS):
            continue
        path = fill_path(raw_path)
        for method in ("get", "post", "put", "patch", "delete"):
            if method not in item:
                continue
            ok = _OK_GET if method == "get" else _OK_MUTATE
            probes.append(Probe(method=method.upper(), path=path, ok=ok))
    probes.extend(
        [
            Probe("GET", "/health/live", frozenset({200})),
            Probe("GET", "/health/ready", frozenset({200, 503})),
            Probe("GET", "/openapi.json", frozenset({200})),
            Probe("GET", "/docs", frozenset({200})),
        ]
    )
    seen: set[tuple[str, str]] = set()
    unique: list[Probe] = []
    for probe in probes:
        key = (probe.method, probe.path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(probe)
    return unique


def _request_live(base_url: str, probe: Probe, timeout: float) -> ProbeResult:
    url = base_url.rstrip("/") + probe.path
    request = Request(url, method=probe.method, headers={"Accept": "application/json", "Content-Type": "application/json"})
    if probe.method in {"POST", "PUT", "PATCH"}:
        request.data = b"{"
        request.add_header("Content-Type", "application/json")
    try:
        with urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", None) or response.getcode())
            response.read(256)
            return ProbeResult(probe, status, None)
    except HTTPError as exc:
        try:
            exc.read(256)
        except OSError:
            pass
        return ProbeResult(probe, int(exc.code), None)
    except (URLError, TimeoutError, OSError) as exc:
        return ProbeResult(probe, None, exc.__class__.__name__)


def wait_for_live(base_url: str, wait_seconds: float) -> bool:
    deadline = time.monotonic() + wait_seconds
    probe = Probe("GET", "/health/live", frozenset({200}))
    while True:
        result = _request_live(base_url, probe, timeout=2.0)
        if result.status == 200:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.5)


def run_live(base_url: str, schema: dict[str, Any], timeout: float) -> list[ProbeResult]:
    return [_request_live(base_url, probe, timeout) for probe in probes_from_openapi(schema)]


def _prepare_in_process_env() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="deal-truth-smoke-"))
    db = tmp / "smoke.db"
    isolated = {
        "APP_ENV": "test",
        "DATABASE_URL": f"sqlite+aiosqlite:///{db}",
        "DATABASE_SYNC_URL": f"sqlite:///{db}",
        "SIGNED_URL_SECRET": "smoke-check-signed-url-secret-not-for-prod",
        "PYAI_WEBHOOK_SECRET": "smoke-check-webhook-secret",
        "AUTH_MODE": "none",
        "API_KEYS": "",
        "NGROK_ENABLED": "false",
        "NGROK_DOMAIN": "",
        "PYAI_API_KEY": "",
        "S3_ACCESS_KEY": "",
        "S3_SECRET_KEY": "",
        "ML_SERVICE_API_KEY": "",
        "PUBLIC_API_BASE_URL": "http://testserver",
    }
    os.environ.update(isolated)


def run_in_process() -> list[ProbeResult]:
    _prepare_in_process_env()
    from app.core.settings import reset_settings_cache
    from app.main import create_app
    from fastapi.testclient import TestClient

    reset_settings_cache()
    app = create_app()
    schema = app.openapi()
    results: list[ProbeResult] = []
    with TestClient(app) as client:
        for probe in probes_from_openapi(schema):
            kwargs: dict[str, Any] = {}
            if probe.method in {"POST", "PUT", "PATCH"}:
                kwargs["content"] = b"{"
                kwargs["headers"] = {"Content-Type": "application/json"}
            try:
                response = client.request(probe.method, probe.path, **kwargs)
                results.append(ProbeResult(probe, response.status_code, None))
            except Exception as exc:
                results.append(ProbeResult(probe, None, exc.__class__.__name__))
    return results


def fetch_live_schema(base_url: str, timeout: float) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/openapi.json"
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def report(results: list[ProbeResult]) -> int:
    failed = [item for item in results if not item.passed]
    width = max((len(item.probe.path) for item in results), default=8)
    for item in results:
        mark = "ok" if item.passed else "FAIL"
        status = item.status if item.status is not None else item.error or "error"
        print(f"  {mark:4} {item.probe.method:6} {item.probe.path:<{width}}  {status}")
    print(f"{len(results) - len(failed)}/{len(results)} endpoints ok")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-check Deal Truth HTTP endpoints")
    parser.add_argument("--in-process", action="store_true", help="Use TestClient (run before starting the server)")
    parser.add_argument("--base-url", default="", help="Live server, e.g. http://localhost:8000")
    parser.add_argument("--wait", type=float, default=45.0, help="Seconds to wait for /health/live")
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args(argv)

    if args.in_process:
        print("Checking endpoints in-process (server not required)...")
        return report(run_in_process())

    base = args.base_url.strip() or os.environ.get("DEAL_TRUTH_BASE_URL", "http://localhost:8000")
    print(f"Checking endpoints at {base} ...")
    if not wait_for_live(base, args.wait):
        print("FAIL  GET /health/live never became ready", file=sys.stderr)
        return 1
    try:
        schema = fetch_live_schema(base, args.timeout)
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        print(f"FAIL  could not load /openapi.json ({exc.__class__.__name__})", file=sys.stderr)
        return 1
    return report(run_live(base, schema, args.timeout))


if __name__ == "__main__":
    raise SystemExit(main())

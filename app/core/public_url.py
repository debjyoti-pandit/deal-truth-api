"""Resolve a URL PyAI can reach (ngrok public HTTPS, not localhost)."""

from __future__ import annotations

import ipaddress
import logging
import time
from urllib.parse import urlparse

import httpx

from app.core.settings import Settings

logger = logging.getLogger(__name__)

_LOOPBACK_HOSTS = frozenset({"localhost", "localhost.localdomain", "127.0.0.1", "::1", "0.0.0.0", "testserver"})
_ALLOWED_NGROK_API_HOSTS = frozenset({"127.0.0.1", "localhost", "ngrok", "::1", "host.docker.internal"})


def is_loopback_base_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not host or host in _LOOPBACK_HOSTS or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_public_https_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False
    return not is_loopback_base_url(url)


def pick_ngrok_https_url(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    tunnels = payload.get("tunnels")
    if not isinstance(tunnels, list):
        return None
    https_url: str | None = None
    for tunnel in tunnels:
        if not isinstance(tunnel, dict):
            continue
        public_url = tunnel.get("public_url")
        if not isinstance(public_url, str) or not public_url.strip():
            continue
        candidate = public_url.strip().rstrip("/")
        proto = str(tunnel.get("proto") or "").lower()
        if proto == "https" or candidate.startswith("https://"):
            https_url = candidate
            break
    return https_url


def _ngrok_api_allowed(api_url: str) -> bool:
    parsed = urlparse(api_url)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    return host in _ALLOWED_NGROK_API_HOSTS


def fetch_ngrok_public_url(api_url: str, *, timeout: float = 2.0) -> str | None:
    if not _ngrok_api_allowed(api_url):
        logger.warning("ngrok API URL host is not allowed")
        return None
    url = f"{api_url.rstrip('/')}/api/tunnels"
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(url)
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    return pick_ngrok_https_url(payload)


def wait_for_ngrok_public_url(api_url: str, wait_seconds: float) -> str | None:
    deadline = time.monotonic() + max(0.0, wait_seconds)
    while True:
        found = fetch_ngrok_public_url(api_url)
        if found:
            return found
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.5)


def hostname_from_public_url(url: str) -> str | None:
    raw = url.strip()
    if not raw or "://" not in raw:
        raw = f"https://{raw}" if raw else ""
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if not host or is_loopback_base_url(f"https://{host}"):
        return None
    if parsed.username or parsed.password:
        return None
    return host


def public_base_from_ngrok_domain(domain: str) -> str | None:
    host = hostname_from_public_url(domain)
    if not host:
        return None
    return f"https://{host}"


def resolve_public_api_base_url(settings: Settings) -> str:
    configured = settings.public_api_base_url.rstrip("/")
    if is_public_https_url(configured):
        return configured
    pinned = public_base_from_ngrok_domain(settings.ngrok_domain)
    if pinned:
        return pinned
    if not settings.ngrok_enabled:
        return configured
    found = wait_for_ngrok_public_url(settings.ngrok_api_url, settings.ngrok_wait_seconds)
    if found:
        return found
    logger.warning("ngrok public URL unavailable; PyAI webhooks and audio_url will not reach this machine")
    return configured

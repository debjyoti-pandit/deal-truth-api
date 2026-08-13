"""HTTPS-only source URL fetching with SSRF protection."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterator
from urllib.parse import urljoin, urlparse

import httpx

from app.core.errors import InvalidSourceURL
from app.core.settings import Settings

_BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "metadata.google.internal",
        "metadata.google.com",
    }
)


def _is_blocked_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return bool(
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
        or (addr.version == 6 and addr.ipv4_mapped is not None and _is_blocked_ip(str(addr.ipv4_mapped)))
    )


def validate_public_https_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https":
        raise InvalidSourceURL("Only HTTPS source URLs are allowed")
    host = (parsed.hostname or "").lower()
    if not host:
        raise InvalidSourceURL("Source URL is missing a host")
    if host in _BLOCKED_HOSTS or host.endswith(".localhost"):
        raise InvalidSourceURL("Source URL host is not allowed")
    try:
        ipaddress.ip_address(host)
        if _is_blocked_ip(host):
            raise InvalidSourceURL("Source URL host is a private or reserved address")
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise InvalidSourceURL("Source URL host could not be resolved") from exc
    if not infos:
        raise InvalidSourceURL("Source URL host could not be resolved")
    for info in infos:
        ip = str(info[4][0])
        if _is_blocked_ip(ip):
            raise InvalidSourceURL("Source URL resolves to a private or reserved address")


def fetch_https_source(url: str, settings: Settings) -> tuple[bytes, str, str]:
    """Return (body, content_type, filename). Re-validates after every redirect."""
    current = url
    for _ in range(settings.source_fetch_max_redirects + 1):
        validate_public_https_url(current)
        with httpx.Client(follow_redirects=False, timeout=settings.source_fetch_timeout_seconds) as client:
            response = client.get(current)
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("location")
            if not location:
                raise InvalidSourceURL("Redirect is missing a Location header")
            current = urljoin(current, location)
            continue
        if response.status_code >= 400:
            raise InvalidSourceURL(
                "Source URL fetch failed",
                details={"status_code": response.status_code},
            )
        content_type = response.headers.get("content-type", "application/octet-stream").split(";")[0]
        parsed = urlparse(current)
        filename = parsed.path.rsplit("/", 1)[-1] or "source-audio.bin"
        body = response.content
        if not body:
            raise InvalidSourceURL("Source URL returned an empty body")
        if len(body) > settings.max_audio_bytes:
            from app.core.errors import AudioTooLarge

            raise AudioTooLarge("Fetched audio exceeds maximum allowed size")
        return body, content_type, filename
    raise InvalidSourceURL("Too many redirects while fetching source URL")


def iter_blocked_examples() -> Iterator[str]:
    yield from (
        "http://example.com/a.mp3",
        "https://localhost/a.mp3",
        "https://127.0.0.1/a.mp3",
        "https://10.0.0.1/a.mp3",
        "https://192.168.1.1/a.mp3",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/a.mp3",
    )

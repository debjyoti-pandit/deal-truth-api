"""HMAC, share-token hashing, and API-key comparison. Never log secrets."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from uuid import UUID

from app.core.errors import SignedURLInvalid, UnauthorizedError
from app.core.settings import Settings


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_share_token() -> str:
    return secrets.token_urlsafe(32)


def constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def verify_api_key(provided: str | None, settings: Settings) -> None:
    if settings.auth_mode.value == "none":
        return
    if not provided:
        raise UnauthorizedError("API key required")
    scheme, _, token = provided.partition(" ")
    candidate = token if scheme.lower() == "bearer" else provided
    for allowed in settings.api_key_set:
        if hmac.compare_digest(candidate, allowed):
            return
    raise UnauthorizedError("Invalid API key")


def sign_payload(secret: bytes, payload: str) -> str:
    return hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_hmac_hex(secret: bytes, payload: bytes, provided: str) -> bool:
    expected = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    provided_hex = provided.strip()
    if provided_hex.lower().startswith("sha256="):
        provided_hex = provided_hex.split("=", 1)[1]
    try:
        return hmac.compare_digest(expected, provided_hex.lower())
    except Exception:
        return False


def build_signed_audio_query(asset_id: UUID, expires: int, secret: bytes) -> str:
    payload = f"{asset_id}:{expires}"
    signature = sign_payload(secret, payload)
    return f"expires={expires}&signature={signature}"


def verify_signed_audio(asset_id: UUID, expires: int, signature: str, secret: bytes) -> None:
    now = int(time.time())
    if expires < now:
        raise SignedURLInvalid("Signed audio URL has expired")
    payload = f"{asset_id}:{expires}"
    expected = sign_payload(secret, payload)
    if not hmac.compare_digest(expected, signature.lower()):
        raise SignedURLInvalid("Invalid signed audio URL")

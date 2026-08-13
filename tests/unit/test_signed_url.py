import time
from uuid import uuid4

import pytest
from app.core.errors import SignedURLInvalid
from app.core.security import build_signed_audio_query, hash_token, verify_signed_audio


def test_signed_audio_url_expiry() -> None:
    asset = uuid4()
    secret = b"unit-test-signed-url-secret"
    expires = int(time.time()) - 10
    query = build_signed_audio_query(asset, expires, secret)
    signature = query.split("signature=")[1]
    with pytest.raises(SignedURLInvalid):
        verify_signed_audio(asset, expires, signature, secret)


def test_signed_audio_url_accepts_future_expiry() -> None:
    asset = uuid4()
    secret = b"unit-test-signed-url-secret"
    expires = int(time.time()) + 60
    query = build_signed_audio_query(asset, expires, secret)
    signature = query.split("signature=")[1]
    verify_signed_audio(asset, expires, signature, secret)


def test_share_token_is_hashed_not_stored_raw() -> None:
    token = "plaintext-share-token-value"
    digest = hash_token(token)
    assert digest != token
    assert len(digest) == 64
    assert hash_token(token) == digest

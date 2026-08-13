from __future__ import annotations

from unittest.mock import MagicMock

from app.core.errors import BlobUploadFailed
from app.core.settings import Settings
from app.storage.seaweed import SeaweedFSS3BlobStore
from botocore.exceptions import EndpointConnectionError


def _store() -> SeaweedFSS3BlobStore:
    settings = Settings(
        app_env="test",
        s3_access_key="local",
        s3_secret_key="local",
        s3_endpoint_url="http://seaweedfs:8333",
    )
    store = SeaweedFSS3BlobStore(settings)
    store._client = MagicMock()
    store._buckets = ("deal-truth-audio",)  # type: ignore[assignment]
    return store


def test_ensure_buckets_retries_endpoint_connection_error() -> None:
    store = _store()
    store._client.head_bucket.side_effect = [
        EndpointConnectionError(endpoint_url="http://seaweedfs:8333"),
        EndpointConnectionError(endpoint_url="http://seaweedfs:8333"),
        {},
    ]
    store.ensure_buckets(attempts=5, delay_seconds=0)
    assert store._client.head_bucket.call_count == 3


def test_ensure_buckets_gives_up_after_attempts() -> None:
    store = _store()
    store._client.head_bucket.side_effect = EndpointConnectionError(endpoint_url="http://seaweedfs:8333")
    try:
        store.ensure_buckets(attempts=2, delay_seconds=0)
        raise AssertionError("expected BlobUploadFailed")
    except BlobUploadFailed as exc:
        assert exc.details["error_code"] == "EndpointConnectionError"
    assert store._client.head_bucket.call_count == 2

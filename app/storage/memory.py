"""In-memory BlobStore for tests. No boto3."""

from __future__ import annotations

from io import BytesIO
from typing import BinaryIO

from app.core.errors import BlobNotFound
from app.storage.base import BlobObject


class MemoryBlobStore:
    def __init__(self) -> None:
        self._objects: dict[tuple[str, str], tuple[bytes, str]] = {}
        self.buckets: set[str] = set()

    def ensure_buckets(self) -> None:
        return None

    def upload_stream(
        self,
        bucket: str,
        key: str,
        stream: BinaryIO,
        content_type: str,
        *,
        length: int | None = None,
    ) -> int:
        data = stream.read()
        self._objects[(bucket, key)] = (data, content_type)
        self.buckets.add(bucket)
        return len(data)

    def put_bytes(self, bucket: str, key: str, data: bytes, content_type: str) -> int:
        self._objects[(bucket, key)] = (data, content_type)
        self.buckets.add(bucket)
        return len(data)

    def get_bytes(self, bucket: str, key: str) -> bytes:
        try:
            return self._objects[(bucket, key)][0]
        except KeyError as exc:
            raise BlobNotFound("Object not found") from exc

    def download_stream(
        self,
        bucket: str,
        key: str,
        *,
        range_start: int | None = None,
        range_end: int | None = None,
    ) -> BlobObject:
        data, content_type = self._lookup(bucket, key)
        start = range_start or 0
        end = range_end if range_end is not None else len(data) - 1
        end = min(end, len(data) - 1)
        if start < 0 or start > end:
            sliced = b""
        else:
            sliced = data[start : end + 1]
        return BlobObject(
            body=BytesIO(sliced),
            content_type=content_type,
            size_bytes=len(data),
            range_start=start if range_start is not None else None,
            range_end=end if range_start is not None else None,
        )

    def exists(self, bucket: str, key: str) -> bool:
        return (bucket, key) in self._objects

    def delete(self, bucket: str, key: str) -> None:
        self._objects.pop((bucket, key), None)

    def _lookup(self, bucket: str, key: str) -> tuple[bytes, str]:
        try:
            return self._objects[(bucket, key)]
        except KeyError as exc:
            raise BlobNotFound("Object not found") from exc

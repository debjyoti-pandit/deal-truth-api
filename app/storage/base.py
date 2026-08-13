"""BlobStore protocol. Only implementations may know S3/boto3."""

from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO, Protocol, runtime_checkable


@dataclass
class BlobObject:
    body: BinaryIO
    content_type: str
    size_bytes: int
    range_start: int | None = None
    range_end: int | None = None
    etag: str | None = None


@runtime_checkable
class BlobStore(Protocol):
    def ensure_buckets(self) -> None: ...

    def upload_stream(
        self,
        bucket: str,
        key: str,
        stream: BinaryIO,
        content_type: str,
        *,
        length: int | None = None,
    ) -> int: ...

    def put_bytes(self, bucket: str, key: str, data: bytes, content_type: str) -> int: ...

    def get_bytes(self, bucket: str, key: str) -> bytes: ...

    def download_stream(
        self,
        bucket: str,
        key: str,
        *,
        range_start: int | None = None,
        range_end: int | None = None,
    ) -> BlobObject: ...

    def exists(self, bucket: str, key: str) -> bool: ...

    def delete(self, bucket: str, key: str) -> None: ...

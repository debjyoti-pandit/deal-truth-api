"""SeaweedFS via the S3-compatible API. This module is the only boto3 consumer."""

from __future__ import annotations

import logging
import time
from io import BytesIO
from typing import BinaryIO

from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

from app.core.errors import BlobDownloadFailed, BlobNotFound, BlobUploadFailed
from app.core.settings import Settings
from app.storage.base import BlobObject

_MISSING_BUCKET = frozenset({"NoSuchBucket", "404", "NotFound"})
_RETRYABLE_CODES = frozenset({"EndpointConnectionError", "ConnectTimeoutError", "ConnectionClosedError"})
_log = logging.getLogger(__name__)


def _error_code(exc: BaseException) -> str:
    if isinstance(exc, ClientError):
        return str((exc.response.get("Error") or {}).get("Code") or "ClientError")
    return type(exc).__name__


class SeaweedFSS3BlobStore:
    def __init__(self, settings: Settings) -> None:
        import boto3

        self._settings = settings
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key or None,
            aws_secret_access_key=settings.s3_secret_key or None,
            region_name=settings.s3_region,
            use_ssl=settings.s3_use_ssl,
            config=Config(
                s3={"addressing_style": settings.s3_addressing_style},  # type: ignore[arg-type]
                signature_version="s3v4",
            ),
        )
        self._buckets = (
            settings.s3_bucket_audio,
            settings.s3_bucket_results,
            settings.s3_bucket_samples,
        )

    def ensure_buckets(self, *, attempts: int = 1, delay_seconds: float = 0.5) -> None:
        last: BlobUploadFailed | None = None
        total = max(attempts, 1)
        for attempt in range(1, total + 1):
            try:
                self._ensure_buckets_once()
                return
            except BlobUploadFailed as exc:
                last = exc
                code = str(exc.details.get("error_code") or "")
                if code not in _RETRYABLE_CODES or attempt >= total:
                    raise
                _log.warning("storage not ready (%s); retry %s/%s", code, attempt, total)
                if delay_seconds > 0:
                    time.sleep(delay_seconds)
        if last is not None:
            raise last

    def _ensure_buckets_once(self) -> None:
        for bucket in self._buckets:
            try:
                self._client.head_bucket(Bucket=bucket)
            except ClientError:
                try:
                    self._client.create_bucket(Bucket=bucket)
                except (ClientError, BotoCoreError, NoCredentialsError) as exc:
                    raise BlobUploadFailed(
                        "Failed to create storage bucket",
                        details={"error_code": _error_code(exc)},
                    ) from exc
            except (BotoCoreError, NoCredentialsError) as exc:
                raise BlobUploadFailed(
                    "Failed to create storage bucket",
                    details={"error_code": _error_code(exc)},
                ) from exc

    def upload_stream(
        self,
        bucket: str,
        key: str,
        stream: BinaryIO,
        content_type: str,
        *,
        length: int | None = None,
    ) -> int:
        extra: dict[str, object] = {"ContentType": content_type}

        def _put() -> None:
            self._client.upload_fileobj(stream, bucket, key, ExtraArgs=extra)

        try:
            _put()
        except (BotoCoreError, ClientError, NoCredentialsError) as exc:
            code = _error_code(exc)
            if code in _MISSING_BUCKET:
                self.ensure_buckets()
                try:
                    stream.seek(0)
                except Exception:
                    pass
                try:
                    _put()
                except (BotoCoreError, ClientError, NoCredentialsError) as retry_exc:
                    raise BlobUploadFailed(
                        "Failed to upload object",
                        details={"error_code": _error_code(retry_exc)},
                    ) from retry_exc
            else:
                raise BlobUploadFailed("Failed to upload object", details={"error_code": code}) from exc
        try:
            head = self._client.head_object(Bucket=bucket, Key=key)
            return int(head.get("ContentLength") or length or 0)
        except (BotoCoreError, ClientError) as exc:
            raise BlobUploadFailed(
                "Failed to confirm uploaded object",
                details={"error_code": _error_code(exc)},
            ) from exc

    def put_bytes(self, bucket: str, key: str, data: bytes, content_type: str) -> int:
        return self.upload_stream(bucket, key, BytesIO(data), content_type, length=len(data))

    def get_bytes(self, bucket: str, key: str) -> bytes:
        obj = self.download_stream(bucket, key)
        return obj.body.read()

    def download_stream(
        self,
        bucket: str,
        key: str,
        *,
        range_start: int | None = None,
        range_end: int | None = None,
    ) -> BlobObject:
        kwargs: dict[str, object] = {"Bucket": bucket, "Key": key}
        range_header = None
        if range_start is not None:
            if range_end is not None:
                range_header = f"bytes={range_start}-{range_end}"
            else:
                range_header = f"bytes={range_start}-"
            kwargs["Range"] = range_header
        try:
            response = self._client.get_object(**kwargs)
        except ClientError as exc:
            code = (exc.response.get("Error") or {}).get("Code", "")
            if code in {"NoSuchKey", "404", "NotFound"}:
                raise BlobNotFound("Object not found") from exc
            raise BlobDownloadFailed("Failed to download object") from exc
        except BotoCoreError as exc:
            raise BlobDownloadFailed("Failed to download object") from exc
        size = int(response.get("ContentLength") or 0)
        content_range = response.get("ContentRange")
        parsed_start = range_start
        parsed_end = range_end
        total = size
        if content_range and "/" in content_range:
            spec, _, total_s = content_range.replace("bytes ", "").partition("/")
            start_s, _, end_s = spec.partition("-")
            parsed_start = int(start_s)
            parsed_end = int(end_s)
            total = int(total_s)
        return BlobObject(
            body=response["Body"],
            content_type=str(response.get("ContentType") or "application/octet-stream"),
            size_bytes=total,
            range_start=parsed_start,
            range_end=parsed_end,
            etag=response.get("ETag"),
        )

    def exists(self, bucket: str, key: str) -> bool:
        try:
            self._client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError:
            return False

    def delete(self, bucket: str, key: str) -> None:
        try:
            self._client.delete_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            raise BlobDownloadFailed("Failed to delete object") from exc

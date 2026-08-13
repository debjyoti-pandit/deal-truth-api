"""Audio upload, source-url fetch, Range streaming, signed public URLs."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import AppContainer, get_container, get_sync_session, require_auth
from app.api.v1.calls import _detail, _get_call
from app.core.enums import CallStatus, EventState, SourceType
from app.core.errors import BlobNotFound, InvalidAudio
from app.core.public_url import resolve_public_api_base_url
from app.core.security import build_signed_audio_query, verify_signed_audio
from app.models.call import AudioAsset
from app.pipeline.state import log_event, transition
from app.schemas import AudioURLOut, CallDetail, SourceURLRequest
from app.storage.keys import blob_keys
from app.storage.ssrf import fetch_https_source
from app.storage.validate import SizeLimitReader, safe_filename, validate_audio_meta

router = APIRouter(prefix="/api/v1", tags=["audio"])


@router.post("/calls/{call_id}/audio", dependencies=[Depends(require_auth)])
async def upload_audio(
    call_id: UUID,
    file: UploadFile = File(...),
    session: Session = Depends(get_sync_session),
    container: AppContainer = Depends(get_container),
) -> CallDetail:
    call = _get_call(session, call_id)
    filename = safe_filename(file.filename or "audio.bin")
    content_type = file.content_type or "application/octet-stream"
    settings = container.settings
    validate_audio_meta(filename, content_type, 1, settings)
    transition(session, call, CallStatus.UPLOADING)
    session.flush()
    limited = SizeLimitReader(file.file, settings.max_audio_bytes)
    keys = blob_keys(call.id, filename)
    size = container.blob.upload_stream(
        settings.s3_bucket_audio,
        keys.original,
        limited,  # type: ignore[arg-type]
        content_type,
    )
    if size <= 0 and limited.bytes_read <= 0:
        raise InvalidAudio("Audio file is empty")
    asset = AudioAsset(
        call_id=call.id,
        bucket=settings.s3_bucket_audio,
        object_key=keys.original,
        original_filename=filename,
        content_type=content_type,
        size_bytes=limited.bytes_read or size,
        checksum=limited.hexdigest(),
    )
    session.add(asset)
    call.source_type = SourceType.UPLOAD
    transition(session, call, CallStatus.QUEUED)
    log_event(session, call, stage="upload", state=EventState.SUCCEEDED)
    return _detail(call)


@router.post("/calls/{call_id}/source-url", dependencies=[Depends(require_auth)])
def source_url(
    call_id: UUID,
    body: SourceURLRequest,
    session: Session = Depends(get_sync_session),
    container: AppContainer = Depends(get_container),
) -> CallDetail:
    call = _get_call(session, call_id)
    data, content_type, filename = fetch_https_source(str(body.url), container.settings)
    filename = safe_filename(filename)
    validate_audio_meta(filename, content_type, len(data), container.settings)
    transition(session, call, CallStatus.UPLOADING)
    session.flush()
    keys = blob_keys(call.id, filename)
    from io import BytesIO

    limited = SizeLimitReader(BytesIO(data), container.settings.max_audio_bytes)
    size = container.blob.upload_stream(
        container.settings.s3_bucket_audio,
        keys.original,
        limited,  # type: ignore[arg-type]
        content_type,
        length=len(data),
    )
    session.add(
        AudioAsset(
            call_id=call.id,
            bucket=container.settings.s3_bucket_audio,
            object_key=keys.original,
            original_filename=filename,
            content_type=content_type,
            size_bytes=size or len(data),
            checksum=limited.hexdigest(),
        )
    )
    call.source_type = SourceType.SOURCE_URL
    transition(session, call, CallStatus.QUEUED)
    log_event(session, call, stage="source_url", state=EventState.SUCCEEDED)
    return _detail(call)


def _range_tuple(header: str | None, size: int) -> tuple[int | None, int | None, int]:
    if not header or not header.startswith("bytes="):
        return None, None, 200
    spec = header.split("=", 1)[1].split(",")[0].strip()
    start_s, _, end_s = spec.partition("-")
    if start_s == "":
        suffix = int(end_s)
        start = max(size - suffix, 0)
        return start, size - 1, 206
    start = int(start_s)
    end = int(end_s) if end_s else size - 1
    if start >= size:
        return 0, size - 1, 416
    return start, min(end, size - 1), 206


@router.get("/calls/{call_id}/audio", dependencies=[Depends(require_auth)])
def get_audio(
    call_id: UUID,
    request: Request,
    session: Session = Depends(get_sync_session),
    container: AppContainer = Depends(get_container),
) -> StreamingResponse:
    call = _get_call(session, call_id)
    asset = session.query(AudioAsset).filter(AudioAsset.call_id == call.id).first()
    if asset is None:
        raise BlobNotFound("Audio asset not found")
    return _stream_asset(asset, request, container)


@router.get("/calls/{call_id}/audio-url", dependencies=[Depends(require_auth)])
def get_audio_url(
    call_id: UUID,
    session: Session = Depends(get_sync_session),
    container: AppContainer = Depends(get_container),
) -> AudioURLOut:
    """GAP-BE-008: mint a short-lived signed URL usable as <audio src> (no custom headers)."""
    call = _get_call(session, call_id)
    asset = session.query(AudioAsset).filter(AudioAsset.call_id == call.id).first()
    if asset is None:
        raise BlobNotFound("Audio asset not found")
    expires = int(time.time()) + container.settings.signed_url_ttl_seconds
    query = build_signed_audio_query(asset.id, expires, container.settings.hmac_secret)
    base = resolve_public_api_base_url(container.settings)
    return AudioURLOut(
        url=f"{base.rstrip('/')}/api/v1/public/audio/{asset.id}?{query}",
        expires_at=datetime.fromtimestamp(expires, tz=UTC),
    )


@router.get("/public/audio/{asset_id}")
def public_audio(
    asset_id: UUID,
    request: Request,
    expires: int = Query(...),
    signature: str = Query(...),
    session: Session = Depends(get_sync_session),
    container: AppContainer = Depends(get_container),
) -> StreamingResponse:
    verify_signed_audio(asset_id, expires, signature, container.settings.hmac_secret)
    asset = session.get(AudioAsset, asset_id)
    if asset is None:
        raise BlobNotFound("Audio asset not found")
    return _stream_asset(asset, request, container)


def signed_audio_url(container: AppContainer, asset_id: UUID) -> str:
    expires = int(time.time()) + container.settings.signed_url_ttl_seconds
    query = build_signed_audio_query(asset_id, expires, container.settings.hmac_secret)
    return f"{container.settings.public_api_base_url.rstrip('/')}/api/v1/public/audio/{asset_id}?{query}"


def _stream_asset(asset: AudioAsset, request: Request, container: AppContainer) -> StreamingResponse:
    head = container.blob.download_stream(asset.bucket, asset.object_key)
    size = asset.size_bytes or head.size_bytes
    start, end, status = _range_tuple(request.headers.get("range"), size)
    if status == 416:
        return StreamingResponse(iter([b""]), status_code=416, headers={"Content-Range": f"bytes */{size}"})
    obj = container.blob.download_stream(asset.bucket, asset.object_key, range_start=start, range_end=end)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": asset.content_type,
        "Cache-Control": "private, max-age=60",
    }
    if start is not None and end is not None:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        headers["Content-Length"] = str(end - start + 1)
    else:
        headers["Content-Length"] = str(size)

    def iterator():
        while True:
            chunk = obj.body.read(64 * 1024)
            if not chunk:
                break
            yield chunk

    return StreamingResponse(iterator(), status_code=status, headers=headers, media_type=asset.content_type)

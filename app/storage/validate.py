"""Safe filenames and audio upload validation."""

from __future__ import annotations

import hashlib
import re
from pathlib import PurePosixPath

from app.core.errors import AudioTooLarge, InvalidAudio
from app.core.settings import Settings

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(original: str) -> str:
    name = PurePosixPath(original.replace("\\", "/")).name
    if not name or name in {".", ".."}:
        return "audio.bin"
    cleaned = _UNSAFE.sub("_", name).strip("._")
    return cleaned or "audio.bin"


def validate_audio_meta(filename: str, content_type: str, size_bytes: int, settings: Settings) -> None:
    if size_bytes <= 0:
        raise InvalidAudio("Audio file is empty")
    if size_bytes > settings.max_audio_bytes:
        raise AudioTooLarge(
            "Audio exceeds maximum allowed size",
            details={"max_bytes": settings.max_audio_bytes, "size_bytes": size_bytes},
        )
    ext = PurePosixPath(filename).suffix.lower()
    if ext not in settings.allowed_ext_set:
        raise InvalidAudio("Audio file extension is not allowed", details={"extension": ext})
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype and ctype not in settings.allowed_mime_set:
        raise InvalidAudio("Audio MIME type is not allowed", details={"content_type": ctype})


class SizeLimitReader:
    """Wrap a stream, count bytes, abort if over the configured maximum."""

    def __init__(self, stream: object, max_bytes: int) -> None:
        self._stream = stream
        self._max = max_bytes
        self.bytes_read = 0
        self._digest = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        chunk = self._stream.read(size)  # type: ignore[attr-defined]
        if not chunk:
            return b""
        self.bytes_read += len(chunk)
        if self.bytes_read > self._max:
            raise AudioTooLarge(
                "Audio exceeds maximum allowed size",
                details={"max_bytes": self._max},
            )
        self._digest.update(chunk)
        return chunk  # type: ignore[no-any-return]

    def hexdigest(self) -> str:
        return self._digest.hexdigest()

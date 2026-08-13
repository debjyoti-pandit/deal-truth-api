"""Stable SeaweedFS object keys."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class BlobKeys:
    original: str
    transcription: str
    recap: str
    srt: str
    vtt: str
    report_json: str
    report_md: str


def blob_keys(call_id: UUID, safe_filename: str) -> BlobKeys:
    cid = str(call_id)
    return BlobKeys(
        original=f"calls/{cid}/original/{safe_filename}",
        transcription=f"calls/{cid}/pyai/transcription.json",
        recap=f"calls/{cid}/pyai/recap.json",
        srt=f"calls/{cid}/subtitles/call.srt",
        vtt=f"calls/{cid}/subtitles/call.vtt",
        report_json=f"calls/{cid}/exports/report.json",
        report_md=f"calls/{cid}/exports/report.md",
    )

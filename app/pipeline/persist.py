"""Pipeline helpers: persist transcript, insights, report artifacts."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.enums import AnalysisRunStatus, SpeakerRole
from app.core.errors import MLResponseInvalid
from app.core.settings import Settings
from app.intelligence.domain import SegmentView, ValidatedInsight
from app.models.analysis import AnalysisRun, CallMetrics, Insight, RecapRecord
from app.models.call import Call
from app.models.evidence import EvidenceLink
from app.models.transcript import Speaker, TranscriptChunk, TranscriptSegment
from app.models.types import EmbeddingVector
from app.providers.normalized import NormalizedRecap, NormalizedTranscript
from app.storage.base import BlobStore


def load_segment_views(session: Session, call: Call) -> list[SegmentView]:
    speakers = {s.id: s for s in session.scalars(select(Speaker).where(Speaker.call_id == call.id)).all()}
    rows = session.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.call_id == call.id)
        .order_by(TranscriptSegment.sequence_number.asc())
    ).all()
    views: list[SegmentView] = []
    for row in rows:
        speaker = speakers.get(row.speaker_id) if row.speaker_id else None
        views.append(
            SegmentView(
                id=row.id,
                provider_segment_id=row.provider_segment_id,
                speaker_id=row.speaker_id,
                speaker_role=speaker.role if speaker else SpeakerRole.UNKNOWN,
                start_ms=row.start_ms,
                end_ms=row.end_ms,
                text=row.text,
                sequence_number=row.sequence_number,
            )
        )
    return views


def persist_transcript(
    session: Session,
    call: Call,
    transcript: NormalizedTranscript,
    resolved: Sequence[tuple[object, SpeakerRole, float, str | None]],
) -> list[SegmentView]:
    existing = session.scalars(select(Speaker).where(Speaker.call_id == call.id)).all()
    by_provider = {s.provider_speaker_id: s for s in existing}
    for speaker, role, confidence, display in resolved:
        provider_id = speaker.provider_speaker_id  # type: ignore[attr-defined]
        row = by_provider.get(provider_id)
        if row is None:
            row = Speaker(
                call_id=call.id,
                provider_speaker_id=provider_id,
                role=role,
                display_name=display,
                confidence=confidence,
                channel=getattr(speaker, "channel", None),
            )
            session.add(row)
            session.flush()
            by_provider[provider_id] = row
        elif not row.manually_overridden:
            row.role = role
            row.confidence = confidence
            if display:
                row.display_name = display
    session.flush()

    session.execute(delete(TranscriptSegment).where(TranscriptSegment.call_id == call.id))
    views: list[SegmentView] = []
    for index, seg in enumerate(transcript.segments):
        speaker_row = by_provider.get(seg.provider_speaker_id)
        seg_row = TranscriptSegment(
            id=uuid4(),
            call_id=call.id,
            provider_segment_id=seg.provider_segment_id,
            speaker_id=speaker_row.id if speaker_row else None,
            start_ms=seg.start_ms,
            end_ms=seg.end_ms,
            text=seg.text,
            sequence_number=index,
            extra={"words": [w.model_dump() for w in seg.words], "channel": seg.channel},
        )
        session.add(seg_row)
        session.flush()
        views.append(
            SegmentView(
                id=seg_row.id,
                provider_segment_id=seg.provider_segment_id,
                speaker_id=speaker_row.id if speaker_row else None,
                speaker_role=speaker_row.role if speaker_row else SpeakerRole.UNKNOWN,
                start_ms=seg.start_ms,
                end_ms=seg.end_ms,
                text=seg.text,
                sequence_number=index,
            )
        )
    call.language = transcript.language or call.language
    call.duration_ms = transcript.duration_ms or call.duration_ms
    return views


def persist_recap(session: Session, call: Call, recap: NormalizedRecap) -> RecapRecord:
    row = session.scalar(select(RecapRecord).where(RecapRecord.call_id == call.id))
    if row is None:
        row = RecapRecord(call_id=call.id, provider_status=recap.status, raw_record={})
        session.add(row)
    row.provider_status = recap.status
    row.headline = recap.headline
    row.tldr = recap.tldr
    row.summary = recap.summary
    row.raw_record = recap.model_dump(mode="json")
    return row


def persist_metrics(session: Session, call: Call, metrics: dict[str, object]) -> CallMetrics:
    row = session.scalar(select(CallMetrics).where(CallMetrics.call_id == call.id))
    if row is None:
        row = CallMetrics(call_id=call.id)
        session.add(row)
    talk = metrics.get("talk_ratio")
    longest = metrics.get("longest_monologue")
    questions = metrics.get("question_rate")
    keywords = metrics.get("keyword_hits")
    row.talk_ratio = talk if isinstance(talk, dict) else {}
    row.longest_monologue = longest if isinstance(longest, dict) else {}
    row.question_rate = questions if isinstance(questions, dict) else {}
    row.keyword_hits = keywords if isinstance(keywords, dict) else {}
    return row


def next_run_version(session: Session, call_id: UUID) -> int:
    current = session.scalars(select(AnalysisRun.version).where(AnalysisRun.call_id == call_id)).all()
    return (max(current) + 1) if current else 1


def persist_insights(
    session: Session,
    call: Call,
    insights: list[ValidatedInsight],
    *,
    manifest: dict[str, object],
) -> AnalysisRun:
    run = AnalysisRun(
        call_id=call.id,
        version=next_run_version(session, call.id),
        status=AnalysisRunStatus.SUCCEEDED,
        model_manifest=manifest,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )
    session.add(run)
    session.flush()
    for item in insights:
        if item.dropped:
            continue
        row = Insight(
            analysis_run_id=run.id,
            type=item.type,
            title=item.title,
            summary=item.summary,
            severity=item.severity,
            confidence=item.confidence,
            evidence_status=item.evidence_status,
            payload=item.payload,
        )
        session.add(row)
        session.flush()
        for order, sid in enumerate(item.segment_ids):
            session.add(
                EvidenceLink(
                    insight_id=row.id,
                    transcript_segment_id=sid,
                    rel=item.relationship,
                    sort_order=order,
                )
            )
    return run


def persist_chunks(
    session: Session,
    call: Call,
    chunks: list[dict[str, object]],
    embeddings: list[list[float]],
) -> None:
    session.execute(delete(TranscriptChunk).where(TranscriptChunk.call_id == call.id))
    for chunk, vector in zip(chunks, embeddings, strict=False):
        if len(vector) != EmbeddingVector.dim:
            raise MLResponseInvalid(
                "ML embedding dimension does not match the database column",
                details={"expected": EmbeddingVector.dim, "got": len(vector)},
            )
        session.add(
            TranscriptChunk(
                call_id=call.id,
                start_segment_id=UUID(str(chunk["start_segment_id"])),
                end_segment_id=UUID(str(chunk["end_segment_id"])),
                text=str(chunk["text"]),
                embedding=vector,
            )
        )


def store_json(blob: BlobStore, settings: Settings, call_id: UUID, key: str, payload: dict[str, object]) -> None:
    blob.put_bytes(
        settings.s3_bucket_results,
        key,
        json.dumps(payload).encode("utf-8"),
        "application/json",
    )


def store_text(blob: BlobStore, settings: Settings, key: str, text: str, content_type: str) -> None:
    blob.put_bytes(settings.s3_bucket_results, key, text.encode("utf-8"), content_type)

"""Report, insights, metrics, ask, follow-up, exports."""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AppContainer, get_container, get_sync_session, require_auth
from app.core.errors import NotFoundError
from app.intelligence.ask import ask as ask_call
from app.intelligence.email import build_follow_up, polish_or_fallback
from app.models.analysis import AnalysisRun, CallMetrics, Insight
from app.models.call import Call
from app.models.evidence import EvidenceLink
from app.models.transcript import TranscriptChunk, TranscriptSegment
from app.schemas import AskRequest
from app.storage.keys import blob_keys

router = APIRouter(prefix="/api/v1", tags=["report"], dependencies=[Depends(require_auth)])


def _latest_run(session: Session, call_id: UUID) -> AnalysisRun | None:
    return session.scalars(
        select(AnalysisRun).where(AnalysisRun.call_id == call_id).order_by(AnalysisRun.version.desc())
    ).first()


@router.get("/calls/{call_id}/report")
def get_report(
    call_id: UUID,
    session: Session = Depends(get_sync_session),
    container: AppContainer = Depends(get_container),
) -> dict[str, object]:
    call = session.get(Call, call_id)
    if call is None:
        raise NotFoundError("Call not found")
    keys = blob_keys(call.id, "audio.bin")
    if container.blob.exists(container.settings.s3_bucket_results, keys.report_json):
        raw = container.blob.get_bytes(container.settings.s3_bucket_results, keys.report_json)
        return json.loads(raw.decode("utf-8"))
    return {
        "call_id": str(call.id),
        "public_call_id": call.public_call_id,
        "status": call.status.value,
        "headline": None,
        "insights": [],
    }


@router.get("/calls/{call_id}/insights")
def get_insights(call_id: UUID, session: Session = Depends(get_sync_session)) -> list[dict[str, object]]:
    if session.get(Call, call_id) is None:
        raise NotFoundError("Call not found")
    run = _latest_run(session, call_id)
    if run is None:
        return []
    insights = session.scalars(select(Insight).where(Insight.analysis_run_id == run.id)).all()
    out: list[dict[str, object]] = []
    for insight in insights:
        links = session.scalars(select(EvidenceLink).where(EvidenceLink.insight_id == insight.id)).all()
        quotes: list[str] = []
        spans: list[dict[str, int]] = []
        for link in sorted(links, key=lambda x: x.sort_order):
            seg = session.get(TranscriptSegment, link.transcript_segment_id)
            if seg:
                quotes.append(seg.text)
                spans.append({"start_ms": seg.start_ms, "end_ms": seg.end_ms})
        out.append(
            {
                "id": str(insight.id),
                "type": insight.type.value,
                "title": insight.title,
                "summary": insight.summary,
                "severity": insight.severity,
                "confidence": insight.confidence,
                "evidence_status": insight.evidence_status.value,
                "segment_ids": [str(link.transcript_segment_id) for link in links],
                "quotes": quotes,
                "audio_spans": spans,
                "payload": insight.payload,
            }
        )
    return out


@router.get("/calls/{call_id}/metrics")
def get_metrics(call_id: UUID, session: Session = Depends(get_sync_session)) -> dict[str, object]:
    if session.get(Call, call_id) is None:
        raise NotFoundError("Call not found")
    row = session.scalar(select(CallMetrics).where(CallMetrics.call_id == call_id))
    if row is None:
        return {}
    return {
        "talk_ratio": row.talk_ratio,
        "longest_monologue": row.longest_monologue,
        "question_rate": row.question_rate,
        "keyword_hits": row.keyword_hits,
    }


@router.post("/calls/{call_id}/ask")
def ask_endpoint(
    call_id: UUID,
    body: AskRequest,
    session: Session = Depends(get_sync_session),
    container: AppContainer = Depends(get_container),
) -> dict[str, object]:
    call = session.get(Call, call_id)
    if call is None:
        raise NotFoundError("Call not found")
    chunks = session.scalars(select(TranscriptChunk).where(TranscriptChunk.call_id == call_id)).all()
    packed = []
    for chunk in chunks:
        packed.append(
            (
                {
                    "text": chunk.text,
                    "start_segment_id": chunk.start_segment_id,
                    "end_segment_id": chunk.end_segment_id,
                    "segment_ids": [chunk.start_segment_id, chunk.end_segment_id],
                },
                chunk.embedding or [],
            )
        )
    return ask_call(body.question, packed, container.ml, top_k=body.top_k, generate=body.generate)


@router.post("/calls/{call_id}/follow-up")
def follow_up(
    call_id: UUID,
    session: Session = Depends(get_sync_session),
    container: AppContainer = Depends(get_container),
) -> dict[str, object]:
    from app.intelligence.domain import ValidatedInsight

    call = session.get(Call, call_id)
    if call is None:
        raise NotFoundError("Call not found")
    run = _latest_run(session, call_id)
    insights: list[ValidatedInsight] = []
    if run:
        rows = session.scalars(select(Insight).where(Insight.analysis_run_id == run.id)).all()
        for row in rows:
            links = session.scalars(select(EvidenceLink).where(EvidenceLink.insight_id == row.id)).all()
            quotes = []
            spans = []
            for link in links:
                seg = session.get(TranscriptSegment, link.transcript_segment_id)
                if seg:
                    quotes.append(seg.text)
                    spans.append((seg.start_ms, seg.end_ms))
            insights.append(
                ValidatedInsight(
                    type=row.type,
                    title=row.title,
                    summary=row.summary,
                    severity=row.severity,
                    confidence=row.confidence,
                    evidence_status=row.evidence_status,
                    segment_ids=[link.transcript_segment_id for link in links],
                    quotes=quotes,
                    audio_spans=spans,
                    payload=row.payload,
                )
            )
    email = build_follow_up(insights, customer_name=call.customer_name)
    if container.settings.ml_generation_enabled:
        try:
            generated = container.ml.generate(email["body"] if isinstance(email["body"], str) else "")
            email = polish_or_fallback(email, generated)
        except Exception:
            email["polish"] = "fallback"
    return email


@router.get("/calls/{call_id}/export/json")
def export_json(
    call_id: UUID,
    session: Session = Depends(get_sync_session),
    container: AppContainer = Depends(get_container),
) -> JSONResponse:
    payload = get_report(call_id, session, container)
    return JSONResponse(payload)


@router.get("/calls/{call_id}/export/markdown")
def export_markdown(
    call_id: UUID,
    session: Session = Depends(get_sync_session),
    container: AppContainer = Depends(get_container),
) -> PlainTextResponse:
    call = session.get(Call, call_id)
    if call is None:
        raise NotFoundError("Call not found")
    keys = blob_keys(call.id, "audio.bin")
    if container.blob.exists(container.settings.s3_bucket_results, keys.report_md):
        text = container.blob.get_bytes(container.settings.s3_bucket_results, keys.report_md).decode("utf-8")
        return PlainTextResponse(text, media_type="text/markdown")
    return PlainTextResponse("# Report not ready\n", media_type="text/markdown")

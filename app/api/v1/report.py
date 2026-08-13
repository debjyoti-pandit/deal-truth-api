"""Report, insights, metrics, ask, search, follow-up, exports."""

from __future__ import annotations

import json
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import AppContainer, get_container, get_sync_session, require_auth
from app.core.enums import CallStatus, SpeakerRole
from app.core.errors import (
    BlobDownloadFailed,
    MLAuthFailed,
    MLInferenceFailed,
    MLModelNotReady,
    MLServiceUnavailable,
    NamedError,
    NotFoundError,
    NotReadyError,
)
from app.intelligence.ask import ask as ask_call
from app.intelligence.ask import ask_lexical
from app.intelligence.email import build_follow_up, polish_or_fallback
from app.intelligence.search import search_calls
from app.models.analysis import AnalysisRun, CallMetrics, Insight
from app.models.call import Call
from app.models.evidence import EvidenceLink
from app.models.transcript import TranscriptChunk, TranscriptSegment
from app.schemas import AskRequest
from app.storage.keys import blob_keys

router = APIRouter(prefix="/api/v1", tags=["report"], dependencies=[Depends(require_auth)])

REPORT_READY_STATUSES = frozenset({CallStatus.SHIPPED, CallStatus.PARTIAL})


def require_report_ready(call: Call) -> None:
    """GAP-BE-001/002/003: a not-yet-built report is a named 409, never a 500."""
    if CallStatus(call.status) not in REPORT_READY_STATUSES:
        raise NotReadyError(
            "Report is not ready; the call has not reached SHIPPED or PARTIAL",
            details={"status": call.status.value},
        )


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
    require_report_ready(call)
    keys = blob_keys(call.id, "audio.bin")
    try:
        if container.blob.exists(container.settings.s3_bucket_results, keys.report_json):
            raw = container.blob.get_bytes(container.settings.s3_bucket_results, keys.report_json)
            return json.loads(raw.decode("utf-8"))
    except NamedError:
        raise
    except Exception as exc:
        raise BlobDownloadFailed("Report artifact could not be read") from exc
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
    # GAP-BE-012: an unindexed call is an empty retrieval result, not a 503.
    if not packed:
        return {
            "answer": "This call is not indexed yet, so no moments could be retrieved.",
            "mode": "no_index",
            "moments": [],
            "evidence_segment_ids": [],
        }
    try:
        return ask_call(
            body.question,
            packed,
            container.ml,
            top_k=body.top_k,
            generate=body.generate,
        )
    except (MLServiceUnavailable, MLModelNotReady, MLAuthFailed, MLInferenceFailed):
        # ML outage degrades to lexical retrieval; it is never presented as a deal judgment.
        return ask_lexical(body.question, packed, top_k=body.top_k)


@router.get("/recommendations")
def recommendations(session: Session = Depends(get_sync_session)) -> dict[str, object]:
    """GAP-BE-005: suggested explorations derived from latest-run insights on finished calls."""
    latest = (
        select(AnalysisRun.call_id, func.max(AnalysisRun.version).label("version"))
        .group_by(AnalysisRun.call_id)
        .subquery()
    )
    latest_run_ids = select(AnalysisRun.id).join(
        latest,
        (AnalysisRun.call_id == latest.c.call_id) & (AnalysisRun.version == latest.c.version),
    )
    rows = session.execute(
        select(Insight, AnalysisRun.call_id)
        .join(AnalysisRun, Insight.analysis_run_id == AnalysisRun.id)
        .join(Call, AnalysisRun.call_id == Call.id)
        .where(
            Insight.analysis_run_id.in_(latest_run_ids),
            Call.status.in_([CallStatus.SHIPPED, CallStatus.PARTIAL]),
        )
    ).all()

    def _bucket(predicate) -> tuple[int, list[str]]:
        call_ids: list[str] = []
        count = 0
        for insight, call_id in rows:
            if predicate(insight):
                count += 1
                if str(call_id) not in call_ids:
                    call_ids.append(str(call_id))
        return count, call_ids

    def _is_pricing_objection(insight: Insight) -> bool:
        if insight.type.value != "OBJECTION":
            return False
        kind = str((insight.payload or {}).get("kind") or "").lower()
        text = f"{insight.title} {insight.summary}".lower()
        return "pricing" in kind or "pricing" in text or "price" in text

    candidates = [
        (
            "pricing-objections",
            "objection",
            "Pricing objections",
            "Calls where the customer pushed back on price.",
            "pricing",
            _is_pricing_objection,
        ),
        (
            "objections",
            "objection",
            "Open objections",
            "Customer objections raised on recent calls.",
            "objection",
            lambda i: i.type.value == "OBJECTION",
        ),
        (
            "deal-risks",
            "deal_risk",
            "Deal risks",
            "Deal killers and unresolved risks flagged with evidence.",
            "risk",
            lambda i: i.type.value == "DEAL_RISK",
        ),
        (
            "competitor-mentions",
            "competitor",
            "Competitor mentions",
            "Calls where a competitor came up.",
            "competitor",
            lambda i: i.type.value == "COMPETITOR",
        ),
        (
            "commitments",
            "commitment",
            "Commitments made",
            "Promises captured in the commitment ledger.",
            "commitment",
            lambda i: i.type.value == "COMMITMENT",
        ),
    ]
    items: list[dict[str, object]] = []
    for item_id, kind, title, description, query, predicate in candidates:
        count, call_ids = _bucket(predicate)
        if count > 0:
            items.append(
                {
                    "id": item_id,
                    "kind": kind,
                    "title": title,
                    "description": description,
                    "count": count,
                    "query": query,
                    "call_ids": call_ids,
                }
            )
    return {"available": True, "items": items}


@router.get("/search")
def search(
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=10, ge=1, le=50),
    status: str | None = Query(
        default=None,
        description="Comma-separated call statuses, e.g. SHIPPED,PARTIAL",
    ),
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    call_id: UUID | None = Query(default=None),
    speaker_role: SpeakerRole | None = Query(default=None),
    types: str | None = Query(
        default=None,
        description="Comma-separated insight types, e.g. OBJECTION,COMPETITOR",
    ),
    session: Session = Depends(get_sync_session),
) -> dict[str, object]:
    """GAP-BE-004: cross-call lexical search (Postgres FTS + SQLite ILIKE)."""
    try:
        return search_calls(
            session,
            q=q,
            limit=limit,
            status=status,
            from_date=from_date,
            to_date=to_date,
            call_id=call_id,
            speaker_role=speaker_role,
            types=types,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
    require_report_ready(call)
    keys = blob_keys(call.id, "audio.bin")
    try:
        if container.blob.exists(container.settings.s3_bucket_results, keys.report_md):
            text = container.blob.get_bytes(container.settings.s3_bucket_results, keys.report_md).decode("utf-8")
            return PlainTextResponse(text, media_type="text/markdown")
    except NamedError:
        raise
    except Exception as exc:
        raise BlobDownloadFailed("Report artifact could not be read") from exc
    return PlainTextResponse("# Report not ready\n", media_type="text/markdown")

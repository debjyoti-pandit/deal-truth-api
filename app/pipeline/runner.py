"""Idempotent call processing pipeline."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.enums import (
    CallStatus,
    EventState,
    FailureKind,
    RecordingMode,
    SpeakerRole,
)
from app.core.errors import (
    CallCancelled,
    ConflictError,
    NamedError,
    PyAIJobTimeout,
    PyAIRecapFailed,
    PyAIRecapPendingTimeout,
    PyAIScopeMissing,
)
from app.core.job_ready import JobReadyWaiter, MemoryJobReadyWaiter
from app.core.public_url import is_public_https_url, resolve_public_api_base_url
from app.core.retry import should_retry
from app.core.security import build_signed_audio_query
from app.core.settings import Settings
from app.evidence import shippable, validate_candidates
from app.exports.report import build_report, render_markdown
from app.intelligence.ask import chunk_segments
from app.intelligence.domain import SegmentView
from app.intelligence.extract import (
    extract_buying_intent,
    extract_commitments,
    extract_competitors,
    extract_customer_truth,
    extract_deal_killers,
    extract_moments,
    extract_objections,
    extract_reality_checks,
    extract_sentiment,
)
from app.intelligence.metrics import compute_metrics
from app.intelligence.speakers import resolve_speakers
from app.ml import MLInferenceClient
from app.models.call import AudioAsset, Call
from app.models.terms import TrackedTerm
from app.pipeline.persist import (
    load_segment_views,
    persist_chunks,
    persist_insights,
    persist_metrics,
    persist_recap,
    persist_transcript,
    store_json,
    store_text,
)
from app.pipeline.state import log_event, transition
from app.providers.base import CallRecapProvider, TranscriptionProvider
from app.providers.normalized import NormalizedRecap
from app.storage.base import BlobStore
from app.storage.keys import blob_keys

logger = logging.getLogger(__name__)


@dataclass
class PipelineDeps:
    session: Session
    settings: Settings
    blob: BlobStore
    transcription: TranscriptionProvider
    recap: CallRecapProvider
    ml: MLInferenceClient
    job_ready: JobReadyWaiter = field(default_factory=MemoryJobReadyWaiter)


def run_pipeline(deps: PipelineDeps, call_id: UUID) -> CallStatus:
    session = deps.session
    call = session.get(Call, call_id)
    if call is None:
        raise LookupError(f"call {call_id} not found")
    if CallStatus(call.status) == CallStatus.CANCELLED:
        raise CallCancelled("Call is cancelled")

    warnings: list[str] = []
    try:
        existing = load_segment_views(session, call)
        if existing:
            recap = None
            recap_row = call.recap_record
            if recap_row is not None:
                recap = NormalizedRecap(
                    status=recap_row.provider_status,
                    headline=recap_row.headline,
                    tldr=recap_row.tldr,
                    summary=recap_row.summary,
                    raw=recap_row.raw_record or {},
                )
            if CallStatus(call.status) in {
                CallStatus.SHIPPED,
                CallStatus.PARTIAL,
                CallStatus.FAILED,
                CallStatus.CREATED,
            }:
                transition(session, call, CallStatus.ANALYZING)
                session.commit()
            views = _analyze(deps, call, existing, recap, warnings)
        else:
            _ensure_queued(deps, call)
            _transcript, views = _transcribe(deps, call)
            recap = _recap(deps, call, warnings)
            views = _analyze(deps, call, views, recap, warnings)
        outcome = CallStatus.PARTIAL if warnings else CallStatus.SHIPPED
        transition(session, call, CallStatus.BUILDING_REPORT)
        session.commit()
        transition(session, call, outcome)
        log_event(session, call, stage="complete", state=EventState.SUCCEEDED, message=outcome.value)
        session.commit()
        return outcome
    except CallCancelled:
        session.rollback()
        raise
    except NamedError as exc:
        session.rollback()
        call = session.get(Call, call_id)
        if call is None:
            raise
        kind = exc.failure_kind
        if kind == FailureKind.TRANSCRIPTION:
            transition(session, call, CallStatus.FAILED, failure_kind=kind)
        elif kind == FailureKind.RECAP or (
            kind == FailureKind.ML_INFERENCE and call.transcript_segments
        ):
            # Recap/ML failure must not delete a successful transcript.
            if call.transcript_segments:
                warnings.append(exc.code)
                transition(session, call, CallStatus.PARTIAL, failure_kind=kind)
                session.commit()
                return CallStatus.PARTIAL
            transition(session, call, CallStatus.FAILED, failure_kind=kind)
        else:
            transition(session, call, CallStatus.FAILED, failure_kind=kind)
        log_event(
            session,
            call,
            stage="pipeline",
            state=EventState.FAILED,
            error_code=exc.code,
            message=exc.message,
        )
        session.commit()
        if should_retry(exc):
            raise
        return CallStatus.FAILED
    except Exception as exc:
        session.rollback()
        call = session.get(Call, call_id)
        if call is not None:
            transition(session, call, CallStatus.FAILED, failure_kind=FailureKind.INFRASTRUCTURE)
            log_event(
                session,
                call,
                stage="pipeline",
                state=EventState.FAILED,
                error_code="INFRASTRUCTURE",
                message=type(exc).__name__,
            )
            session.commit()
        raise


def _await_transcript(deps: PipelineDeps, job_id: str, *, webhook_url: str | None):
    # Poll immediately. Waiting the full webhook deadline first left calls stuck in
    # TRANSCRIBING until PyAI happened to POST (or for 10 minutes).
    deadline = time.monotonic() + deps.settings.pyai_poll_deadline_seconds
    interval = max(0.5, deps.settings.pyai_poll_interval_seconds)
    while time.monotonic() < deadline:
        payload = deps.transcription.get_job(job_id)
        status = str(payload.get("status") or "").lower()
        if status in {
            "completed",
            "complete",
            "succeeded",
            "success",
            "done",
            "failed",
            "cancelled",
            "canceled",
            "error",
        }:
            return deps.transcription.fetch_normalized(job_id)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        wait_for = min(interval, remaining)
        if webhook_url:
            deps.job_ready.wait(job_id, wait_for)
        else:
            time.sleep(wait_for)
    raise PyAIJobTimeout("PyAI transcription job timed out", details={"job_id": job_id})


def _ensure_queued(deps: PipelineDeps, call: Call) -> None:
    status = CallStatus(call.status)
    if status == CallStatus.ANALYZING:
        # Reanalyze-without-transcript used to land here, then _transcribe crashed
        # with ANALYZING -> TRANSCRIBING.
        transition(deps.session, call, CallStatus.FAILED)
        status = CallStatus.FAILED
    if status in {CallStatus.CREATED, CallStatus.UPLOADING, CallStatus.FAILED}:
        transition(deps.session, call, CallStatus.QUEUED)
        deps.session.commit()


def _transcribe(deps: PipelineDeps, call: Call) -> tuple[object, list[SegmentView]]:
    session = deps.session
    status = CallStatus(call.status)
    if status not in {CallStatus.QUEUED, CallStatus.TRANSCRIBING}:
        raise ConflictError(f"Cannot transcribe from {status.value}")
    if status != CallStatus.TRANSCRIBING:
        transition(session, call, CallStatus.TRANSCRIBING)
        log_event(session, call, stage="transcribe", state=EventState.STARTED)
        session.commit()

    public_base = resolve_public_api_base_url(deps.settings)
    webhook = f"{public_base}/api/v1/webhooks/pyai/transcription" if is_public_https_url(public_base) else None

    if call.pyai_job_id:
        job_id = call.pyai_job_id
    else:
        asset = session.scalars(select(AudioAsset).where(AudioAsset.call_id == call.id)).first()
        audio_url = None
        if asset is not None:
            expires = int(time.time()) + deps.settings.signed_url_ttl_seconds
            query = build_signed_audio_query(asset.id, expires, deps.settings.hmac_secret)
            audio_url = f"{public_base}/api/v1/public/audio/{asset.id}?{query}"
        handle = deps.transcription.submit_job(
            call_id=call.id,
            public_call_id=call.public_call_id,
            audio_url=audio_url,
            audio_stream=None,
            call_direction=call.call_direction.value,
            customer_name=call.customer_name,
            recording_mode=call.recording_mode.value,
            webhook_url=webhook,
            idempotency_key=f"transcribe:{call.id}",
        )
        call.pyai_job_id = handle.job_id
        session.commit()
        job_id = handle.job_id

    transcript = _await_transcript(deps, job_id, webhook_url=webhook)
    keys = blob_keys(call.id, "audio.bin")
    store_json(deps.blob, deps.settings, call.id, keys.transcription, transcript.raw)
    if transcript.recording_mode:
        try:
            call.recording_mode = RecordingMode(transcript.recording_mode)
        except ValueError:
            pass

    resolved = resolve_speakers(
        transcript,
        recording_mode=call.recording_mode,
        seller_channel=call.stereo_seller_channel,
        call_direction=call.call_direction,
        customer_name=call.customer_name,
        rep_name=call.rep_name,
    )
    views = persist_transcript(session, call, transcript, resolved)
    log_event(session, call, stage="transcribe", state=EventState.SUCCEEDED)
    session.commit()
    return transcript, views


def _recap(deps: PipelineDeps, call: Call, warnings: list[str]) -> NormalizedRecap | None:
    if not deps.settings.pyai_recap_enabled:
        return None
    session = deps.session
    transition(session, call, CallStatus.WAITING_FOR_RECAP)
    log_event(session, call, stage="recap", state=EventState.STARTED)
    session.commit()
    try:
        recap = deps.recap.poll_until_ready(call.id, call.public_call_id)
        if recap.capability_warning:
            warnings.append(recap.capability_warning)
        persist_recap(session, call, recap)
        keys = blob_keys(call.id, "audio.bin")
        store_json(deps.blob, deps.settings, call.id, keys.recap, recap.raw)
        log_event(session, call, stage="recap", state=EventState.SUCCEEDED)
        session.commit()
        return recap
    except (PyAIScopeMissing, PyAIRecapFailed, PyAIRecapPendingTimeout) as exc:
        warnings.append(exc.code)
        log_event(
            session,
            call,
            stage="recap",
            state=EventState.FAILED,
            error_code=exc.code,
            message=exc.message,
        )
        session.commit()
        return None


def _ml_or_warn[T](
    deps: PipelineDeps,
    call: Call,
    warnings: list[str],
    stage: str,
    fn: Callable[[], list[T]],
) -> list[T]:
    try:
        return fn()
    except NamedError as exc:
        if exc.failure_kind != FailureKind.ML_INFERENCE:
            raise
        warnings.append(exc.code)
        log_event(
            deps.session,
            call,
            stage=stage,
            state=EventState.FAILED,
            error_code=exc.code,
            message=exc.message,
        )
        deps.session.commit()
        return []


def _analyze(
    deps: PipelineDeps,
    call: Call,
    views: list[SegmentView],
    recap: NormalizedRecap | None,
    warnings: list[str],
) -> list[SegmentView]:
    session = deps.session
    transition(session, call, CallStatus.ANALYZING)
    log_event(session, call, stage="analyze", state=EventState.STARTED)
    session.commit()

    texts = [v.text for v in views]
    classifications = (
        _ml_or_warn(deps, call, warnings, "classify", lambda: deps.ml.classify(texts)) if texts else []
    )
    customer_idx = [i for i, v in enumerate(views) if v.speaker_role == SpeakerRole.CUSTOMER]
    emotions = (
        _ml_or_warn(
            deps,
            call,
            warnings,
            "emotion",
            lambda: deps.ml.emotion([views[i].text for i in customer_idx]),
        )
        if customer_idx
        else []
    )
    emotion_by_index = dict(zip(customer_idx, emotions, strict=False))
    updated: list[SegmentView] = []
    for i, view in enumerate(views):
        labels = classifications[i].as_dict() if i < len(classifications) else {}
        emo = emotion_by_index.get(i)
        grouped = emo.grouped() if emo else {"positive": 0, "negative": 0, "neutral": 1, "valence": 0}
        updated.append(
            view.model_copy(
                update={
                    "labels": labels,
                    "emotions": {item.label: item.score for item in (emo.labels if emo else [])},
                    "valence": float(grouped["valence"]),
                }
            )
        )
    views = updated

    terms_rows = session.scalars(
        select(TrackedTerm).where((TrackedTerm.call_id == call.id) | (TrackedTerm.call_id.is_(None)))
    ).all()
    tracked = [(row.value, list(row.aliases or [])) for row in terms_rows]
    metrics = compute_metrics(views, duration_ms=call.duration_ms, tracked_terms=tracked)
    persist_metrics(session, call, metrics)

    intent = extract_buying_intent(views)
    candidates = [
        *extract_customer_truth(views),
        *extract_sentiment(views),
        *intent,
        *extract_objections(views),
        *extract_commitments(views, recap),
        *extract_reality_checks(views),
        *extract_deal_killers(views, intent),
        *extract_competitors(views, tracked),
        *extract_moments(views),
    ]
    transition(session, call, CallStatus.VALIDATING)
    session.commit()
    validated, events = validate_candidates(candidates, views, confidence_threshold=deps.settings.confidence_threshold)
    for event in events:
        log_event(
            session,
            call,
            stage="validate",
            state=EventState.FAILED if event.get("error_code") else EventState.SUCCEEDED,
            error_code=str(event.get("error_code")) if event.get("error_code") else None,
            message=str(event.get("message")),
            details=event,
        )
    shipped = shippable(validated)
    persist_insights(
        session,
        call,
        shipped,
        manifest={
            "pyai_recap": bool(recap),
            "warnings": warnings,
            "ml": "deal-truth-ml",
        },
    )

    transition(session, call, CallStatus.INDEXING)
    session.commit()
    chunks = chunk_segments(views)
    embeddings = (
        _ml_or_warn(
            deps,
            call,
            warnings,
            "embed",
            lambda: deps.ml.embed([str(c["text"]) for c in chunks]),
        )
        if chunks
        else []
    )
    persist_chunks(session, call, chunks, embeddings)

    report = build_report(call, recap, metrics, shipped, warnings)
    keys = blob_keys(call.id, "audio.bin")
    store_json(deps.blob, deps.settings, call.id, keys.report_json, report)
    store_text(deps.blob, deps.settings, keys.report_md, render_markdown(report), "text/markdown")
    log_event(session, call, stage="analyze", state=EventState.SUCCEEDED)
    session.commit()
    return views


def load_call(session: Session, call_id: UUID) -> Call | None:
    return session.scalar(
        select(Call)
        .options(
            selectinload(Call.speakers),
            selectinload(Call.transcript_segments),
            selectinload(Call.audio_assets),
            selectinload(Call.analysis_runs),
            selectinload(Call.metrics),
            selectinload(Call.recap_record),
        )
        .where(Call.id == call_id)
    )

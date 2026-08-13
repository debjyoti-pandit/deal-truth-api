"""Call CRUD, processing, transcript, speakers, SSE."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import AppContainer, get_container, get_sync_session, require_auth
from app.core.enums import (
    TERMINAL_CALL_STATUSES,
    CallStatus,
    EventState,
    TrackedTermType,
)
from app.core.errors import ConflictError, NotFoundError
from app.models.call import Call
from app.models.events import ProcessingEvent
from app.models.terms import TrackedTerm
from app.models.transcript import Speaker
from app.pipeline.state import log_event, transition
from app.schemas import (
    CallCreate,
    CallDetail,
    CallSummary,
    EventOut,
    SegmentOut,
    SpeakerOut,
    SpeakerPatch,
    TranscriptOut,
)

router = APIRouter(prefix="/api/v1", tags=["calls"], dependencies=[Depends(require_auth)])


def _get_call(session: Session, call_id: UUID) -> Call:
    call = session.get(Call, call_id)
    if call is None:
        raise NotFoundError("Call not found")
    return call


def _summary(call: Call) -> CallSummary:
    return CallSummary(
        id=call.id,
        public_call_id=call.public_call_id,
        title=call.title,
        customer_name=call.customer_name,
        status=call.status,
        terminal_outcome=call.terminal_outcome,
        duration_ms=call.duration_ms,
        created_at=call.created_at,
        updated_at=call.updated_at,
    )


def _detail(call: Call) -> CallDetail:
    return CallDetail(
        **_summary(call).model_dump(),
        rep_name=call.rep_name,
        call_direction=call.call_direction,
        source_type=call.source_type,
        recording_mode=call.recording_mode,
        failure_kind=call.failure_kind.value if call.failure_kind else None,
        language=call.language,
        completed_at=call.completed_at,
    )


@router.post("/calls", status_code=201)
def create_call(
    body: CallCreate,
    session: Session = Depends(get_sync_session),
    container: AppContainer = Depends(get_container),
) -> CallDetail:
    public_id = uuid4().hex[:12]
    channel = (
        body.stereo_seller_channel
        if body.stereo_seller_channel is not None
        else container.settings.stereo_default_channel_seller
    )
    call = Call(
        public_call_id=public_id,
        title=body.title,
        customer_name=body.customer_name,
        rep_name=body.rep_name,
        call_direction=body.call_direction,
        recording_mode=body.recording_mode,
        status=CallStatus.CREATED,
        stereo_seller_channel=channel,
        extra={},
    )
    session.add(call)
    session.flush()
    for name in body.tracked_competitors:
        session.add(TrackedTerm(call_id=call.id, type=TrackedTermType.COMPETITOR, value=name, aliases=[]))
    for name in body.tracked_keywords:
        session.add(TrackedTerm(call_id=call.id, type=TrackedTermType.KEYWORD, value=name, aliases=[]))
    log_event(session, call, stage="created", state=EventState.SUCCEEDED)
    return _detail(call)


@router.get("/calls")
def list_calls(session: Session = Depends(get_sync_session)) -> list[CallSummary]:
    rows = session.scalars(select(Call).order_by(Call.created_at.desc())).all()
    return [_summary(c) for c in rows]


@router.get("/calls/{call_id}")
def get_call(call_id: UUID, session: Session = Depends(get_sync_session)) -> CallDetail:
    return _detail(_get_call(session, call_id))


@router.delete("/calls/{call_id}", status_code=204)
def delete_call(call_id: UUID, session: Session = Depends(get_sync_session)) -> None:
    call = _get_call(session, call_id)
    session.delete(call)


@router.post("/calls/{call_id}/process")
def process_call(
    call_id: UUID,
    session: Session = Depends(get_sync_session),
    container: AppContainer = Depends(get_container),
) -> CallDetail:
    call = _get_call(session, call_id)
    if CallStatus(call.status) == CallStatus.CANCELLED:
        raise ConflictError("Call is cancelled")
    if CallStatus(call.status) == CallStatus.CREATED:
        transition(session, call, CallStatus.QUEUED)
    session.commit()
    container.enqueue_process(call.id)
    return _detail(call)


@router.post("/calls/{call_id}/reanalyze")
def reanalyze_call(
    call_id: UUID,
    session: Session = Depends(get_sync_session),
    container: AppContainer = Depends(get_container),
) -> CallDetail:
    call = _get_call(session, call_id)
    if CallStatus(call.status) not in {CallStatus.SHIPPED, CallStatus.PARTIAL, CallStatus.FAILED, CallStatus.ANALYZING}:
        if CallStatus(call.status) not in TERMINAL_CALL_STATUSES | {CallStatus.CREATED, CallStatus.QUEUED}:
            pass
    if CallStatus(call.status) in {CallStatus.SHIPPED, CallStatus.PARTIAL, CallStatus.FAILED}:
        transition(session, call, CallStatus.ANALYZING)
    session.commit()
    container.enqueue_process(call.id)
    return _detail(call)


@router.post("/calls/{call_id}/cancel")
def cancel_call(call_id: UUID, session: Session = Depends(get_sync_session)) -> CallDetail:
    call = _get_call(session, call_id)
    if CallStatus(call.status) in TERMINAL_CALL_STATUSES and CallStatus(call.status) != CallStatus.FAILED:
        if CallStatus(call.status) == CallStatus.CANCELLED:
            return _detail(call)
        raise ConflictError("Call already finished")
    transition(session, call, CallStatus.CANCELLED)
    log_event(session, call, stage="cancel", state=EventState.SUCCEEDED)
    return _detail(call)


@router.get("/calls/{call_id}/events")
def list_events(call_id: UUID, session: Session = Depends(get_sync_session)) -> list[EventOut]:
    _get_call(session, call_id)
    rows = session.scalars(
        select(ProcessingEvent).where(ProcessingEvent.call_id == call_id).order_by(ProcessingEvent.created_at.asc())
    ).all()
    return [
        EventOut(
            id=r.id,
            stage=r.stage,
            state=r.state.value,
            attempt=r.attempt,
            error_code=r.error_code,
            message=r.message,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/calls/{call_id}/stream")
async def stream_events(
    call_id: UUID,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    container: AppContainer = Depends(get_container),
) -> StreamingResponse:
    factory = __import__("app.db", fromlist=["sync_session_factory"]).sync_session_factory()

    async def gen() -> AsyncIterator[str]:
        after: datetime | None = None
        if last_event_id:
            try:
                after = datetime.fromisoformat(last_event_id.replace("Z", "+00:00"))
            except ValueError:
                after = None
        terminal = False
        idle = 0
        while not terminal and idle < 120:
            with factory() as session:
                call = session.get(Call, call_id)
                if call is None:
                    yield 'event: error\ndata: {"error":"not_found"}\n\n'
                    return
                stmt = select(ProcessingEvent).where(ProcessingEvent.call_id == call_id)
                if after is not None:
                    stmt = stmt.where(ProcessingEvent.created_at > after)
                rows = session.scalars(stmt.order_by(ProcessingEvent.created_at.asc())).all()
                for row in rows:
                    after = row.created_at
                    payload = {
                        "id": str(row.id),
                        "stage": row.stage,
                        "state": row.state.value,
                        "error_code": row.error_code,
                        "message": row.message,
                    }
                    eid = row.created_at.isoformat()
                    yield f"id: {eid}\nevent: processing\ndata: {json.dumps(payload)}\n\n"
                if CallStatus(call.status) in TERMINAL_CALL_STATUSES:
                    yield f"id: terminal\nevent: terminal\ndata: {json.dumps({'status': call.status.value})}\n\n"
                    terminal = True
                    break
            idle += 1
            await asyncio.sleep(0.25)

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/calls/{call_id}/transcript")
def get_transcript(call_id: UUID, session: Session = Depends(get_sync_session)) -> TranscriptOut:
    call = session.scalar(
        select(Call)
        .options(selectinload(Call.speakers), selectinload(Call.transcript_segments))
        .where(Call.id == call_id)
    )
    if call is None:
        raise NotFoundError("Call not found")
    speakers = [
        SpeakerOut(
            id=s.id,
            provider_speaker_id=s.provider_speaker_id,
            role=s.role,
            display_name=s.display_name,
            confidence=s.confidence,
            manually_overridden=s.manually_overridden,
        )
        for s in call.speakers
    ]
    role_by_id = {s.id: s.role for s in call.speakers}
    segments = [
        SegmentOut(
            id=seg.id,
            speaker_id=seg.speaker_id,
            speaker_role=role_by_id.get(seg.speaker_id) if seg.speaker_id else None,
            start_ms=seg.start_ms,
            end_ms=seg.end_ms,
            text=seg.text,
            sequence_number=seg.sequence_number,
        )
        for seg in sorted(call.transcript_segments, key=lambda s: s.sequence_number)
    ]
    return TranscriptOut(
        call_id=call.id,
        language=call.language,
        duration_ms=call.duration_ms,
        speakers=speakers,
        segments=segments,
    )


@router.patch("/calls/{call_id}/speakers")
def patch_speakers(
    call_id: UUID,
    body: SpeakerPatch,
    session: Session = Depends(get_sync_session),
    container: AppContainer = Depends(get_container),
) -> TranscriptOut:
    call = _get_call(session, call_id)
    speaker = session.get(Speaker, body.speaker_id)
    if speaker is None or speaker.call_id != call.id:
        raise NotFoundError("Speaker not found")
    if body.swap_with is not None:
        other = session.get(Speaker, body.swap_with)
        if other is None or other.call_id != call.id:
            raise NotFoundError("Speaker not found")
        speaker.role, other.role = other.role, speaker.role
        speaker.display_name, other.display_name = other.display_name, speaker.display_name
        speaker.manually_overridden = True
        other.manually_overridden = True
    else:
        if body.role is not None:
            speaker.role = body.role
        if body.display_name is not None:
            speaker.display_name = body.display_name
        speaker.manually_overridden = True
    from app.models.analysis import AnalysisRun, Insight

    runs = session.scalars(select(AnalysisRun).where(AnalysisRun.call_id == call.id)).all()
    for run in runs:
        insights = session.scalars(select(Insight).where(Insight.analysis_run_id == run.id)).all()
        for insight in insights:
            if insight.type.value in {"CUSTOMER_FACT", "SENTIMENT_POINT"}:
                session.delete(insight)
    if CallStatus(call.status) in {CallStatus.SHIPPED, CallStatus.PARTIAL, CallStatus.FAILED}:
        transition(session, call, CallStatus.ANALYZING)
    session.commit()
    container.enqueue_process(call.id)
    return get_transcript(call_id, session)

from app.core.enums import CallStatus, EvidenceStatus, InsightType
from app.core.settings import Settings
from app.models.analysis import AnalysisRun, Insight
from app.models.call import Call
from app.storage.memory import MemoryBlobStore
from fixtures.catalog import SCENARIOS
from sqlalchemy.orm import Session
from tests.conftest import run_scenario


def test_happy_path_ships(session: Session, settings: Settings, blob: MemoryBlobStore) -> None:
    call_id = run_scenario(session, settings, blob, "happy_path")
    call = session.get(Call, call_id)
    assert call is not None
    assert call.status == CallStatus.SHIPPED
    assert call.terminal_outcome is not None
    assert call.terminal_outcome.value == "SHIPPED"


def test_partial_when_recap_fails(session: Session, settings: Settings, blob: MemoryBlobStore) -> None:
    call_id = run_scenario(session, settings, blob, "happy_path", recap_fail=True)
    call = session.get(Call, call_id)
    assert call is not None
    assert call.status == CallStatus.PARTIAL
    from app.models.transcript import TranscriptSegment
    from sqlalchemy import select

    segs = session.scalars(select(TranscriptSegment).where(TranscriptSegment.call_id == call_id)).all()
    assert segs, "recap failure must not delete the transcript"


def test_partial_when_ml_is_down(session: Session, settings: Settings, blob: MemoryBlobStore) -> None:
    call_id = run_scenario(session, settings, blob, "happy_path", ml_fail=True)
    call = session.get(Call, call_id)
    assert call is not None
    assert call.status == CallStatus.PARTIAL
    from app.models.transcript import TranscriptSegment
    from sqlalchemy import select

    segs = session.scalars(select(TranscriptSegment).where(TranscriptSegment.call_id == call_id)).all()
    assert segs, "ML failure must not delete the transcript"


def test_failed_when_transcription_fails(session: Session, settings: Settings, blob: MemoryBlobStore) -> None:
    call_id = run_scenario(session, settings, blob, "happy_path", transcribe_fail=True)
    call = session.get(Call, call_id)
    assert call is not None
    assert call.status == CallStatus.FAILED
    assert call.failure_kind is not None
    assert call.failure_kind.value == "TRANSCRIPTION"


def test_all_fixture_scenarios_reach_shipped(session: Session, settings: Settings, blob: MemoryBlobStore) -> None:
    for name in SCENARIOS:
        call_id = run_scenario(session, settings, blob, name)
        call = session.get(Call, call_id)
        assert call is not None, name
        assert call.status == CallStatus.SHIPPED, name


def test_customer_truth_only_customer_speakers(session: Session, settings: Settings, blob: MemoryBlobStore) -> None:
    call_id = run_scenario(session, settings, blob, "happy_path")
    from app.models.evidence import EvidenceLink
    from app.models.transcript import Speaker, TranscriptSegment
    from sqlalchemy import select

    run = session.scalars(
        select(AnalysisRun).where(AnalysisRun.call_id == call_id).order_by(AnalysisRun.version.desc())
    ).first()
    assert run is not None
    facts = session.scalars(
        select(Insight).where(Insight.analysis_run_id == run.id, Insight.type == InsightType.CUSTOMER_FACT)
    ).all()
    assert facts
    speakers = {s.id: s for s in session.scalars(select(Speaker).where(Speaker.call_id == call_id)).all()}
    for fact in facts:
        links = session.scalars(select(EvidenceLink).where(EvidenceLink.insight_id == fact.id)).all()
        for link in links:
            seg = session.get(TranscriptSegment, link.transcript_segment_id)
            assert seg is not None
            role = speakers[seg.speaker_id].role if seg.speaker_id else None
            assert role is not None
            assert role.value == "customer"


def test_absence_based_risks_for_no_timeline(session: Session, settings: Settings, blob: MemoryBlobStore) -> None:
    call_id = run_scenario(session, settings, blob, "no_purchase_timeline")
    from sqlalchemy import select

    run = session.scalars(
        select(AnalysisRun).where(AnalysisRun.call_id == call_id).order_by(AnalysisRun.version.desc())
    ).first()
    assert run is not None
    risks = session.scalars(
        select(Insight).where(Insight.analysis_run_id == run.id, Insight.type == InsightType.DEAL_RISK)
    ).all()
    assert any(r.evidence_status == EvidenceStatus.ABSENCE_BASED and "timeline" in r.title.lower() for r in risks)


def _queued_call_with_audio(session: Session, settings: Settings, blob: MemoryBlobStore, *, status: CallStatus, pyai_job_id: str | None = None):
    from uuid import uuid4

    from app.core.enums import CallDirection, RecordingMode, SourceType
    from app.models.call import AudioAsset, Call
    from app.pipeline.runner import PipelineDeps
    from tests.conftest import _scenario_providers

    transcription, recap, ml, _data = _scenario_providers("happy_path")
    call = Call(
        public_call_id=uuid4().hex[:12],
        title="pipeline-resume",
        customer_name="Sarah",
        rep_name="Rahul",
        call_direction=CallDirection.OUTBOUND,
        source_type=SourceType.UPLOAD,
        recording_mode=RecordingMode.MONO,
        status=status,
        pyai_job_id=pyai_job_id,
        extra={},
    )
    session.add(call)
    session.flush()
    blob.put_bytes(settings.s3_bucket_audio, f"calls/{call.id}/original/call.wav", b"RIFF....WAVEfmt", "audio/wav")
    session.add(
        AudioAsset(
            call_id=call.id,
            bucket=settings.s3_bucket_audio,
            object_key=f"calls/{call.id}/original/call.wav",
            original_filename="call.wav",
            content_type="audio/wav",
            size_bytes=16,
            checksum="abc",
        )
    )
    session.commit()
    deps = PipelineDeps(session=session, settings=settings, blob=blob, transcription=transcription, recap=recap, ml=ml)
    return call, transcription, deps


def test_resume_transcribing_does_not_resubmit_job(session: Session, settings: Settings, blob: MemoryBlobStore) -> None:
    from app.pipeline.runner import run_pipeline

    call, transcription, deps = _queued_call_with_audio(
        session, settings, blob, status=CallStatus.TRANSCRIBING, pyai_job_id="job_already_submitted"
    )
    run_pipeline(deps, call.id)
    assert transcription.submitted == []
    refreshed = session.get(Call, call.id)
    assert refreshed is not None
    assert refreshed.status == CallStatus.SHIPPED


def test_analyzing_without_transcript_retries_transcribe(
    session: Session, settings: Settings, blob: MemoryBlobStore
) -> None:
    from app.pipeline.runner import run_pipeline

    call, transcription, deps = _queued_call_with_audio(session, settings, blob, status=CallStatus.ANALYZING)
    outcome = run_pipeline(deps, call.id)
    assert outcome == CallStatus.SHIPPED
    assert transcription.submitted
    refreshed = session.get(Call, call.id)
    assert refreshed is not None
    assert refreshed.status == CallStatus.SHIPPED

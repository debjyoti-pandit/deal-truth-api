"""Shared pytest fixtures: isolated sqlite DB, fake providers, TestClient."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from app.core.job_ready import MemoryJobReadyWaiter
from app.core.settings import Settings, reset_settings_cache
from app.db import configure_engines, create_all_sync, sync_session_factory
from app.main import create_app
from app.models.base import Base
from app.pipeline.deps import reset_memory_blob
from app.pipeline.runner import PipelineDeps, run_pipeline
from app.providers.fakes import FakeMLClient, FakeRecapProvider, FakeTranscriptionProvider
from app.storage.memory import MemoryBlobStore
from fastapi.testclient import TestClient
from fixtures.catalog import SCENARIOS
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def secret() -> str:
    return "unit-test-signed-url-secret"


@pytest.fixture
def settings(tmp_path: Path, secret: str) -> Iterator[Settings]:
    db = tmp_path / "deal-truth-api.db"
    env = {
        "APP_ENV": "test",
        "DATABASE_URL": f"sqlite+aiosqlite:///{db}",
        "DATABASE_SYNC_URL": f"sqlite:///{db}",
        "SIGNED_URL_SECRET": secret,
        "PYAI_WEBHOOK_SECRET": "unit-test-webhook-secret",
        "AUTH_MODE": "none",
        "API_KEYS": "",
        "PYAI_RECAP_ENABLED": "true",
        "ML_GENERATION_ENABLED": "true",
        "PUBLIC_API_BASE_URL": "http://testserver",
        "NGROK_ENABLED": "false",
        "NGROK_DOMAIN": "",
        "S3_ACCESS_KEY": "",
        "S3_SECRET_KEY": "",
        "PYAI_API_KEY": "",
        "ML_SERVICE_API_KEY": "",
    }
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    reset_settings_cache()
    reset_memory_blob()
    s = Settings()
    configure_engines(s)
    Base.metadata.drop_all(bind=__import__("app.db", fromlist=["get_sync_engine"]).get_sync_engine())
    create_all_sync()
    yield s
    reset_settings_cache()
    for key, value in old.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture
def session(settings: Settings) -> Iterator[Session]:
    factory = sync_session_factory()
    with factory() as sess:
        yield sess


@pytest.fixture
def blob() -> MemoryBlobStore:
    return MemoryBlobStore()


def _scenario_providers(
    name: str, *, recap_fail: bool = False, transcribe_fail: bool = False, ml_fail: bool = False
):
    data = SCENARIOS[name]
    transcription = FakeTranscriptionProvider(data["transcript"], fail=transcribe_fail)
    recap = FakeRecapProvider(data["recap"], fail=recap_fail)
    ml = FakeMLClient(classifications=data["classifications"], emotions=data.get("emotions") or {})
    if ml_fail:
        from app.core.errors import MLServiceUnavailable

        class DownML(FakeMLClient):
            def classify(self, texts: list[str], labels: list[str] | None = None) -> list:
                raise MLServiceUnavailable("ml down")

        ml = DownML()
    return transcription, recap, ml, data


def run_scenario(
    session: Session,
    settings: Settings,
    blob: MemoryBlobStore,
    name: str,
    *,
    recap_fail: bool = False,
    transcribe_fail: bool = False,
    ml_fail: bool = False,
    customer_name: str = "Sarah",
    rep_name: str = "Rahul",
) -> UUID:
    from app.core.enums import CallDirection, CallStatus, RecordingMode, SourceType, TrackedTermType
    from app.models.call import AudioAsset, Call
    from app.models.terms import TrackedTerm

    transcription, recap, ml, data = _scenario_providers(
        name, recap_fail=recap_fail, transcribe_fail=transcribe_fail, ml_fail=ml_fail
    )
    call = Call(
        public_call_id=uuid4().hex[:12],
        title=name,
        customer_name=customer_name,
        rep_name=rep_name,
        call_direction=CallDirection.OUTBOUND,
        source_type=SourceType.UPLOAD,
        recording_mode=RecordingMode.MONO,
        status=CallStatus.QUEUED,
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
    for term, aliases in data.get("tracked") or []:
        session.add(TrackedTerm(call_id=call.id, type=TrackedTermType.COMPETITOR, value=term, aliases=aliases))
    session.commit()
    deps = PipelineDeps(
        session=session,
        settings=settings,
        blob=blob,
        transcription=transcription,
        recap=recap,
        ml=ml,
    )
    run_pipeline(deps, call.id)
    session.commit()
    return call.id


@pytest.fixture
def client(settings: Settings, blob: MemoryBlobStore, session: Session) -> Iterator[TestClient]:
    app = create_app()

    def enqueue(call_id: UUID) -> None:
        from app.models.call import Call
        from fixtures.catalog import SCENARIOS

        factory = sync_session_factory()
        with factory() as sess:
            call = sess.get(Call, call_id)
            name = call.title if call and call.title in SCENARIOS else "happy_path"
            transcription, recap, ml, _ = _scenario_providers(name)
            deps = PipelineDeps(
                session=sess,
                settings=settings,
                blob=blob,
                transcription=transcription,
                recap=recap,
                ml=ml,
            )
            run_pipeline(deps, call_id)
            sess.commit()

    from app.api.deps import AppContainer

    with TestClient(app) as test_client:
        test_client.app.state.container = AppContainer(  # type: ignore[attr-defined]
            settings=settings,
            blob=blob,
            transcription=FakeTranscriptionProvider(SCENARIOS["happy_path"]["transcript"]),
            recap=FakeRecapProvider(SCENARIOS["happy_path"]["recap"]),
            ml=FakeMLClient(
                classifications=SCENARIOS["happy_path"]["classifications"],
                emotions=SCENARIOS["happy_path"].get("emotions") or {},
            ),
            enqueue_process=enqueue,
            job_ready=MemoryJobReadyWaiter(),
        )
        yield test_client

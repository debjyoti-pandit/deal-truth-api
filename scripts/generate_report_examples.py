"""Generate SHIPPED report/insights/metrics/events examples for the frontend (GAP-BE-009).

Runs the fixture pipeline in-process (SQLite + memory blob + fake providers), then writes
docs/examples/*.json. No network, no PyAI, no ML service, no customer data.

Usage: uv run python scripts/generate_report_examples.py
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "examples"


def _configure_env(tmp: Path) -> None:
    db = tmp / "examples.db"
    os.environ.update(
        {
            "APP_ENV": "test",
            "DATABASE_URL": f"sqlite+aiosqlite:///{db}",
            "DATABASE_SYNC_URL": f"sqlite:///{db}",
            "SIGNED_URL_SECRET": "examples-signed-url-secret",
            "PYAI_WEBHOOK_SECRET": "examples-webhook-secret",
            "AUTH_MODE": "none",
            "NGROK_ENABLED": "false",
            "PUBLIC_API_BASE_URL": "http://localhost:8000",
        }
    )


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="deal-truth-examples-"))
    _configure_env(tmp)

    from app.core.enums import CallDirection, CallStatus, RecordingMode, SourceType, TrackedTermType
    from app.core.settings import Settings, reset_settings_cache
    from app.db import configure_engines, create_all_sync, sync_session_factory
    from app.models.call import AudioAsset, Call
    from app.models.terms import TrackedTerm
    from app.pipeline.runner import PipelineDeps, run_pipeline
    from app.providers.fakes import FakeMLClient, FakeRecapProvider, FakeTranscriptionProvider
    from app.storage.memory import MemoryBlobStore
    from fixtures.catalog import SCENARIOS

    reset_settings_cache()
    settings = Settings()
    configure_engines(settings)
    create_all_sync()

    data = SCENARIOS["happy_path"]
    blob = MemoryBlobStore()
    factory = sync_session_factory()
    with factory() as session:
        call = Call(
            public_call_id=uuid4().hex[:12],
            title="Acme discovery call (synthetic fixture)",
            customer_name="Sarah",
            rep_name="Rahul",
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
                checksum="synthetic",
            )
        )
        for term, aliases in data.get("tracked") or []:
            session.add(TrackedTerm(call_id=call.id, type=TrackedTermType.COMPETITOR, value=term, aliases=aliases))
        session.commit()

        deps = PipelineDeps(
            session=session,
            settings=settings,
            blob=blob,
            transcription=FakeTranscriptionProvider(data["transcript"]),
            recap=FakeRecapProvider(data["recap"]),
            ml=FakeMLClient(classifications=data["classifications"], emotions=data.get("emotions") or {}),
        )
        outcome = run_pipeline(deps, call.id)
        session.commit()
        if outcome.value != "SHIPPED":
            raise SystemExit(f"expected SHIPPED, got {outcome.value}")

        from types import SimpleNamespace

        from app.api.v1.calls import get_transcript, list_events
        from app.api.v1.report import get_insights, get_metrics, get_report

        container = SimpleNamespace(settings=settings, blob=blob)
        OUT.mkdir(parents=True, exist_ok=True)
        report = get_report(call.id, session, container)  # type: ignore[arg-type]
        insights = get_insights(call.id, session)
        metrics = get_metrics(call.id, session)
        events = [e.model_dump(mode="json") for e in list_events(call.id, session)]
        transcript = get_transcript(call.id, session).model_dump(mode="json")

        for name, payload in (
            ("report.shipped.json", report),
            ("insights.shipped.json", insights),
            ("metrics.shipped.json", metrics),
            ("events.shipped.json", events),
            ("transcript.shipped.json", transcript),
        ):
            (OUT / name).write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
            print(f"wrote docs/examples/{name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

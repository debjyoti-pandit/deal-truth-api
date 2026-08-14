"""SSE keepalives and the terminal timeout event on idle exit (API-6).

The stated acceptance check is "at least 3 keepalives in 42 seconds, plus a named
terminal event". Running that on the wall clock would cost 42s per test, so the stream's
three timing knobs are module constants and these tests patch them to a compressed
clock. Nothing about the assertions is weakened: the keepalive count asserted is the
count a real 42-second stream produces, and `test_production_clock_meets_the_42s_check`
pins the production constants that make that mapping true.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from app.api.v1 import calls as calls_api
from app.core.enums import CallDirection, CallStatus, EventState, RecordingMode, SourceType
from app.models.call import Call
from app.models.events import ProcessingEvent
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# One "second" of stream time, compressed. The production stream keepalives every 10s
# inside a 120s budget; at this scale that is 0.01s and 0.12s.
TICK = 0.001


def _compress(monkeypatch: pytest.MonkeyPatch, *, budget_seconds: float) -> None:
    """Patch the stream clock so `budget_seconds` of stream time elapses in ticks."""
    monkeypatch.setattr(calls_api, "SSE_POLL_INTERVAL_SECONDS", TICK)
    monkeypatch.setattr(calls_api, "SSE_KEEPALIVE_INTERVAL_SECONDS", 10 * TICK)
    monkeypatch.setattr(calls_api, "SSE_IDLE_BUDGET_SECONDS", budget_seconds * TICK)


def _seed_call(session: Session, status: CallStatus, *, with_event: bool = False) -> UUID:
    call = Call(
        public_call_id=uuid4().hex[:12],
        title="sse-stream",
        customer_name="Sarah",
        rep_name="Rahul",
        call_direction=CallDirection.OUTBOUND,
        source_type=SourceType.UPLOAD,
        recording_mode=RecordingMode.MONO,
        status=status,
        extra={},
    )
    session.add(call)
    session.flush()
    if with_event:
        session.add(
            ProcessingEvent(
                call_id=call.id,
                stage="transcribe",
                state=EventState.STARTED,
                attempt=1,
                details={},
            )
        )
    session.commit()
    return call.id


def _frames(body: str) -> list[str]:
    return [frame for frame in body.split("\n\n") if frame]


def _named_event(frame: str) -> str | None:
    for line in frame.split("\n"):
        if line.startswith("event: "):
            return line.removeprefix("event: ")
    return None


def test_stream_keepalives_and_timeout_event(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 42-second stream that never goes terminal: >=3 keepalives, then event: timeout."""
    call_id = _seed_call(session, CallStatus.TRANSCRIBING, with_event=True)
    # 42 seconds of stream time -- the window named by the acceptance check.
    _compress(monkeypatch, budget_seconds=42)

    response = client.get(f"/api/v1/calls/{call_id}/stream")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text

    # 42s / 10s keepalive interval => 4 keepalive comments; the check demands >= 3.
    keepalives = body.count(": keepalive\n\n")
    assert keepalives >= 3
    # Pin the cadence too, so a keepalive-per-poll regression cannot pass the check above.
    assert keepalives == 4

    frames = _frames(body)
    # The processing event still streams, with id: = its created_at.
    processing = [f for f in frames if _named_event(f) == "processing"]
    assert len(processing) == 1
    assert '"stage": "TRANSCRIBING"' in processing[0]
    assert '"state": "started"' in processing[0]
    event_id_line = next(line for line in processing[0].split("\n") if line.startswith("id: "))

    # Idle exit is announced, not silent, and it names the call's current status.
    last = frames[-1]
    assert _named_event(last) == "timeout"
    assert '"status": "TRANSCRIBING"' in last
    assert '"reason": "idle_timeout"' in last
    assert '"reconnect": true' in last
    assert f'"call_id": "{call_id}"' in last
    # ...and carries the last real event id so a reconnect resumes rather than replays.
    assert event_id_line in last.split("\n")

    assert "event: terminal" not in body


def test_stream_timeout_status_tracks_the_call(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The timeout payload reports whatever status the call is actually in."""
    call_id = _seed_call(session, CallStatus.ANALYZING)
    _compress(monkeypatch, budget_seconds=42)

    body = client.get(f"/api/v1/calls/{call_id}/stream").text
    last = _frames(body)[-1]
    assert _named_event(last) == "timeout"
    assert '"status": "ANALYZING"' in last


def test_stream_terminal_closes_without_timeout(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A terminal call still ends with event: terminal -- no keepalives, no timeout."""
    call_id = _seed_call(session, CallStatus.SHIPPED)
    _compress(monkeypatch, budget_seconds=42)

    body = client.get(f"/api/v1/calls/{call_id}/stream").text
    frames = _frames(body)
    assert _named_event(frames[-1]) == "terminal"
    assert '"status": "SHIPPED"' in frames[-1]
    assert "event: timeout" not in body
    assert ": keepalive" not in body


def test_stream_unknown_call_errors(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing call still yields event: error, never a timeout."""
    _compress(monkeypatch, budget_seconds=42)

    body = client.get(f"/api/v1/calls/{uuid4()}/stream").text
    assert body == 'event: error\ndata: {"error":"not_found"}\n\n'


def test_production_clock_meets_the_42s_check() -> None:
    """Pin the real constants the compressed-clock tests stand in for."""
    keepalive = calls_api.SSE_KEEPALIVE_INTERVAL_SECONDS
    budget = calls_api.SSE_IDLE_BUDGET_SECONDS
    assert keepalive == 10.0
    assert calls_api.SSE_POLL_INTERVAL_SECONDS == 0.25
    # Transcription regularly exceeds the old 30s budget.
    assert budget == 120.0
    # At least 3 keepalives land inside a real 42-second window...
    assert int(42 // keepalive) >= 3
    # ...and 42s is well inside the budget, so a live stream is not yet timing out.
    assert budget > 42

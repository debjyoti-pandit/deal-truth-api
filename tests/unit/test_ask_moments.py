"""API-5: an Ask moment without a timestamp cannot be played, so it is not a moment.

Chunks reloaded from transcript_chunks carry text and segment ids but no timestamps, so
moments came back with start_ms/end_ms null. The span is resolved from the segments the
chunk already cites — no migration, and no timestamp that is not in the transcript.
"""

from __future__ import annotations

from typing import Any

from app.core.errors import MLServiceUnavailable
from app.core.settings import Settings
from app.models.transcript import TranscriptSegment
from app.storage.memory import MemoryBlobStore
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.conftest import run_scenario


class DownML:
    """An ML service that is down in every direction the ask path can reach it."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise MLServiceUnavailable("down")

    def classify(self, texts: list[str], labels: list[str] | None = None) -> list[Any]:
        raise MLServiceUnavailable("down")

    def emotion(self, texts: list[str]) -> list[Any]:
        raise MLServiceUnavailable("down")

    def generate(self, prompt: str, *, max_tokens: int = 256) -> str:
        raise MLServiceUnavailable("down")


def _assert_moments_are_playable(session: Session, body: dict[str, Any]) -> None:
    spans = {str(seg.id): (seg.start_ms, seg.end_ms) for seg in session.scalars(select(TranscriptSegment)).all()}
    for moment in body["moments"]:
        assert moment["start_ms"] is not None, f"unplayable moment: {moment}"
        assert moment["end_ms"] is not None, f"unplayable moment: {moment}"
        assert moment["end_ms"] > moment["start_ms"], f"moment span is not forward: {moment}"
        cited = [spans[sid] for sid in moment["segment_ids"] if sid in spans]
        assert cited, "a moment must cite transcript segments that exist"
        # The span is the transcript's, not a number the API made up.
        assert moment["start_ms"] == min(start for start, _ in cited)
        assert moment["end_ms"] == max(end for _, end in cited)


def test_retrieval_moments_have_playable_timestamps(
    client: TestClient, session: Session, settings: Settings, blob: MemoryBlobStore
) -> None:
    call_id = run_scenario(session, settings, blob, "happy_path")
    response = client.post(
        f"/api/v1/calls/{call_id}/ask",
        json={"question": "What did the customer say about manually routing calls?"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "retrieval"
    assert body["moments"], "an indexed call must return moments"
    _assert_moments_are_playable(session, body)
    # The answer cites those timestamps, so a null span was visible to the reader too.
    assert "None ms" not in body["answer"]


def test_generation_path_moments_have_playable_timestamps(
    client: TestClient, session: Session, settings: Settings, blob: MemoryBlobStore
) -> None:
    call_id = run_scenario(session, settings, blob, "happy_path")
    response = client.post(
        f"/api/v1/calls/{call_id}/ask",
        json={"question": "What did the customer say about manually routing calls?", "generate": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["mode"].startswith(("generated", "retrieval"))
    assert body["moments"]
    _assert_moments_are_playable(session, body)


def test_lexical_fallback_moments_have_playable_timestamps(
    client: TestClient, session: Session, settings: Settings, blob: MemoryBlobStore
) -> None:
    call_id = run_scenario(session, settings, blob, "security_blocker")
    app = client.app
    assert isinstance(app, FastAPI)
    original = app.state.container.ml
    app.state.container.ml = DownML()
    try:
        response = client.post(
            f"/api/v1/calls/{call_id}/ask",
            json={"question": "security review for a new vendor"},
        )
    finally:
        app.state.container.ml = original
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "retrieval_lexical_fallback"
    assert body["moments"], "the lexical fallback must still find the security segments"
    _assert_moments_are_playable(session, body)
    assert "None ms" not in body["answer"]


def test_unindexed_call_returns_no_moments_at_all(client: TestClient) -> None:
    """no_index has nothing to play; the guarantee is that it ships no unplayable moment."""
    created = client.post("/api/v1/calls", json={"title": "happy_path", "customer_name": "Sarah"})
    assert created.status_code == 201
    call_id = created.json()["id"]
    body = client.post(f"/api/v1/calls/{call_id}/ask", json={"question": "anything at all"}).json()
    assert body["mode"] == "no_index"
    assert body["moments"] == []

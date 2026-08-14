"""A one-hour call must not fail on the Worker's batch cap.

The Worker enforces `MAX_BATCH_SIZE` (32) per request. An hour of audio is hundreds of
segments and transcript chunks, so the client chunks every batched call and reassembles the
results in input order — the cap bounds a request, never a call.
"""

from __future__ import annotations

import json

import httpx
import pytest
from app.core.errors import MLInferenceFailed
from app.core.settings import Settings
from app.ml import DealTruthMLClient

WORKER_MAX_BATCH = 32


class CappedWorker:
    """Mimics deal-truth-ml exactly where it matters: 413 on any request over the cap,
    id-keyed rows derived from the item text so misalignment is detectable."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.fail_from_request: int | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        self.requests.append({"path": request.url.path, "items": body.get("items", [])})
        if self.fail_from_request is not None and len(self.requests) >= self.fail_from_request:
            return httpx.Response(500, json={"error": {"code": "INTERNAL_ERROR"}})
        items = body.get("items", [])
        if len(items) > WORKER_MAX_BATCH:
            return httpx.Response(
                413,
                json={"error": {"code": "BATCH_TOO_LARGE", "message": "Too many items."}},
            )
        path = request.url.path
        if path == "/v1/classify":
            rows = [{"id": it["id"], "labels": [{"id": "pain_point", "score": _score_for(it["text"])}]} for it in items]
        elif path == "/v1/emotions":
            rows = [
                {
                    "id": it["id"],
                    "emotion": [{"label": "hesitant", "score": _score_for(it["text"])}],
                    "buying_intent": [],
                    "deal_signals": ([{"label": "budget_blocker", "score": 0.9}] if "budget" in it["text"] else []),
                }
                for it in items
            ]
        elif path == "/v1/embeddings":
            rows = [
                {"id": it["id"], "vector": [_score_for(it["text"])] + [0.01] * 1023, "dimension": 1024} for it in items
            ]
        else:
            return httpx.Response(404, json={"error": {"code": "NOT_FOUND"}})
        return httpx.Response(200, json={"items": rows, "model": "fake", "request_id": "r"})


def _score_for(text: str) -> float:
    """Encode the item's global index into its score, so any cross-chunk misalignment
    (chunk 2's rows landing on chunk 1's items) shows up as a wrong number."""
    return round(0.001 * int(text.rsplit("-", 1)[-1]), 3)


def _texts(count: int) -> list[str]:
    return [f"segment-{i}" for i in range(count)]


@pytest.fixture
def worker() -> CappedWorker:
    return CappedWorker()


@pytest.fixture
def ml(worker: CappedWorker, settings: Settings) -> DealTruthMLClient:
    return DealTruthMLClient(settings, client=httpx.Client(transport=httpx.MockTransport(worker)))


def test_classify_survives_a_one_hour_call(ml: DealTruthMLClient, worker: CappedWorker) -> None:
    results = ml.classify(_texts(70))
    assert len(results) == 70
    assert len(worker.requests) == 3, "70 items against a cap of 32 is three requests"
    assert all(len(r["items"]) <= WORKER_MAX_BATCH for r in worker.requests)
    # Alignment across chunk boundaries: item 40's result carries item 40's score.
    assert results[40].score("pain point") == pytest.approx(0.040)
    assert results[69].score("pain point") == pytest.approx(0.069)


def test_emotions_survive_and_stay_aligned_across_chunks(ml: DealTruthMLClient, worker: CappedWorker) -> None:
    texts = _texts(70)
    texts[40] = "budget frozen segment-40"  # the only blocker in the batch
    axes = ml.emotions(texts)
    assert len(axes) == 70
    assert len(worker.requests) == 3
    flagged = [i for i, a in enumerate(axes) if a.deal_signals]
    assert flagged == [40], "the blocker must land on the segment that said it"
    assert axes[40].emotion[0].score == pytest.approx(0.040)


def test_embeddings_survive_and_stay_aligned(ml: DealTruthMLClient, worker: CappedWorker) -> None:
    vectors = ml.embed(_texts(200))
    assert len(vectors) == 200
    assert len(worker.requests) == 7, "200 chunks of transcript is seven requests"
    assert vectors[150][0] == pytest.approx(0.150)


def test_a_request_over_the_cap_is_never_sent(ml: DealTruthMLClient, worker: CappedWorker) -> None:
    ml.classify(_texts(33))
    sizes = sorted(len(r["items"]) for r in worker.requests)
    assert sizes == [1, 32]


def test_a_failed_chunk_keeps_the_existing_degradation_semantics(ml: DealTruthMLClient, worker: CappedWorker) -> None:
    # Any chunk failing raises the same named error one request failing always did; the
    # pipeline's warn -> PARTIAL path is unchanged, the cap just no longer counts as failure.
    worker.fail_from_request = 2
    with pytest.raises(MLInferenceFailed):
        ml.classify(_texts(70))


def test_small_batches_still_go_in_one_request(ml: DealTruthMLClient, worker: CappedWorker) -> None:
    ml.emotions(_texts(5))
    assert len(worker.requests) == 1

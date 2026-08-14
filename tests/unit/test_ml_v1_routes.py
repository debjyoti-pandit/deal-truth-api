"""DealTruthMLClient speaks the `/v1` routes, and the three emotion axes survive to the report.

The compat `/emotion` route flattens `emotion`, `buying_intent` and `deal_signals` into one
array, which loses axis identity (`neutral` lives on two axes) and cannot say "this axis was
never scored". These tests pin the replacement: separate axes on the wire, separate axes on
`SENTIMENT_POINT.payload`, and an unavailable axis that is distinguishable from an empty one.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from app.core.enums import CallDirection, CallStatus, RecordingMode, SourceType
from app.core.errors import (
    MLAuthFailed,
    MLInferenceFailed,
    MLModelNotReady,
    MLResponseInvalid,
    MLServiceUnavailable,
)
from app.core.settings import Settings
from app.ml import DealTruthMLClient, EmotionAxes, canonical_sales_label, sales_label_slug
from app.models.call import AudioAsset, Call
from app.pipeline.runner import PipelineDeps, run_pipeline
from app.providers.fakes import FakeMLClient, FakeRecapProvider, FakeTranscriptionProvider, build_emotion_axes
from app.storage.keys import blob_keys
from app.storage.memory import MemoryBlobStore
from fixtures.catalog import HAPPY_SEGMENTS, SCENARIOS
from sqlalchemy.orm import Session

AXES = ("emotion", "buying_intent", "deal_signals")


class Recorder:
    """Captures every request and replays canned JSON, so the wire shape is assertable."""

    def __init__(self, response: Any, status: int = 200, body: bytes | None = None) -> None:
        self.response = response
        self.status = status
        self.body = body
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.body is not None:
            return httpx.Response(self.status, content=self.body, headers={"Content-Type": "application/json"})
        return httpx.Response(self.status, json=self.response)

    @property
    def path(self) -> str:
        return self.requests[-1].url.path

    def sent(self) -> dict[str, Any]:
        payload: dict[str, Any] = json.loads(self.requests[-1].content)
        return payload


def _client(recorder: Recorder, settings: Settings) -> DealTruthMLClient:
    transport = httpx.MockTransport(recorder)
    return DealTruthMLClient(settings, client=httpx.Client(transport=transport))


def _classify_response(labels: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "items": [{"id": "0", "labels": labels}],
        "model": "@cf/qwen/qwen3-30b-a3b-fp8",
        "request_id": "req-1",
    }


def _emotions_response(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"items": rows, "model": "@cf/qwen/qwen3-30b-a3b-fp8", "request_id": "req-2"}


# --------------------------------------------------------------------------------------
# wire contract
# --------------------------------------------------------------------------------------


def test_classify_posts_v1_classify_with_id_keyed_items(settings: Settings) -> None:
    recorder = Recorder(_classify_response([{"id": "pain_point", "score": 0.91, "passed_threshold": True}]))
    results = _client(recorder, settings).classify(["we lose six hours a week"])

    assert recorder.path == "/v1/classify"
    assert recorder.sent() == {"items": [{"id": "0", "text": "we lose six hours a week"}]}
    # No candidate_labels: the Worker's own 24-label catalogue carries real hypotheses and
    # per-label thresholds, and is a superset of SALES_LABELS.
    assert "candidate_labels" not in recorder.sent()
    assert results[0].as_dict() == {"pain point": 0.91}
    assert results[0].score("pain point") == 0.91


def test_classify_sends_candidate_labels_only_when_asked(settings: Settings) -> None:
    recorder = Recorder(_classify_response([{"id": "budget_blocker", "score": 0.8, "passed_threshold": True}]))
    _client(recorder, settings).classify(["finance froze the budget"], ["budget blocker", "out-of-scope request"])

    assert recorder.sent()["candidate_labels"] == [
        {"id": "budget_blocker", "hypothesis": "budget blocker"},
        {"id": "out_of_scope_request", "hypothesis": "out-of-scope request"},
    ]


def test_slug_round_trip_survives_hyphenated_labels() -> None:
    # The Worker slugifies `out-of-scope request` to `out_of_scope_request`; that id has to
    # find its way back to the extractor key or the label silently stops existing.
    assert sales_label_slug("out-of-scope request") == "out_of_scope_request"
    assert canonical_sales_label("out_of_scope_request") == "out-of-scope request"
    assert canonical_sales_label("pain_point") == "pain point"
    assert canonical_sales_label("security-blocker") == "security blocker"


def test_emotions_posts_v1_emotions_and_keeps_axes_separate(settings: Settings) -> None:
    recorder = Recorder(
        _emotions_response(
            [
                {
                    "id": "0",
                    "emotion": [{"label": "enthusiastic", "score": 0.9}, {"label": "neutral", "score": 0.3}],
                    "buying_intent": [{"label": "neutral", "score": 0.55}, {"label": "negative", "score": 0.7}],
                    "deal_signals": [{"label": "budget_blocker", "score": 0.85}],
                    "unavailable": {"emotion": False, "buying_intent": False, "deal_signals": False},
                }
            ]
        )
    )
    rows = _client(recorder, settings).emotions(["I love this, but finance froze our budget"])

    assert recorder.path == "/v1/emotions"
    assert recorder.sent() == {"items": [{"id": "0", "text": "I love this, but finance froze our budget"}]}
    row = rows[0]
    # The canonical case: emotion HIGH, buying intent LOW, blocker CRITICAL — all at once.
    assert [x.label for x in row.emotion] == ["enthusiastic", "neutral"]
    assert [x.label for x in row.buying_intent] == ["neutral", "negative"]
    assert [x.label for x in row.deal_signals] == ["budget_blocker"]
    # `neutral` sits on two axes meaning two different things; neither absorbs the other.
    assert row.axis("emotion")[1].score == 0.3
    assert row.axis("buying_intent")[0].score == 0.55
    # Valence reads the emotion axis alone: `negative` on buying_intent must not drag it down.
    assert row.valence() == pytest.approx(0.9)


def test_emotions_rows_are_matched_by_id_not_position(settings: Settings) -> None:
    recorder = Recorder(
        _emotions_response(
            [
                {
                    "id": "1",
                    "emotion": [{"label": "frustrated", "score": 0.8}],
                    "buying_intent": [],
                    "deal_signals": [],
                    "unavailable": {"emotion": False, "buying_intent": False, "deal_signals": False},
                },
                {
                    "id": "0",
                    "emotion": [{"label": "enthusiastic", "score": 0.9}],
                    "buying_intent": [],
                    "deal_signals": [],
                    "unavailable": {"emotion": False, "buying_intent": False, "deal_signals": False},
                },
            ]
        )
    )
    rows = _client(recorder, settings).emotions(["first", "second"])
    assert [x.label for x in rows[0].emotion] == ["enthusiastic"]
    assert [x.label for x in rows[1].emotion] == ["frustrated"]


def test_unavailable_axis_is_unknown_not_neutral(settings: Settings) -> None:
    recorder = Recorder(
        _emotions_response(
            [
                {
                    "id": "0",
                    "emotion": [{"label": "interested", "score": 0.6}],
                    "buying_intent": [],
                    "deal_signals": [],
                    "unavailable": {"emotion": False, "buying_intent": True, "deal_signals": False},
                }
            ]
        )
    )
    row = _client(recorder, settings).emotions(["maybe"])[0]

    # Two empty arrays, two different meanings. deal_signals was scored and found nothing;
    # buying_intent was never scored and asserts nothing at all.
    assert row.buying_intent == [] and row.is_unavailable("buying_intent")
    assert row.deal_signals == [] and not row.is_unavailable("deal_signals")
    assert row.any_available()
    assert row.as_payload()["unavailable"] == {"emotion": False, "buying_intent": True, "deal_signals": False}


def test_missing_axis_key_is_unavailable_not_empty(settings: Settings) -> None:
    recorder = Recorder(_emotions_response([{"id": "0", "emotion": [{"label": "curious", "score": 0.4}]}]))
    row = _client(recorder, settings).emotions(["hmm"])[0]

    assert not row.is_unavailable("emotion")
    assert row.is_unavailable("buying_intent")
    assert row.is_unavailable("deal_signals")


def test_flagged_axis_never_keeps_scores(settings: Settings) -> None:
    recorder = Recorder(
        _emotions_response(
            [
                {
                    "id": "0",
                    "emotion": [{"label": "interested", "score": 0.6}],
                    "buying_intent": [{"label": "positive", "score": 0.9}],
                    "deal_signals": [],
                    "unavailable": {"emotion": False, "buying_intent": True, "deal_signals": False},
                }
            ]
        )
    )
    row = _client(recorder, settings).emotions(["contradictory row"])[0]
    assert row.buying_intent == []


def test_all_axes_unavailable_has_no_valence(settings: Settings) -> None:
    row = EmotionAxes.all_unavailable()
    assert row.valence() is None
    assert row.grouped() is None
    assert not row.any_available()


def test_embed_posts_v1_embeddings_and_reads_vector(settings: Settings) -> None:
    recorder = Recorder(
        {
            "items": [{"id": "0", "vector": [0.1, 0.2, 0.3], "dimension": 3, "normalized": True}],
            "model": "@cf/qwen/qwen3-embedding-0.6b",
            "request_id": "req-3",
        }
    )
    vectors = _client(recorder, settings).embed(["hello"])

    assert recorder.path == "/v1/embeddings"
    assert recorder.sent() == {"items": [{"id": "0", "text": "hello"}], "normalize": True}
    assert vectors == [[0.1, 0.2, 0.3]]


def test_generate_posts_v1_generate_with_a_task(settings: Settings) -> None:
    recorder = Recorder({"text": "drafted", "task": "summary_fallback", "model": "m", "grounded": False})
    assert _client(recorder, settings).generate("summarise this", max_tokens=64) == "drafted"

    assert recorder.path == "/v1/generate"
    assert recorder.sent() == {
        "task": "summary_fallback",
        "input": "summarise this",
        "max_new_tokens": 64,
        "temperature": 0,
    }


# --------------------------------------------------------------------------------------
# degradation: the named errors have to fire on exactly the same conditions
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, MLAuthFailed),
        (403, MLAuthFailed),
        (503, MLModelNotReady),
        (502, MLInferenceFailed),
        (504, MLInferenceFailed),
        (429, MLInferenceFailed),
        (413, MLInferenceFailed),
    ],
)
def test_named_errors_on_v1_emotions(status: int, expected: type[Exception], settings: Settings) -> None:
    recorder = Recorder({"error": {"code": "X", "message": "y"}}, status=status)
    with pytest.raises(expected):
        _client(recorder, settings).emotions(["text"])


def test_transport_failure_is_service_unavailable(settings: Settings) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = DealTruthMLClient(settings, client=httpx.Client(transport=httpx.MockTransport(boom)))
    with pytest.raises(MLServiceUnavailable):
        client.emotions(["text"])


def test_non_json_body_is_response_invalid(settings: Settings) -> None:
    recorder = Recorder(None, body=b"<html>nope</html>")
    with pytest.raises(MLResponseInvalid):
        _client(recorder, settings).emotions(["text"])


def test_short_batch_is_response_invalid(settings: Settings) -> None:
    recorder = Recorder(_emotions_response([{"id": "0", "emotion": [], "buying_intent": [], "deal_signals": []}]))
    with pytest.raises(MLResponseInvalid):
        _client(recorder, settings).emotions(["one", "two"])


# --------------------------------------------------------------------------------------
# the stated check: all three axes reach the report, separately
# --------------------------------------------------------------------------------------


CUSTOMER_ONE = HAPPY_SEGMENTS[1]["text"]
CUSTOMER_TWO = HAPPY_SEGMENTS[3]["text"]


def _run(session: Session, settings: Settings, blob: MemoryBlobStore, ml: FakeMLClient) -> UUID:
    data = SCENARIOS["happy_path"]
    call = Call(
        public_call_id=uuid4().hex[:12],
        title="axes",
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
            checksum="abc",
        )
    )
    session.commit()
    run_pipeline(
        PipelineDeps(
            session=session,
            settings=settings,
            blob=blob,
            transcription=FakeTranscriptionProvider(data["transcript"]),
            recap=FakeRecapProvider(data["recap"]),
            ml=ml,
        ),
        call.id,
    )
    session.commit()
    return call.id


def _report(blob: MemoryBlobStore, settings: Settings, call_id: UUID) -> dict[str, Any]:
    keys = blob_keys(call_id, "audio.bin")
    report: dict[str, Any] = json.loads(blob.get_bytes(settings.s3_bucket_results, keys.report_json))
    return report


def test_report_sentiment_timeline_carries_three_separate_axes(
    session: Session, settings: Settings, blob: MemoryBlobStore
) -> None:
    ml = FakeMLClient(
        classifications=SCENARIOS["happy_path"]["classifications"],
        emotions={
            CUSTOMER_ONE: {
                "emotion": {"enthusiastic": 0.9},
                "buying_intent": {"negative": 0.7},
                "deal_signals": {"budget_blocker": 0.85},
            },
            CUSTOMER_TWO: {
                "emotion": {"interested": 0.6},
                "buying_intent": {},
                "deal_signals": {},
                "unavailable": {"buying_intent": True},
            },
        },
    )
    report = _report(blob, settings, _run(session, settings, blob, ml))
    timeline = report["sentiment_timeline"]
    assert timeline, "customer segments must produce sentiment points"

    # The stated check, verbatim: every entry carries all three axes as separate arrays.
    for entry in timeline:
        payload = entry["payload"]
        for axis in AXES:
            assert isinstance(payload[axis], list), f"{axis} must be an array"
        assert set(payload["unavailable"]) == set(AXES)

    by_quote = {entry["quotes"][0]: entry["payload"] for entry in timeline}
    hot = by_quote[CUSTOMER_ONE]
    # Emotion HIGH while buying intent reads negative and a budget blocker is live. The
    # compat route could only have returned these three as one undifferentiated list.
    assert hot["emotion"] == [{"label": "enthusiastic", "score": 0.9}]
    assert hot["buying_intent"] == [{"label": "negative", "score": 0.7}]
    assert hot["deal_signals"] == [{"label": "budget_blocker", "score": 0.85}]
    assert hot["unavailable"] == {"emotion": False, "buying_intent": False, "deal_signals": False}


def test_report_distinguishes_unavailable_axis_from_empty_one(
    session: Session, settings: Settings, blob: MemoryBlobStore
) -> None:
    ml = FakeMLClient(
        classifications=SCENARIOS["happy_path"]["classifications"],
        emotions={
            CUSTOMER_TWO: {
                "emotion": {"interested": 0.6},
                "buying_intent": {},
                "deal_signals": {},
                "unavailable": {"buying_intent": True},
            }
        },
    )
    report = _report(blob, settings, _run(session, settings, blob, ml))
    payload = next(e["payload"] for e in report["sentiment_timeline"] if e["quotes"][0] == CUSTOMER_TWO)

    # Both arrays are empty. Only the flag says which emptiness is a fact about the
    # customer and which is a hole in what we know.
    assert payload["buying_intent"] == [] and payload["unavailable"]["buying_intent"] is True
    assert payload["deal_signals"] == [] and payload["unavailable"]["deal_signals"] is False
    assert payload["grouped"]["valence"] == pytest.approx(0.6)


def test_segment_with_every_axis_unavailable_is_not_a_finding(
    session: Session, settings: Settings, blob: MemoryBlobStore
) -> None:
    all_unknown = {
        "unavailable": {"emotion": True, "buying_intent": True, "deal_signals": True},
    }
    ml = FakeMLClient(
        classifications=SCENARIOS["happy_path"]["classifications"],
        emotions={CUSTOMER_ONE: all_unknown, CUSTOMER_TWO: {"emotion": {"interested": 0.6}}},
    )
    report = _report(blob, settings, _run(session, settings, blob, ml))
    quotes = [entry["quotes"][0] for entry in report["sentiment_timeline"]]

    # Nothing was scored for this segment, so nothing is claimed about it. Emitting a
    # neutral-looking point would turn an inference gap into a finding.
    assert CUSTOMER_ONE not in quotes
    assert CUSTOMER_TWO in quotes


def test_ml_outage_leaves_no_fabricated_sentiment(session: Session, settings: Settings, blob: MemoryBlobStore) -> None:
    class DeadEmotions(FakeMLClient):
        def emotions(self, texts: list[str]) -> list[EmotionAxes]:
            raise MLServiceUnavailable("ml down")

    call_id = _run(
        session,
        settings,
        blob,
        DeadEmotions(classifications=SCENARIOS["happy_path"]["classifications"]),
    )
    call = session.get(Call, call_id)
    assert call is not None and call.status == CallStatus.PARTIAL
    report = _report(blob, settings, call_id)
    assert report["sentiment_timeline"] == []
    assert "ML_SERVICE_UNAVAILABLE" in report["warnings"]


def test_fake_axes_builder_accepts_legacy_flat_fixtures() -> None:
    # fixtures/catalog.py still writes `{"optimism": 0.7}`. That is the emotion axis; the
    # other two were scored and empty, not unknown.
    axes = build_emotion_axes({"optimism": 0.7, "approval": 0.2})
    assert [x.label for x in axes.emotion] == ["optimism", "approval"]
    assert axes.buying_intent == [] and not axes.is_unavailable("buying_intent")
    assert axes.deal_signals == [] and not axes.is_unavailable("deal_signals")
    assert axes.valence() == pytest.approx(0.9)

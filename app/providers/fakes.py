"""Test doubles for providers and ML. Used by unit tests and the in-process pipeline."""

from __future__ import annotations

from uuid import UUID

from app.core.errors import PyAIJobFailed, PyAIRecapFailed, PyAIScopeMissing
from app.ml import SALES_LABELS, ClassificationResult, EmotionResult, LabelScore
from app.providers.normalized import NormalizedRecap, NormalizedTranscript, TranscriptionJobHandle
from app.providers.pyai import normalize_recap, normalize_transcript


class FakeTranscriptionProvider:
    def __init__(
        self,
        transcript: NormalizedTranscript | dict[str, object] | None = None,
        *,
        fail: bool = False,
        recording_mode: str = "mono",
    ) -> None:
        self.fail = fail
        self.recording_mode = recording_mode
        if isinstance(transcript, NormalizedTranscript):
            self.transcript = transcript
        elif transcript is not None:
            self.transcript = normalize_transcript(transcript, recording_mode=recording_mode)
        else:
            self.transcript = NormalizedTranscript(text="", segments=[], speakers=[], recording_mode=recording_mode)
        self.submitted: list[dict[str, object]] = []

    def submit_job(self, **kwargs: object) -> TranscriptionJobHandle:
        self.submitted.append(dict(kwargs))
        if self.fail:
            raise PyAIJobFailed("fixture transcription failed")
        return TranscriptionJobHandle(
            job_id="job_fake", status="queued", public_call_id=str(kwargs.get("public_call_id"))
        )

    def get_job(self, job_id: str) -> dict[str, object]:
        return {"id": job_id, "status": "completed"}

    def fetch_normalized(self, job_id: str) -> NormalizedTranscript:
        if self.fail:
            raise PyAIJobFailed("fixture transcription failed")
        return self.transcript

    def poll_until_complete(self, job_id: str) -> NormalizedTranscript:
        return self.fetch_normalized(job_id)


class FakeRecapProvider:
    def __init__(
        self,
        recap: NormalizedRecap | dict[str, object] | None = None,
        *,
        fail: bool = False,
        scope_missing: bool = False,
    ) -> None:
        self.fail = fail
        self.scope_missing = scope_missing
        if isinstance(recap, NormalizedRecap):
            self.recap = recap
        elif recap is not None:
            self.recap = normalize_recap(recap)
        else:
            self.recap = NormalizedRecap(status="completed", headline="Fixture recap")

    def get_recap(self, call_id: UUID, public_call_id: str) -> NormalizedRecap:
        if self.scope_missing:
            raise PyAIScopeMissing("fixture recap scope missing")
        if self.fail:
            raise PyAIRecapFailed("fixture recap failed")
        return self.recap

    def poll_until_ready(self, call_id: UUID, public_call_id: str) -> NormalizedRecap:
        return self.get_recap(call_id, public_call_id)


class FakeMLClient:
    def __init__(
        self,
        classifications: dict[str, dict[str, float]] | None = None,
        emotions: dict[str, dict[str, float]] | None = None,
        *,
        generation_text: str | None = None,
        fail_generation: bool = False,
        embedding_dim: int = 384,
    ) -> None:
        self.classifications = classifications or {}
        self.emotions = emotions or {}
        self.generation_text = generation_text
        self.fail_generation = fail_generation
        self.embedding_dim = embedding_dim
        self.classify_calls = 0
        self.embed_calls = 0

    def classify(self, texts: list[str], labels: list[str] | None = None) -> list[ClassificationResult]:
        self.classify_calls += 1
        out: list[ClassificationResult] = []
        for text in texts:
            scores = self.classifications.get(text, {})
            if not scores:
                scores = {label: 0.0 for label in (labels or list(SALES_LABELS))}
            out.append(ClassificationResult(labels=[LabelScore(label=k, score=v) for k, v in scores.items()]))
        return out

    def emotion(self, texts: list[str]) -> list[EmotionResult]:
        out: list[EmotionResult] = []
        for text in texts:
            scores = self.emotions.get(text, {"neutral": 1.0})
            out.append(EmotionResult(labels=[LabelScore(label=k, score=v) for k, v in scores.items()]))
        return out

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls += 1
        vectors: list[list[float]] = []
        for text in texts:
            seed = float(sum(ord(c) for c in text) % 100) / 100.0
            vec = [0.0] * self.embedding_dim
            if vec:
                vec[0] = seed
                vec[1] = 1.0 - seed
            vectors.append(vec)
        return vectors

    def generate(self, prompt: str, *, max_tokens: int = 256) -> str:
        if self.fail_generation:
            from app.core.errors import MLInferenceFailed

            raise MLInferenceFailed("fixture generation failed")
        if self.generation_text is not None:
            return self.generation_text
        return "generated"

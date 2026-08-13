"""ML inference client interface and deal-truth-ml HTTP implementation."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import httpx
from pydantic import BaseModel, Field

from app.core.errors import (
    MLAuthFailed,
    MLGenerationDisabled,
    MLInferenceFailed,
    MLModelNotReady,
    MLResponseInvalid,
    MLServiceUnavailable,
)
from app.core.settings import Settings

SALES_LABELS: tuple[str, ...] = (
    "pain point",
    "positive buying signal",
    "negative buying signal",
    "pricing objection",
    "security blocker",
    "technical blocker",
    "budget blocker",
    "competitor mention",
    "competitor preference",
    "decision maker identified",
    "economic buyer identified",
    "purchase timeline",
    "next meeting commitment",
    "customer commitment",
    "seller commitment",
    "feature requirement",
    "integration requirement",
    "out-of-scope request",
    "customer question",
    "customer concern",
    "customer praise",
)

POSITIVE_EMOTIONS = frozenset(
    {
        "admiration",
        "amusement",
        "approval",
        "caring",
        "desire",
        "excitement",
        "gratitude",
        "joy",
        "love",
        "optimism",
        "pride",
        "relief",
    }
)
NEGATIVE_EMOTIONS = frozenset(
    {
        "anger",
        "annoyance",
        "disappointment",
        "disapproval",
        "disgust",
        "embarrassment",
        "fear",
        "grief",
        "nervousness",
        "remorse",
        "sadness",
    }
)
NEUTRAL_EMOTIONS = frozenset({"curiosity", "confusion", "realization", "surprise", "neutral"})


class LabelScore(BaseModel):
    label: str
    score: float


class EmotionResult(BaseModel):
    labels: list[LabelScore] = Field(default_factory=list)

    def grouped(self) -> dict[str, float]:
        pos = sum(x.score for x in self.labels if x.label in POSITIVE_EMOTIONS)
        neg = sum(x.score for x in self.labels if x.label in NEGATIVE_EMOTIONS)
        neu = sum(x.score for x in self.labels if x.label in NEUTRAL_EMOTIONS)
        return {"positive": pos, "negative": neg, "neutral": neu, "valence": pos - neg}


class ClassificationResult(BaseModel):
    labels: list[LabelScore] = Field(default_factory=list)

    def score(self, label: str) -> float:
        for item in self.labels:
            if item.label == label:
                return item.score
        return 0.0

    def as_dict(self) -> dict[str, float]:
        return {item.label: item.score for item in self.labels}


@runtime_checkable
class MLInferenceClient(Protocol):
    def classify(self, texts: list[str], labels: list[str] | None = None) -> list[ClassificationResult]: ...

    def emotion(self, texts: list[str]) -> list[EmotionResult]: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def generate(self, prompt: str, *, max_tokens: int = 256) -> str: ...


class DealTruthMLClient:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.Client(timeout=60.0)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self._settings.ml_service_api_key:
            headers["Authorization"] = f"Bearer {self._settings.ml_service_api_key}"
        base = self._settings.resolved_ml_service_base_url.lower()
        if "ngrok" in base:
            headers["ngrok-skip-browser-warning"] = "true"
        return headers

    def _post(self, path: str, json_body: dict[str, object]) -> dict[str, object] | list[object]:
        url = f"{self._settings.resolved_ml_service_base_url.rstrip('/')}{path}"
        try:
            response = self._client.post(url, json=json_body, headers=self._headers())
        except httpx.HTTPError as exc:
            raise MLServiceUnavailable("ML service is unavailable") from exc
        if response.status_code in {401, 403}:
            raise MLAuthFailed("ML service authentication failed")
        if response.status_code == 503:
            raise MLModelNotReady("ML models are not ready")
        if response.status_code in {408, 429, 500, 502, 504}:
            raise MLInferenceFailed("ML inference failed with a transient error")
        if response.status_code >= 400:
            raise MLInferenceFailed("ML inference failed", details={"status_code": response.status_code})
        try:
            payload = response.json()
        except ValueError as exc:
            raise MLResponseInvalid("ML service returned non-JSON") from exc
        return payload  # type: ignore[no-any-return]

    def classify(self, texts: list[str], labels: list[str] | None = None) -> list[ClassificationResult]:
        payload = self._post("/classify", {"texts": texts, "labels": labels or list(SALES_LABELS)})
        return [_parse_classification(item) for item in _as_items(payload, len(texts))]

    def emotion(self, texts: list[str]) -> list[EmotionResult]:
        payload = self._post("/emotion", {"texts": texts})
        return [_parse_emotion(item) for item in _as_items(payload, len(texts))]

    def embed(self, texts: list[str]) -> list[list[float]]:
        payload = self._post("/embed", {"texts": texts})
        items = _as_items(payload, len(texts))
        vectors: list[list[float]] = []
        for item in items:
            if isinstance(item, dict) and "embedding" in item:
                vec = item["embedding"]
            else:
                vec = item
            if not isinstance(vec, list) or not vec:
                raise MLResponseInvalid("ML embed response missing vector")
            vectors.append([float(x) for x in vec])
        return vectors

    def generate(self, prompt: str, *, max_tokens: int = 256) -> str:
        if not self._settings.ml_generation_enabled:
            raise MLGenerationDisabled("ML generation is disabled")
        payload = self._post("/generate", {"prompt": prompt, "max_tokens": max_tokens})
        if isinstance(payload, dict):
            text = payload.get("text") or payload.get("generated_text")
            if isinstance(text, str):
                return text
        raise MLResponseInvalid("ML generate response missing text")


def _as_items(payload: dict[str, object] | list[object], expected: int) -> list[object]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        raw = payload.get("results") or payload.get("data") or payload.get("items")
        if isinstance(raw, list):
            items = raw
        else:
            items = [payload]
    else:
        raise MLResponseInvalid("Unexpected ML response shape")
    if len(items) != expected:
        # Allow a single batched object that itself contains per-text scores.
        if expected == 1 and items:
            return items[:1]
        if len(items) < expected:
            raise MLResponseInvalid("ML response item count mismatch")
        return items[:expected]
    return items


def _parse_classification(item: object) -> ClassificationResult:
    labels: list[LabelScore] = []
    if isinstance(item, dict):
        raw = item.get("labels") or item.get("scores") or item
        if isinstance(raw, dict):
            labels = [LabelScore(label=str(k), score=float(v)) for k, v in raw.items() if isinstance(v, (int, float))]
        elif isinstance(raw, list):
            for entry in raw:
                if isinstance(entry, dict):
                    labels.append(
                        LabelScore(
                            label=str(entry.get("label") or entry.get("name")), score=float(entry.get("score") or 0)
                        )
                    )
    return ClassificationResult(labels=labels)


def _parse_emotion(item: object) -> EmotionResult:
    parsed = _parse_classification(item)
    return EmotionResult(labels=parsed.labels)

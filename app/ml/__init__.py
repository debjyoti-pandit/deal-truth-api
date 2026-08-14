"""ML inference client interface and deal-truth-ml HTTP implementation.

Speaks the modern `/v1` routes only. The compat aliases (`/classify`, `/emotion`,
`/embed`, `/generate`) are still live on the Worker but deprecated, and `/emotion` in
particular flattens three deliberately-separate axes into one `labels` array — an axis
that was never scored becomes indistinguishable from one that scored nothing, and
`neutral` (a member of both `emotion` and `buying_intent`) can appear twice meaning
different things. `/v1/emotions` keeps the axes named, unmerged, and each carrying its own
`unavailable` flag.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
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

logger = logging.getLogger(__name__)

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

# The three axes `/v1/emotions` returns. Always all three, always separately: an axis is
# never null and never omitted, and labels are never deduped across axes.
EMOTION_AXES: tuple[str, ...] = ("emotion", "buying_intent", "deal_signals")

# Worker taxonomies (deal-truth-ml `src/taxonomies/emotions.ts`). Mirrored here so the
# axis a label belongs to is nameable on this side too.
SALES_EMOTIONS: tuple[str, ...] = (
    "enthusiastic",
    "interested",
    "curious",
    "neutral",
    "uncertain",
    "hesitant",
    "concerned",
    "frustrated",
    "skeptical",
    "rejecting",
)
BUYING_INTENT_LABELS: tuple[str, ...] = (
    "strong_positive",
    "positive",
    "neutral",
    "weak",
    "negative",
)
DEAL_SIGNAL_LABELS: tuple[str, ...] = (
    "pricing_blocker",
    "security_blocker",
    "budget_blocker",
    "competitor_active",
    "timeline_present",
    "next_step_committed",
)

# Valence buckets for the `emotion` axis ONLY. Buying intent has its own polarity words
# (`positive`, `negative`) that mean something entirely different; rolling them into a
# single valence is the exact merge this client exists to avoid. The GoEmotions names are
# kept because older fixtures still speak them.
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
        "enthusiastic",
        "interested",
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
        "hesitant",
        "concerned",
        "frustrated",
        "skeptical",
        "rejecting",
    }
)
NEUTRAL_EMOTIONS = frozenset(
    {
        "curiosity",
        "confusion",
        "realization",
        "surprise",
        "neutral",
        "curious",
        "uncertain",
    }
)


def _label_key(raw: str) -> str:
    """Spaced, lower-cased form of a label id, so `pain_point`/`pain-point`/`Pain Point` agree."""
    return " ".join(raw.strip().lower().replace("-", " ").replace("_", " ").split())


_LABEL_BY_KEY = {_label_key(label): label for label in SALES_LABELS}


def canonical_sales_label(raw: str) -> str:
    """Map Worker slug ids (`pain_point`) back to API extractor keys (`pain point`)."""
    return _LABEL_BY_KEY.get(_label_key(raw), raw.strip())


def sales_label_slug(label: str) -> str:
    """Worker-side id for a label. Matches `slugify` in deal-truth-ml `src/index.ts`."""
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "label"


class LabelScore(BaseModel):
    label: str
    score: float


class AxisAvailability(BaseModel):
    """Per-axis "was this scored at all?" flags.

    `True` means the axis was never scored: the empty array beside it is UNKNOWN, not
    neutral. Axes fail independently — one unavailable axis says nothing about the others.
    """

    emotion: bool = False
    buying_intent: bool = False
    deal_signals: bool = False


class EmotionAxes(BaseModel):
    """One `/v1/emotions` row: three axes that are never merged and never deduped together.

    `[]` on an axis means it *was* scored and nothing cleared the threshold — a genuinely
    flat utterance. `unavailable.<axis>` means it was not scored at all.
    """

    emotion: list[LabelScore] = Field(default_factory=list)
    buying_intent: list[LabelScore] = Field(default_factory=list)
    deal_signals: list[LabelScore] = Field(default_factory=list)
    unavailable: AxisAvailability = Field(default_factory=AxisAvailability)

    @classmethod
    def all_unavailable(cls) -> EmotionAxes:
        """Nothing was scored for this item — every axis unknown, none of them neutral."""
        return cls(unavailable=AxisAvailability(emotion=True, buying_intent=True, deal_signals=True))

    def axis(self, name: str) -> list[LabelScore]:
        if name not in EMOTION_AXES:
            raise KeyError(f"unknown emotion axis {name!r}")
        scores: list[LabelScore] = getattr(self, name)
        return scores

    def is_unavailable(self, name: str) -> bool:
        if name not in EMOTION_AXES:
            raise KeyError(f"unknown emotion axis {name!r}")
        flag: bool = getattr(self.unavailable, name)
        return flag

    def any_available(self) -> bool:
        return any(not self.is_unavailable(name) for name in EMOTION_AXES)

    def top_score(self) -> float | None:
        scores = [item.score for name in EMOTION_AXES for item in self.axis(name)]
        return max(scores) if scores else None

    def valence(self) -> float | None:
        """Emotion-axis valence, or None when that axis was never scored.

        None is not zero. Zero is "we scored the emotion axis and it came out balanced";
        None is "we do not know", and a caller must not render it as a neutral customer.
        """
        if self.is_unavailable("emotion"):
            return None
        grouped = self.grouped()
        return None if grouped is None else grouped["valence"]

    def grouped(self) -> dict[str, float] | None:
        """Positive/negative/neutral roll-up of the emotion axis, or None when unscored.

        Deliberately emotion-only. Buying intent is a separate axis with its own labels.
        """
        if self.is_unavailable("emotion"):
            return None
        pos = sum(x.score for x in self.emotion if x.label in POSITIVE_EMOTIONS)
        neg = sum(x.score for x in self.emotion if x.label in NEGATIVE_EMOTIONS)
        neu = sum(x.score for x in self.emotion if x.label in NEUTRAL_EMOTIONS)
        return {"positive": pos, "negative": neg, "neutral": neu, "valence": pos - neg}

    def as_payload(self) -> dict[str, object]:
        """The three axes as separate arrays plus the availability flags, ready to persist."""
        payload: dict[str, object] = {
            name: [{"label": item.label, "score": item.score} for item in self.axis(name)] for name in EMOTION_AXES
        }
        payload["unavailable"] = {name: self.is_unavailable(name) for name in EMOTION_AXES}
        return payload


class ClassificationResult(BaseModel):
    labels: list[LabelScore] = Field(default_factory=list)

    def score(self, label: str) -> float:
        want = canonical_sales_label(label)
        for item in self.labels:
            if item.label == label or canonical_sales_label(item.label) == want:
                return item.score
        return 0.0

    def as_dict(self) -> dict[str, float]:
        return {item.label: item.score for item in self.labels}


@runtime_checkable
class MLInferenceClient(Protocol):
    def classify(self, texts: list[str], labels: list[str] | None = None) -> list[ClassificationResult]: ...

    def emotions(self, texts: list[str]) -> list[EmotionAxes]: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def generate(self, prompt: str, *, max_tokens: int = 256) -> str: ...


class DealTruthMLClient:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self._settings = settings
        # The Worker chunks classify/emotions sequentially inside one HTTP request.
        self._client = client or httpx.Client(timeout=httpx.Timeout(300.0, connect=10.0))
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
            logger.warning("ml_unavailable path=%s error=%s", path, type(exc).__name__)
            raise MLServiceUnavailable("ML service is unavailable") from exc
        if response.status_code in {401, 403}:
            logger.warning("ml_auth_failed path=%s status=%s", path, response.status_code)
            raise MLAuthFailed("ML service authentication failed")
        if response.status_code == 503:
            logger.warning("ml_not_ready path=%s", path)
            raise MLModelNotReady("ML models are not ready")
        if response.status_code in {408, 429, 500, 502, 504}:
            logger.warning("ml_transient_error path=%s status=%s", path, response.status_code)
            raise MLInferenceFailed("ML inference failed with a transient error")
        if response.status_code >= 400:
            logger.warning("ml_error path=%s status=%s", path, response.status_code)
            raise MLInferenceFailed("ML inference failed", details={"status_code": response.status_code})
        try:
            payload = response.json()
        except ValueError as exc:
            raise MLResponseInvalid("ML service returned non-JSON") from exc
        logger.debug("ml_ok path=%s status=%s", path, response.status_code)
        return payload  # type: ignore[no-any-return]

    def classify(self, texts: list[str], labels: list[str] | None = None) -> list[ClassificationResult]:
        logger.info("ml_classify texts=%s", len(texts))
        body: dict[str, object] = {"items": _request_items(texts)}
        if labels:
            # Omitted entirely when the caller has no opinion, so the Worker's own
            # 24-label catalogue (real NLI hypotheses, per-label thresholds) is used. It is
            # a strict superset of SALES_LABELS.
            body["candidate_labels"] = [{"id": sales_label_slug(label), "hypothesis": label} for label in labels]
        payload = self._post("/v1/classify", body)
        _log_meta("/v1/classify", payload)
        return [_parse_classification(item) for item in _aligned_rows(payload, len(texts))]

    def emotions(self, texts: list[str]) -> list[EmotionAxes]:
        logger.info("ml_emotions texts=%s", len(texts))
        # No threshold/top_k: the Worker defaults (0.2 / 6) are the shipped contract.
        payload = self._post("/v1/emotions", {"items": _request_items(texts)})
        _log_meta("/v1/emotions", payload)
        return [_parse_emotion_axes(item) for item in _aligned_rows(payload, len(texts))]

    def embed(self, texts: list[str]) -> list[list[float]]:
        logger.info("ml_embed texts=%s", len(texts))
        payload = self._post("/v1/embeddings", {"items": _request_items(texts), "normalize": True})
        _log_meta("/v1/embeddings", payload)
        vectors: list[list[float]] = []
        for item in _aligned_rows(payload, len(texts)):
            if isinstance(item, dict):
                vec = item.get("vector", item.get("embedding"))
            else:
                vec = item
            if not isinstance(vec, list) or not vec:
                raise MLResponseInvalid("ML embed response missing vector")
            vectors.append([float(x) for x in vec])
        return vectors

    def generate(self, prompt: str, *, max_tokens: int = 256) -> str:
        if not self._settings.ml_generation_enabled:
            raise MLGenerationDisabled("ML generation is disabled")
        payload = self._post(
            "/v1/generate",
            {
                "task": "summary_fallback",
                "input": prompt,
                "max_new_tokens": max_tokens,
                "temperature": 0,
            },
        )
        if isinstance(payload, dict):
            text = payload.get("text") or payload.get("generated_text")
            if isinstance(text, str):
                return text
        raise MLResponseInvalid("ML generate response missing text")


def _request_items(texts: Sequence[str]) -> list[dict[str, str]]:
    """`/v1/*` batches are id-keyed. Positional ids are unique by construction, which
    `/v1/emotions` requires: duplicates are a 400, because a shared id would silently hand
    one item's scores to another while still reporting `unavailable: false`."""
    return [{"id": str(index), "text": text} for index, text in enumerate(texts)]


def _log_meta(path: str, payload: dict[str, object] | list[object]) -> None:
    if isinstance(payload, dict):
        logger.debug("ml_meta path=%s model=%s request_id=%s", path, payload.get("model"), payload.get("request_id"))


def _as_items(payload: dict[str, object] | list[object], expected: int) -> list[object]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        raw = payload.get("items") or payload.get("results") or payload.get("data")
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


def _aligned_rows(payload: dict[str, object] | list[object], expected: int) -> list[object]:
    """Re-key `/v1` rows by the ids we sent, falling back to response order.

    Scores are attributed by id on the Worker side; honouring that here means a reordered
    response cannot hand one segment another segment's emotions.
    """
    items = _as_items(payload, expected)
    by_id: dict[str, object] = {}
    for row in items:
        if isinstance(row, dict) and isinstance(row.get("id"), (str, int)):
            by_id[str(row["id"])] = row
    wanted = [str(index) for index in range(expected)]
    if all(key in by_id for key in wanted):
        return [by_id[key] for key in wanted]
    return items


def _parse_scores(raw: object) -> list[LabelScore]:
    scores: list[LabelScore] = []
    if isinstance(raw, dict):
        return [LabelScore(label=str(k), score=float(v)) for k, v in raw.items() if isinstance(v, (int, float))]
    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            # `/v1/classify` names the label `id`; `/v1/emotions` names it `label`.
            name = entry.get("label") or entry.get("id") or entry.get("name") or ""
            scores.append(LabelScore(label=str(name), score=float(entry.get("score") or 0)))
    return scores


def _parse_classification(item: object) -> ClassificationResult:
    labels: list[LabelScore] = []
    if isinstance(item, dict):
        raw = item.get("labels") or item.get("scores") or item
        labels = [
            LabelScore(label=canonical_sales_label(score.label), score=score.score) for score in _parse_scores(raw)
        ]
    return ClassificationResult(labels=labels)


def _parse_emotion_axes(item: object) -> EmotionAxes:
    """Parse one `/v1/emotions` row, preserving the unknown/neutral distinction.

    A row that is missing an axis, or that is not an object at all, is unavailable — never
    an empty-but-scored axis, because downstream that reads as "the customer was flat".
    """
    if not isinstance(item, dict):
        return EmotionAxes.all_unavailable()
    flags = item.get("unavailable")
    flags = flags if isinstance(flags, dict) else {}
    axes: dict[str, list[LabelScore]] = {}
    unavailable: dict[str, bool] = {}
    for name in EMOTION_AXES:
        raw = item.get(name)
        missing = raw is None
        unavailable[name] = bool(flags.get(name)) or missing
        axes[name] = [] if missing else _parse_scores(raw)
        if unavailable[name]:
            # The contract pairs the flag with an empty array. Enforce it so a flagged
            # axis can never also carry scores that a reader might believe.
            axes[name] = []
    return EmotionAxes(
        emotion=axes["emotion"],
        buying_intent=axes["buying_intent"],
        deal_signals=axes["deal_signals"],
        unavailable=AxisAvailability(
            emotion=unavailable["emotion"],
            buying_intent=unavailable["buying_intent"],
            deal_signals=unavailable["deal_signals"],
        ),
    )

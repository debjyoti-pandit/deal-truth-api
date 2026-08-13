"""Evidence validator — the product invariant.

NO PROOF IN THE TRANSCRIPT, NO CLAIM IN THE REPORT.

Unsupported claims are dropped or marked UNCONFIRMED. They are never retried.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from uuid import UUID

from app.core.enums import EvidenceStatus, InsightType, SpeakerRole
from app.intelligence.domain import CandidateInsight, SegmentView, ValidatedInsight

logger = logging.getLogger(__name__)

CUSTOMER_ONLY_TYPES = {InsightType.CUSTOMER_FACT, InsightType.SENTIMENT_POINT}

ABSENCE_OK_TYPES = {InsightType.DEAL_RISK, InsightType.QUALIFICATION_SIGNAL}


def validate_candidates(
    candidates: Sequence[CandidateInsight],
    segments: Sequence[SegmentView],
    *,
    confidence_threshold: float,
) -> tuple[list[ValidatedInsight], list[dict[str, object]]]:
    by_id = {s.id: s for s in segments}
    seen: set[tuple[str, str, str]] = set()
    kept: list[ValidatedInsight] = []
    events: list[dict[str, object]] = []

    for cand in candidates:
        if cand.evidence_status == EvidenceStatus.ABSENCE_BASED:
            validated = ValidatedInsight(
                type=cand.type,
                title=cand.title,
                summary=cand.summary,
                severity=cand.severity,
                confidence=cand.confidence,
                evidence_status=EvidenceStatus.ABSENCE_BASED,
                segment_ids=[],
                quotes=[],
                audio_spans=[],
                payload={**cand.payload, "absence": True},
                relationship=cand.relationship,
            )
            kept.append(validated)
            continue

        if cand.evidence_status == EvidenceStatus.NON_FACTUAL:
            kept.append(
                ValidatedInsight(
                    type=cand.type,
                    title=cand.title,
                    summary=cand.summary,
                    severity=cand.severity,
                    confidence=cand.confidence,
                    evidence_status=EvidenceStatus.NON_FACTUAL,
                    segment_ids=[],
                    quotes=[],
                    audio_spans=[],
                    payload=cand.payload,
                    relationship=cand.relationship,
                )
            )
            continue

        if not cand.segment_ids:
            events.append(_event("EVIDENCE_UNSUPPORTED", cand, "no evidence for factual insight"))
            kept.append(_unconfirmed_or_drop(cand, "no evidence"))
            continue

        quotes: list[str] = []
        spans: list[tuple[int, int]] = []
        valid_ids: list[UUID] = []
        failed = False
        for sid in cand.segment_ids:
            seg = by_id.get(sid)
            if seg is None:
                events.append(_event("EVIDENCE_SEGMENT_MISSING", cand, f"missing segment {sid}"))
                failed = True
                break
            required = cand.required_role
            if required is None and cand.type in CUSTOMER_ONLY_TYPES:
                required = SpeakerRole.CUSTOMER
            if required is not None and seg.speaker_role != required:
                events.append(_event("EVIDENCE_WRONG_SPEAKER", cand, f"expected {required.value}"))
                failed = True
                break
            claimed_quote = cand.payload.get("quote")
            if isinstance(claimed_quote, str) and claimed_quote.strip():
                if claimed_quote.strip() not in seg.text:
                    events.append(_event("EVIDENCE_UNSUPPORTED", cand, "quote is not in transcript"))
                    failed = True
                    break
            quotes.append(seg.text)
            spans.append((seg.start_ms, seg.end_ms))
            valid_ids.append(sid)
            key = (cand.type.value, cand.title, str(sid))
            if key in seen:
                events.append(_event("EVIDENCE_UNSUPPORTED", cand, "duplicate insight/evidence"))
                failed = True
                break
            seen.add(key)

        if failed:
            kept.append(_unconfirmed_or_drop(cand, "validation failed"))
            continue

        status = cand.evidence_status
        if cand.confidence < confidence_threshold:
            status = EvidenceStatus.UNCONFIRMED
            events.append(_event("EVIDENCE_UNSUPPORTED", cand, "below confidence threshold"))

        payload = dict(cand.payload)
        payload.pop("quote", None)
        payload["quotes"] = quotes
        payload["audio_spans"] = [{"start_ms": a, "end_ms": b} for a, b in spans]
        kept.append(
            ValidatedInsight(
                type=cand.type,
                title=cand.title,
                summary=cand.summary,
                severity=cand.severity,
                confidence=cand.confidence,
                evidence_status=status,
                segment_ids=valid_ids,
                quotes=quotes,
                audio_spans=spans,
                payload=payload,
                relationship=cand.relationship,
            )
        )
    return kept, events


def _unconfirmed_or_drop(cand: CandidateInsight, reason: str) -> ValidatedInsight:
    return ValidatedInsight(
        type=cand.type,
        title=cand.title,
        summary=cand.summary,
        severity=cand.severity,
        confidence=cand.confidence,
        evidence_status=EvidenceStatus.UNCONFIRMED,
        segment_ids=[],
        quotes=[],
        audio_spans=[],
        payload={**cand.payload, "unconfirmed_reason": reason},
        dropped=True,
        drop_reason=reason,
    )


def _event(code: str, cand: CandidateInsight, message: str) -> dict[str, object]:
    logger.info("evidence_validation code=%s type=%s message=%s", code, cand.type.value, message)
    return {"error_code": code, "insight_type": cand.type.value, "title": cand.title, "message": message}


def shippable(insights: Sequence[ValidatedInsight]) -> list[ValidatedInsight]:
    """Insights that may appear as factual claims in the report."""
    return [i for i in insights if not i.dropped]

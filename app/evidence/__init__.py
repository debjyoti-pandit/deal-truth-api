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
            kept.append(
                _unconfirmed_or_drop(
                    cand,
                    "No segment supports this claim.",
                    "EVIDENCE_UNSUPPORTED",
                )
            )
            continue

        quotes: list[str] = []
        spans: list[tuple[int, int]] = []
        valid_ids: list[UUID] = []
        # The specific code and reason travel with the refusal, not just into the event
        # log — a refusal that cannot say why it was refused proves nothing.
        failure: tuple[str, str] | None = None
        for sid in cand.segment_ids:
            seg = by_id.get(sid)
            if seg is None:
                events.append(_event("EVIDENCE_SEGMENT_MISSING", cand, f"missing segment {sid}"))
                failure = ("EVIDENCE_SEGMENT_MISSING", f"Cited segment {sid} does not exist on this call.")
                break
            required = cand.required_role
            if required is None and cand.type in CUSTOMER_ONLY_TYPES:
                required = SpeakerRole.CUSTOMER
            if required is not None and seg.speaker_role != required:
                events.append(_event("EVIDENCE_WRONG_SPEAKER", cand, f"expected {required.value}"))
                failure = (
                    "EVIDENCE_WRONG_SPEAKER",
                    f"The cited segment was spoken by the {seg.speaker_role.value}, "
                    f"but this claim requires the {required.value}.",
                )
                break
            claimed_quote = cand.payload.get("quote")
            if isinstance(claimed_quote, str) and claimed_quote.strip():
                if claimed_quote.strip() not in seg.text:
                    events.append(_event("EVIDENCE_UNSUPPORTED", cand, "quote is not in transcript"))
                    failure = (
                        "EVIDENCE_UNSUPPORTED",
                        "The quoted words do not appear in the cited transcript segment.",
                    )
                    break
            quotes.append(seg.text)
            spans.append((seg.start_ms, seg.end_ms))
            valid_ids.append(sid)
            key = (cand.type.value, cand.title, str(sid))
            if key in seen:
                events.append(_event("EVIDENCE_UNSUPPORTED", cand, "duplicate insight/evidence"))
                failure = (
                    "EVIDENCE_UNSUPPORTED",
                    "This claim was already made against the same segment.",
                )
                break
            seen.add(key)

        if failure is not None:
            kept.append(_unconfirmed_or_drop(cand, failure[1], failure[0]))
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


def _unconfirmed_or_drop(cand: CandidateInsight, reason: str, error_code: str) -> ValidatedInsight:
    claimed_quote = cand.payload.get("quote")
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
        error_code=error_code,
        # What it tried to stand on. Kept for the refusal record only; segment_ids stays
        # empty so nothing downstream can mistake an attempt for evidence.
        attempted_segment_ids=list(cand.segment_ids),
        attempted_quote=claimed_quote.strip() if isinstance(claimed_quote, str) and claimed_quote.strip() else None,
    )


def _event(code: str, cand: CandidateInsight, message: str) -> dict[str, object]:
    logger.info("evidence_validation code=%s type=%s message=%s", code, cand.type.value, message)
    return {"error_code": code, "insight_type": cand.type.value, "title": cand.title, "message": message}


def shippable(insights: Sequence[ValidatedInsight]) -> list[ValidatedInsight]:
    """Insights that may appear as factual claims in the report."""
    return [i for i in insights if not i.dropped]

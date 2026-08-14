"""Evidence-safe follow-up email as sentence objects.

Every factual sentence in the draft is either backed by transcript segment ids or listed
in ``unsupported_claims`` with the reason it is not. The two lists are built together, so
a claim can never be shown without also being accounted for.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.core.enums import InsightType
from app.intelligence.domain import ValidatedInsight

COURTESY = "Thanks for the discussion today."
NEXT_MEETING_TEXT = "Looking forward to the next meeting we agreed on."
NO_MEETING_TEXT = "Happy to find a time that works if you would like to continue the conversation."

NO_EVIDENCE_REASON = "No transcript segment on this call supports this claim."
NO_NEXT_MEETING_REASON = "A next meeting was referred to on the call, but no customer segment commits to one."

# The only deterministic source of a contradicting segment. The reality-check extractor
# already recorded which customer segment it weighed the seller's claim against, and the
# evidence gate already proved that segment exists on this call. Nothing else is used:
# a missing pointer is correct, an inferred one would be a fabrication.
NEXT_MEETING_CONTRADICTION_CODE = "NO_EXPLICIT_COMMITMENT"


def build_follow_up(insights: Sequence[ValidatedInsight], *, customer_name: str | None) -> dict[str, object]:
    greeting = f"Hi {customer_name}," if customer_name else "Hi,"
    sentences: list[dict[str, object]] = [
        {"text": greeting, "evidence_segment_ids": [], "supported": False, "kind": "NON_FACTUAL"},
        {"text": COURTESY, "evidence_segment_ids": [], "supported": False, "kind": "NON_FACTUAL"},
    ]
    unsupported: list[dict[str, object]] = []

    def add_fact(
        text: str,
        evidence_segment_ids: list[str],
        *,
        reason: str,
        contradicting_segment_id: str | None = None,
    ) -> None:
        """Append a factual sentence, and record it when its evidence did not resolve."""
        supported = bool(evidence_segment_ids)
        sentences.append(
            {
                "text": text,
                "evidence_segment_ids": evidence_segment_ids,
                "supported": supported,
                "kind": "FACT",
            }
        )
        if not supported:
            unsupported.append(
                {
                    "text": text,
                    "reason": reason,
                    "contradicting_segment_id": contradicting_segment_id,
                }
            )

    for insight in insights:
        if insight.dropped or insight.type != InsightType.COMMITMENT:
            continue
        if insight.payload.get("side") != "seller":
            continue
        action = str(insight.payload.get("action") or insight.summary)
        due = insight.payload.get("due_text")
        text = f"As discussed, I will follow up on: {action}."
        if due:
            text = f"As discussed, I will follow up on: {action} ({due})."
        add_fact(text, [str(s) for s in insight.segment_ids], reason=NO_EVIDENCE_REASON)
    for insight in insights:
        if insight.dropped or insight.type != InsightType.CUSTOMER_FACT:
            continue
        if insight.payload.get("label") not in {"blocker", "budget", "requirement"}:
            continue
        quote = insight.quotes[0] if insight.quotes else insight.summary
        add_fact(
            f"You mentioned: {quote}",
            [str(s) for s in insight.segment_ids],
            reason=NO_EVIDENCE_REASON,
        )

    meetings = [
        i
        for i in insights
        if i.type == InsightType.COMMITMENT and i.payload.get("action") == "next meeting" and not i.dropped
    ]
    meeting_ids = [str(s) for i in meetings for s in i.segment_ids]
    contradiction = _contradicting_segment_id(insights, NEXT_MEETING_CONTRADICTION_CODE)
    if meeting_ids:
        add_fact(NEXT_MEETING_TEXT, meeting_ids, reason=NO_EVIDENCE_REASON)
    elif meetings or contradiction:
        # A next meeting was spoken about on the call, so the draft a rep would write says
        # so — but nothing in the transcript backs it. Show the sentence flagged, with the
        # segment that contradicts it, rather than quietly deleting the rep's own words.
        add_fact(
            NEXT_MEETING_TEXT,
            [],
            reason=NO_NEXT_MEETING_REASON,
            contradicting_segment_id=contradiction,
        )
    else:
        # Nothing was claimed, so there is nothing to refuse. An absence is not a claim.
        sentences.append(
            {
                "text": NO_MEETING_TEXT,
                "evidence_segment_ids": [],
                "supported": False,
                "kind": "NON_FACTUAL",
            }
        )
    return {
        "sentences": sentences,
        "unsupported_claims": unsupported,
        "body": "\n\n".join(str(s["text"]) for s in sentences),
    }


def _contradicting_segment_id(insights: Sequence[ValidatedInsight], reason_code: str) -> str | None:
    """The real customer segment a reality check weighed against a seller claim, or None.

    The id is returned only when it is among the segments the evidence gate resolved for
    that insight, so it is always a segment that exists on this call. When no reality
    check identifies one, the answer is None — never a guess.
    """
    for insight in insights:
        if insight.dropped or insight.type != InsightType.REALITY_CHECK:
            continue
        if insight.payload.get("reason_code") != reason_code:
            continue
        candidate = insight.payload.get("customer_segment_id")
        if not isinstance(candidate, str) or not candidate:
            continue
        if candidate in {str(s) for s in insight.segment_ids}:
            return candidate
    return None


def polish_or_fallback(
    original: dict[str, object],
    generated_text: str | None,
) -> dict[str, object]:
    """Optional polish must preserve sentence count and evidence mapping."""
    sentences = original.get("sentences")
    if not isinstance(sentences, list) or not generated_text:
        return original
    parts = [p.strip() for p in generated_text.split("\n") if p.strip()]
    if len(parts) != len(sentences):
        original = dict(original)
        original["polish"] = "fallback_sentence_count_mismatch"
        return original
    polished = []
    for src, text in zip(sentences, parts, strict=True):
        if not isinstance(src, dict):
            return original
        item = dict(src)
        item["text"] = text
        polished.append(item)
    return {
        "sentences": polished,
        "unsupported_claims": _reconcile_claims(polished, original.get("unsupported_claims")),
        "body": "\n\n".join(parts),
        "polish": "applied",
    }


def _reconcile_claims(sentences: list[dict[str, object]], previous: object) -> list[dict[str, object]]:
    """Keep ``unsupported_claims`` in step with the sentences after a rewrite.

    Polish rewrites sentence text one for one and never touches ``kind`` or ``supported``,
    so the k-th unsupported factual sentence is still the k-th claim. The reason and the
    contradiction pointer carry over; the text is retaken from the sentence itself so the
    two lists cannot drift apart.
    """
    prior = [c for c in previous if isinstance(c, dict)] if isinstance(previous, list) else []
    claims: list[dict[str, object]] = []
    for item in sentences:
        if item.get("kind") != "FACT" or item.get("supported"):
            continue
        source: dict[str, object] = prior[len(claims)] if len(claims) < len(prior) else {}
        claims.append(
            {
                "text": item.get("text"),
                "reason": source.get("reason") or NO_EVIDENCE_REASON,
                "contradicting_segment_id": source.get("contradicting_segment_id"),
            }
        )
    return claims

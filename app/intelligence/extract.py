"""Sales intelligence extractors. Quotes always come from transcript segments."""

from __future__ import annotations

from collections.abc import Sequence

from app.core.enums import EvidenceStatus, InsightType, SpeakerRole
from app.intelligence.domain import CandidateInsight, SegmentView
from app.providers.normalized import NormalizedRecap

LABEL_THRESHOLD = 0.55

CUSTOMER_TRUTH_MAP: tuple[tuple[str, str], ...] = (
    ("pain point", "pain"),
    ("feature requirement", "requirement"),
    ("integration requirement", "requirement"),
    ("positive buying signal", "buying_signal"),
    ("security blocker", "blocker"),
    ("budget blocker", "budget"),
    ("technical blocker", "blocker"),
    ("purchase timeline", "timeline"),
    ("competitor mention", "competition"),
    ("customer commitment", "commitment"),
)

OBJECTION_LABELS = (
    ("pricing objection", "pricing"),
    ("security blocker", "security"),
    ("technical blocker", "technical"),
    ("budget blocker", "budget"),
    ("purchase timeline", "timing"),
    ("integration requirement", "integration"),
    ("competitor mention", "competition"),
)

COACHING_PLAYBOOK: dict[str, str] = {
    "pricing": (
        "If quantified pain is available, reframe price against the cost of the current workflow. "
        "Do not invent company-specific ROI numbers."
    ),
    "security": (
        "Identify the security owner and the required documents (for example SOC2). Do not invent policy answers."
    ),
    "budget": "Confirm budget process and economic buyer. Do not claim approval that was not stated.",
    "technical": "List the technical questions to resolve on the next call. Do not promise unsupported capabilities.",
    "timing": "Ask for a concrete purchase or evaluation deadline. Do not invent a timeline.",
    "integration": "Confirm the systems named on the call and the owner of the integration review.",
    "competition": "Ask how they will compare vendors and which capabilities matter. Do not disparage competitors.",
}

MOMENT_KINDS: tuple[tuple[str, str], ...] = (
    ("pain point", "pain"),
    ("pricing objection", "pricing"),
    ("competitor mention", "competitor"),
    ("security blocker", "security"),
    ("positive buying signal", "buying_signal"),
    ("customer commitment", "commitment"),
    ("seller commitment", "next_step"),
    ("next meeting commitment", "next_step"),
    ("pricing objection", "objection"),
)


def _score(seg: SegmentView, label: str) -> float:
    return float(seg.labels.get(label, 0.0))


def customer_segments(segments: Sequence[SegmentView]) -> list[SegmentView]:
    return [s for s in segments if s.speaker_role == SpeakerRole.CUSTOMER]


def seller_segments(segments: Sequence[SegmentView]) -> list[SegmentView]:
    return [s for s in segments if s.speaker_role == SpeakerRole.SELLER]


def extract_customer_truth(segments: Sequence[SegmentView]) -> list[CandidateInsight]:
    out: list[CandidateInsight] = []
    for seg in customer_segments(segments):
        for label, category in CUSTOMER_TRUTH_MAP:
            score = _score(seg, label)
            if score < LABEL_THRESHOLD:
                continue
            out.append(
                CandidateInsight(
                    type=InsightType.CUSTOMER_FACT,
                    title=f"Customer {category.replace('_', ' ')}",
                    summary=seg.text,
                    confidence=score,
                    segment_ids=[seg.id],
                    required_role=SpeakerRole.CUSTOMER,
                    payload={"label": category, "ml_label": label},
                )
            )
    return out


def extract_sentiment(segments: Sequence[SegmentView]) -> list[CandidateInsight]:
    out: list[CandidateInsight] = []
    for seg in customer_segments(segments):
        grouped = {
            "positive": max(0.0, seg.valence) if seg.valence > 0 else 0.0,
            "negative": max(0.0, -seg.valence) if seg.valence < 0 else 0.0,
            "neutral": 1.0 - min(1.0, abs(seg.valence)),
            "valence": seg.valence,
            "raw": seg.emotions,
        }
        out.append(
            CandidateInsight(
                type=InsightType.SENTIMENT_POINT,
                title="Customer emotion",
                summary=seg.text,
                confidence=max(seg.emotions.values()) if seg.emotions else 0.5,
                segment_ids=[seg.id],
                required_role=SpeakerRole.CUSTOMER,
                payload={"grouped": grouped, "timestamp_ms": seg.start_ms},
            )
        )
    return out


def extract_buying_intent(segments: Sequence[SegmentView]) -> list[CandidateInsight]:
    cust = customer_segments(segments)
    dimensions = {
        "pain_identified": _best(cust, "pain point"),
        "business_impact_identified": _quantified_pain(cust),
        "timeline_identified": _best(cust, "purchase timeline"),
        "economic_buyer_identified": _best(cust, "economic buyer identified"),
        "decision_maker_identified": _best(cust, "decision maker identified"),
        "next_meeting_committed": _best(cust, "next meeting commitment"),
        "competitor_active": _best(cust, "competitor mention"),
        "blocker_active": _max_label(cust, ("security blocker", "budget blocker", "technical blocker")),
    }
    out: list[CandidateInsight] = []
    for name, hit in dimensions.items():
        seg, score = hit
        present = score >= LABEL_THRESHOLD
        out.append(
            CandidateInsight(
                type=InsightType.QUALIFICATION_SIGNAL,
                title=name,
                summary=seg.text if seg and present else f"{name} not supported by transcript",
                confidence=score,
                evidence_status=EvidenceStatus.SUPPORTED if present and seg else EvidenceStatus.ABSENCE_BASED,
                segment_ids=[seg.id] if seg and present else [],
                required_role=SpeakerRole.CUSTOMER if present else None,
                payload={"dimension": name, "present": present},
            )
        )
    return out


def extract_objections(segments: Sequence[SegmentView]) -> list[CandidateInsight]:
    out: list[CandidateInsight] = []
    for seg in customer_segments(segments):
        for label, kind in OBJECTION_LABELS:
            score = _score(seg, label)
            if score < LABEL_THRESHOLD:
                continue
            out.append(
                CandidateInsight(
                    type=InsightType.OBJECTION,
                    title=f"{kind.title()} objection",
                    summary=seg.text,
                    severity="high" if score >= 0.8 else "medium",
                    confidence=score,
                    segment_ids=[seg.id],
                    required_role=SpeakerRole.CUSTOMER,
                    payload={"kind": kind},
                )
            )
            coaching = COACHING_PLAYBOOK.get(kind)
            if coaching:
                out.append(
                    CandidateInsight(
                        type=InsightType.COACHING,
                        title=f"Handle {kind} objection",
                        summary=coaching,
                        confidence=score,
                        segment_ids=[seg.id],
                        required_role=SpeakerRole.CUSTOMER,
                        payload={"kind": kind, "playbook": True},
                    )
                )
    return out


def extract_commitments(segments: Sequence[SegmentView], recap: NormalizedRecap | None) -> list[CandidateInsight]:
    out: list[CandidateInsight] = []
    for seg in segments:
        if _score(seg, "seller commitment") >= LABEL_THRESHOLD and seg.speaker_role == SpeakerRole.SELLER:
            out.append(
                CandidateInsight(
                    type=InsightType.COMMITMENT,
                    title="Seller commitment",
                    summary=seg.text,
                    confidence=_score(seg, "seller commitment"),
                    segment_ids=[seg.id],
                    required_role=SpeakerRole.SELLER,
                    payload={"side": "seller", "action": seg.text, "due_text": _due_text(seg.text)},
                )
            )
        if _score(seg, "customer commitment") >= LABEL_THRESHOLD and seg.speaker_role == SpeakerRole.CUSTOMER:
            out.append(
                CandidateInsight(
                    type=InsightType.COMMITMENT,
                    title="Customer commitment",
                    summary=seg.text,
                    confidence=_score(seg, "customer commitment"),
                    segment_ids=[seg.id],
                    required_role=SpeakerRole.CUSTOMER,
                    payload={"side": "customer", "action": seg.text, "due_text": _due_text(seg.text)},
                )
            )
        if _score(seg, "next meeting commitment") >= LABEL_THRESHOLD and seg.speaker_role == SpeakerRole.CUSTOMER:
            out.append(
                CandidateInsight(
                    type=InsightType.COMMITMENT,
                    title="Next meeting commitment",
                    summary=seg.text,
                    confidence=_score(seg, "next meeting commitment"),
                    segment_ids=[seg.id],
                    required_role=SpeakerRole.CUSTOMER,
                    payload={"side": "customer", "action": "next meeting", "due_text": _due_text(seg.text)},
                )
            )
    if recap:
        for item in recap.action_items:
            match = _best_text_match(segments, item.text)
            if match is None:
                continue
            seg, _ = match
            side = item.side or ("seller" if seg.speaker_role == SpeakerRole.SELLER else "customer")
            out.append(
                CandidateInsight(
                    type=InsightType.COMMITMENT,
                    title="Recap action item",
                    summary=item.text,
                    confidence=0.7,
                    segment_ids=[seg.id],
                    payload={
                        "side": side,
                        "owner": item.owner,
                        "action": item.text,
                        "due_text": item.due_text,
                        "source": "recap",
                    },
                )
            )
    return out


def extract_reality_checks(segments: Sequence[SegmentView]) -> list[CandidateInsight]:
    seller = seller_segments(segments)
    customer = customer_segments(segments)
    out: list[CandidateInsight] = []

    def add(
        code: str, title: str, seller_seg: SegmentView | None, customer_seg: SegmentView | None, severity: str
    ) -> None:
        ids = []
        if seller_seg:
            ids.append(seller_seg.id)
        if customer_seg:
            ids.append(customer_seg.id)
        if not customer_seg:
            return
        out.append(
            CandidateInsight(
                type=InsightType.REALITY_CHECK,
                title=title,
                summary=f"{code}: seller statement vs customer evidence",
                severity=severity,
                confidence=0.8,
                segment_ids=ids,
                payload={
                    "reason_code": code,
                    "seller_segment_id": str(seller_seg.id) if seller_seg else None,
                    "customer_segment_id": str(customer_seg.id),
                },
            )
        )

    seller_confident = _best(seller, "positive buying signal")
    customer_blocker = _max_label(customer, ("security blocker", "budget blocker", "technical blocker"))
    if seller_confident[1] >= LABEL_THRESHOLD and customer_blocker[1] >= LABEL_THRESHOLD:
        add(
            "OVERSTATED_INTENT",
            "Seller confidence vs customer blocker",
            seller_confident[0],
            customer_blocker[0],
            "high",
        )

    seller_meeting = next(
        (
            s
            for s in seller
            if "next week" in s.text.lower() or "follow-up" in s.text.lower() or "next meeting" in s.text.lower()
        ),
        None,
    )
    customer_meeting = _best(customer, "next meeting commitment")
    if seller_meeting and customer_meeting[1] < LABEL_THRESHOLD:
        cust_weak = next(
            (s for s in customer if "get back" in s.text.lower() or "send me" in s.text.lower()),
            customer[0] if customer else None,
        )
        add(
            "NO_EXPLICIT_COMMITMENT",
            "Seller claimed a next meeting the customer did not commit to",
            seller_meeting,
            cust_weak,
            "high",
        )

    seller_intent = _best(seller, "positive buying signal")
    competitor = _best(customer, "competitor mention")
    if seller_intent[1] >= LABEL_THRESHOLD and competitor[1] >= LABEL_THRESHOLD:
        add(
            "COMPETITOR_VS_INTENT",
            "Seller described strong intent while customer is evaluating a competitor",
            seller_intent[0],
            competitor[0],
            "medium",
        )

    seller_budget = next((s for s in seller if "budget" in s.text.lower() and "approv" in s.text.lower()), None)
    customer_budget = _best(customer, "budget blocker")
    if seller_budget and customer_budget[1] >= LABEL_THRESHOLD:
        add(
            "BUDGET_MISMATCH",
            "Seller claimed budget approval while customer signaled a budget blocker",
            seller_budget,
            customer_budget[0],
            "high",
        )

    return out


def extract_deal_killers(segments: Sequence[SegmentView], intent: Sequence[CandidateInsight]) -> list[CandidateInsight]:
    cust = customer_segments(segments)
    out: list[CandidateInsight] = []

    def supported(label: str, title: str, kind: str) -> None:
        seg, score = _best(cust, label)
        if seg and score >= LABEL_THRESHOLD:
            out.append(
                CandidateInsight(
                    type=InsightType.DEAL_RISK,
                    title=title,
                    summary=seg.text,
                    severity="high",
                    confidence=score,
                    evidence_status=EvidenceStatus.SUPPORTED,
                    segment_ids=[seg.id],
                    required_role=SpeakerRole.CUSTOMER,
                    payload={"kind": kind},
                )
            )

    supported("security blocker", "Security review required", "security_blocker")
    supported("budget blocker", "Budget blocker", "budget_blocker")
    supported("competitor mention", "Active competitor", "active_competitor")
    supported("technical blocker", "Technical blocker", "technical_blocker")
    rejection = _best(cust, "negative buying signal")
    if rejection[0] and rejection[1] >= 0.75:
        out.append(
            CandidateInsight(
                type=InsightType.DEAL_RISK,
                title="Explicit rejection",
                summary=rejection[0].text,
                severity="high",
                confidence=rejection[1],
                segment_ids=[rejection[0].id],
                required_role=SpeakerRole.CUSTOMER,
                payload={"kind": "explicit_rejection"},
            )
        )

    present = {c.payload.get("dimension"): c.payload.get("present") for c in intent}
    absences = [
        ("timeline_identified", "No purchase timeline", "no_timeline"),
        ("economic_buyer_identified", "No economic buyer", "no_economic_buyer"),
        ("next_meeting_committed", "No next meeting", "no_next_meeting"),
    ]
    for dim, title, kind in absences:
        if not present.get(dim):
            out.append(
                CandidateInsight(
                    type=InsightType.DEAL_RISK,
                    title=title,
                    summary=f"{title} — no supporting customer evidence in the transcript.",
                    severity="medium",
                    confidence=1.0,
                    evidence_status=EvidenceStatus.ABSENCE_BASED,
                    segment_ids=[],
                    payload={"kind": kind, "absence": True},
                )
            )
    return out


def extract_competitors(
    segments: Sequence[SegmentView],
    tracked: Sequence[tuple[str, list[str]]],
) -> list[CandidateInsight]:
    out: list[CandidateInsight] = []
    for seg in customer_segments(segments):
        mentioned: list[str] = []
        hay = seg.text.lower()
        for name, aliases in tracked:
            for needle in [name, *aliases]:
                if needle.lower() in hay:
                    mentioned.append(name)
                    break
        score = _score(seg, "competitor mention")
        if not mentioned and score < LABEL_THRESHOLD:
            continue
        name = mentioned[0] if mentioned else "unnamed competitor"
        position = "evaluating"
        if _score(seg, "competitor preference") >= LABEL_THRESHOLD:
            position = "preference"
        out.append(
            CandidateInsight(
                type=InsightType.COMPETITOR,
                title=name,
                summary=seg.text,
                confidence=max(score, 0.7 if mentioned else 0.0),
                segment_ids=[seg.id],
                required_role=SpeakerRole.CUSTOMER,
                payload={"competitor": name, "position": position, "context": seg.text},
            )
        )
    return out


def extract_moments(segments: Sequence[SegmentView]) -> list[CandidateInsight]:
    out: list[CandidateInsight] = []
    for seg in segments:
        for label, kind in MOMENT_KINDS:
            score = _score(seg, label)
            if score < LABEL_THRESHOLD:
                continue
            out.append(
                CandidateInsight(
                    type=InsightType.CALL_MOMENT,
                    title=kind.replace("_", " ").title(),
                    summary=seg.text,
                    confidence=score,
                    segment_ids=[seg.id],
                    payload={"kind": kind, "timestamp_ms": seg.start_ms},
                )
            )
    return out


def _best(segments: Sequence[SegmentView], label: str) -> tuple[SegmentView | None, float]:
    best_seg: SegmentView | None = None
    best_score = 0.0
    for seg in segments:
        score = _score(seg, label)
        if score > best_score:
            best_seg, best_score = seg, score
    return best_seg, best_score


def _max_label(segments: Sequence[SegmentView], labels: tuple[str, ...]) -> tuple[SegmentView | None, float]:
    best_seg: SegmentView | None = None
    best_score = 0.0
    for label in labels:
        seg, score = _best(segments, label)
        if score > best_score:
            best_seg, best_score = seg, score
    return best_seg, best_score


def _quantified_pain(segments: Sequence[SegmentView]) -> tuple[SegmentView | None, float]:
    seg, score = _best(segments, "pain point")
    if seg is None:
        return None, 0.0
    text = seg.text.lower()
    quantified = any(token in text for token in ("hour", "hours", "$", "percent", "%", "week", "cost"))
    return (seg, score if quantified else 0.0)


def _due_text(text: str) -> str | None:
    lowered = text.lower()
    for token in ("friday", "tomorrow", "next week", "monday", "tuesday", "eod", "end of day"):
        if token in lowered:
            return token
    return None


def _best_text_match(segments: Sequence[SegmentView], text: str) -> tuple[SegmentView, float] | None:
    needle = text.lower().strip()
    if not needle:
        return None
    best: tuple[SegmentView, float] | None = None
    for seg in segments:
        hay = seg.text.lower()
        if needle in hay or hay in needle:
            score = min(len(needle), len(hay)) / max(len(needle), len(hay), 1)
            if best is None or score > best[1]:
                best = (seg, score)
    return best

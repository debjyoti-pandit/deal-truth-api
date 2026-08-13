"""Deterministic templates for battlecard and manager brief. Generation may polish wording only."""

from __future__ import annotations

from collections.abc import Sequence

from app.core.enums import EvidenceStatus, InsightType
from app.intelligence.domain import ValidatedInsight
from app.providers.normalized import NormalizedRecap


def build_battlecard(insights: Sequence[ValidatedInsight], recap: NormalizedRecap | None) -> dict[str, object]:
    objections = [i for i in insights if i.type == InsightType.OBJECTION and not i.dropped]
    risks = [i for i in insights if i.type == InsightType.DEAL_RISK and not i.dropped]
    facts = [i for i in insights if i.type == InsightType.CUSTOMER_FACT and not i.dropped]
    missing = [
        i.title.replace("_", " ")
        for i in insights
        if i.type == InsightType.QUALIFICATION_SIGNAL and i.evidence_status == EvidenceStatus.ABSENCE_BASED
    ]
    primary = "Advance the deal using only facts the customer stated."
    if any(i.payload.get("kind") == "security_blocker" for i in risks):
        primary = "Get the security-review process and owner confirmed."
    elif any(i.payload.get("kind") == "no_next_meeting" for i in risks):
        primary = "Secure an explicit next-meeting commitment."
    questions = [
        "Who owns the next approval step?",
        "What documents or access do you need from us?",
        "When should we reconvene with those owners?",
    ]
    if any(i.payload.get("kind") == "security_blocker" for i in risks):
        questions = [
            "Who owns the security approval?",
            "What documentation do they require?",
            "Can we schedule the technical or security review now?",
        ]
    objection = objections[0].title if objections else "None observed with evidence"
    send = [
        i.payload.get("action")
        for i in insights
        if i.type == InsightType.COMMITMENT and i.payload.get("side") == "seller" and not i.dropped
    ]
    warning = "Do not claim unsupported facts. Every statement in the next call must map to transcript evidence."
    return {
        "primary_goal": primary,
        "questions_to_ask": questions,
        "objection_to_prepare_for": objection,
        "documents_to_send": [s for s in send if isinstance(s, str)],
        "missing_qualification_fields": missing,
        "warning": warning,
        "headline": recap.headline if recap else None,
        "customer_facts": [f.title for f in facts[:5]],
    }


def build_manager_brief(insights: Sequence[ValidatedInsight], recap: NormalizedRecap | None) -> dict[str, object]:
    why_buy = [
        i.summary
        for i in insights
        if i.type == InsightType.CUSTOMER_FACT and i.payload.get("label") in {"pain", "buying_signal"} and not i.dropped
    ]
    why_not = [i.title for i in insights if i.type in {InsightType.OBJECTION, InsightType.DEAL_RISK} and not i.dropped]
    intent = {i.title: bool(i.payload.get("present")) for i in insights if i.type == InsightType.QUALIFICATION_SIGNAL}
    competition = [i.title for i in insights if i.type == InsightType.COMPETITOR and not i.dropped]
    risks = [i for i in insights if i.type == InsightType.DEAL_RISK and not i.dropped]
    biggest = risks[0].title if risks else "None evidenced"
    commitments = [
        i
        for i in insights
        if i.type == InsightType.COMMITMENT and i.payload.get("side") == "customer" and not i.dropped
    ]
    next_move = "Follow the next-call battlecard. Do not invent commitments."
    if any(i.payload.get("kind") == "security_blocker" for i in risks):
        next_move = "Get the security lead into the next call."
    return {
        "why_they_buy": why_buy,
        "why_they_do_not": why_not,
        "buying_intent": intent,
        "competition": competition,
        "biggest_risk": biggest,
        "customer_commitment": "present" if commitments else "weak",
        "recommended_next_move": next_move,
        "headline": recap.headline if recap else None,
        "tldr": recap.tldr if recap else None,
    }

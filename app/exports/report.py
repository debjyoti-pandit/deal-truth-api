"""JSON and Markdown report builders. Quotes come only from stored transcript text."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.core.enums import InsightType
from app.intelligence.domain import ValidatedInsight
from app.intelligence.email import build_follow_up
from app.intelligence.templates import build_battlecard, build_manager_brief
from app.models.call import Call
from app.providers.normalized import NormalizedRecap

# Every report key whose value is a list of insight projections. The report buckets one
# insight into exactly one of these, so this is the whole surface a reader has to walk.
INSIGHT_SECTIONS: tuple[str, ...] = (
    "customer_truth",
    "buying_intent",
    "objections",
    "coaching",
    "commitments",
    "reality_checks",
    "deal_killers",
    "competitors",
    "moments",
    "sentiment_timeline",
)

# (type, title, summary, segment_ids): the content a persisted Insight row was written
# from, and so the only thing a report insight and its row provably share.
InsightIdentity = tuple[str, str, str, tuple[str, ...]]


def build_report(
    call: Call,
    recap: NormalizedRecap | None,
    metrics: dict[str, Any],
    insights: list[ValidatedInsight],
    warnings: list[str],
    *,
    refused_count: int = 0,
) -> dict[str, Any]:
    def by_type(t: InsightType) -> list[dict[str, Any]]:
        return [_insight_dict(i) for i in insights if i.type == t]

    return {
        "call_id": str(call.id),
        # What the gate let through, and what it turned away. Both at the top level so a
        # brief can state them without a second request. Full refusals: GET .../refusals.
        "shipped_count": len(insights),
        "refused_count": refused_count,
        "public_call_id": call.public_call_id,
        "title": call.title,
        "customer_name": call.customer_name,
        "rep_name": call.rep_name,
        "status": call.status.value if hasattr(call.status, "value") else call.status,
        "duration_ms": call.duration_ms,
        "warnings": warnings,
        "headline": recap.headline if recap else None,
        "tldr": recap.tldr if recap else None,
        "summary": recap.summary if recap else None,
        "decisions": recap.decisions if recap else [],
        "action_items": [i.model_dump() for i in recap.action_items] if recap else [],
        "next_steps": [i.model_dump() for i in recap.next_steps] if recap else [],
        "metrics": metrics,
        "customer_truth": by_type(InsightType.CUSTOMER_FACT),
        "buying_intent": by_type(InsightType.QUALIFICATION_SIGNAL),
        "objections": by_type(InsightType.OBJECTION),
        "coaching": by_type(InsightType.COACHING),
        "commitments": by_type(InsightType.COMMITMENT),
        "reality_checks": by_type(InsightType.REALITY_CHECK),
        "deal_killers": by_type(InsightType.DEAL_RISK),
        "competitors": by_type(InsightType.COMPETITOR),
        "moments": by_type(InsightType.CALL_MOMENT),
        "sentiment_timeline": by_type(InsightType.SENTIMENT_POINT),
        "battlecard": build_battlecard(insights, recap),
        "manager_brief": build_manager_brief(insights, recap),
        "follow_up": build_follow_up(insights, customer_name=call.customer_name),
        "invariant": "NO PROOF IN THE TRANSCRIPT, NO CLAIM IN THE REPORT.",
    }


def _insight_dict(item: ValidatedInsight) -> dict[str, Any]:
    return {
        "type": item.type.value,
        "title": item.title,
        "summary": item.summary,
        "severity": item.severity,
        "confidence": item.confidence,
        "evidence_status": item.evidence_status.value,
        "segment_ids": [str(s) for s in item.segment_ids],
        "quotes": item.quotes,
        "audio_spans": [{"start_ms": a, "end_ms": b} for a, b in item.audio_spans],
        "payload": item.payload,
    }


def insight_identity(item: Mapping[str, Any]) -> InsightIdentity:
    """Key a report insight (or an Insight row projected the same way) by its content.

    build_report runs on ValidatedInsight objects, which carry no database id, so the
    report artifact cannot name the Insight row it became. Content is what the two share:
    persist_insights writes type/title/summary straight through, and the evidence links in
    sort_order are exactly ValidatedInsight.segment_ids.
    """
    raw_ids = item.get("segment_ids") or []
    if not isinstance(raw_ids, list):
        raw_ids = []
    return (
        str(item.get("type") or ""),
        str(item.get("title") or ""),
        str(item.get("summary") or ""),
        tuple(str(s) for s in raw_ids),
    )


def attach_insight_ids(
    report: dict[str, Any],
    ids_by_identity: Mapping[InsightIdentity, Sequence[str]],
) -> dict[str, Any]:
    """Stamp each report insight with the persisted Insight.id it was built from.

    Read-time, not build-time: the ids do not exist in ValidatedInsight, and doing this on
    read also repairs report artifacts stored before the id existed. Identical insights are
    paired first-come-first-served, and an insight with no matching row gets id None rather
    than an invented one — a fabricated id would point the UI at an insight that is not there.
    """
    pending = {key: list(values) for key, values in ids_by_identity.items()}
    for section in INSIGHT_SECTIONS:
        items = report.get(section)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            queue = pending.get(insight_identity(item)) or []
            item["id"] = queue.pop(0) if queue else None
    return report


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# {report.get('title') or report.get('public_call_id')}",
        "",
        f"**Customer:** {report.get('customer_name') or '—'}",
        f"**Headline:** {report.get('headline') or '—'}",
        "",
        "## Summary",
        str(report.get("summary") or report.get("tldr") or "—"),
        "",
        "## Customer Truth",
    ]
    for item in report.get("customer_truth") or []:
        quote = (item.get("quotes") or ["—"])[0]
        lines.append(f"- **{item.get('title')}**: {quote}")
    lines += ["", "## Reality Check"]
    for item in report.get("reality_checks") or []:
        lines.append(f"- {item.get('title')}: {item.get('summary')}")
    lines += ["", "## Deal Killers"]
    for item in report.get("deal_killers") or []:
        lines.append(f"- ({item.get('evidence_status')}) {item.get('title')}")
    lines += ["", "## Next Call Battlecard", str((report.get("battlecard") or {}).get("primary_goal"))]
    lines += ["", "> NO PROOF IN THE TRANSCRIPT, NO CLAIM IN THE REPORT."]
    return "\n".join(lines) + "\n"

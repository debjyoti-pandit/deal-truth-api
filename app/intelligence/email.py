"""Evidence-safe follow-up email as sentence objects."""

from __future__ import annotations

from collections.abc import Sequence

from app.core.enums import InsightType
from app.intelligence.domain import ValidatedInsight

COURTESY = "Thanks for the discussion today."


def build_follow_up(insights: Sequence[ValidatedInsight], *, customer_name: str | None) -> dict[str, object]:
    greeting = f"Hi {customer_name}," if customer_name else "Hi,"
    sentences: list[dict[str, object]] = [
        {"text": greeting, "evidence_segment_ids": [], "supported": False, "kind": "NON_FACTUAL"},
        {"text": COURTESY, "evidence_segment_ids": [], "supported": False, "kind": "NON_FACTUAL"},
    ]
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
        sentences.append(
            {
                "text": text,
                "evidence_segment_ids": [str(s) for s in insight.segment_ids],
                "supported": True,
                "kind": "FACT",
            }
        )
    for insight in insights:
        if insight.dropped or insight.type != InsightType.CUSTOMER_FACT:
            continue
        if insight.payload.get("label") not in {"blocker", "budget", "requirement"}:
            continue
        quote = insight.quotes[0] if insight.quotes else insight.summary
        sentences.append(
            {
                "text": f"You mentioned: {quote}",
                "evidence_segment_ids": [str(s) for s in insight.segment_ids],
                "supported": True,
                "kind": "FACT",
            }
        )
    next_meeting = any(
        i.type == InsightType.COMMITMENT and i.payload.get("action") == "next meeting" and not i.dropped
        for i in insights
    )
    if next_meeting:
        ids = [
            str(s)
            for i in insights
            if i.type == InsightType.COMMITMENT and i.payload.get("action") == "next meeting"
            for s in i.segment_ids
        ]
        sentences.append(
            {
                "text": "Looking forward to the next meeting we agreed on.",
                "evidence_segment_ids": ids,
                "supported": True,
                "kind": "FACT",
            }
        )
    else:
        sentences.append(
            {
                "text": "Happy to find a time that works if you would like to continue the conversation.",
                "evidence_segment_ids": [],
                "supported": False,
                "kind": "NON_FACTUAL",
            }
        )
    return {
        "sentences": sentences,
        "unsupported_claims": [],
        "body": "\n\n".join(str(s["text"]) for s in sentences),
    }


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
    return {"sentences": polished, "unsupported_claims": [], "body": "\n\n".join(parts), "polish": "applied"}

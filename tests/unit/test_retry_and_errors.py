from uuid import uuid4

from app.core.enums import EvidenceStatus, InsightType
from app.intelligence.domain import ValidatedInsight
from app.intelligence.email import build_follow_up, polish_or_fallback


def test_safe_email_marks_courtesy_non_factual_and_facts_supported() -> None:
    commitment = ValidatedInsight(
        type=InsightType.COMMITMENT,
        title="Seller commitment",
        summary="I will send the SOC2 report by Friday.",
        confidence=0.9,
        evidence_status=EvidenceStatus.SUPPORTED,
        segment_ids=[uuid4()],
        quotes=["I will send the SOC2 report by Friday."],
        audio_spans=[(1000, 2000)],
        payload={"side": "seller", "action": "I will send the SOC2 report by Friday.", "due_text": "friday"},
    )
    email = build_follow_up([commitment], customer_name="Sarah")
    sentences = email["sentences"]
    assert isinstance(sentences, list)
    kinds = [s["kind"] for s in sentences if isinstance(s, dict)]
    assert "NON_FACTUAL" in kinds
    facts = [s for s in sentences if isinstance(s, dict) and s["kind"] == "FACT"]
    assert facts
    assert all(s["supported"] and s["evidence_segment_ids"] for s in facts)


def test_polish_falls_back_on_sentence_count_change() -> None:
    original: dict[str, object] = {
        "sentences": [
            {"text": "Hi,", "evidence_segment_ids": [], "supported": False, "kind": "NON_FACTUAL"},
            {"text": "Fact.", "evidence_segment_ids": ["abc"], "supported": True, "kind": "FACT"},
        ]
    }
    result = polish_or_fallback(original, "one line only")
    assert result.get("polish") == "fallback_sentence_count_mismatch"
    assert result["sentences"] == original["sentences"]

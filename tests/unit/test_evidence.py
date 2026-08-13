from uuid import uuid4

from app.core.enums import EvidenceStatus, InsightType, SpeakerRole
from app.evidence import validate_candidates
from app.intelligence.domain import CandidateInsight, SegmentView


def _seg(*, role: SpeakerRole, text: str) -> SegmentView:
    return SegmentView(
        id=uuid4(),
        provider_segment_id="1",
        speaker_role=role,
        start_ms=1000,
        end_ms=2000,
        text=text,
        sequence_number=0,
    )


def test_customer_truth_rejects_seller_segment() -> None:
    seller = _seg(role=SpeakerRole.SELLER, text="They are ready to buy.")
    cand = CandidateInsight(
        type=InsightType.CUSTOMER_FACT,
        title="Buying signal",
        summary=seller.text,
        confidence=0.9,
        segment_ids=[seller.id],
        required_role=SpeakerRole.CUSTOMER,
    )
    kept, events = validate_candidates([cand], [seller], confidence_threshold=0.5)
    assert any(e["error_code"] == "EVIDENCE_WRONG_SPEAKER" for e in events)
    assert kept[0].dropped or kept[0].evidence_status == EvidenceStatus.UNCONFIRMED


def test_no_hallucinated_quote() -> None:
    customer = _seg(role=SpeakerRole.CUSTOMER, text="We need security approval.")
    cand = CandidateInsight(
        type=InsightType.CUSTOMER_FACT,
        title="Blocker",
        summary="hallucinated",
        confidence=0.9,
        segment_ids=[customer.id],
        required_role=SpeakerRole.CUSTOMER,
        payload={"quote": "We will sign tomorrow."},
    )
    kept, events = validate_candidates([cand], [customer], confidence_threshold=0.5)
    assert any(e["error_code"] == "EVIDENCE_UNSUPPORTED" for e in events)
    assert "We will sign tomorrow." not in (kept[0].quotes or [])


def test_missing_segment() -> None:
    customer = _seg(role=SpeakerRole.CUSTOMER, text="hello")
    cand = CandidateInsight(
        type=InsightType.OBJECTION,
        title="Pricing",
        summary="x",
        confidence=0.9,
        segment_ids=[uuid4()],
        required_role=SpeakerRole.CUSTOMER,
    )
    kept, events = validate_candidates([cand], [customer], confidence_threshold=0.5)
    assert any(e["error_code"] == "EVIDENCE_SEGMENT_MISSING" for e in events)


def test_absence_based_allowed_without_segments() -> None:
    cand = CandidateInsight(
        type=InsightType.DEAL_RISK,
        title="No timeline",
        summary="No purchase timeline",
        confidence=1.0,
        evidence_status=EvidenceStatus.ABSENCE_BASED,
        payload={"kind": "no_timeline"},
    )
    kept, events = validate_candidates([cand], [], confidence_threshold=0.5)
    assert kept[0].evidence_status == EvidenceStatus.ABSENCE_BASED
    assert kept[0].segment_ids == []
    assert not kept[0].dropped


def test_quote_loaded_from_transcript() -> None:
    customer = _seg(role=SpeakerRole.CUSTOMER, text="We're losing around 6 hours every week.")
    cand = CandidateInsight(
        type=InsightType.CUSTOMER_FACT,
        title="Pain",
        summary="pain",
        confidence=0.9,
        segment_ids=[customer.id],
        required_role=SpeakerRole.CUSTOMER,
    )
    kept, _ = validate_candidates([cand], [customer], confidence_threshold=0.5)
    assert kept[0].quotes == [customer.text]
    assert kept[0].audio_spans == [(1000, 2000)]

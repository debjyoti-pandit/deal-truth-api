from uuid import uuid4

from app.core.enums import SpeakerRole
from app.intelligence.domain import SegmentView
from app.intelligence.extract import extract_reality_checks


def test_overstated_intent_rule() -> None:
    seller = SegmentView(
        id=uuid4(),
        provider_segment_id="s",
        speaker_role=SpeakerRole.SELLER,
        start_ms=0,
        end_ms=3000,
        text="They are ready to purchase this month.",
        sequence_number=0,
        labels={"positive buying signal": 0.9},
    )
    customer = SegmentView(
        id=uuid4(),
        provider_segment_id="c",
        speaker_role=SpeakerRole.CUSTOMER,
        start_ms=4000,
        end_ms=8000,
        text="Our security team has to approve any new vendor.",
        sequence_number=1,
        labels={"security blocker": 0.95},
    )
    checks = extract_reality_checks([seller, customer])
    codes = {c.payload.get("reason_code") for c in checks}
    assert "OVERSTATED_INTENT" in codes


def test_no_meeting_commitment_rule() -> None:
    seller = SegmentView(
        id=uuid4(),
        provider_segment_id="s",
        speaker_role=SpeakerRole.SELLER,
        start_ms=0,
        end_ms=3000,
        text="They agreed to a follow-up next week.",
        sequence_number=0,
        labels={},
    )
    customer = SegmentView(
        id=uuid4(),
        provider_segment_id="c",
        speaker_role=SpeakerRole.CUSTOMER,
        start_ms=4000,
        end_ms=8000,
        text="Send me something and I'll get back to you.",
        sequence_number=1,
        labels={"next meeting commitment": 0.1},
    )
    checks = extract_reality_checks([seller, customer])
    codes = {c.payload.get("reason_code") for c in checks}
    assert "NO_EXPLICIT_COMMITMENT" in codes

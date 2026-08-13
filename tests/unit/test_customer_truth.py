from uuid import uuid4

from app.core.enums import SpeakerRole
from app.intelligence.domain import SegmentView
from app.intelligence.extract import (
    extract_customer_truth,
)


def test_customer_truth_skips_seller_text() -> None:
    seller = SegmentView(
        id=uuid4(),
        provider_segment_id="s",
        speaker_role=SpeakerRole.SELLER,
        start_ms=0,
        end_ms=2000,
        text="We're losing around 6 hours every week.",
        sequence_number=0,
        labels={"pain point": 0.99},
    )
    facts = extract_customer_truth([seller])
    assert facts == []

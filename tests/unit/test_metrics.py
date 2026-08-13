from __future__ import annotations

from uuid import uuid4

from app.core.enums import SpeakerRole
from app.intelligence.domain import SegmentView
from app.intelligence.metrics import compute_metrics


def _seg(i: int, role: SpeakerRole, start: int, end: int, text: str) -> SegmentView:
    return SegmentView(
        id=uuid4(),
        provider_segment_id=str(i),
        speaker_id=uuid4() if role == SpeakerRole.SELLER else uuid4(),
        speaker_role=role,
        start_ms=start,
        end_ms=end,
        text=text,
        sequence_number=i,
    )


def test_talk_ratio_split() -> None:
    seller_id = uuid4()
    customer_id = uuid4()
    segs = [
        SegmentView(
            id=uuid4(),
            provider_segment_id="1",
            speaker_id=seller_id,
            speaker_role=SpeakerRole.SELLER,
            start_ms=0,
            end_ms=10000,
            text="hello",
            sequence_number=0,
        ),
        SegmentView(
            id=uuid4(),
            provider_segment_id="2",
            speaker_id=customer_id,
            speaker_role=SpeakerRole.CUSTOMER,
            start_ms=10000,
            end_ms=20000,
            text="why?",
            sequence_number=1,
        ),
    ]
    metrics = compute_metrics(segs, duration_ms=20000)
    assert metrics["talk_ratio"]["seller"] == 0.5
    assert metrics["talk_ratio"]["customer"] == 0.5


def test_longest_monologue() -> None:
    sid = uuid4()
    segs = [
        SegmentView(
            id=uuid4(),
            provider_segment_id="1",
            speaker_id=sid,
            speaker_role=SpeakerRole.SELLER,
            start_ms=0,
            end_ms=5000,
            text="a",
            sequence_number=0,
        ),
        SegmentView(
            id=uuid4(),
            provider_segment_id="2",
            speaker_id=sid,
            speaker_role=SpeakerRole.SELLER,
            start_ms=5200,
            end_ms=15000,
            text="b",
            sequence_number=1,
        ),
    ]
    metrics = compute_metrics(segs, duration_ms=15000)
    assert metrics["longest_monologue"]["duration_ms"] == 15000


def test_question_rate() -> None:
    segs = [
        SegmentView(
            id=uuid4(),
            provider_segment_id="1",
            speaker_role=SpeakerRole.SELLER,
            start_ms=0,
            end_ms=60000,
            text="How are you evaluating tools?",
            sequence_number=0,
        ),
        SegmentView(
            id=uuid4(),
            provider_segment_id="2",
            speaker_role=SpeakerRole.CUSTOMER,
            start_ms=60000,
            end_ms=120000,
            text="We like it.",
            sequence_number=1,
        ),
    ]
    metrics = compute_metrics(segs, duration_ms=120000)
    assert metrics["question_rate"]["count"] == 1
    assert metrics["question_rate"]["per_speaker"]["seller"] == 1
    assert metrics["question_rate"]["per_minute"] == 0.5

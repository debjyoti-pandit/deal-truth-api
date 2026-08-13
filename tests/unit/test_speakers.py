from app.core.enums import CallDirection, RecordingMode, SpeakerRole
from app.intelligence.speakers import resolve_speakers
from app.providers.normalized import NormalizedSegment, NormalizedSpeaker, NormalizedTranscript


def test_stereo_channel_mapping_default_seller_zero() -> None:
    transcript = NormalizedTranscript(
        recording_mode="stereo",
        speakers=[
            NormalizedSpeaker(provider_speaker_id="ch0", channel=0),
            NormalizedSpeaker(provider_speaker_id="ch1", channel=1),
        ],
        segments=[],
    )
    resolved = resolve_speakers(
        transcript,
        recording_mode=RecordingMode.STEREO,
        seller_channel=0,
        call_direction=CallDirection.OUTBOUND,
        customer_name="Sarah",
        rep_name="Rahul",
    )
    roles = {r[0].provider_speaker_id: r[1] for r in resolved}
    assert roles["ch0"] == SpeakerRole.SELLER
    assert roles["ch1"] == SpeakerRole.CUSTOMER


def test_stereo_can_invert_mapping() -> None:
    transcript = NormalizedTranscript(
        recording_mode="stereo",
        speakers=[
            NormalizedSpeaker(provider_speaker_id="ch0", channel=0),
            NormalizedSpeaker(provider_speaker_id="ch1", channel=1),
        ],
        segments=[],
    )
    resolved = resolve_speakers(
        transcript,
        recording_mode=RecordingMode.STEREO,
        seller_channel=1,
        call_direction=CallDirection.OUTBOUND,
        customer_name="Sarah",
        rep_name="Rahul",
    )
    roles = {r[0].provider_speaker_id: r[1] for r in resolved}
    assert roles["ch1"] == SpeakerRole.SELLER
    assert roles["ch0"] == SpeakerRole.CUSTOMER


def test_mono_heuristics_prefer_seller_cues() -> None:
    transcript = NormalizedTranscript(
        recording_mode="mono",
        speakers=[
            NormalizedSpeaker(provider_speaker_id="speaker_0"),
            NormalizedSpeaker(provider_speaker_id="speaker_1"),
        ],
        segments=[
            NormalizedSegment(
                provider_segment_id="1",
                provider_speaker_id="speaker_0",
                start_ms=0,
                end_ms=3000,
                text="I will send the SOC2 report by Friday.",
            ),
            NormalizedSegment(
                provider_segment_id="2",
                provider_speaker_id="speaker_1",
                start_ms=3000,
                end_ms=7000,
                text="Our security team has to approve any new vendor.",
            ),
        ],
    )
    resolved = resolve_speakers(
        transcript,
        recording_mode=RecordingMode.MONO,
        seller_channel=0,
        call_direction=CallDirection.OUTBOUND,
        customer_name="Sarah",
        rep_name="Rahul",
    )
    roles = {r[0].provider_speaker_id: r[1] for r in resolved}
    assert roles["speaker_0"] == SpeakerRole.SELLER
    assert roles["speaker_1"] == SpeakerRole.CUSTOMER
    assert all(r[2] > 0 for r in resolved)

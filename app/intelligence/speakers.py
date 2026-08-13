"""Speaker role resolution for stereo channel maps and mono diarization."""

from __future__ import annotations

from app.core.enums import CallDirection, RecordingMode, SpeakerRole
from app.intelligence.domain import SegmentView
from app.providers.normalized import NormalizedSpeaker, NormalizedTranscript

_SELLER_CUES = (
    "our product",
    "our platform",
    "i can send",
    "i'll send",
    "i will send",
    "we can do",
    "happy to share",
    "next step on our side",
)
_CUSTOMER_CUES = (
    "our security",
    "our budget",
    "we need",
    "we currently pay",
    "we can't",
    "we cannot",
    "i'll speak with",
    "i will talk to",
    "evaluate",
    "other vendors",
)


def resolve_speakers(
    transcript: NormalizedTranscript,
    *,
    recording_mode: RecordingMode,
    seller_channel: int,
    call_direction: CallDirection,
    customer_name: str | None,
    rep_name: str | None,
    label_scores: dict[str, dict[str, float]] | None = None,
) -> list[tuple[NormalizedSpeaker, SpeakerRole, float, str | None]]:
    """Return (speaker, role, confidence, display_name) for each provider speaker."""
    speakers = transcript.speakers
    if not speakers:
        ids = {s.provider_speaker_id for s in transcript.segments}
        speakers = [NormalizedSpeaker(provider_speaker_id=sid) for sid in sorted(ids)]
    if recording_mode == RecordingMode.STEREO:
        return _stereo(speakers, seller_channel, customer_name, rep_name)
    return _mono(
        speakers,
        transcript,
        call_direction,
        customer_name,
        rep_name,
        label_scores or {},
    )


def _stereo(
    speakers: list[NormalizedSpeaker],
    seller_channel: int,
    customer_name: str | None,
    rep_name: str | None,
) -> list[tuple[NormalizedSpeaker, SpeakerRole, float, str | None]]:
    result: list[tuple[NormalizedSpeaker, SpeakerRole, float, str | None]] = []
    for sp in speakers:
        channel = sp.channel if sp.channel is not None else _channel_from_id(sp.provider_speaker_id)
        if channel == seller_channel:
            result.append((sp, SpeakerRole.SELLER, 0.9, rep_name))
        elif channel is not None:
            result.append((sp, SpeakerRole.CUSTOMER, 0.9, customer_name))
        else:
            result.append((sp, SpeakerRole.UNKNOWN, 0.2, None))
    return result


def _channel_from_id(provider_id: str) -> int | None:
    if provider_id.endswith("0") or provider_id in {"0", "channel_0"}:
        return 0
    if provider_id.endswith("1") or provider_id in {"1", "channel_1"}:
        return 1
    return None


def _mono(
    speakers: list[NormalizedSpeaker],
    transcript: NormalizedTranscript,
    call_direction: CallDirection,
    customer_name: str | None,
    rep_name: str | None,
    label_scores: dict[str, dict[str, float]],
) -> list[tuple[NormalizedSpeaker, SpeakerRole, float, str | None]]:
    scored: list[tuple[NormalizedSpeaker, float]] = []
    by_speaker: dict[str, list[str]] = {}
    for seg in transcript.segments:
        by_speaker.setdefault(seg.provider_speaker_id, []).append(seg.text)
    first_id = transcript.segments[0].provider_speaker_id if transcript.segments else None
    for sp in speakers:
        texts = by_speaker.get(sp.provider_speaker_id, [])
        joined = " ".join(texts).lower()
        score = 0.0
        for cue in _SELLER_CUES:
            if cue in joined:
                score += 1.0
        for cue in _CUSTOMER_CUES:
            if cue in joined:
                score -= 1.0
        for text in texts:
            labels = label_scores.get(text, {})
            score += labels.get("seller commitment", 0) * 2
            score -= labels.get("customer commitment", 0) * 2
            score -= labels.get("budget blocker", 0)
            score -= labels.get("security blocker", 0)
        if call_direction == CallDirection.OUTBOUND and sp.provider_speaker_id == first_id:
            score += 0.5
        scored.append((sp, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    result: list[tuple[NormalizedSpeaker, SpeakerRole, float, str | None]] = []
    if not scored:
        return result
    seller_sp, seller_score = scored[0]
    conf = min(0.95, 0.5 + abs(seller_score) / 6)
    result.append((seller_sp, SpeakerRole.SELLER, conf, rep_name))
    remaining = scored[1:]
    if remaining:
        customer_sp, customer_score = remaining[0]
        result.append(
            (
                customer_sp,
                SpeakerRole.CUSTOMER,
                min(0.95, 0.5 + abs(customer_score) / 6),
                customer_name,
            )
        )
        for sp, _ in remaining[1:]:
            result.append((sp, SpeakerRole.UNKNOWN, 0.3, None))
    return result


def views_from_segments(
    segments: list[SegmentView],
    role_by_speaker_id: dict[object, SpeakerRole],
) -> list[SegmentView]:
    updated: list[SegmentView] = []
    for seg in segments:
        role = role_by_speaker_id.get(seg.speaker_id, seg.speaker_role)
        updated.append(seg.model_copy(update={"speaker_role": role}))
    return updated

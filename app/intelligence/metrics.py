"""Deterministic call metrics. No generative models.

Formulas
--------
speaking_ms(role) = sum(end_ms - start_ms) over segments whose speaker has that role.

talk_ratio.seller = speaking_ms(seller) / max(total_speaking_ms, 1)
talk_ratio.customer = speaking_ms(customer) / max(total_speaking_ms, 1)
talk_ratio.unknown = speaking_ms(unknown) / max(total_speaking_ms, 1)

A monologue is a run of consecutive same-speaker segments whose inter-segment
gap is <= MONOLOGUE_GAP_MS (500). Duration = last.end_ms - first.start_ms.
longest_monologue is the maximum such duration.

A question is a segment whose trimmed text contains '?' or starts with an
interrogative cue (who/what/when/where/why/how/do/does/did/can/could/would/will/is/are).
question_rate.per_minute = question_count / max(duration_minutes, 1/60).

keyword_hits: case-insensitive substring match of each tracked term and alias.

silence_gaps: adjacent-segment gaps > SILENCE_GAP_MS (2000).

call_duration_ms = provided duration or (last.end_ms - first.start_ms).
"""

from __future__ import annotations

import re
from typing import Any

from app.core.enums import SpeakerRole
from app.intelligence.domain import SegmentView

MONOLOGUE_GAP_MS = 500
SILENCE_GAP_MS = 2000
_INTERROGATIVE = re.compile(
    r"^(who|what|when|where|why|how|do|does|did|can|could|would|will|is|are|may|might)\b",
    re.IGNORECASE,
)


def compute_metrics(
    segments: list[SegmentView],
    *,
    duration_ms: int | None,
    tracked_terms: list[tuple[str, list[str]]] | None = None,
) -> dict[str, Any]:
    ordered = sorted(segments, key=lambda s: (s.start_ms, s.sequence_number))
    speaking: dict[str, int] = {role.value: 0 for role in SpeakerRole}
    for seg in ordered:
        speaking[seg.speaker_role.value] += max(0, seg.end_ms - seg.start_ms)
    total_speaking = sum(speaking.values()) or 1
    talk_ratio: dict[str, object] = {role: round(ms / total_speaking, 4) for role, ms in speaking.items()}
    talk_ratio["total_speaking_ms"] = sum(speaking.values())
    talk_ratio["by_role_ms"] = speaking

    longest = _longest_monologue(ordered)
    questions = _questions(ordered)
    duration = duration_ms
    if duration is None and ordered:
        duration = max(0, ordered[-1].end_ms - ordered[0].start_ms)
    duration = duration or 0
    minutes = max(duration / 60_000, 1 / 60)
    question_rate = {
        "count": questions["count"],
        "per_speaker": questions["per_speaker"],
        "per_minute": round(questions["count"] / minutes, 4),
        "duration_ms": duration,
    }
    keywords = _keyword_hits(ordered, tracked_terms or [])
    silences = _silence_gaps(ordered)
    return {
        "talk_ratio": talk_ratio,
        "longest_monologue": longest,
        "question_rate": question_rate,
        "keyword_hits": keywords,
        "silence_gaps": silences,
        "duration_ms": duration,
        "speaking_duration_ms": speaking,
    }


def _longest_monologue(segments: list[SegmentView]) -> dict[str, Any]:
    best: dict[str, Any] = {
        "duration_ms": 0,
        "speaker_role": None,
        "start_ms": None,
        "end_ms": None,
        "segment_ids": [],
    }
    if not segments:
        return best
    run = [segments[0]]
    for seg in segments[1:]:
        prev = run[-1]
        same = seg.speaker_id == prev.speaker_id and seg.speaker_role == prev.speaker_role
        gap = seg.start_ms - prev.end_ms
        if same and gap <= MONOLOGUE_GAP_MS:
            run.append(seg)
            continue
        best = _maybe_best(best, run)
        run = [seg]
    return _maybe_best(best, run)


def _maybe_best(best: dict[str, Any], run: list[SegmentView]) -> dict[str, Any]:
    duration = run[-1].end_ms - run[0].start_ms
    if duration > int(best["duration_ms"]):
        return {
            "duration_ms": duration,
            "speaker_role": run[0].speaker_role.value,
            "start_ms": run[0].start_ms,
            "end_ms": run[-1].end_ms,
            "segment_ids": [str(s.id) for s in run],
        }
    return best


def _questions(segments: list[SegmentView]) -> dict[str, Any]:
    per_speaker: dict[str, int] = {role.value: 0 for role in SpeakerRole}
    count = 0
    for seg in segments:
        text = seg.text.strip()
        if "?" in text or _INTERROGATIVE.match(text):
            count += 1
            per_speaker[seg.speaker_role.value] += 1
    return {"count": count, "per_speaker": per_speaker}


def _keyword_hits(segments: list[SegmentView], terms: list[tuple[str, list[str]]]) -> dict[str, Any]:
    hits: list[dict[str, Any]] = []
    for canonical, aliases in terms:
        needles = [canonical, *aliases]
        for seg in segments:
            hay = seg.text.lower()
            for needle in needles:
                if needle and needle.lower() in hay:
                    hits.append(
                        {
                            "term": canonical,
                            "matched": needle,
                            "segment_id": str(seg.id),
                            "start_ms": seg.start_ms,
                            "end_ms": seg.end_ms,
                            "speaker_role": seg.speaker_role.value,
                        }
                    )
                    break
    return {"hits": hits, "count": len(hits)}


def _silence_gaps(segments: list[SegmentView]) -> list[dict[str, int]]:
    gaps: list[dict[str, int]] = []
    for prev, nxt in zip(segments, segments[1:], strict=False):
        gap = nxt.start_ms - prev.end_ms
        if gap > SILENCE_GAP_MS:
            gaps.append({"start_ms": prev.end_ms, "end_ms": nxt.start_ms, "duration_ms": gap})
    return gaps

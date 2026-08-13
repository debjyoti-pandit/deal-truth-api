"""Ask-the-Call: chunk, embed, retrieve, optional generation with segment IDs retained."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence

from app.core.errors import MLGenerationDisabled, MLInferenceFailed
from app.intelligence.domain import SegmentView
from app.ml import MLInferenceClient

_GAP_MS = 1500


def chunk_segments(segments: Sequence[SegmentView], *, max_chars: int = 800) -> list[dict[str, object]]:
    ordered = sorted(segments, key=lambda s: s.sequence_number)
    chunks: list[list[SegmentView]] = []
    current: list[SegmentView] = []
    for seg in ordered:
        if not current:
            current = [seg]
            continue
        prev = current[-1]
        same = prev.speaker_id == seg.speaker_id
        gap = seg.start_ms - prev.end_ms
        size = sum(len(s.text) for s in current) + len(seg.text)
        if same and gap <= _GAP_MS and size <= max_chars:
            current.append(seg)
        else:
            chunks.append(current)
            current = [seg]
    if current:
        chunks.append(current)
    out: list[dict[str, object]] = []
    for group in chunks:
        out.append(
            {
                "start_segment_id": group[0].id,
                "end_segment_id": group[-1].id,
                "segment_ids": [s.id for s in group],
                "text": " ".join(s.text for s in group),
                "start_ms": group[0].start_ms,
                "end_ms": group[-1].end_ms,
            }
        )
    return out


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def retrieve(
    question_vec: Sequence[float],
    chunks: Sequence[tuple[dict[str, object], Sequence[float]]],
    *,
    top_k: int = 5,
) -> list[tuple[dict[str, object], float]]:
    scored = [(chunk, cosine(question_vec, vec)) for chunk, vec in chunks]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def _build_moments(
    ranked: Sequence[tuple[dict[str, object], float]],
) -> tuple[list[dict[str, object]], list[str]]:
    moments: list[dict[str, object]] = []
    segment_ids: list[str] = []
    for chunk, score in ranked:
        ids = chunk.get("segment_ids") or []
        if not isinstance(ids, list):
            ids = []
        for sid in ids:
            segment_ids.append(str(sid))
        moments.append(
            {
                "text": chunk.get("text"),
                "score": round(score, 4),
                "start_ms": chunk.get("start_ms"),
                "end_ms": chunk.get("end_ms"),
                "segment_ids": [str(s) for s in ids],
            }
        )
    return moments, segment_ids


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9']+", text.lower()) if len(t) > 2}


def ask_lexical(
    question: str,
    chunks: Sequence[tuple[dict[str, object], Sequence[float]]],
    *,
    top_k: int = 5,
) -> dict[str, object]:
    """Token-overlap retrieval used when the ML service is unavailable. No generation."""
    want = _tokens(question)
    scored: list[tuple[dict[str, object], float]] = []
    for chunk, _vec in chunks:
        words = _tokens(str(chunk.get("text") or ""))
        score = len(want & words) / len(want) if want else 0.0
        scored.append((chunk, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    ranked = [(chunk, score) for chunk, score in scored[:top_k] if score > 0]
    moments, segment_ids = _build_moments(ranked)
    if moments:
        lines = [f"{i + 1}. {m['text']} ({m.get('start_ms')} ms)" for i, m in enumerate(moments)]
        answer = "I found relevant moments (lexical match; ML service unavailable):\n" + "\n".join(lines)
    else:
        answer = "No matching moments were found (ML service unavailable; lexical match only)."
    return {
        "answer": answer,
        "mode": "retrieval_lexical_fallback",
        "moments": moments,
        "evidence_segment_ids": segment_ids,
    }


def ask(
    question: str,
    chunks: Sequence[tuple[dict[str, object], Sequence[float]]],
    ml: MLInferenceClient,
    *,
    top_k: int = 5,
    generate: bool = False,
) -> dict[str, object]:
    qvec = ml.embed([question])[0]
    ranked = retrieve(qvec, chunks, top_k=top_k)
    moments, segment_ids = _build_moments(ranked)
    answer = None
    mode = "retrieval"
    if generate and ranked:
        try:
            prompt = _prompt(question, moments)
            generated = ml.generate(prompt)
            if _retains_ids(generated, segment_ids):
                answer = generated
                mode = "generated"
            else:
                mode = "retrieval_generation_dropped"
        except (MLInferenceFailed, MLGenerationDisabled):
            mode = "retrieval_generation_failed"
    if answer is None:
        lines = [f"{i + 1}. {m['text']} ({m.get('start_ms')} ms)" for i, m in enumerate(moments)]
        answer = "I found relevant moments:\n" + "\n".join(lines)
    return {
        "answer": answer,
        "mode": mode,
        "moments": moments,
        "evidence_segment_ids": segment_ids,
    }


def _prompt(question: str, moments: list[dict[str, object]]) -> str:
    lines: list[str] = []
    for m in moments:
        raw_ids = m.get("segment_ids") or []
        id_list = [str(x) for x in raw_ids] if isinstance(raw_ids, list) else []
        lines.append(f"- [{', '.join(id_list)}] {m.get('text')}")
    body = "\n".join(lines)
    return (
        "Answer the question using only the moments below. "
        "Keep every segment id in brackets in the answer. Do not add facts.\n"
        f"Question: {question}\nMoments:\n{body}"
    )


def _retains_ids(text: str, segment_ids: list[str]) -> bool:
    if not segment_ids:
        return True
    found = set(re.findall(r"[0-9a-fA-F-]{36}", text))
    needed = set(segment_ids)
    return bool(needed & found)

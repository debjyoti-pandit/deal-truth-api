"""The eight observable deal-signal dimensions, and their per-call state.

These are **observed states, not a score.** Deal Truth never emits a close probability or a
deal-health number; it reports which dimensions the transcript actually establishes and which
it does not. `docs/frontend-contract.md` refuses `biggest_risk` on `CallSummary` for the same
reason — a risk badge is a UI judgement, a dimension state is an observation.

Derived entirely from the latest analysis run's `QUALIFICATION_SIGNAL` insights, which
`extract_buying_intent` emits with `payload = {"dimension": ..., "present": bool}`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

# The classifier score at or above which a label counts as established. Mirrors
# app.intelligence.extract.LABEL_THRESHOLD; imported there rather than redefined.
from app.intelligence.extract import LABEL_THRESHOLD

DIMENSIONS: tuple[str, ...] = (
    "pain_identified",
    "business_impact_identified",
    "decision_maker_identified",
    "economic_buyer_identified",
    "timeline_identified",
    "next_meeting_committed",
    "competitor_active",
    "blocker_active",
)

#: Dimensions where presence is bad news. A competitor in the deal or an active blocker is
#: not progress to be celebrated as "proven" — it is an obstacle, and the UI colours it so.
ADVERSE_DIMENSIONS: frozenset[str] = frozenset({"competitor_active", "blocker_active"})

#: The four states a dimension can be in.
#:   proven  — established by a real customer segment.
#:   blocked — an adverse dimension is present: something is actively working against the deal.
#:   weak    — hinted at but below the threshold that counts as established. Mentioned, not settled.
#:   missing — no signal at all. For an absence-based finding this is the honest answer, and an
#:             empty evidence list beside it is correct rather than a bug.
STATES: tuple[str, ...] = ("proven", "blocked", "weak", "missing")


class _SignalLike(Protocol):
    """Structural view of a QUALIFICATION_SIGNAL, satisfied by both ValidatedInsight and the
    Insight ORM row, so the state is computed identically at build time and at read time."""

    title: str
    confidence: float
    payload: dict[str, Any]


def dimension_state(*, dimension: str, present: bool, confidence: float) -> str:
    if present:
        return "blocked" if dimension in ADVERSE_DIMENSIONS else "proven"
    # Not established. Distinguish "the classifier saw something and it did not clear the bar"
    # from "nothing was said at all" — the difference is what a rep would want to chase.
    if confidence > 0.0 and confidence < LABEL_THRESHOLD:
        return "weak"
    return "missing"


def signal_pips(signals: Sequence[_SignalLike]) -> dict[str, str]:
    """Map QUALIFICATION_SIGNAL insights onto all eight dimension states.

    Every dimension is always present in the result. A call with no analysis run yet reports
    all eight as `missing`, which is accurate: nothing has been observed.
    """
    states = dict.fromkeys(DIMENSIONS, "missing")
    for signal in signals:
        payload = signal.payload or {}
        dimension = str(payload.get("dimension") or signal.title or "")
        if dimension not in states:
            continue
        states[dimension] = dimension_state(
            dimension=dimension,
            present=bool(payload.get("present")),
            confidence=float(signal.confidence or 0.0),
        )
    return states


def dimension_deltas(
    previous: dict[str, str],
    current: dict[str, str],
) -> list[dict[str, str]]:
    """Dimensions whose state changed between two consecutive calls.

    A pure diff — no model involved. The finding this exists to surface is the one no
    summarisation tool catches: a dimension that was `proven` on the last call and is absent
    on this one. Nobody notices that from a summary.
    """
    out: list[dict[str, str]] = []
    for dimension in DIMENSIONS:
        was = previous.get(dimension, "missing")
        now = current.get(dimension, "missing")
        if was != now:
            out.append({"dimension": dimension, "from": was, "to": now})
    return out

"""Deals — a sequence of calls on one account, and what changed between them.

Deliberately **not** in scope: a health score. Counting proven dimensions per call is
observable; a 0-100 number is the fake precision this product refuses everywhere else.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_sync_session, require_auth
from app.core.enums import InsightType
from app.core.errors import NotFoundError
from app.intelligence.dimensions import dimension_deltas, signal_pips
from app.models.analysis import AnalysisRun, Insight
from app.models.call import Call, Deal
from app.models.evidence import EvidenceLink

router = APIRouter(prefix="/api/v1", tags=["deals"], dependencies=[Depends(require_auth)])


def attach_to_deal(session: Session, call: Call) -> Deal | None:
    """Match a call to an account by name, creating the account if it is new.

    Case-insensitive exact match on `customer_name`. Deliberately naive — it does not need to
    be clever, and a rep can correct it later.
    """
    name = (call.customer_name or "").strip()
    if not name:
        return None
    deal = session.scalars(select(Deal).where(Deal.account_name.ilike(name))).first()
    if deal is None:
        deal = Deal(account_name=name)
        session.add(deal)
        session.flush()
    call.deal_id = deal.id
    return deal


def _states_for_run(session: Session, run: AnalysisRun | None) -> dict[str, str]:
    if run is None:
        return signal_pips([])
    signals = session.scalars(
        select(Insight).where(
            Insight.analysis_run_id == run.id,
            Insight.type == InsightType.QUALIFICATION_SIGNAL,
        )
    ).all()
    return signal_pips(list(signals))


def _evidence_for_dimension(session: Session, run: AnalysisRun | None, dimension: str) -> list[str]:
    """Segments that establish a dimension, resolved through evidence_links at read time.

    An absent dimension legitimately has no segments — that empty list is the honest answer,
    not a missing value.
    """
    if run is None:
        return []
    insight = session.scalars(
        select(Insight).where(
            Insight.analysis_run_id == run.id,
            Insight.type == InsightType.QUALIFICATION_SIGNAL,
            Insight.title == dimension,
        )
    ).first()
    if insight is None:
        return []
    links = session.scalars(select(EvidenceLink).where(EvidenceLink.insight_id == insight.id)).all()
    return [str(link.transcript_segment_id) for link in sorted(links, key=lambda x: x.sort_order)]


@router.get("/deals/{deal_id}")
def get_deal(deal_id: UUID, session: Session = Depends(get_sync_session)) -> dict[str, object]:
    deal = session.get(Deal, deal_id)
    if deal is None:
        raise NotFoundError("Deal not found")
    calls = list(session.scalars(select(Call).where(Call.deal_id == deal.id).order_by(Call.created_at.asc())).all())

    entries: list[dict[str, object]] = []
    runs: list[AnalysisRun | None] = []
    for call in calls:
        run = session.scalars(
            select(AnalysisRun).where(AnalysisRun.call_id == call.id).order_by(AnalysisRun.version.desc())
        ).first()
        runs.append(run)
        entries.append(
            {
                "call_id": str(call.id),
                "title": call.title,
                "created_at": call.created_at.isoformat(),
                "duration_ms": call.duration_ms,
                "dimension_states": _states_for_run(session, run),
            }
        )

    # A pure Python diff of consecutive calls. No model involved. The finding this exists to
    # surface is the one no summarisation tool catches: a dimension that was proven last call
    # and has quietly gone.
    deltas: list[dict[str, object]] = []
    for index in range(1, len(entries)):
        previous = entries[index - 1]["dimension_states"]
        current = entries[index]["dimension_states"]
        assert isinstance(previous, dict) and isinstance(current, dict)
        for change in dimension_deltas(previous, current):
            deltas.append(
                {
                    **change,
                    "from_call_id": entries[index - 1]["call_id"],
                    "to_call_id": entries[index]["call_id"],
                    "evidence_segment_ids": _evidence_for_dimension(session, runs[index - 1], change["dimension"]),
                }
            )

    span_days = 0
    if len(calls) >= 2:
        span_days = (calls[-1].created_at - calls[0].created_at).days

    return {
        "id": str(deal.id),
        "account_name": deal.account_name,
        "primary_contact": deal.primary_contact,
        "call_count": len(calls),
        "span_days": span_days,
        "calls": entries,
        "deltas": deltas,
    }

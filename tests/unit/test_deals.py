"""Deals: a sequence of calls read as one account, and what changed between them.

The finding this exists to surface is the one no summarisation tool catches — a dimension
that was proven on the last call and has quietly disappeared on this one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.api.v1.deals import attach_to_deal
from app.core.enums import (
    AnalysisRunStatus,
    CallDirection,
    CallStatus,
    EvidenceStatus,
    InsightType,
    RecordingMode,
    SourceType,
)
from app.intelligence.dimensions import DIMENSIONS, signal_pips
from app.models.analysis import AnalysisRun, Insight
from app.models.call import Call, Deal
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session


def _call(session: Session, *, customer: str, title: str, days_ago: int) -> Call:
    call = Call(
        public_call_id=uuid4().hex[:12],
        title=title,
        customer_name=customer,
        rep_name="Rahul",
        call_direction=CallDirection.OUTBOUND,
        source_type=SourceType.UPLOAD,
        recording_mode=RecordingMode.MONO,
        status=CallStatus.SHIPPED,
        duration_ms=600_000,
        extra={},
        created_at=datetime.now(UTC) - timedelta(days=days_ago),
    )
    session.add(call)
    session.flush()
    return call


def _run_with_dimensions(session: Session, call: Call, present: dict[str, bool]) -> AnalysisRun:
    run = AnalysisRun(
        call_id=call.id,
        version=1,
        status=AnalysisRunStatus.SUCCEEDED,
        model_manifest={},
    )
    session.add(run)
    session.flush()
    for dimension in DIMENSIONS:
        is_present = present.get(dimension, False)
        session.add(
            Insight(
                analysis_run_id=run.id,
                type=InsightType.QUALIFICATION_SIGNAL,
                title=dimension,
                summary=dimension,
                confidence=0.9 if is_present else 0.0,
                evidence_status=EvidenceStatus.SUPPORTED if is_present else EvidenceStatus.ABSENCE_BASED,
                payload={"dimension": dimension, "present": is_present},
            )
        )
    session.flush()
    return run


def test_calls_attach_to_one_deal_case_insensitively(session: Session) -> None:
    first = _call(session, customer="Acme Inc.", title="discovery", days_ago=10)
    second = _call(session, customer="acme inc.", title="deep dive", days_ago=2)
    attach_to_deal(session, first)
    attach_to_deal(session, second)
    session.flush()

    deals = session.scalars(select(Deal)).all()
    assert len(deals) == 1, "same account under different casing must not create two deals"
    assert first.deal_id == second.deal_id


def test_a_dimension_proven_last_call_and_gone_this_call_is_a_delta(client: TestClient, session: Session) -> None:
    first = _call(session, customer="Acme Inc.", title="discovery", days_ago=18)
    second = _call(session, customer="Acme Inc.", title="deep dive", days_ago=0)
    attach_to_deal(session, first)
    attach_to_deal(session, second)
    _run_with_dimensions(session, first, {"pain_identified": True, "next_meeting_committed": True})
    _run_with_dimensions(session, second, {"pain_identified": True})
    session.commit()

    body = client.get(f"/api/v1/deals/{first.deal_id}").json()

    assert body["call_count"] == 2
    assert body["span_days"] == 18
    assert all(len(c["dimension_states"]) == 8 for c in body["calls"])
    assert all(has in c for c in body["calls"] for has in ("call_id", "title", "created_at"))

    regression = [d for d in body["deltas"] if d["dimension"] == "next_meeting_committed"]
    assert len(regression) == 1, "the silent regression must be reported exactly once"
    assert regression[0]["from"] == "proven"
    assert regression[0]["to"] == "missing"
    assert regression[0]["from_call_id"] == str(first.id)
    assert regression[0]["to_call_id"] == str(second.id)
    # A dimension that held steady is not a delta.
    assert not [d for d in body["deltas"] if d["dimension"] == "pain_identified"]


def test_every_delta_carries_the_fields_the_ui_keys_on(client: TestClient, session: Session) -> None:
    first = _call(session, customer="Globex", title="one", days_ago=5)
    second = _call(session, customer="Globex", title="two", days_ago=1)
    attach_to_deal(session, first)
    attach_to_deal(session, second)
    _run_with_dimensions(session, first, {"timeline_identified": True})
    _run_with_dimensions(session, second, {"competitor_active": True})
    session.commit()

    body = client.get(f"/api/v1/deals/{first.deal_id}").json()
    assert body["deltas"], "expected at least one change between the two calls"
    for delta in body["deltas"]:
        assert {"dimension", "from", "to", "from_call_id", "to_call_id"} <= set(delta)
        assert isinstance(delta["evidence_segment_ids"], list)

    # A competitor appearing is "blocked", never "proven" — presence here is bad news.
    appeared = [d for d in body["deltas"] if d["dimension"] == "competitor_active"]
    assert appeared and appeared[0]["to"] == "blocked"


def test_no_score_or_probability_is_ever_emitted(client: TestClient, session: Session) -> None:
    call = _call(session, customer="Initech", title="only", days_ago=1)
    attach_to_deal(session, call)
    _run_with_dimensions(session, call, {"pain_identified": True})
    session.commit()

    body = client.get(f"/api/v1/deals/{call.deal_id}").json()
    flat = str(body).lower()
    for banned in ("close_probability", "health_score", "deal_score", "likelihood"):
        assert banned not in flat


def test_unknown_deal_is_404(client: TestClient) -> None:
    assert client.get(f"/api/v1/deals/{uuid4()}").status_code == 404


def test_pips_cover_all_eight_dimensions_with_no_run(session: Session) -> None:
    states = signal_pips([])
    assert len(states) == 8
    assert set(states) == set(DIMENSIONS)
    assert set(states.values()) == {"missing"}


def test_call_list_carries_eight_pips_in_one_request(client: TestClient, session: Session, settings, blob) -> None:
    """API-2's stated check: every call returns exactly 8 pips, each an allowed value."""
    from tests.conftest import run_scenario

    run_scenario(session, settings, blob, "happy_path")
    session.commit()

    items = client.get("/api/v1/calls").json()
    assert items, "expected at least one call"
    for item in items:
        assert set(item["signal_pips"]) == set(DIMENSIONS)
        assert len(item["signal_pips"]) == 8
        assert all(v in ("proven", "blocked", "weak", "missing") for v in item["signal_pips"].values())
        assert "close_probability" not in item and "health_score" not in item


def test_a_call_with_no_analysis_still_reports_all_eight_as_missing(client: TestClient) -> None:
    created = client.post("/api/v1/calls", json={"title": "fresh", "customer_name": "Acme"})
    assert created.status_code == 201
    item = next(c for c in client.get("/api/v1/calls").json() if c["id"] == created.json()["id"])
    assert len(item["signal_pips"]) == 8
    assert set(item["signal_pips"].values()) == {"missing"}
    assert item["deal_id"], "a named customer must attach to a deal at creation"

"""Refused claims are recorded, not discarded.

The evidence gate is the product. A gate that silently drops what it rejects cannot be
shown to work, so every refusal is persisted with the code and reason that caused it.
"""

from __future__ import annotations

from uuid import uuid4

from app.core.enums import (
    CallDirection,
    CallStatus,
    EvidenceStatus,
    InsightType,
    RecordingMode,
    SourceType,
    SpeakerRole,
)
from app.core.settings import Settings
from app.evidence import shippable, validate_candidates
from app.intelligence.domain import CandidateInsight, SegmentView
from app.models.analysis import Insight, RefusedClaim
from app.models.call import Call
from app.pipeline.persist import persist_insights
from app.storage.memory import MemoryBlobStore
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.conftest import run_scenario


def _call(session: Session) -> Call:
    call = Call(
        public_call_id=uuid4().hex[:12],
        title="refusals",
        customer_name="Sarah",
        rep_name="Rahul",
        call_direction=CallDirection.OUTBOUND,
        source_type=SourceType.UPLOAD,
        recording_mode=RecordingMode.MONO,
        status=CallStatus.QUEUED,
        extra={},
    )
    session.add(call)
    session.flush()
    return call


def _seg(*, role: SpeakerRole, text: str) -> SegmentView:
    return SegmentView(
        id=uuid4(),
        provider_segment_id="1",
        speaker_role=role,
        start_ms=1000,
        end_ms=2000,
        text=text,
        sequence_number=0,
    )


def _persist(session: Session, candidates: list[CandidateInsight], segments: list[SegmentView]) -> Call:
    call = _call(session)
    validated, _ = validate_candidates(candidates, segments, confidence_threshold=0.5)
    persist_insights(session, call, validated, manifest={})
    session.flush()
    return call


def _refusals(session: Session, call: Call) -> list[RefusedClaim]:
    return list(session.scalars(select(RefusedClaim).where(RefusedClaim.call_id == call.id)).all())


def test_missing_segment_is_recorded_as_evidence_segment_missing(session: Session) -> None:
    ghost = uuid4()
    customer = _seg(role=SpeakerRole.CUSTOMER, text="We are still evaluating.")
    cand = CandidateInsight(
        type=InsightType.OBJECTION,
        title="Pricing pushback",
        summary="Customer pushed back on price.",
        confidence=0.9,
        segment_ids=[ghost],
    )
    call = _persist(session, [cand], [customer])

    rows = _refusals(session, call)
    assert len(rows) == 1
    assert rows[0].error_code == "EVIDENCE_SEGMENT_MISSING"
    assert rows[0].drop_reason
    assert rows[0].attempted_segment_ids == [str(ghost)]
    # The refusal is recorded, and nothing about it reached the insights table.
    assert session.scalars(select(Insight)).all() == []


def test_customer_truth_citing_a_seller_segment_is_wrong_speaker(session: Session) -> None:
    seller = _seg(role=SpeakerRole.SELLER, text="They are ready to buy.")
    cand = CandidateInsight(
        type=InsightType.CUSTOMER_FACT,
        title="Customer is ready to buy",
        summary="The customer is ready to buy.",
        confidence=0.9,
        segment_ids=[seller.id],
    )
    call = _persist(session, [cand], [seller])

    rows = _refusals(session, call)
    assert len(rows) == 1
    assert rows[0].error_code == "EVIDENCE_WRONG_SPEAKER"
    assert rows[0].attempted_segment_ids == [str(seller.id)]
    # The seller's words are not the customer's truth, and the seller's segment must not
    # be reachable from a shipped insight.
    assert session.scalars(select(Insight)).all() == []


def test_hallucinated_quote_is_kept_as_attempted_never_as_evidence(session: Session) -> None:
    customer = _seg(role=SpeakerRole.CUSTOMER, text="We need security approval.")
    cand = CandidateInsight(
        type=InsightType.CUSTOMER_FACT,
        title="Customer will sign",
        summary="Customer committed to signing.",
        confidence=0.9,
        segment_ids=[customer.id],
        payload={"quote": "We will sign tomorrow."},
    )
    call = _persist(session, [cand], [customer])

    rows = _refusals(session, call)
    assert len(rows) == 1
    assert rows[0].error_code == "EVIDENCE_UNSUPPORTED"
    assert rows[0].attempted_quote == "We will sign tomorrow."


def test_shipped_plus_refused_equals_total_candidates(session: Session) -> None:
    customer = _seg(role=SpeakerRole.CUSTOMER, text="Manual routing costs us six hours a week.")
    seller = _seg(role=SpeakerRole.SELLER, text="I can walk you through how we route calls.")
    candidates = [
        # ships
        CandidateInsight(
            type=InsightType.CUSTOMER_FACT,
            title="Manual routing is expensive",
            summary=customer.text,
            confidence=0.9,
            segment_ids=[customer.id],
        ),
        # ships without segments: an observable absence is not an unsupported claim
        CandidateInsight(
            type=InsightType.DEAL_RISK,
            title="No timeline",
            summary="No purchase timeline was stated.",
            confidence=1.0,
            evidence_status=EvidenceStatus.ABSENCE_BASED,
        ),
        # refused: wrong speaker
        CandidateInsight(
            type=InsightType.CUSTOMER_FACT,
            title="Customer offered a walkthrough",
            summary=seller.text,
            confidence=0.9,
            segment_ids=[seller.id],
        ),
        # refused: no evidence at all
        CandidateInsight(
            type=InsightType.OBJECTION,
            title="Budget objection",
            summary="Customer raised budget.",
            confidence=0.9,
            segment_ids=[],
        ),
    ]
    call = _call(session)
    validated, _ = validate_candidates(candidates, [customer, seller], confidence_threshold=0.5)
    persist_insights(session, call, validated, manifest={})
    session.flush()

    shipped = session.scalars(select(Insight)).all()
    refused = _refusals(session, call)
    assert len(shipped) == len(shippable(validated))
    assert len(shipped) + len(refused) == len(candidates)
    assert len(refused) == 2


def test_refusals_endpoint_reconciles_with_the_report(
    client: TestClient, session: Session, settings: Settings, blob: MemoryBlobStore
) -> None:
    call_id = run_scenario(session, settings, blob, "seller_overstates_intent")

    body = client.get(f"/api/v1/calls/{call_id}/refusals").json()
    assert body["call_id"] == str(call_id)
    assert isinstance(body["refusals"], list)
    assert len(body["refusals"]) == body["refused_count"]
    for row in body["refusals"]:
        assert row["error_code"] in {
            "EVIDENCE_UNSUPPORTED",
            "EVIDENCE_WRONG_SPEAKER",
            "EVIDENCE_SEGMENT_MISSING",
        }
        assert row["drop_reason"]

    insights = client.get(f"/api/v1/calls/{call_id}/insights").json()
    assert body["shipped_count"] == len(insights)

    report = client.get(f"/api/v1/calls/{call_id}/report").json()
    assert report["refused_count"] == body["refused_count"]
    assert report["shipped_count"] == body["shipped_count"]


def test_refusals_for_unknown_call_is_404(client: TestClient) -> None:
    assert client.get(f"/api/v1/calls/{uuid4()}/refusals").status_code == 404


def test_refusals_before_analysis_is_an_empty_zeroed_body(client: TestClient, session: Session) -> None:
    call = _call(session)
    session.commit()
    body = client.get(f"/api/v1/calls/{call.id}/refusals").json()
    assert body == {
        "call_id": str(call.id),
        "refused_count": 0,
        "shipped_count": 0,
        "refusals": [],
    }


def _inject_refusable_candidates(monkeypatch) -> None:
    """Make the pipeline produce real refusals.

    The deterministic extractors cannot fail validation by construction, so without this the
    only end-to-end assertions available are `0 == 0` — which is how reverting the runner to
    pass `shipped` instead of `validated` slipped past the whole suite.
    """
    from app.intelligence import extract as extract_module
    from app.pipeline import runner as runner_module

    real = extract_module.extract_objections

    def with_bad_candidates(segments):  # type: ignore[no-untyped-def]
        out = list(real(segments))
        seller = next((s for s in segments if s.speaker_role == SpeakerRole.SELLER), None)
        customer = next((s for s in segments if s.speaker_role == SpeakerRole.CUSTOMER), None)
        out.append(
            CandidateInsight(
                type=InsightType.OBJECTION,
                title="Cites a segment that is not on this call",
                summary="ghost",
                confidence=0.9,
                segment_ids=[uuid4()],
            )
        )
        if seller is not None:
            out.append(
                CandidateInsight(
                    type=InsightType.CUSTOMER_FACT,
                    title="Attributes the rep's words to the customer",
                    summary=seller.text,
                    confidence=0.9,
                    segment_ids=[seller.id],
                )
            )
        if customer is not None:
            out.append(
                CandidateInsight(
                    type=InsightType.CUSTOMER_FACT,
                    title="Quotes words nobody said",
                    summary="invented",
                    confidence=0.9,
                    segment_ids=[customer.id],
                    payload={"quote": "We will sign the contract tomorrow."},
                )
            )
        return out

    monkeypatch.setattr(extract_module, "extract_objections", with_bad_candidates)
    monkeypatch.setattr(runner_module, "extract_objections", with_bad_candidates)


def test_refusals_survive_the_pipeline_and_reach_the_endpoint(
    client: TestClient, session: Session, settings: Settings, blob: MemoryBlobStore, monkeypatch
) -> None:
    """The end-to-end guarantee: refusals reach the database and the API, not a local variable.

    This is the test that fails if persist_insights is handed `shipped` instead of
    `validated` — the exact regression this feature exists to prevent.
    """
    _inject_refusable_candidates(monkeypatch)
    call_id = run_scenario(session, settings, blob, "happy_path")

    body = client.get(f"/api/v1/calls/{call_id}/refusals").json()
    assert body["refused_count"] >= 3, "injected bad candidates must be refused, not discarded"
    assert {r["error_code"] for r in body["refusals"]} == {
        "EVIDENCE_SEGMENT_MISSING",
        "EVIDENCE_WRONG_SPEAKER",
        "EVIDENCE_UNSUPPORTED",
    }
    assert all(r["drop_reason"] for r in body["refusals"])

    report = client.get(f"/api/v1/calls/{call_id}/report").json()
    assert report["refused_count"] == body["refused_count"] > 0
    assert report["shipped_count"] == body["shipped_count"] > 0

    # Nothing refused may appear as a claim anywhere.
    refused_titles = {r["title"] for r in body["refusals"]}
    shipped_titles = {i["title"] for i in client.get(f"/api/v1/calls/{call_id}/insights").json()}
    assert not (refused_titles & shipped_titles)
    assert "We will sign the contract tomorrow." not in str(report)


def test_counts_track_the_latest_run_only(
    client: TestClient, session: Session, settings: Settings, blob: MemoryBlobStore, monkeypatch
) -> None:
    """Refusals are per-run. A later run must not accumulate an earlier run's rows."""
    _inject_refusable_candidates(monkeypatch)
    call_id = run_scenario(session, settings, blob, "happy_path")
    first = client.get(f"/api/v1/calls/{call_id}/refusals").json()
    assert first["refused_count"] > 0

    # A second analysis run over the same call, as a reanalysis would produce.
    call = session.get(Call, call_id)
    assert call is not None
    validated, _ = validate_candidates(
        [
            CandidateInsight(
                type=InsightType.OBJECTION,
                title="Second run, still unsupported",
                summary="x",
                confidence=0.9,
                segment_ids=[uuid4()],
            )
        ],
        [],
        confidence_threshold=0.5,
    )
    persist_insights(session, call, validated, manifest={})
    session.commit()

    second = client.get(f"/api/v1/calls/{call_id}/refusals").json()
    stored = session.scalars(select(RefusedClaim).where(RefusedClaim.call_id == call_id)).all()
    assert len(stored) > second["refused_count"], "both runs' rows must be stored"
    assert second["refused_count"] == 1, "the endpoint reports the latest run only"
    assert second["shipped_count"] == 0, "shipped_count must not accumulate across runs"
    assert [r["title"] for r in second["refusals"]] == ["Second run, still unsupported"]


def test_a_refused_claim_does_not_poison_a_later_valid_one(session: Session) -> None:
    """A refused candidate must not consume its segments.

    Marking segments as claimed while still validating let a candidate that went on to fail
    reserve them anyway. The next, entirely valid claim on the same segment was then refused
    as a duplicate of something that was never made — and told so in a sentence the UI shows
    to a user.
    """
    customer = _seg(role=SpeakerRole.CUSTOMER, text="Manual routing costs us six hours a week.")
    seller = _seg(role=SpeakerRole.SELLER, text="I can walk you through how we route calls.")
    doomed = CandidateInsight(
        type=InsightType.CUSTOMER_FACT,
        title="Manual routing is expensive",
        summary=customer.text,
        confidence=0.9,
        segment_ids=[customer.id, seller.id],  # second segment is the wrong speaker
    )
    valid = CandidateInsight(
        type=InsightType.CUSTOMER_FACT,
        title="Manual routing is expensive",
        summary=customer.text,
        confidence=0.9,
        segment_ids=[customer.id],
    )
    call = _persist(session, [doomed, valid], [customer, seller])

    rows = _refusals(session, call)
    assert [r.error_code for r in rows] == ["EVIDENCE_WRONG_SPEAKER"]
    assert not [r for r in rows if "already made" in r.drop_reason]
    shipped = session.scalars(select(Insight)).all()
    assert len(shipped) == 1, "the valid claim must still ship"

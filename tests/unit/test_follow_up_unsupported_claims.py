"""A follow-up draft must account for every factual sentence it contains.

The draft is the one place the product writes prose on the rep's behalf, so it is the one
place a claim could slip out without proof. Every FACT sentence is either backed by
transcript segment ids or listed in `unsupported_claims` with the reason it is not — and
the two lists are checked against each other here so they can never silently diverge.

A `contradicting_segment_id` is a pointer the UI turns into "Hear what they actually
said". It must be a real segment on the call. Absence is correct; a wrong pointer would
be a fabrication, so the no-pointer cases are tested as hard as the pointer case.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from app.core.enums import EvidenceStatus, InsightType
from app.core.settings import Settings
from app.intelligence.domain import ValidatedInsight
from app.intelligence.email import build_follow_up, polish_or_fallback
from app.storage.memory import MemoryBlobStore
from fastapi.testclient import TestClient
from fixtures.catalog import SCENARIOS
from sqlalchemy.orm import Session
from tests.conftest import run_scenario

# The fixture whose transcript contains a next meeting the customer never commits to.
WEAKENED_SCENARIO = "customer_weakens_commitment"
NEXT_MEETING_TEXT = "Looking forward to the next meeting we agreed on."


def _unsupported_facts(email: dict[str, object]) -> list[dict[str, object]]:
    sentences = email["sentences"]
    assert isinstance(sentences, list)
    return [s for s in sentences if s["kind"] == "FACT" and not s["supported"]]


def _claims(email: dict[str, object]) -> list[dict[str, object]]:
    claims = email["unsupported_claims"]
    assert isinstance(claims, list)
    return claims


def _segment_ids(client: TestClient, call_id: object) -> set[str]:
    body = client.get(f"/api/v1/calls/{call_id}/transcript").json()
    return {s["id"] for s in body["segments"]}


def _insight(
    insight_type: InsightType,
    *,
    title: str = "insight",
    payload: dict[str, object] | None = None,
    segment_ids: list[UUID] | None = None,
    dropped: bool = False,
) -> ValidatedInsight:
    return ValidatedInsight(
        type=insight_type,
        title=title,
        summary=title,
        severity=None,
        confidence=0.9,
        evidence_status=EvidenceStatus.SUPPORTED,
        segment_ids=segment_ids or [],
        quotes=[],
        audio_spans=[],
        payload=payload or {},
        dropped=dropped,
    )


def test_next_meeting_the_customer_never_committed_to_is_reported_with_its_contradiction(
    client: TestClient, session: Session, settings: Settings, blob: MemoryBlobStore
) -> None:
    call_id = run_scenario(session, settings, blob, WEAKENED_SCENARIO)

    email = client.post(f"/api/v1/calls/{call_id}/follow-up").json()
    claims = _claims(email)

    # The draft says there is a next meeting. Nothing in the transcript backs it, so the
    # claim is surfaced rather than shipped as fact.
    assert len(claims) == 1
    claim = claims[0]
    assert claim["text"] == NEXT_MEETING_TEXT
    assert claim["reason"]
    assert [s["text"] for s in _unsupported_facts(email)] == [NEXT_MEETING_TEXT]

    # The pointer the UI plays back must be a segment that exists on this call.
    assert claim["contradicting_segment_id"] in _segment_ids(client, call_id)

    # And it must be the segment the reality check itself weighed the claim against —
    # not merely any segment that happens to be on the call.
    report = client.get(f"/api/v1/calls/{call_id}/report").json()
    checks = [r for r in report["reality_checks"] if r["payload"]["reason_code"] == "NO_EXPLICIT_COMMITMENT"]
    assert len(checks) == 1
    assert claim["contradicting_segment_id"] == checks[0]["payload"]["customer_segment_id"]
    assert claim["contradicting_segment_id"] in checks[0]["segment_ids"]


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_unsupported_claims_reconcile_with_the_sentence_list(
    client: TestClient,
    session: Session,
    settings: Settings,
    blob: MemoryBlobStore,
    scenario: str,
) -> None:
    """The stated check, on every fixture: the two lists can never disagree."""
    call_id = run_scenario(session, settings, blob, scenario)
    email = client.post(f"/api/v1/calls/{call_id}/follow-up").json()

    unsupported = _unsupported_facts(email)
    claims = _claims(email)
    assert len(unsupported) == len(claims)
    assert [s["text"] for s in unsupported] == [c["text"] for c in claims]

    real_ids = _segment_ids(client, call_id)
    for claim in claims:
        assert claim["reason"]
        pointer = claim["contradicting_segment_id"]
        # Absent is allowed. Invented is not.
        assert pointer is None or pointer in real_ids

    # A supported sentence is never also reported as a claim.
    sentences = email["sentences"]
    assert isinstance(sentences, list)
    for sentence in sentences:
        if sentence["supported"]:
            assert sentence["evidence_segment_ids"]
            assert sentence["text"] not in {c["text"] for c in claims}


def test_a_committed_next_meeting_stays_supported_and_reports_nothing(
    client: TestClient, session: Session, settings: Settings, blob: MemoryBlobStore
) -> None:
    call_id = run_scenario(session, settings, blob, "happy_path")
    email = client.post(f"/api/v1/calls/{call_id}/follow-up").json()

    sentences = email["sentences"]
    assert isinstance(sentences, list)
    meeting = [s for s in sentences if s["text"] == NEXT_MEETING_TEXT]
    assert len(meeting) == 1
    assert meeting[0]["supported"] is True
    assert meeting[0]["evidence_segment_ids"]
    assert _claims(email) == []


def test_a_claim_without_a_contradiction_is_reported_with_no_pointer() -> None:
    """Evidence resolution failed and nothing contradicts it: reason yes, pointer no."""
    email = build_follow_up(
        [_insight(InsightType.COMMITMENT, payload={"side": "customer", "action": "next meeting"})],
        customer_name="Sarah",
    )

    claims = _claims(email)
    assert len(claims) == 1
    assert claims[0]["text"] == NEXT_MEETING_TEXT
    assert claims[0]["reason"]
    assert claims[0]["contradicting_segment_id"] is None
    assert len(_unsupported_facts(email)) == 1


def test_a_pointer_the_evidence_gate_did_not_resolve_is_never_returned() -> None:
    """A reality check naming a segment it does not cite proves nothing about this call."""
    ghost = uuid4()
    cited = uuid4()
    email = build_follow_up(
        [
            _insight(InsightType.COMMITMENT, payload={"side": "customer", "action": "next meeting"}),
            _insight(
                InsightType.REALITY_CHECK,
                payload={"reason_code": "NO_EXPLICIT_COMMITMENT", "customer_segment_id": str(ghost)},
                segment_ids=[cited],
            ),
        ],
        customer_name="Sarah",
    )

    claims = _claims(email)
    assert len(claims) == 1
    assert claims[0]["contradicting_segment_id"] is None


def test_a_refused_reality_check_is_not_a_source_of_pointers() -> None:
    """Dropped insights carry no evidence, so they cannot supply one here either."""
    segment = uuid4()
    email = build_follow_up(
        [
            _insight(InsightType.COMMITMENT, payload={"side": "customer", "action": "next meeting"}),
            _insight(
                InsightType.REALITY_CHECK,
                payload={"reason_code": "NO_EXPLICIT_COMMITMENT", "customer_segment_id": str(segment)},
                segment_ids=[segment],
                dropped=True,
            ),
        ],
        customer_name="Sarah",
    )

    assert _claims(email)[0]["contradicting_segment_id"] is None


def test_a_call_with_nothing_to_claim_reports_nothing() -> None:
    """No next meeting was spoken about at all. An absence is not an unsupported claim."""
    email = build_follow_up([], customer_name="Sarah")

    assert _claims(email) == []
    assert _unsupported_facts(email) == []
    sentences = email["sentences"]
    assert isinstance(sentences, list)
    assert all(s["kind"] == "NON_FACTUAL" for s in sentences)


def test_polish_keeps_the_claims_in_step_with_the_sentences() -> None:
    """A rewrite may change the words. It may not lose track of what is unproven."""
    segment = uuid4()
    email = build_follow_up(
        [
            _insight(InsightType.COMMITMENT, payload={"side": "customer", "action": "next meeting"}),
            _insight(
                InsightType.REALITY_CHECK,
                payload={"reason_code": "NO_EXPLICIT_COMMITMENT", "customer_segment_id": str(segment)},
                segment_ids=[segment],
            ),
        ],
        customer_name="Sarah",
    )
    assert _claims(email)[0]["contradicting_segment_id"] == str(segment)

    sentences = email["sentences"]
    assert isinstance(sentences, list)
    rewritten = ["Hello Sarah,", "Thank you for the conversation.", "Looking forward to reconnecting next week."]
    assert len(rewritten) == len(sentences)

    polished = polish_or_fallback(email, "\n".join(rewritten))
    assert polished["polish"] == "applied"

    claims = _claims(polished)
    unsupported = _unsupported_facts(polished)
    assert len(claims) == len(unsupported) == 1
    # The claim tracks the rewritten wording, and keeps the reason and the pointer.
    assert claims[0]["text"] == "Looking forward to reconnecting next week."
    assert claims[0]["text"] == unsupported[0]["text"]
    assert claims[0]["reason"]
    assert claims[0]["contradicting_segment_id"] == str(segment)


def test_a_rejected_polish_keeps_the_original_claims() -> None:
    email = build_follow_up(
        [_insight(InsightType.COMMITMENT, payload={"side": "customer", "action": "next meeting"})],
        customer_name="Sarah",
    )

    polished = polish_or_fallback(email, "one line only")

    assert polished["polish"] == "fallback_sentence_count_mismatch"
    assert len(_claims(polished)) == len(_unsupported_facts(polished)) == 1

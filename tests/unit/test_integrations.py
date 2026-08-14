"""Field-level CRM provenance, and a Slack webhook that never leaves the server.

Two guarantees are under test here, and both are the product rather than a nicety:

1. A CRM field is written only when a stored transcript segment backs it, and it carries the
   segment id that backs it. Everything else is refused *with a reason* — `BLOCKED` when the
   dimension it depends on was never established (absent, weak, or refused by the evidence
   gate), `MANUAL` when nothing customer-attributable could be resolved. `BLOCKED` is asserted
   against `signal_pips` directly, so a hand-maintained list of blocked fields would fail.
2. The Slack webhook is stored server-side and appears in no response body and no log line.
"""

from __future__ import annotations

import logging
from uuid import uuid4

import pytest
from app.api.v1.integrations import BLOCKED, CRM_FIELDS, FIELD_STATES, MANUAL, SUPPORTED
from app.core.enums import InsightType
from app.core.settings import Settings
from app.intelligence.dimensions import signal_pips
from app.models.analysis import AnalysisRun, Insight
from app.models.integrations import SLACK, IntegrationSetting
from app.models.transcript import TranscriptSegment
from app.storage.memory import MemoryBlobStore
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.conftest import run_scenario

WEBHOOK = "https://hooks.slack.com/services/example/webhook/placeholder-not-a-secret"
OTHER_WEBHOOK = "https://hooks.slack.com/services/example/webhook/replacement-placeholder"

#: field name -> the dimension it is gated on, for the fields that have a gate.
GATED: dict[str, str] = {f.name: f.depends_on for f in CRM_FIELDS if f.depends_on is not None}

SCENARIOS = ("happy_path", "pricing_objection", "active_competitor", "seller_overstates_intent")


def _preview(client: TestClient, call_id: object) -> dict:
    response = client.get(f"/api/v1/calls/{call_id}/crm-preview")
    assert response.status_code == 200
    return response.json()


def _field(body: dict, name: str) -> dict:
    return next(item for item in body["fields"] if item["name"] == name)


def _segment_text(session: Session, call_id: object) -> dict[str, str]:
    rows = session.scalars(select(TranscriptSegment).where(TranscriptSegment.call_id == call_id)).all()
    return {str(row.id): row.text for row in rows}


def _pips(session: Session, call_id: object) -> dict[str, str]:
    run = session.scalars(
        select(AnalysisRun).where(AnalysisRun.call_id == call_id).order_by(AnalysisRun.version.desc())
    ).first()
    assert run is not None
    signals = session.scalars(
        select(Insight).where(
            Insight.analysis_run_id == run.id,
            Insight.type == InsightType.QUALIFICATION_SIGNAL,
        )
    ).all()
    return signal_pips(list(signals))


# --- CRM field provenance -----------------------------------------------------------------


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_every_field_is_one_of_three_states_and_carries_its_proof_or_its_reason(
    scenario: str, client: TestClient, session: Session, settings: Settings, blob: MemoryBlobStore
) -> None:
    """The task's stated checks, on four different calls."""
    call_id = run_scenario(session, settings, blob, scenario)
    session.commit()

    body = _preview(client, call_id)
    assert body["call_id"] == str(call_id)
    assert [item["name"] for item in body["fields"]] == [f.name for f in CRM_FIELDS]

    for field in body["fields"]:
        assert field["state"] in FIELD_STATES
        assert set(field) == {"name", "state", "value", "reason", "evidence_segment_ids"}
        if field["state"] == SUPPORTED:
            assert field["evidence_segment_ids"], f"{field['name']} shipped a value with no evidence"
            assert field["value"] is not None
        else:
            assert field["value"] is None, f"{field['name']} is not SUPPORTED but carries a value"
            assert isinstance(field["reason"], str) and field["reason"].strip(), (
                f"{field['name']} refused a write without saying why"
            )


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_blocked_is_derived_from_the_dimension_state_not_from_a_list(
    scenario: str, client: TestClient, session: Session, settings: Settings, blob: MemoryBlobStore
) -> None:
    """BLOCKED must fall out of `signal_pips`, so it cannot drift from the rest of the API.

    A hand-listed set of blocked fields passes the shape checks above and fails this one.
    """
    call_id = run_scenario(session, settings, blob, scenario)
    session.commit()
    pips = _pips(session, call_id)

    for field in _preview(client, call_id)["fields"]:
        dimension = GATED.get(field["name"])
        if dimension is None:
            assert field["state"] != BLOCKED, "an ungated field has no dimension to be blocked by"
            continue
        expected = pips[dimension] != "proven"
        assert (field["state"] == BLOCKED) is expected, (
            f"{field['name']} is {field['state']} while {dimension} is {pips[dimension]}"
        )


def test_a_supported_value_is_verbatim_transcript_text_from_this_call(
    client: TestClient, session: Session, settings: Settings, blob: MemoryBlobStore
) -> None:
    call_id = run_scenario(session, settings, blob, "happy_path")
    session.commit()
    texts = _segment_text(session, call_id)

    body = _preview(client, call_id)
    supported = [item for item in body["fields"] if item["state"] == SUPPORTED]
    assert supported, "the happy path establishes dimensions, so something must be writable"
    for field in supported:
        assert field["evidence_segment_ids"]
        for segment_id in field["evidence_segment_ids"]:
            assert segment_id in texts, "a CRM field cited a segment that is not on this call"
        if isinstance(field["value"], str):
            assert field["value"] in texts.values(), "a CRM note must be transcript text, never a paraphrase"

    note = _field(body, "call_note_why_they_buy")
    assert note["state"] == SUPPORTED
    assert note["reason"] is None
    assert note["value"] == texts[note["evidence_segment_ids"][0]]

    meeting = _field(body, "log_completed_meeting")
    assert meeting["state"] == SUPPORTED
    assert meeting["value"] is True
    assert meeting["evidence_segment_ids"]


def test_log_completed_meeting_blocks_when_the_customer_never_committed(
    client: TestClient, session: Session, settings: Settings, blob: MemoryBlobStore
) -> None:
    call_id = run_scenario(session, settings, blob, "pricing_objection")
    session.commit()
    assert _pips(session, call_id)["next_meeting_committed"] != "proven"

    field = _field(_preview(client, call_id), "log_completed_meeting")
    assert field["state"] == BLOCKED
    assert field["value"] is None
    assert field["reason"] == "The customer did not commit to a next meeting."
    # An absent dimension legitimately cites nothing. Empty is the honest answer, not a bug.
    assert field["evidence_segment_ids"] == []


def test_a_dimension_below_the_threshold_blocks_and_says_so(
    client: TestClient, session: Session, settings: Settings, blob: MemoryBlobStore
) -> None:
    """`weak` is not `proven`. A mention that never cleared the bar must not reach the CRM."""
    call_id = run_scenario(session, settings, blob, "active_competitor")
    session.commit()
    assert _pips(session, call_id)["timeline_identified"] == "weak"

    field = _field(_preview(client, call_id), "deal_close_date")
    assert field["state"] == BLOCKED
    assert "below the evidence threshold" in field["reason"]


def test_a_refused_dimension_blocks_the_field_exactly_like_an_absent_one(
    client: TestClient,
    session: Session,
    settings: Settings,
    blob: MemoryBlobStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Absent or refused is one rule, because a refused claim never becomes an insight.

    The next-meeting signal is made to cite a segment that is not on this call, so the evidence
    gate refuses it. The dimension then reads `missing`, and the field blocks — without the CRM
    layer knowing anything about refusals.
    """
    from app.intelligence import extract as extract_module
    from app.pipeline import runner as runner_module

    real = extract_module.extract_buying_intent

    def cite_a_ghost_segment(segments):  # type: ignore[no-untyped-def]
        out = []
        for candidate in real(segments):
            if candidate.payload.get("dimension") == "next_meeting_committed" and candidate.payload.get("present"):
                out.append(candidate.model_copy(update={"segment_ids": [uuid4()]}))
                continue
            out.append(candidate)
        return out

    monkeypatch.setattr(extract_module, "extract_buying_intent", cite_a_ghost_segment)
    monkeypatch.setattr(runner_module, "extract_buying_intent", cite_a_ghost_segment)
    call_id = run_scenario(session, settings, blob, "happy_path")
    session.commit()

    refusals = client.get(f"/api/v1/calls/{call_id}/refusals").json()
    refused = [row for row in refusals["refusals"] if row["title"] == "next_meeting_committed"]
    assert refused and refused[0]["error_code"] == "EVIDENCE_SEGMENT_MISSING"

    body = _preview(client, call_id)
    field = _field(body, "log_completed_meeting")
    assert field["state"] == BLOCKED
    assert field["reason"]
    assert field["evidence_segment_ids"] == []
    # The segment the refused claim tried to stand on must not surface as evidence anywhere.
    assert refused[0]["attempted_segment_ids"][0] not in str(body)
    # A dimension that did survive the gate still writes its field.
    assert _field(body, "call_note_why_they_buy")["state"] == SUPPORTED


def test_deal_amount_is_manual_and_quotes_the_figure_the_call_actually_contained(
    client: TestClient, session: Session, settings: Settings, blob: MemoryBlobStore
) -> None:
    """A price the rep named is not a price the customer agreed to, so it is never written."""
    call_id = run_scenario(session, settings, blob, "pricing_objection")
    session.commit()
    texts = _segment_text(session, call_id)

    field = _field(_preview(client, call_id), "deal_amount")
    assert field["state"] == MANUAL
    assert field["value"] is None
    assert "800 dollars" in field["reason"]
    assert "quoted by the rep" in field["reason"]
    assert field["evidence_segment_ids"], "the reason cites a figure, so it must cite where it came from"
    for segment_id in field["evidence_segment_ids"]:
        assert segment_id in texts
    # The figure in the reason is transcript text, not a number the API produced.
    assert any("800 dollars" in text for text in texts.values())


def test_deal_amount_is_manual_even_when_every_dimension_is_proven(
    client: TestClient, session: Session, settings: Settings, blob: MemoryBlobStore
) -> None:
    """There is no "price agreed" dimension, so this field is never auto-written at all."""
    call_id = run_scenario(session, settings, blob, "happy_path")
    session.commit()

    field = _field(_preview(client, call_id), "deal_amount")
    assert field["state"] == MANUAL
    assert field["value"] is None
    assert field["reason"]


def test_a_call_with_no_analysis_run_blocks_every_gated_field(client: TestClient) -> None:
    created = client.post("/api/v1/calls", json={"title": "fresh", "customer_name": "Acme"})
    assert created.status_code == 201

    body = _preview(client, created.json()["id"])
    gated = [item for item in body["fields"] if item["name"] in GATED]
    assert len(gated) == len(GATED)
    for field in gated:
        assert field["state"] == BLOCKED
        assert field["reason"] == "This call has no analysis run yet, so no dimension has been observed."
    assert all(item["evidence_segment_ids"] == [] for item in body["fields"])


def test_crm_preview_never_emits_a_score_or_a_probability(
    client: TestClient, session: Session, settings: Settings, blob: MemoryBlobStore
) -> None:
    call_id = run_scenario(session, settings, blob, "happy_path")
    session.commit()

    flat = str(_preview(client, call_id)).lower()
    for banned in ("close_probability", "health_score", "deal_score", "likelihood", "confidence"):
        assert banned not in flat


def test_crm_preview_for_an_unknown_call_is_404(client: TestClient) -> None:
    assert client.get(f"/api/v1/calls/{uuid4()}/crm-preview").status_code == 404


# --- Slack webhook ------------------------------------------------------------------------


def test_posting_the_webhook_reports_configured(client: TestClient) -> None:
    response = client.post("/api/v1/integrations/slack", json={"webhook_url": WEBHOOK})
    assert response.status_code == 200
    assert response.json() == {"configured": True}


def test_the_webhook_is_stored_server_side(client: TestClient, session: Session) -> None:
    assert client.post("/api/v1/integrations/slack", json={"webhook_url": WEBHOOK}).status_code == 200

    session.rollback()
    rows = list(session.scalars(select(IntegrationSetting)).all())
    assert len(rows) == 1
    assert rows[0].provider == SLACK
    # `secret` is deferred: this line is the explicit, greppable load of the credential.
    assert rows[0].secret == WEBHOOK


def test_reconfiguring_replaces_the_single_stored_row(client: TestClient, session: Session) -> None:
    assert client.post("/api/v1/integrations/slack", json={"webhook_url": WEBHOOK}).json() == {"configured": True}
    assert client.post("/api/v1/integrations/slack", json={"webhook_url": OTHER_WEBHOOK}).json() == {"configured": True}

    session.rollback()
    rows = list(session.scalars(select(IntegrationSetting)).all())
    assert len(rows) == 1
    assert rows[0].secret == OTHER_WEBHOOK


def test_get_integrations_reports_booleans_and_never_the_webhook(client: TestClient) -> None:
    """The task's stated check: the response, stringified, must not contain the Slack host."""
    before = client.get("/api/v1/integrations")
    assert before.status_code == 200
    assert before.json() == {SLACK: {"configured": False}}

    client.post("/api/v1/integrations/slack", json={"webhook_url": WEBHOOK})

    after = client.get("/api/v1/integrations")
    assert after.json() == {SLACK: {"configured": True}}
    assert "hooks.slack.com" not in str(after.json())
    assert "hooks.slack.com" not in after.text
    assert WEBHOOK not in after.text


def test_the_webhook_never_appears_in_a_crm_payload_or_a_report(
    client: TestClient, session: Session, settings: Settings, blob: MemoryBlobStore
) -> None:
    call_id = run_scenario(session, settings, blob, "happy_path")
    session.commit()
    assert client.post("/api/v1/integrations/slack", json={"webhook_url": WEBHOOK}).status_code == 200

    for path in (
        f"/api/v1/calls/{call_id}/crm-preview",
        f"/api/v1/calls/{call_id}/report",
        f"/api/v1/calls/{call_id}/insights",
        "/api/v1/integrations",
        "/api/v1/calls",
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "hooks.slack.com" not in response.text, f"{path} leaked the webhook host"
        assert WEBHOOK not in response.text, f"{path} leaked the webhook"


def test_the_webhook_is_never_written_to_a_log_line(client: TestClient, caplog) -> None:
    with caplog.at_level(logging.DEBUG):
        assert client.post("/api/v1/integrations/slack", json={"webhook_url": WEBHOOK}).status_code == 200
        client.get("/api/v1/integrations")
        client.post("/api/v1/integrations/slack", json={"webhook_url": "https://example.com/hook"})

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "hooks.slack.com" not in logged
    assert WEBHOOK not in logged
    assert "example.com/hook" not in logged, "even a rejected URL must not be logged"


@pytest.mark.parametrize(
    "url",
    [
        "http://hooks.slack.com/services/T/B/x",  # not https
        "https://example.com/services/T/B/x",  # not a Slack host
        "https://hooks.slack.com.evil.example/services/T/B/x",  # lookalike host
        "https://hooks.slack.com@evil.example/services/T/B/x",  # userinfo trick
        "https://hooks.slack.com",  # no path, so no webhook
        "not-a-url",
    ],
)
def test_a_url_that_is_not_an_https_slack_webhook_is_a_named_400(url: str, client: TestClient) -> None:
    response = client.post("/api/v1/integrations/slack", json={"webhook_url": url})
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "WEBHOOK_URL_INVALID"
    assert body["error"]["failure_kind"] == "USER_INPUT"
    assert body["error"]["retryable"] is False
    # The rejection explains the rule without echoing what was sent.
    assert url not in response.text


def test_a_rejected_url_is_not_stored(client: TestClient, session: Session) -> None:
    assert client.post("/api/v1/integrations/slack", json={"webhook_url": "https://example.com/x"}).status_code == 400

    session.rollback()
    assert list(session.scalars(select(IntegrationSetting)).all()) == []
    assert client.get("/api/v1/integrations").json() == {SLACK: {"configured": False}}

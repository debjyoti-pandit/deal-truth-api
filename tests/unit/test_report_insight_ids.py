"""API-4: a report card must be able to name the insight row it renders.

GET /insights gives every insight an id. The same insights inside GET /report carried none,
so the UI could not key a card to a row, nor build a stable ?insight=<id> deep link. The
report artifact is built from ValidatedInsight objects, which have no id, so the id is
resolved at read time against the persisted rows — never invented.
"""

from __future__ import annotations

from app.core.settings import Settings
from app.exports.report import INSIGHT_SECTIONS, attach_insight_ids, insight_identity
from app.storage.memory import MemoryBlobStore
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from tests.conftest import run_scenario

# The sections named in the API-4 acceptance criteria. Asserted to be non-empty across the
# scenarios below, so the check can never pass vacuously.
REQUIRED_SECTIONS = ("customer_truth", "objections", "deal_killers", "reality_checks")

SCENARIOS = (
    "happy_path",
    "pricing_objection",
    "security_blocker",
    "no_purchase_timeline",
    "seller_overstates_intent",
)


def test_every_report_insight_carries_its_persisted_insight_id(
    client: TestClient, session: Session, settings: Settings, blob: MemoryBlobStore
) -> None:
    exercised: set[str] = set()
    for scenario in SCENARIOS:
        call_id = run_scenario(session, settings, blob, scenario)
        report = client.get(f"/api/v1/calls/{call_id}/report")
        assert report.status_code == 200
        rows = {row["id"]: row for row in client.get(f"/api/v1/calls/{call_id}/insights").json()}
        assert rows, f"{scenario}: the fixture shipped no insights"

        seen: list[str] = []
        for section in INSIGHT_SECTIONS:
            items = report.json().get(section) or []
            if items:
                exercised.add(section)
            for item in items:
                insight_id = item.get("id")
                assert insight_id, f"{scenario}/{section}: report insight has no id"
                assert insight_id in rows, f"{scenario}/{section}: {insight_id} is not a GET /insights id"
                row = rows[insight_id]
                assert row["type"] == item["type"]
                assert row["title"] == item["title"]
                assert row["summary"] == item["summary"]
                assert sorted(row["segment_ids"]) == sorted(item["segment_ids"])
                seen.append(insight_id)

        assert len(seen) == len(set(seen)), f"{scenario}: one insight id was reused by two cards"
        assert set(seen) == set(rows), f"{scenario}: report and /insights disagree on what shipped"

    missing = set(REQUIRED_SECTIONS) - exercised
    assert not missing, f"required sections never produced an insight: {sorted(missing)}"


def test_export_json_carries_the_same_ids_as_the_report(
    client: TestClient, session: Session, settings: Settings, blob: MemoryBlobStore
) -> None:
    call_id = run_scenario(session, settings, blob, "happy_path")
    report = client.get(f"/api/v1/calls/{call_id}/report").json()
    exported = client.get(f"/api/v1/calls/{call_id}/export/json").json()
    assert exported == report
    ids = [item["id"] for section in INSIGHT_SECTIONS for item in exported.get(section) or []]
    assert ids and all(ids)


def test_identical_insights_are_paired_one_id_each() -> None:
    item = {"type": "OBJECTION", "title": "Pricing", "summary": "Too expensive.", "segment_ids": ["seg-1"]}
    report = {"objections": [dict(item), dict(item)]}
    out = attach_insight_ids(report, {insight_identity(item): ["id-1", "id-2"]})
    assert [card["id"] for card in out["objections"]] == ["id-1", "id-2"]


def test_an_insight_with_no_persisted_row_is_not_given_an_invented_id() -> None:
    report = {
        "customer_truth": [
            {"type": "CUSTOMER_FACT", "title": "Manual routing", "summary": "Six hours a week.", "segment_ids": []}
        ]
    }
    out = attach_insight_ids(report, {})
    assert out["customer_truth"][0]["id"] is None

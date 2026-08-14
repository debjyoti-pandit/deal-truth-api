"""The battlecard has to be about the call it was built from.

Two things are enforced here. A field name must not lie about its contents: `documents_to_send`
promises documents, so a whole sentence of seller pleasantries cannot appear in it — and the
documents it does list must be words the seller actually said. And a card must differ per call:
`primary_goal` and `questions_to_ask` are keyed off the top deal killer and the qualification
dimensions the transcript never supported, so two calls with different evidence get different
coaching. All of it is lookup on fixed text — deterministic, and nothing is invented.
"""

from __future__ import annotations

import re

from app.core.settings import Settings
from app.intelligence.templates import (
    DEAL_KILLER_QUESTIONS,
    DEFAULT_QUESTIONS,
    MISSING_FIELD_QUESTIONS,
    document_mentions,
)
from app.storage.memory import MemoryBlobStore
from fastapi.testclient import TestClient
from fixtures.catalog import SCENARIOS
from sqlalchemy.orm import Session
from tests.conftest import run_scenario

# The exact prose the shipped fixture used to offer as a document to send.
COMMITMENT_PROSE = re.compile(r"Thanks for|walk you through")
MAX_DOCUMENT_CHARS = 90
MAX_DOCUMENT_WORDS = 6


def _battlecard(
    client: TestClient,
    session: Session,
    settings: Settings,
    blob: MemoryBlobStore,
    scenario: str,
) -> dict[str, object]:
    call_id = run_scenario(session, settings, blob, scenario)
    report = client.get(f"/api/v1/calls/{call_id}/report").json()
    card = report["battlecard"]
    assert isinstance(card, dict), scenario
    return card


def _documents(card: dict[str, object]) -> list[str]:
    documents = card["documents_to_send"]
    assert isinstance(documents, list)
    return [str(d) for d in documents]


def _questions(card: dict[str, object]) -> list[str]:
    questions = card["questions_to_ask"]
    assert isinstance(questions, list)
    return [str(q) for q in questions]


def test_documents_to_send_lists_document_names_not_commitment_prose(
    client: TestClient, session: Session, settings: Settings, blob: MemoryBlobStore
) -> None:
    """The task's check 1, on the fixture that used to fail it.

    happy_path has two seller commitments: a pleasantry that names no document, and
    "I will send the SOC2 report by Friday". Only the second one is a document.
    """
    card = _battlecard(client, session, settings, blob, "happy_path")
    documents = _documents(card)

    assert documents == ["SOC2 report"]
    for entry in documents:
        assert len(entry) < MAX_DOCUMENT_CHARS, entry
        assert not COMMITMENT_PROSE.search(entry), entry


def test_no_scenario_ships_a_sentence_as_a_document(
    client: TestClient, session: Session, settings: Settings, blob: MemoryBlobStore
) -> None:
    """Check 1 again, across every fixture, plus: a name is never invented.

    Every entry has to be a verbatim slice of a seller commitment on the same call. An
    empty list is a legitimate answer — most calls name no document — so
    test_documents_to_send_lists_document_names_not_commitment_prose pins the positive case.
    """
    for scenario in SCENARIOS:
        card = _battlecard(client, session, settings, blob, scenario)
        commitments = card["seller_commitments"]
        assert isinstance(commitments, list), scenario
        haystack = " ".join(str(c) for c in commitments)
        for entry in _documents(card):
            assert len(entry) < MAX_DOCUMENT_CHARS, (scenario, entry)
            assert not COMMITMENT_PROSE.search(entry), (scenario, entry)
            assert len(entry.split()) <= MAX_DOCUMENT_WORDS, (scenario, entry)
            assert entry in haystack, (scenario, entry)


def test_seller_commitment_text_ships_under_a_name_that_describes_it(
    client: TestClient, session: Session, settings: Settings, blob: MemoryBlobStore
) -> None:
    """Fixing the label must not lose the content: the raw commitment still ships."""
    card = _battlecard(client, session, settings, blob, "happy_path")
    commitments = card["seller_commitments"]
    assert isinstance(commitments, list)

    pleasantry = "Thanks for taking the time today. I can walk you through how we route calls."
    assert pleasantry in commitments
    assert pleasantry not in _documents(card)
    assert "That is helpful. I will send the SOC2 report by Friday." in commitments


def test_document_names_are_lifted_out_of_the_sentence_that_named_them() -> None:
    """The extractor itself: a document noun plus the qualifier the speaker put on it."""
    assert document_mentions("That is helpful. I will send the SOC2 report by Friday.") == ["SOC2 report"]
    assert document_mentions("I will send the Salesforce integration docs tomorrow.") == ["Salesforce integration docs"]
    assert document_mentions("I will email over our security questionnaire and the statement of work.") == [
        "security questionnaire",
        "statement of work",
    ]
    # No document noun, so nothing to send. The field is allowed to be empty.
    assert document_mentions("Thanks for taking the time today. I can walk you through how we route calls.") == []
    assert document_mentions("Great, we will reconvene next week.") == []


def test_two_different_calls_do_not_produce_identical_battlecards(
    client: TestClient, session: Session, settings: Settings, blob: MemoryBlobStore
) -> None:
    """The task's check 2, literally.

    Weak on its own — the headline alone has always made two cards unequal — so
    test_the_coaching_itself_differs_between_two_calls carries the real weight.
    """
    pricing = _battlecard(client, session, settings, blob, "pricing_objection")
    competitor = _battlecard(client, session, settings, blob, "active_competitor")

    assert pricing != competitor


def test_the_coaching_itself_differs_between_two_calls(
    client: TestClient, session: Session, settings: Settings, blob: MemoryBlobStore
) -> None:
    """Check 2 where it counts.

    A different headline is not a different battlecard. Neither of these calls has a security
    blocker, so under the old two-branch template both shipped the same goal and the same
    three questions; the rep read identical advice for a pricing fight and a bake-off.
    """
    pricing = _battlecard(client, session, settings, blob, "pricing_objection")
    competitor = _battlecard(client, session, settings, blob, "active_competitor")

    assert pricing["primary_goal"] != competitor["primary_goal"]
    assert _questions(pricing) != _questions(competitor)
    assert pricing["top_deal_killer"] == "no_next_meeting"
    assert competitor["top_deal_killer"] == "active_competitor"


def test_questions_come_from_the_top_deal_killer_then_the_missing_fields(
    client: TestClient, session: Session, settings: Settings, blob: MemoryBlobStore
) -> None:
    card = _battlecard(client, session, settings, blob, "security_blocker")
    questions = _questions(card)
    lead = list(DEAL_KILLER_QUESTIONS["security_blocker"])

    assert card["top_deal_killer"] == "security_blocker"
    assert questions[: len(lead)] == lead
    # ...and the card keeps asking about what this call never established.
    tail = questions[len(lead) :]
    assert tail
    assert all(question in MISSING_FIELD_QUESTIONS.values() for question in tail)
    assert questions != list(DEFAULT_QUESTIONS)


def test_every_question_on_every_card_is_templated_never_free_text(
    client: TestClient, session: Session, settings: Settings, blob: MemoryBlobStore
) -> None:
    known = {q for questions in DEAL_KILLER_QUESTIONS.values() for q in questions}
    known |= set(MISSING_FIELD_QUESTIONS.values())
    known |= set(DEFAULT_QUESTIONS)

    for scenario in SCENARIOS:
        card = _battlecard(client, session, settings, blob, scenario)
        questions = _questions(card)
        assert questions, scenario
        assert len(questions) <= 5, scenario
        assert len(set(questions)) == len(questions), scenario
        for question in questions:
            assert question in known, (scenario, question)


def test_the_same_call_always_produces_the_same_battlecard(
    client: TestClient, session: Session, settings: Settings, blob: MemoryBlobStore
) -> None:
    """Differing per call must not mean varying per run."""
    first = _battlecard(client, session, settings, blob, "happy_path")
    second = _battlecard(client, session, settings, blob, "happy_path")

    assert first == second

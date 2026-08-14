"""Deterministic templates for battlecard and manager brief. Generation may polish wording only."""

from __future__ import annotations

import string
from collections.abc import Iterable, Sequence

from app.core.enums import EvidenceStatus, InsightType
from app.intelligence.domain import ValidatedInsight
from app.providers.normalized import NormalizedRecap

# ---------------------------------------------------------------------------------------
# battlecard.documents_to_send
#
# The field used to carry the raw full text of every seller commitment, so a shipped card
# listed "Thanks for taking the time today. I can walk you through how we route calls." as a
# document to send. It now carries only document names lifted verbatim out of the seller's
# own words: if the seller named no document, the list is empty and nothing is invented to
# fill it. The commitment text itself still ships, under a name that describes it —
# `seller_commitments`.
# ---------------------------------------------------------------------------------------

#: Document head nouns. A name is only ever *found* in the transcript, never composed.
DOCUMENT_NOUNS: tuple[str, ...] = (
    "statement of work",
    "security questionnaire",
    "security review documentation",
    "integration guide",
    "implementation plan",
    "onboarding plan",
    "migration plan",
    "pilot plan",
    "trial plan",
    "case study",
    "pricing sheet",
    "price list",
    "order form",
    "api documentation",
    "api docs",
    "release notes",
    "data sheet",
    "one pager",
    "soc 2",
    "documentation",
    "questionnaire",
    "certification",
    "certificate",
    "whitepaper",
    "one-pager",
    "onepager",
    "proposal",
    "contract",
    "agreement",
    "checklist",
    "playbook",
    "template",
    "roadmap",
    "document",
    "documents",
    "invoice",
    "summary",
    "slides",
    "report",
    "policy",
    "agenda",
    "notes",
    "quote",
    "specs",
    "spec",
    "deck",
    "docs",
    "doc",
    "guide",
    "brief",
    "soc2",
    "soc-2",
    "faq",
    "msa",
    "nda",
    "dpa",
    "sow",
    "pdf",
)

#: Words that end the walk backwards from a document noun, so the name picks up "SOC2" out
#: of "I will send the SOC2 report by Friday" and stops before "send the".
_QUALIFIER_STOP: frozenset[str] = frozenset(
    [
        "a",
        "about",
        "across",
        "after",
        "all",
        "also",
        "am",
        "an",
        "and",
        "another",
        "any",
        "are",
        "as",
        "at",
        "attach",
        "attached",
        "attaching",
        "be",
        "been",
        "before",
        "being",
        "both",
        "but",
        "by",
        "can",
        "circulate",
        "could",
        "did",
        "do",
        "does",
        "draft",
        "drafting",
        "drop",
        "each",
        "email",
        "emailed",
        "emailing",
        "every",
        "for",
        "forward",
        "forwarding",
        "from",
        "get",
        "getting",
        "give",
        "giving",
        "glad",
        "go",
        "going",
        "had",
        "happy",
        "has",
        "have",
        "he",
        "her",
        "here",
        "his",
        "how",
        "i",
        "i'll",
        "i've",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "just",
        "let",
        "let's",
        "lets",
        "like",
        "may",
        "me",
        "might",
        "more",
        "must",
        "my",
        "need",
        "next",
        "no",
        "not",
        "now",
        "of",
        "on",
        "or",
        "other",
        "our",
        "out",
        "over",
        "per",
        "ping",
        "please",
        "prepare",
        "preparing",
        "provide",
        "provided",
        "providing",
        "pull",
        "put",
        "send",
        "sending",
        "sent",
        "shall",
        "share",
        "shared",
        "sharing",
        "she",
        "should",
        "so",
        "some",
        "sure",
        "than",
        "that",
        "that's",
        "the",
        "their",
        "them",
        "then",
        "there",
        "there's",
        "these",
        "they",
        "this",
        "those",
        "to",
        "today",
        "tomorrow",
        "tonight",
        "up",
        "us",
        "via",
        "want",
        "was",
        "we",
        "we'll",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "why",
        "will",
        "with",
        "would",
        "write",
        "you",
        "your",
    ]
)

_SENTENCE_END: tuple[str, ...] = (".", "!", "?", ":", ";")
_MAX_QUALIFIERS = 3
_MAX_DOCUMENT_CHARS = 80
_MAX_QUESTIONS = 5

_DOCUMENT_PHRASES: tuple[tuple[str, ...], ...] = tuple(
    sorted((tuple(noun.split()) for noun in DOCUMENT_NOUNS), key=len, reverse=True)
)

# ---------------------------------------------------------------------------------------
# battlecard.primary_goal / battlecard.questions_to_ask
#
# Both used to be static strings picked from a two-branch if, so two different calls shipped
# the same coaching. They are now keyed off what this call actually evidenced: the top deal
# killer's `payload.kind` and the qualification dimensions the transcript never supported.
# Still fully deterministic — every string below is fixed text, chosen by lookup.
# ---------------------------------------------------------------------------------------

#: Evidenced blockers outrank absences: something the customer said outranks something
#: nobody said. Ordering is fixed here so the pick never depends on insight list order.
DEAL_KILLER_PRIORITY: tuple[str, ...] = (
    "explicit_rejection",
    "security_blocker",
    "budget_blocker",
    "technical_blocker",
    "active_competitor",
    "no_next_meeting",
    "no_economic_buyer",
    "no_timeline",
)

DEFAULT_PRIMARY_GOAL = "Advance the deal using only facts the customer stated."

PRIMARY_GOALS: dict[str, str] = {
    "explicit_rejection": "Find out what drove the rejection before spending another call.",
    "security_blocker": "Get the security-review process and owner confirmed.",
    "budget_blocker": "Get the budget owner and the funding process confirmed.",
    "technical_blocker": "Get the open technical questions and their owner confirmed.",
    "active_competitor": "Get their evaluation criteria and the other options confirmed.",
    "no_next_meeting": "Secure an explicit next-meeting commitment.",
    "no_economic_buyer": "Get the budget owner named and into the next conversation.",
    "no_timeline": "Get a concrete decision date confirmed.",
}

#: Questions the top deal killer earns. Absence-based kinds reuse the exact wording of the
#: matching missing-field question below, so the two sources dedupe into one line.
DEAL_KILLER_QUESTIONS: dict[str, tuple[str, ...]] = {
    "explicit_rejection": (
        "What led you to that conclusion?",
        "Is there a version of this that would work for you?",
    ),
    "security_blocker": (
        "Who owns the security approval?",
        "What documentation does that review require?",
        "Can we schedule the security review now?",
    ),
    "budget_blocker": (
        "Who owns the budget for this?",
        "What would have to change for this to get funded?",
    ),
    "technical_blocker": (
        "Which technical questions have to be resolved first?",
        "Who runs that technical review?",
    ),
    "active_competitor": (
        "How will you compare the options you are looking at?",
        "Which capabilities decide that comparison?",
    ),
    "no_next_meeting": (
        "When should we reconvene, and who needs to be there?",
        "What has to happen before that meeting?",
    ),
    "no_economic_buyer": (
        "Who owns the budget for this?",
        "How do we get that person into the next conversation?",
    ),
    "no_timeline": (
        "What date do you need this working by?",
        "What happens between now and that date?",
    ),
}

#: One question per qualification dimension the transcript never supported. Iterated in this
#: order, so the card is stable regardless of how the insights arrive.
MISSING_FIELD_QUESTIONS: dict[str, str] = {
    "pain_identified": "What problem do you need solved first?",
    "business_impact_identified": "What is that costing you today, in time or money?",
    "timeline_identified": "What date do you need this working by?",
    "economic_buyer_identified": "Who owns the budget for this?",
    "decision_maker_identified": "Who else has to say yes?",
    "next_meeting_committed": "When should we reconvene, and who needs to be there?",
    "competitor_active": "What else are you evaluating?",
    "blocker_active": "What could stop this from going ahead?",
}

#: Used only when a call evidenced no deal killer and no missing dimension.
DEFAULT_QUESTIONS: tuple[str, ...] = (
    "Who owns the next approval step?",
    "What documents or access do you need from us?",
    "When should we reconvene with those owners?",
)


def build_battlecard(insights: Sequence[ValidatedInsight], recap: NormalizedRecap | None) -> dict[str, object]:
    objections = [i for i in insights if i.type == InsightType.OBJECTION and not i.dropped]
    risks = [i for i in insights if i.type == InsightType.DEAL_RISK and not i.dropped]
    facts = [i for i in insights if i.type == InsightType.CUSTOMER_FACT and not i.dropped]
    missing_dimensions = [
        str(i.payload.get("dimension") or i.title)
        for i in insights
        if i.type == InsightType.QUALIFICATION_SIGNAL and i.evidence_status == EvidenceStatus.ABSENCE_BASED
    ]
    missing = [d.replace("_", " ") for d in missing_dimensions]
    unsupported = set(missing_dimensions)
    top_killer = _top_deal_killer(risks)
    primary = PRIMARY_GOALS.get(top_killer or "", DEFAULT_PRIMARY_GOAL)
    questions = _dedupe(
        [
            *DEAL_KILLER_QUESTIONS.get(top_killer or "", ()),
            *(question for field, question in MISSING_FIELD_QUESTIONS.items() if field in unsupported),
        ]
    )[:_MAX_QUESTIONS]
    if not questions:
        questions = list(DEFAULT_QUESTIONS)
    objection = objections[0].title if objections else "None observed with evidence"
    seller_commitments = _dedupe(
        text
        for text in (
            i.payload.get("action")
            for i in insights
            if i.type == InsightType.COMMITMENT and i.payload.get("side") == "seller" and not i.dropped
        )
        if isinstance(text, str)
    )
    documents = _dedupe(name for text in seller_commitments for name in document_mentions(text))
    warning = "Do not claim unsupported facts. Every statement in the next call must map to transcript evidence."
    return {
        "primary_goal": primary,
        "questions_to_ask": questions,
        "objection_to_prepare_for": objection,
        "documents_to_send": documents,
        "seller_commitments": seller_commitments,
        "top_deal_killer": top_killer,
        "missing_qualification_fields": missing,
        "warning": warning,
        "headline": recap.headline if recap else None,
        "customer_facts": [f.title for f in facts[:5]],
    }


def document_mentions(text: str) -> list[str]:
    """Document names the speaker actually said, e.g. "SOC2 report" out of a whole sentence.

    Each returned name is a verbatim slice of `text`: a document head noun from
    DOCUMENT_NOUNS plus up to three preceding qualifier words, stopping at articles, verbs,
    and sentence boundaries. A sentence that names no document returns nothing — the point
    of the field is that it lists documents, so it must be allowed to be empty.
    """
    raw = text.split()
    words = [w.strip(string.punctuation) for w in raw]
    lowered = [w.lower() for w in words]
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(lowered):
        length = _phrase_length_at(lowered, index)
        if not length:
            index += 1
            continue
        start = index
        qualifiers = 0
        while start > 0 and qualifiers < _MAX_QUALIFIERS:
            previous = start - 1
            token = words[previous]
            if raw[previous].endswith(_SENTENCE_END):
                break
            if not token or not token[0].isalnum() or lowered[previous] in _QUALIFIER_STOP:
                break
            start = previous
            qualifiers += 1
        spans.append((start, index + length))
        index += length
    out: list[str] = []
    for start, end in spans:
        # "SOC2" inside "SOC2 report" is the same document named twice; keep the longer span.
        if any((s, e) != (start, end) and s <= start and end <= e for s, e in spans):
            continue
        name = " ".join(words[start:end]).strip()
        if name:
            out.append(name[:_MAX_DOCUMENT_CHARS].strip())
    return out


def _phrase_length_at(lowered: Sequence[str], index: int) -> int:
    for phrase in _DOCUMENT_PHRASES:
        length = len(phrase)
        if tuple(lowered[index : index + length]) == phrase:
            return length
    return 0


def _top_deal_killer(risks: Sequence[ValidatedInsight]) -> str | None:
    kinds = {kind for kind in (i.payload.get("kind") for i in risks) if isinstance(kind, str)}
    for kind in DEAL_KILLER_PRIORITY:
        if kind in kinds:
            return kind
    # An unranked kind still has to resolve the same way every time, so sort rather than
    # trusting the order the insights arrived in.
    return sorted(kinds)[0] if kinds else None


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        normalized = " ".join(item.split())
        key = normalized.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(normalized)
    return out


def build_manager_brief(insights: Sequence[ValidatedInsight], recap: NormalizedRecap | None) -> dict[str, object]:
    why_buy = [
        i.summary
        for i in insights
        if i.type == InsightType.CUSTOMER_FACT and i.payload.get("label") in {"pain", "buying_signal"} and not i.dropped
    ]
    why_not = [i.title for i in insights if i.type in {InsightType.OBJECTION, InsightType.DEAL_RISK} and not i.dropped]
    intent = {i.title: bool(i.payload.get("present")) for i in insights if i.type == InsightType.QUALIFICATION_SIGNAL}
    competition = [i.title for i in insights if i.type == InsightType.COMPETITOR and not i.dropped]
    risks = [i for i in insights if i.type == InsightType.DEAL_RISK and not i.dropped]
    biggest = risks[0].title if risks else "None evidenced"
    commitments = [
        i
        for i in insights
        if i.type == InsightType.COMMITMENT and i.payload.get("side") == "customer" and not i.dropped
    ]
    next_move = "Follow the next-call battlecard. Do not invent commitments."
    if any(i.payload.get("kind") == "security_blocker" for i in risks):
        next_move = "Get the security lead into the next call."
    return {
        "why_they_buy": why_buy,
        "why_they_do_not": why_not,
        "buying_intent": intent,
        "competition": competition,
        "biggest_risk": biggest,
        "customer_commitment": "present" if commitments else "weak",
        "recommended_next_move": next_move,
        "headline": recap.headline if recap else None,
        "tldr": recap.tldr if recap else None,
    }

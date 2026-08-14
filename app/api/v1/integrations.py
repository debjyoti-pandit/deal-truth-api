"""CRM field provenance, and the Slack webhook the server stores.

Every other conversation tool writes the model's output straight into the CRM and inherits its
hallucinations. This refuses per field, with the quote: a field is written only when a stored
transcript segment backs it, and the segment ids travel with the value.

`state` is derived by one rule. Nothing here is hand-listed:

    BLOCKED    the dimension the field depends on is not established on the latest analysis
               run — absent, weak, or refused by the evidence gate. The dimension states come
               from `app.intelligence.dimensions.signal_pips`, the same function the call list
               and the deal timeline read. This module never re-derives them.
    MANUAL     the gate passed (or the field has no gate) but no customer-attributable value
               could be resolved from stored transcript text. A human decides, and the reason
               says what was found instead.
    SUPPORTED  a value was resolved out of stored segments, and those segment ids are returned
               beside it.

A SUPPORTED field with no evidence is structurally impossible: every resolver reads its value
out of segment text, so no segments means no value, which is MANUAL. `_field_payload` checks
it once more anyway — this is the product invariant, not a nicety.

The Slack half of the file stores a credential and is written to leak nothing: the URL is
never returned by a GET, never put in a CRM payload, never logged, and never placed in an
error message or `details` (see `WebhookURLInvalid`).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AppContainer, get_container, get_sync_session, require_auth
from app.core.enums import FailureKind, InsightType, SpeakerRole
from app.core.errors import NamedError, NotFoundError
from app.core.settings import Settings
from app.intelligence.dimensions import signal_pips
from app.models.analysis import AnalysisRun, Insight
from app.models.call import Call
from app.models.evidence import EvidenceLink
from app.models.integrations import SLACK, IntegrationSetting
from app.models.transcript import Speaker, TranscriptSegment

router = APIRouter(prefix="/api/v1", tags=["integrations"], dependencies=[Depends(require_auth)])

# --- CRM field provenance ---------------------------------------------------------------

#: The three states a CRM field can be in. Written to the CRM: SUPPORTED only.
SUPPORTED = "SUPPORTED"
MANUAL = "MANUAL"
BLOCKED = "BLOCKED"
FIELD_STATES: tuple[str, ...] = (SUPPORTED, MANUAL, BLOCKED)

#: The dimension state that unblocks a field. Every gate below is a positive dimension, where
#: `proven` means established. An adverse dimension (`competitor_active`, `blocker_active`)
#: never reads `proven` — presence reads `blocked` — so a future field gated on one has to
#: declare its own establishing state rather than reuse this.
_ESTABLISHED = "proven"

#: (sentence for `missing`, noun phrase reused by the `weak` sentence), per gate dimension.
#: The wording is written once here; which of the two a field gets is derived from the state.
_GATE_LANGUAGE: dict[str, tuple[str, str]] = {
    "pain_identified": (
        "The customer never described a problem the transcript can stand behind.",
        "a customer pain",
    ),
    "business_impact_identified": (
        "The customer never put a number on what the problem costs them.",
        "a quantified business impact",
    ),
    "timeline_identified": ("The customer never stated a purchase timeline.", "a purchase timeline"),
    "decision_maker_identified": ("The customer never said who makes this decision.", "the decision maker"),
    "economic_buyer_identified": ("The customer never said who owns the budget.", "the economic buyer"),
    "next_meeting_committed": ("The customer did not commit to a next meeting.", "a next meeting"),
}

_NO_RUN_REASON = "This call has no analysis run yet, so no dimension has been observed."
_UNTRACEABLE_REASON = "No transcript segment could be resolved for this field, so nothing is written."

_SPEAKER_WORD: dict[SpeakerRole, str] = {
    SpeakerRole.SELLER: "the rep",
    SpeakerRole.CUSTOMER: "the customer",
    SpeakerRole.UNKNOWN: "a speaker on the call",
}

_MONTHS = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?"
    r"|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)
#: An explicit calendar date. "Next week" deliberately does not match — converting a relative
#: phrase into a CRM date is a judgement, and this module does not make judgements.
_DATE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b"
    r"|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"
    rf"|\b(?:{_MONTHS})\s+\d{{1,2}}(?:st|nd|rd|th)?\b"
    rf"|\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{_MONTHS})\b",
    re.IGNORECASE,
)
#: A figure with an explicit currency marker. A bare number is not money — "6 hours a week"
#: must never be read as a price.
_MONEY = re.compile(
    r"[$€£]\s?\d[\d,]*(?:\.\d+)?(?:\s?[km]\b)?"
    r"|\b\d[\d,]*(?:\.\d+)?\s*(?:dollars?|usd|euros?|pounds?|gbp|eur)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _Evidence:
    """A stored transcript segment. The only thing a value may be built out of."""

    segment_id: str
    text: str
    speaker_role: SpeakerRole


@dataclass(frozen=True)
class _Context:
    #: Segments that established the field's gate dimension, in evidence order.
    evidence: tuple[_Evidence, ...]
    #: Every segment on the call, in transcript order.
    segments: tuple[_Evidence, ...]


#: (value, evidence segment ids, reason). `value is None` means the field is not writable and
#: the reason explains why; the ids stay populated so the UI can show what was found instead.
_Resolved = tuple[object | None, list[str], str]


def _customer_quote(ctx: _Context) -> _Resolved:
    """The customer's own words, verbatim from the segment that established the dimension."""
    if not ctx.evidence:
        return None, [], _UNTRACEABLE_REASON
    return ctx.evidence[0].text, [e.segment_id for e in ctx.evidence], ""


def _flag(ctx: _Context) -> _Resolved:
    """A boolean the CRM can set, true only because a segment proves it."""
    if not ctx.evidence:
        return None, [], _UNTRACEABLE_REASON
    return True, [e.segment_id for e in ctx.evidence], ""


def _explicit_date(ctx: _Context) -> _Resolved:
    """A calendar date, only if the customer actually said one."""
    for item in ctx.evidence:
        found = _DATE.search(item.text)
        if found:
            return found.group(0), [item.segment_id], ""
    return (
        None,
        [e.segment_id for e in ctx.evidence],
        "The customer gave a timeline in words, not a date. Turning that into a close date is a "
        "judgement, so it is left for a human.",
    )


def _agreed_amount(ctx: _Context) -> _Resolved:
    """Never writable. A figure that was said is not a figure that was agreed.

    There is no dimension for "price accepted", which is the point: this field has no gate to
    pass and no value to resolve, so it lands MANUAL every time — with whatever figure the call
    did contain cited verbatim, so the rep can see exactly what the number came from.
    """
    priced = [(item, match) for item in ctx.segments if (match := _MONEY.search(item.text))]
    if not priced:
        return None, [], "Nothing in the transcript establishes an agreed amount, and no figure was named on the call."
    first, match = priced[0]
    return (
        None,
        [item.segment_id for item, _ in priced],
        f'Nothing in the transcript establishes an agreed amount. "{match.group(0)}" was quoted by '
        f"{_SPEAKER_WORD.get(first.speaker_role, _SPEAKER_WORD[SpeakerRole.UNKNOWN])}; a figure that was "
        "said is not a figure that was agreed.",
    )


@dataclass(frozen=True)
class _CrmField:
    #: The CRM property name. Stable — the UI and any CRM mapping key on it.
    name: str
    #: The dimension that must be established before the field may be written at all, or None
    #: for a field that is never auto-written.
    depends_on: str | None
    resolve: Callable[[_Context], _Resolved]


#: The CRM payload. Order is the render order; every field is always present, because a field
#: that silently disappears is a field nobody notices was refused.
CRM_FIELDS: tuple[_CrmField, ...] = (
    _CrmField("call_note_why_they_buy", "pain_identified", _customer_quote),
    _CrmField("call_note_business_impact", "business_impact_identified", _customer_quote),
    _CrmField("deal_close_date", "timeline_identified", _explicit_date),
    _CrmField("deal_amount", None, _agreed_amount),
    _CrmField("contact_is_decision_maker", "decision_maker_identified", _flag),
    _CrmField("contact_is_economic_buyer", "economic_buyer_identified", _flag),
    _CrmField("log_completed_meeting", "next_meeting_committed", _flag),
)


def _gate_reason(dimension: str, state: str) -> str:
    spoken = dimension.replace("_", " ")
    absent, subject = _GATE_LANGUAGE.get(dimension, (f"No customer evidence established {spoken}.", spoken))
    if state == "weak":
        return f"{subject.capitalize()} came up on the call but stayed below the evidence threshold."
    return absent


def _row(field: _CrmField, state: str, value: object | None, reason: str | None, ids: list[str]) -> dict[str, object]:
    return {
        "name": field.name,
        "state": state,
        "value": value,
        "reason": reason,
        "evidence_segment_ids": ids,
    }


def _field_payload(
    field: _CrmField,
    *,
    has_run: bool,
    states: dict[str, str],
    evidence_by_dimension: dict[str, tuple[_Evidence, ...]],
    segments: tuple[_Evidence, ...],
) -> dict[str, object]:
    evidence = evidence_by_dimension.get(field.depends_on or "", ())
    if field.depends_on is not None:
        if not has_run:
            return _row(field, BLOCKED, None, _NO_RUN_REASON, [])
        state = states.get(field.depends_on, "missing")
        if state != _ESTABLISHED:
            # An absent dimension legitimately cites nothing. That empty list is the honest
            # answer, not a missing value.
            return _row(field, BLOCKED, None, _gate_reason(field.depends_on, state), [e.segment_id for e in evidence])
    value, ids, reason = field.resolve(_Context(evidence=evidence, segments=segments))
    if value is None or not ids:
        # `not ids` is the belt to the resolvers' braces: a value that cannot name the segment
        # it came from is not evidence, and must never ship as SUPPORTED.
        return _row(field, MANUAL, None, reason or _UNTRACEABLE_REASON, ids)
    return _row(field, SUPPORTED, value, None, ids)


def _latest_run(session: Session, call_id: UUID) -> AnalysisRun | None:
    return session.scalars(
        select(AnalysisRun).where(AnalysisRun.call_id == call_id).order_by(AnalysisRun.version.desc())
    ).first()


def _qualification_signals(session: Session, run: AnalysisRun | None) -> list[Insight]:
    if run is None:
        return []
    return list(
        session.scalars(
            select(Insight).where(
                Insight.analysis_run_id == run.id,
                Insight.type == InsightType.QUALIFICATION_SIGNAL,
            )
        ).all()
    )


def _dimension_of(signal: Insight) -> str:
    """Same key signal_pips uses, so evidence and state can never disagree about a dimension."""
    payload = signal.payload or {}
    return str(payload.get("dimension") or signal.title or "")


def _evidence_by_dimension(session: Session, signals: list[Insight]) -> dict[str, tuple[_Evidence, ...]]:
    """Resolve each dimension's segments at read time, joining transcript_segments for the text.

    The join is the invariant: `evidence_links` stores no quote, so a value built from it
    cannot be a fabricated one. A link whose segment has gone yields no row, so it yields no
    quote and no claim.
    """
    dimension_by_insight = {signal.id: _dimension_of(signal) for signal in signals}
    if not dimension_by_insight:
        return {}
    rows = session.execute(
        select(
            EvidenceLink.insight_id,
            TranscriptSegment.id,
            TranscriptSegment.text,
            Speaker.role,
        )
        .join(TranscriptSegment, EvidenceLink.transcript_segment_id == TranscriptSegment.id)
        .join(Speaker, TranscriptSegment.speaker_id == Speaker.id, isouter=True)
        .where(EvidenceLink.insight_id.in_(list(dimension_by_insight)))
        .order_by(EvidenceLink.sort_order)
    ).all()
    out: dict[str, list[_Evidence]] = {}
    for insight_id, segment_id, text, role in rows:
        dimension = dimension_by_insight.get(insight_id)
        if not dimension:
            continue
        out.setdefault(dimension, []).append(
            _Evidence(segment_id=str(segment_id), text=text, speaker_role=SpeakerRole(role or SpeakerRole.UNKNOWN))
        )
    return {dimension: tuple(items) for dimension, items in out.items()}


def _call_segments(session: Session, call_id: UUID) -> tuple[_Evidence, ...]:
    rows = session.execute(
        select(TranscriptSegment.id, TranscriptSegment.text, Speaker.role)
        .join(Speaker, TranscriptSegment.speaker_id == Speaker.id, isouter=True)
        .where(TranscriptSegment.call_id == call_id)
        .order_by(TranscriptSegment.sequence_number)
    ).all()
    return tuple(
        _Evidence(segment_id=str(row[0]), text=row[1], speaker_role=SpeakerRole(row[2] or SpeakerRole.UNKNOWN))
        for row in rows
    )


@router.get("/calls/{call_id}/crm-preview")
def crm_preview(call_id: UUID, session: Session = Depends(get_sync_session)) -> dict[str, object]:
    """The CRM payload with per-field provenance: what would be written, and what would not.

    No readiness gate, deliberately — like `/refusals` and unlike `/report`. A call with no
    analysis run answers "every field is blocked, nothing has been observed", which is true and
    renderable; a 409 would only make the panel disappear.
    """
    call = session.get(Call, call_id)
    if call is None:
        raise NotFoundError("Call not found")
    run = _latest_run(session, call.id)
    signals = _qualification_signals(session, run)
    states = signal_pips(signals)
    evidence = _evidence_by_dimension(session, signals)
    segments = _call_segments(session, call.id)
    return {
        "call_id": str(call.id),
        "fields": [
            _field_payload(
                field,
                has_run=run is not None,
                states=states,
                evidence_by_dimension=evidence,
                segments=segments,
            )
            for field in CRM_FIELDS
        ],
    }


# --- Slack webhook (stored server-side, never returned) -----------------------------------


class WebhookURLInvalid(NamedError):
    """A named 400 for a webhook URL that is not an https `hooks.slack.com` URL.

    The message and `details` are fixed strings and never contain the rejected URL: the error
    handler logs `message` and returns `details` to the caller, so putting the URL in either
    would defeat the point of storing it server-side.
    """

    code = "WEBHOOK_URL_INVALID"
    http_status = 400
    retryable = False
    failure_kind = FailureKind.USER_INPUT


class SlackWebhookIn(BaseModel):
    #: Plain `str`, not `HttpUrl`: the rejection has to be our named 400, not pydantic's 422.
    webhook_url: str = Field(min_length=1, max_length=2048)


def _validated_slack_webhook(raw: str, settings: Settings) -> str:
    url = raw.strip()
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise WebhookURLInvalid("Slack webhook URL must use https", details={"reason": "scheme"})
    # `hostname` (not `netloc`) so `https://hooks.slack.com@evil.example/x` is read as the host
    # a browser would read it as, and rejected.
    if (parsed.hostname or "").lower() not in settings.slack_webhook_host_set:
        raise WebhookURLInvalid("Slack webhook URL must point at a Slack webhook host", details={"reason": "host"})
    if not parsed.path.strip("/"):
        raise WebhookURLInvalid("Slack webhook URL is missing its path", details={"reason": "path"})
    return url


@router.post("/integrations/slack")
def configure_slack(
    body: SlackWebhookIn,
    session: Session = Depends(get_sync_session),
    container: AppContainer = Depends(get_container),
) -> dict[str, bool]:
    """Store the Slack incoming-webhook URL server-side. Idempotent: re-posting replaces it.

    The URL is written to `integration_settings.secret` and nowhere else. It is not logged, not
    echoed, and not returned by any endpoint — the response says whether it worked, and nothing
    more.
    """
    url = _validated_slack_webhook(body.webhook_url, container.settings)
    row = session.scalar(select(IntegrationSetting).where(IntegrationSetting.provider == SLACK))
    if row is None:
        session.add(IntegrationSetting(provider=SLACK, secret=url))
    else:
        row.secret = url
    return {"configured": True}


@router.get("/integrations")
def get_integrations(session: Session = Depends(get_sync_session)) -> dict[str, dict[str, bool]]:
    """What is configured — booleans only, never the credential.

    The query selects `provider` alone, so the secret is not merely omitted from the response:
    it is never read out of the database on this path.
    """
    configured = set(session.scalars(select(IntegrationSetting.provider)).all())
    return {SLACK: {"configured": SLACK in configured}}

"""Cross-call lexical search (Postgres FTS + SQLite ILIKE fallback)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.core.enums import CallStatus, InsightType, SpeakerRole
from app.models.analysis import AnalysisRun, Insight
from app.models.call import Call
from app.models.transcript import Speaker, TranscriptSegment


def _parse_statuses(raw: str | None) -> list[CallStatus] | None:
    if not raw:
        return None
    out: list[CallStatus] = []
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        try:
            out.append(CallStatus(token.upper()))
        except ValueError as exc:
            raise ValueError(f"Invalid call status filter value: {token}") from exc
    return out or None


def _parse_insight_types(raw: str | None) -> list[InsightType] | None:
    if not raw:
        return None
    out: list[InsightType] = []
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        try:
            out.append(InsightType(token.upper()))
        except ValueError as exc:
            raise ValueError(f"Invalid insight type filter value: {token}") from exc
    return out or None


def _day_start(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=UTC)


def _day_end(d: date) -> datetime:
    return datetime.combine(d, time.max, tzinfo=UTC)


def _is_postgres(session: Session) -> bool:
    return session.get_bind().dialect.name == "postgresql"


def search_calls(
    session: Session,
    *,
    q: str,
    limit: int = 10,
    status: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    call_id: UUID | None = None,
    speaker_role: SpeakerRole | None = None,
    types: str | None = None,
) -> dict[str, object]:
    """Ranked FTS on Postgres; ILIKE on SQLite. Filters apply to all groups where relevant."""
    statuses = _parse_statuses(status)
    insight_types = _parse_insight_types(types)
    use_fts = _is_postgres(session)

    insights = _search_insights(
        session,
        q=q,
        limit=limit,
        statuses=statuses,
        from_date=from_date,
        to_date=to_date,
        call_id=call_id,
        insight_types=insight_types,
        use_fts=use_fts,
    )
    segments = _search_segments(
        session,
        q=q,
        limit=limit,
        statuses=statuses,
        from_date=from_date,
        to_date=to_date,
        call_id=call_id,
        speaker_role=speaker_role,
        use_fts=use_fts,
    )
    calls = _search_call_rows(
        session,
        q=q,
        limit=limit,
        statuses=statuses,
        from_date=from_date,
        to_date=to_date,
        call_id=call_id,
    )
    return {
        "query": q,
        "groups": {"insights": insights, "segments": segments, "calls": calls},
        "total": len(insights) + len(segments) + len(calls),
    }


def _call_filters(
    *,
    statuses: list[CallStatus] | None,
    from_date: date | None,
    to_date: date | None,
    call_id: UUID | None,
) -> list[ColumnElement[bool]]:
    clauses: list[ColumnElement[bool]] = []
    if call_id is not None:
        clauses.append(Call.id == call_id)
    if statuses:
        clauses.append(Call.status.in_(statuses))
    if from_date is not None:
        clauses.append(Call.created_at >= _day_start(from_date))
    if to_date is not None:
        clauses.append(Call.created_at <= _day_end(to_date))
    return clauses


def _search_insights(
    session: Session,
    *,
    q: str,
    limit: int,
    statuses: list[CallStatus] | None,
    from_date: date | None,
    to_date: date | None,
    call_id: UUID | None,
    insight_types: list[InsightType] | None,
    use_fts: bool,
) -> list[dict[str, object]]:
    call_clauses = _call_filters(statuses=statuses, from_date=from_date, to_date=to_date, call_id=call_id)
    base = (
        select(Insight, AnalysisRun.call_id, Call.title)
        .join(AnalysisRun, Insight.analysis_run_id == AnalysisRun.id)
        .join(Call, AnalysisRun.call_id == Call.id)
    )
    for clause in call_clauses:
        base = base.where(clause)
    if insight_types:
        base = base.where(Insight.type.in_(insight_types))

    if use_fts:
        rows = _insights_fts(session, base, q=q, limit=limit)
        if not rows:
            rows = _insights_ilike(session, base, q=q, limit=limit)
    else:
        rows = _insights_ilike(session, base, q=q, limit=limit)

    return [
        {
            "id": str(insight.id),
            "call_id": str(cid),
            "call_title": title,
            "type": insight.type.value,
            "title": insight.title,
            "summary": insight.summary,
            "evidence_status": insight.evidence_status.value,
        }
        for insight, cid, title in rows
    ]


def _insights_ilike(session: Session, base, *, q: str, limit: int):
    like = f"%{q.lower()}%"
    stmt = (
        base.where(
            or_(
                func.lower(func.coalesce(Insight.title, "")).like(like),
                func.lower(func.coalesce(Insight.summary, "")).like(like),
            )
        )
        .order_by(Insight.confidence.desc())
        .limit(limit)
    )
    return session.execute(stmt).all()


def _insights_fts(session: Session, base, *, q: str, limit: int):
    tsquery = func.websearch_to_tsquery("english", q)
    rank = func.ts_rank(Insight.text_search, tsquery)
    stmt = (
        base.where(Insight.text_search.op("@@")(tsquery)).order_by(rank.desc(), Insight.confidence.desc()).limit(limit)
    )
    return session.execute(stmt).all()


def _search_segments(
    session: Session,
    *,
    q: str,
    limit: int,
    statuses: list[CallStatus] | None,
    from_date: date | None,
    to_date: date | None,
    call_id: UUID | None,
    speaker_role: SpeakerRole | None,
    use_fts: bool,
) -> list[dict[str, object]]:
    call_clauses = _call_filters(statuses=statuses, from_date=from_date, to_date=to_date, call_id=call_id)
    base = (
        select(TranscriptSegment, Speaker.role)
        .outerjoin(Speaker, TranscriptSegment.speaker_id == Speaker.id)
        .join(Call, TranscriptSegment.call_id == Call.id)
    )
    for clause in call_clauses:
        base = base.where(clause)
    if speaker_role is not None:
        base = base.where(Speaker.role == speaker_role)

    if use_fts:
        rows = _segments_fts(session, base, q=q, limit=limit)
        if not rows:
            rows = _segments_ilike(session, base, q=q, limit=limit)
    else:
        rows = _segments_ilike(session, base, q=q, limit=limit)

    return [
        {
            "id": str(seg.id),
            "call_id": str(seg.call_id),
            "text": seg.text,
            "start_ms": seg.start_ms,
            "end_ms": seg.end_ms,
            "sequence_number": seg.sequence_number,
            "speaker_role": role.value if role is not None else None,
        }
        for seg, role in rows
    ]


def _segments_ilike(session: Session, base, *, q: str, limit: int):
    like = f"%{q.lower()}%"
    stmt = (
        base.where(func.lower(TranscriptSegment.text).like(like))
        .order_by(TranscriptSegment.start_ms.asc())
        .limit(limit)
    )
    return session.execute(stmt).all()


def _segments_fts(session: Session, base, *, q: str, limit: int):
    tsquery = func.websearch_to_tsquery("english", q)
    rank = func.ts_rank(TranscriptSegment.text_search, tsquery)
    # Prefer FTS; short tokens may miss — caller falls back to ILIKE/trgm.
    match = TranscriptSegment.text_search.op("@@")(tsquery)
    # Also allow trigram similarity via ILIKE OR when the query is short.
    like = f"%{q}%"
    trgm = TranscriptSegment.text.ilike(like)
    stmt = base.where(or_(match, trgm)).order_by(rank.desc(), TranscriptSegment.start_ms.asc()).limit(limit)
    return session.execute(stmt).all()


def _search_call_rows(
    session: Session,
    *,
    q: str,
    limit: int,
    statuses: list[CallStatus] | None,
    from_date: date | None,
    to_date: date | None,
    call_id: UUID | None,
) -> list[dict[str, object]]:
    like = f"%{q.lower()}%"
    stmt = select(Call).where(
        or_(
            func.lower(func.coalesce(Call.title, "")).like(like),
            func.lower(func.coalesce(Call.customer_name, "")).like(like),
            func.lower(func.coalesce(Call.rep_name, "")).like(like),
        )
    )
    for clause in _call_filters(statuses=statuses, from_date=from_date, to_date=to_date, call_id=call_id):
        stmt = stmt.where(clause)
    stmt = stmt.order_by(Call.created_at.desc()).limit(limit)
    rows = session.scalars(stmt).all()
    return [
        {
            "id": str(c.id),
            "title": c.title,
            "customer_name": c.customer_name,
            "status": c.status.value,
        }
        for c in rows
    ]

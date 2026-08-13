"""Postgres FTS indexes and ranked search. Skipped unless RUN_INTEGRATION_TESTS=1."""

from __future__ import annotations

import os
import uuid

import pytest
from app.core.enums import CallStatus, SourceType
from app.intelligence.search import search_calls
from app.models.call import Call
from app.models.transcript import TranscriptSegment
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration

_SKIP = os.environ.get("RUN_INTEGRATION_TESTS") != "1"
_URL = os.environ.get(
    "DATABASE_SYNC_URL",
    "postgresql+psycopg://deal_truth:deal_truth@localhost:5432/deal_truth",
)


@pytest.mark.skipif(_SKIP, reason="integration tests disabled")
def test_fts_indexes_exist() -> None:
    engine = create_engine(_URL)
    with engine.connect() as conn:
        indexes = {
            row[0]
            for row in conn.execute(
                text(
                    """
                    SELECT indexname FROM pg_indexes
                    WHERE tablename IN ('transcript_segments', 'insights')
                    """
                )
            )
        }
        assert "ix_transcript_segments_text_search" in indexes
        assert "ix_transcript_segments_text_trgm" in indexes
        assert "ix_insights_text_search" in indexes

        cols = {
            row[0]
            for row in conn.execute(
                text(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'transcript_segments' AND column_name = 'text_search'
                    """
                )
            )
        }
        assert "text_search" in cols


@pytest.mark.skipif(_SKIP, reason="integration tests disabled")
def test_fts_ranks_matching_segments() -> None:
    engine = create_engine(_URL)
    call_id = uuid.uuid4()
    seg_hi = uuid.uuid4()
    seg_lo = uuid.uuid4()

    with Session(engine) as session:
        session.add(
            Call(
                id=call_id,
                public_call_id=f"fts-{call_id.hex[:10]}",
                title="FTS probe",
                customer_name="Acme",
                status=CallStatus.SHIPPED,
                source_type=SourceType.UPLOAD,
            )
        )
        session.add(
            TranscriptSegment(
                id=seg_hi,
                call_id=call_id,
                provider_segment_id="fts-1",
                start_ms=0,
                end_ms=1000,
                text="Customer asked about SOC2 and compliance paperwork repeatedly.",
                sequence_number=1,
            )
        )
        session.add(
            TranscriptSegment(
                id=seg_lo,
                call_id=call_id,
                provider_segment_id="fts-2",
                start_ms=1000,
                end_ms=2000,
                text="Thanks for joining the call today.",
                sequence_number=2,
            )
        )
        session.commit()

        try:
            result = search_calls(session, q="SOC2 compliance", limit=10, call_id=call_id)
            segments = result["groups"]["segments"]  # type: ignore[index]
            assert segments
            assert segments[0]["id"] == str(seg_hi)
            if len(segments) > 1:
                assert segments[0]["id"] != str(seg_lo)
        finally:
            session.execute(text("DELETE FROM transcript_segments WHERE call_id = :cid"), {"cid": call_id})
            session.execute(text("DELETE FROM calls WHERE id = :cid"), {"cid": call_id})
            session.commit()

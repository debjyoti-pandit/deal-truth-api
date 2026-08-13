from __future__ import annotations

from uuid import uuid4

import pytest
from app.core.enums import CallDirection, CallStatus, RecordingMode
from app.core.errors import MLResponseInvalid
from app.models.call import Call
from app.models.types import EmbeddingVector
from app.pipeline.persist import persist_chunks
from sqlalchemy.orm import Session


def test_pgvector_column_matches_qwen3_embedding() -> None:
    assert EmbeddingVector.dim == 1024


def test_persist_chunks_rejects_wrong_embedding_dim(session: Session) -> None:
    call = Call(
        public_call_id=uuid4().hex[:12],
        call_direction=CallDirection.OUTBOUND,
        recording_mode=RecordingMode.MONO,
        status=CallStatus.CREATED,
        extra={},
    )
    session.add(call)
    session.flush()
    with pytest.raises(MLResponseInvalid) as exc:
        persist_chunks(
            session,
            call,
            [
                {
                    "start_segment_id": str(uuid4()),
                    "end_segment_id": str(uuid4()),
                    "text": "hello",
                }
            ],
            [[0.0] * 384],
        )
    assert exc.value.details["expected"] == 1024
    assert exc.value.details["got"] == 384

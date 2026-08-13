"""Call state machine."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.enums import (
    TERMINAL_CALL_STATUSES,
    CallStatus,
    EventState,
    FailureKind,
    TerminalOutcome,
)
from app.core.errors import CallCancelled, ConflictError
from app.models.call import Call
from app.models.events import ProcessingEvent

logger = logging.getLogger(__name__)

ALLOWED: dict[CallStatus, set[CallStatus]] = {
    CallStatus.CREATED: {CallStatus.UPLOADING, CallStatus.QUEUED, CallStatus.CANCELLED, CallStatus.FAILED},
    CallStatus.UPLOADING: {CallStatus.QUEUED, CallStatus.FAILED, CallStatus.CANCELLED},
    CallStatus.QUEUED: {CallStatus.TRANSCRIBING, CallStatus.CANCELLED, CallStatus.FAILED},
    CallStatus.TRANSCRIBING: {
        CallStatus.WAITING_FOR_RECAP,
        CallStatus.ANALYZING,
        CallStatus.FAILED,
        CallStatus.CANCELLED,
    },
    CallStatus.WAITING_FOR_RECAP: {CallStatus.ANALYZING, CallStatus.PARTIAL, CallStatus.FAILED, CallStatus.CANCELLED},
    CallStatus.ANALYZING: {CallStatus.VALIDATING, CallStatus.FAILED, CallStatus.CANCELLED},
    CallStatus.VALIDATING: {CallStatus.INDEXING, CallStatus.FAILED, CallStatus.CANCELLED},
    CallStatus.INDEXING: {CallStatus.BUILDING_REPORT, CallStatus.FAILED, CallStatus.CANCELLED},
    CallStatus.BUILDING_REPORT: {CallStatus.SHIPPED, CallStatus.PARTIAL, CallStatus.FAILED},
    CallStatus.SHIPPED: {CallStatus.ANALYZING},
    CallStatus.PARTIAL: {CallStatus.ANALYZING, CallStatus.QUEUED},
    CallStatus.FAILED: {CallStatus.QUEUED, CallStatus.ANALYZING},
    CallStatus.CANCELLED: set(),
}


def transition(session: Session, call: Call, target: CallStatus, *, failure_kind: FailureKind | None = None) -> Call:
    current = CallStatus(call.status)
    if current in TERMINAL_CALL_STATUSES and target not in ALLOWED.get(current, set()):
        if current == CallStatus.CANCELLED:
            raise CallCancelled("Call is cancelled")
        raise ConflictError(f"Cannot transition from {current.value} to {target.value}")
    if target != current and target not in ALLOWED.get(current, set()):
        raise ConflictError(f"Illegal state transition {current.value} -> {target.value}")
    if target != current:
        logger.info(
            "call_transition call_id=%s from=%s to=%s failure_kind=%s",
            call.id,
            current.value,
            target.value,
            failure_kind.value if failure_kind else None,
        )
    call.status = target
    if target in TERMINAL_CALL_STATUSES:
        call.terminal_outcome = TerminalOutcome(target.value)
        call.completed_at = datetime.now(UTC)
        if failure_kind:
            call.failure_kind = failure_kind
    session.add(call)
    return call


def log_event(
    session: Session,
    call: Call,
    *,
    stage: str,
    state: EventState,
    attempt: int = 1,
    error_code: str | None = None,
    message: str | None = None,
    details: dict[str, object] | None = None,
) -> ProcessingEvent:
    event = ProcessingEvent(
        call_id=call.id,
        stage=stage,
        state=state,
        attempt=attempt,
        error_code=error_code,
        message=message,
        details=details or {},
    )
    session.add(event)
    session.flush()
    return event

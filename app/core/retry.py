"""Retry classification: infrastructure only, never semantic failures."""

from __future__ import annotations

from app.core.enums import FailureKind
from app.core.errors import NamedError

RETRYABLE_CODES = frozenset(
    {
        "PYAI_SUBMIT_FAILED",
        "PYAI_JOB_TIMEOUT",
        "PYAI_RESULT_FETCH_FAILED",
        "PYAI_RECAP_PENDING_TIMEOUT",
        "ML_SERVICE_UNAVAILABLE",
        "ML_MODEL_NOT_READY",
        "ML_INFERENCE_FAILED",
        "BLOB_UPLOAD_FAILED",
        "BLOB_DOWNLOAD_FAILED",
        "DATABASE_WRITE_FAILED",
        "EMBEDDING_FAILED",
    }
)

NON_RETRYABLE_CODES = frozenset(
    {
        "EVIDENCE_SEGMENT_MISSING",
        "EVIDENCE_WRONG_SPEAKER",
        "EVIDENCE_UNSUPPORTED",
        "ANALYSIS_SCHEMA_INVALID",
        "INVALID_AUDIO",
        "AUDIO_TOO_LARGE",
        "PYAI_AUTH_FAILED",
        "PYAI_SCOPE_MISSING",
        "PYAI_WEBHOOK_SIGNATURE_INVALID",
        "PYAI_JOB_FAILED",
        "PYAI_JOB_CANCELLED",
        "PYAI_RECAP_FAILED",
        "ML_AUTH_FAILED",
        "ML_GENERATION_DISABLED",
        "ML_RESPONSE_INVALID",
        "BLOB_NOT_FOUND",
        "SPEAKER_ROLE_UNRESOLVED",
        "INVALID_SOURCE_URL",
    }
)


def should_retry(exc: BaseException) -> bool:
    if isinstance(exc, NamedError):
        if exc.code in NON_RETRYABLE_CODES:
            return False
        if exc.code in RETRYABLE_CODES:
            return True
        return bool(exc.retryable and exc.failure_kind == FailureKind.INFRASTRUCTURE)
    return False


def retry_reason(exc: BaseException) -> str:
    if isinstance(exc, NamedError):
        return f"{exc.code}: {exc.message}"
    return type(exc).__name__

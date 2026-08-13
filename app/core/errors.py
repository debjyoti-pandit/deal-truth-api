"""Typed named errors with a consistent API envelope."""

from __future__ import annotations

from typing import Any

from app.core.enums import FailureKind


class NamedError(Exception):
    """Base typed error. Subclasses set a stable `code`."""

    code: str = "INTERNAL_ERROR"
    http_status: int = 500
    retryable: bool = False
    failure_kind: FailureKind = FailureKind.INFRASTRUCTURE

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_payload(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
                "retryable": self.retryable,
                "failure_kind": self.failure_kind.value,
            }
        }


# --- PyAI ---


class PyAIAuthFailed(NamedError):
    code = "PYAI_AUTH_FAILED"
    http_status = 502
    retryable = False
    failure_kind = FailureKind.TRANSCRIPTION


class PyAIPaymentRequired(NamedError):
    code = "PYAI_PAYMENT_REQUIRED"
    http_status = 402
    retryable = False
    failure_kind = FailureKind.TRANSCRIPTION


class PyAIScopeMissing(NamedError):
    code = "PYAI_SCOPE_MISSING"
    http_status = 502
    retryable = False
    failure_kind = FailureKind.RECAP


class PyAISubmitFailed(NamedError):
    code = "PYAI_SUBMIT_FAILED"
    http_status = 502
    retryable = True
    failure_kind = FailureKind.TRANSCRIPTION


class PyAIWebhookSignatureInvalid(NamedError):
    code = "PYAI_WEBHOOK_SIGNATURE_INVALID"
    http_status = 401
    retryable = False
    failure_kind = FailureKind.USER_INPUT


class PyAIJobFailed(NamedError):
    code = "PYAI_JOB_FAILED"
    http_status = 502
    retryable = False
    failure_kind = FailureKind.TRANSCRIPTION


class PyAIJobCancelled(NamedError):
    code = "PYAI_JOB_CANCELLED"
    http_status = 409
    retryable = False
    failure_kind = FailureKind.TRANSCRIPTION


class PyAIJobTimeout(NamedError):
    code = "PYAI_JOB_TIMEOUT"
    http_status = 504
    retryable = True
    failure_kind = FailureKind.INFRASTRUCTURE


class PyAIResultFetchFailed(NamedError):
    code = "PYAI_RESULT_FETCH_FAILED"
    http_status = 502
    retryable = True
    failure_kind = FailureKind.INFRASTRUCTURE


class PyAIRecapPendingTimeout(NamedError):
    code = "PYAI_RECAP_PENDING_TIMEOUT"
    http_status = 504
    retryable = True
    failure_kind = FailureKind.RECAP


class PyAIRecapFailed(NamedError):
    code = "PYAI_RECAP_FAILED"
    http_status = 502
    retryable = False
    failure_kind = FailureKind.RECAP


# --- ML ---


class MLServiceUnavailable(NamedError):
    code = "ML_SERVICE_UNAVAILABLE"
    http_status = 503
    retryable = True
    failure_kind = FailureKind.ML_INFERENCE


class MLAuthFailed(NamedError):
    code = "ML_AUTH_FAILED"
    http_status = 502
    retryable = False
    failure_kind = FailureKind.ML_INFERENCE


class MLModelNotReady(NamedError):
    code = "ML_MODEL_NOT_READY"
    http_status = 503
    retryable = True
    failure_kind = FailureKind.ML_INFERENCE


class MLInferenceFailed(NamedError):
    code = "ML_INFERENCE_FAILED"
    http_status = 502
    retryable = True
    failure_kind = FailureKind.ML_INFERENCE


class MLGenerationDisabled(NamedError):
    code = "ML_GENERATION_DISABLED"
    http_status = 503
    retryable = False
    failure_kind = FailureKind.ML_INFERENCE


class MLResponseInvalid(NamedError):
    code = "ML_RESPONSE_INVALID"
    http_status = 502
    retryable = False
    failure_kind = FailureKind.ML_INFERENCE


# --- Storage ---


class BlobUploadFailed(NamedError):
    code = "BLOB_UPLOAD_FAILED"
    http_status = 502
    retryable = True
    failure_kind = FailureKind.STORAGE


class BlobDownloadFailed(NamedError):
    code = "BLOB_DOWNLOAD_FAILED"
    http_status = 502
    retryable = True
    failure_kind = FailureKind.STORAGE


class BlobNotFound(NamedError):
    code = "BLOB_NOT_FOUND"
    http_status = 404
    retryable = False
    failure_kind = FailureKind.STORAGE


class InvalidAudio(NamedError):
    code = "INVALID_AUDIO"
    http_status = 400
    retryable = False
    failure_kind = FailureKind.USER_INPUT


class AudioTooLarge(NamedError):
    code = "AUDIO_TOO_LARGE"
    http_status = 413
    retryable = False
    failure_kind = FailureKind.USER_INPUT


# --- Analysis ---


class SpeakerRoleUnresolved(NamedError):
    code = "SPEAKER_ROLE_UNRESOLVED"
    http_status = 422
    retryable = False
    failure_kind = FailureKind.VALIDATION


class EvidenceSegmentMissing(NamedError):
    code = "EVIDENCE_SEGMENT_MISSING"
    http_status = 422
    retryable = False
    failure_kind = FailureKind.VALIDATION


class EvidenceWrongSpeaker(NamedError):
    code = "EVIDENCE_WRONG_SPEAKER"
    http_status = 422
    retryable = False
    failure_kind = FailureKind.VALIDATION


class EvidenceUnsupported(NamedError):
    code = "EVIDENCE_UNSUPPORTED"
    http_status = 422
    retryable = False
    failure_kind = FailureKind.VALIDATION


class AnalysisSchemaInvalid(NamedError):
    code = "ANALYSIS_SCHEMA_INVALID"
    http_status = 422
    retryable = False
    failure_kind = FailureKind.VALIDATION


class EmbeddingFailed(NamedError):
    code = "EMBEDDING_FAILED"
    http_status = 502
    retryable = True
    failure_kind = FailureKind.ML_INFERENCE


# --- Database ---


class DatabaseWriteFailed(NamedError):
    code = "DATABASE_WRITE_FAILED"
    http_status = 500
    retryable = True
    failure_kind = FailureKind.DATABASE


class MigrationRequired(NamedError):
    code = "MIGRATION_REQUIRED"
    http_status = 503
    retryable = False
    failure_kind = FailureKind.DATABASE


# --- Generic / request ---


class NotFoundError(NamedError):
    code = "NOT_FOUND"
    http_status = 404
    retryable = False
    failure_kind = FailureKind.USER_INPUT


class ConflictError(NamedError):
    code = "CONFLICT"
    http_status = 409
    retryable = False
    failure_kind = FailureKind.USER_INPUT


class NotReadyError(NamedError):
    """Report/derived artifacts are not available until the call is SHIPPED or PARTIAL."""

    code = "NOT_READY"
    http_status = 409
    retryable = True
    failure_kind = FailureKind.USER_INPUT


class UnauthorizedError(NamedError):
    code = "UNAUTHORIZED"
    http_status = 401
    retryable = False
    failure_kind = FailureKind.USER_INPUT


class ForbiddenError(NamedError):
    code = "FORBIDDEN"
    http_status = 403
    retryable = False
    failure_kind = FailureKind.USER_INPUT


class InvalidSourceURL(NamedError):
    code = "INVALID_SOURCE_URL"
    http_status = 400
    retryable = False
    failure_kind = FailureKind.USER_INPUT


class ShareTokenInvalid(NamedError):
    code = "SHARE_TOKEN_INVALID"
    http_status = 404
    retryable = False
    failure_kind = FailureKind.USER_INPUT


class SignedURLInvalid(NamedError):
    code = "SIGNED_URL_INVALID"
    http_status = 403
    retryable = False
    failure_kind = FailureKind.USER_INPUT


class CallCancelled(NamedError):
    code = "CALL_CANCELLED"
    http_status = 409
    retryable = False
    failure_kind = FailureKind.USER_INPUT


def is_retryable(exc: BaseException) -> bool:
    """Retry only infrastructure failures; never retry semantic/validation errors."""
    from app.core.retry import should_retry

    return should_retry(exc)

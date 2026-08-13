"""String enums used across models, schemas, and the pipeline."""

from enum import StrEnum


class CallStatus(StrEnum):
    CREATED = "CREATED"
    UPLOADING = "UPLOADING"
    QUEUED = "QUEUED"
    TRANSCRIBING = "TRANSCRIBING"
    WAITING_FOR_RECAP = "WAITING_FOR_RECAP"
    ANALYZING = "ANALYZING"
    VALIDATING = "VALIDATING"
    INDEXING = "INDEXING"
    BUILDING_REPORT = "BUILDING_REPORT"
    SHIPPED = "SHIPPED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TerminalOutcome(StrEnum):
    SHIPPED = "SHIPPED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class FailureKind(StrEnum):
    INFRASTRUCTURE = "INFRASTRUCTURE"
    TRANSCRIPTION = "TRANSCRIPTION"
    RECAP = "RECAP"
    ML_INFERENCE = "ML_INFERENCE"
    VALIDATION = "VALIDATION"
    STORAGE = "STORAGE"
    DATABASE = "DATABASE"
    USER_INPUT = "USER_INPUT"


class CallDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


class SourceType(StrEnum):
    UPLOAD = "upload"
    SOURCE_URL = "source_url"


class RecordingMode(StrEnum):
    MONO = "mono"
    STEREO = "stereo"


class SpeakerRole(StrEnum):
    SELLER = "seller"
    CUSTOMER = "customer"
    UNKNOWN = "unknown"


class InsightType(StrEnum):
    CUSTOMER_FACT = "CUSTOMER_FACT"
    BUYING_SIGNAL = "BUYING_SIGNAL"
    OBJECTION = "OBJECTION"
    COMMITMENT = "COMMITMENT"
    DEAL_RISK = "DEAL_RISK"
    COMPETITOR = "COMPETITOR"
    REALITY_CHECK = "REALITY_CHECK"
    CALL_MOMENT = "CALL_MOMENT"
    COACHING = "COACHING"
    SENTIMENT_POINT = "SENTIMENT_POINT"
    QUALIFICATION_SIGNAL = "QUALIFICATION_SIGNAL"


class EvidenceStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    ABSENCE_BASED = "ABSENCE_BASED"
    UNCONFIRMED = "UNCONFIRMED"
    NON_FACTUAL = "NON_FACTUAL"


class AnalysisRunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class EventState(StrEnum):
    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    SKIPPED = "SKIPPED"


class TrackedTermType(StrEnum):
    KEYWORD = "keyword"
    COMPETITOR = "competitor"


class AuthMode(StrEnum):
    NONE = "none"
    API_KEY = "api_key"


class AudioInputMode(StrEnum):
    AUDIO_URL = "audio_url"
    MULTIPART = "multipart"


class PyAIJobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_CALL_STATUSES = frozenset(
    {
        CallStatus.SHIPPED,
        CallStatus.PARTIAL,
        CallStatus.FAILED,
        CallStatus.CANCELLED,
    }
)

TERMINAL_PYAI_JOB_STATUSES = frozenset(
    {
        PyAIJobStatus.COMPLETED,
        PyAIJobStatus.FAILED,
        PyAIJobStatus.CANCELLED,
    }
)

CUSTOMER_ONLY_INSIGHT_TYPES = frozenset(
    {
        InsightType.CUSTOMER_FACT,
        InsightType.SENTIMENT_POINT,
    }
)

from app.core.errors import (
    EvidenceUnsupported,
    InvalidAudio,
    MLServiceUnavailable,
    PyAIJobFailed,
    PyAIJobTimeout,
    PyAISubmitFailed,
)
from app.core.retry import should_retry


def test_retry_infrastructure_not_semantic() -> None:
    assert should_retry(PyAIJobTimeout("timeout"))
    assert should_retry(PyAISubmitFailed("5xx"))
    assert should_retry(MLServiceUnavailable("down"))
    assert not should_retry(EvidenceUnsupported("no proof"))
    assert not should_retry(InvalidAudio("bad"))
    assert not should_retry(PyAIJobFailed("model failed the transcription"))


def test_infrastructure_failure_is_not_a_sales_test() -> None:
    err = MLServiceUnavailable("ml down")
    payload = err.to_payload()
    assert payload["error"]["failure_kind"] == "INFRASTRUCTURE" or payload["error"]["failure_kind"] == "ML_INFERENCE"
    assert payload["error"]["failure_kind"] != "VALIDATION"
    sales_fail = EvidenceUnsupported("no evidence")
    assert sales_fail.failure_kind.value == "VALIDATION"
    assert not should_retry(sales_fail)

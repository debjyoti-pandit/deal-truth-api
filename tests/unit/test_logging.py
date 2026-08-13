from __future__ import annotations

import json
import logging

from app.core.logging import JsonFormatter, RedactingFilter, configure_logging, redact_value
from app.core.settings import Settings


def test_redact_secrets_and_long_transcript() -> None:
    assert redact_value("api_key", "secret-value") == "[REDACTED]"
    assert redact_value("PYAI_API_KEY", "x") == "[REDACTED]"
    long = "a" * 100
    redacted = redact_value("transcript", long)
    assert isinstance(redacted, str)
    assert "omitted" in redacted
    assert len(redacted) < len(long)


def test_redacting_filter_strips_bearer() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Authorization: Bearer abc.def.ghi",
        args=(),
        exc_info=None,
    )
    assert RedactingFilter().filter(record) is True
    assert "[REDACTED]" in record.getMessage()


def test_json_formatter_emits_object() -> None:
    record = logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.test"


def test_configure_logging_idempotent(settings: Settings) -> None:
    configure_logging(settings, force=True)
    configure_logging(settings)
    root = logging.getLogger()
    assert root.handlers

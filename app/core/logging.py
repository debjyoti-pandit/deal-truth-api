"""Logging with credential and transcript redaction."""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

from app.core.settings import Settings

_SECRET_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "token",
        "secret",
        "password",
        "access_key",
        "secret_key",
        "aws_secret_access_key",
        "pyai_api_key",
        "pyai_webhook_secret",
        "ml_service_api_key",
        "signed_url_secret",
        "ngrok_authtoken",
        "s3_secret_key",
        "s3_access_key",
        "signature",
    }
)

_REDACT = "[REDACTED]"
_BEARER = re.compile(r"(Bearer\s+)[A-Za-z0-9._\-+=/]+", re.IGNORECASE)
_QUERY_SIG = re.compile(r"(signature=)[^&\s]+", re.IGNORECASE)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _redact_text(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: redact_value(k, v) for k, v in record.args.items()}
            else:
                record.args = tuple(_redact_text(str(a)) if isinstance(a, str) else a for a in record.args)
        return True


def _redact_text(text: str) -> str:
    text = _BEARER.sub(rf"\1{_REDACT}", text)
    text = _QUERY_SIG.sub(rf"\1{_REDACT}", text)
    return text


def redact_value(key: str, value: Any) -> Any:
    lowered = key.lower().replace("-", "_")
    if any(part in lowered for part in _SECRET_KEYS):
        return _REDACT
    if isinstance(value, str) and lowered in {"text", "transcript", "quote"}:
        if len(value) > 80:
            return value[:40] + "…[transcript omitted]"
    if isinstance(value, dict):
        return {k: redact_value(k, v) for k, v in value.items()}
    return value


def configure_logging(settings: Settings) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RedactingFilter())
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("boto3").setLevel(logging.WARNING)

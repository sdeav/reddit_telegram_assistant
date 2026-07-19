from __future__ import annotations

import logging
from collections.abc import Iterable

SENSITIVE_MARKER = "[REDACTED]"


class RedactingFilter(logging.Filter):
    def __init__(self, secrets: Iterable[str] = ()) -> None:
        super().__init__()
        self._secrets = tuple(secret for secret in secrets if secret)

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        record.msg = sanitize_log_message(message, self._secrets)
        record.args = ()
        return True


def configure_logging(level: str, *, secrets: Iterable[str] = ()) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    redactor = RedactingFilter(secrets)
    for handler in logging.getLogger().handlers:
        handler.addFilter(redactor)


def sanitize_log_message(message: str, secrets: Iterable[str] = ()) -> str:
    sanitized = message
    for secret in secrets:
        if secret:
            sanitized = sanitized.replace(secret, SENSITIVE_MARKER)
    return sanitized


def safe_error_detail(exc: BaseException) -> str:
    details = [exc.__class__.__name__]
    for attr in ("status", "status_code", "error_type"):
        value = getattr(exc, attr, None)
        if value is not None:
            details.append(f"{attr}={value}")
    return " ".join(details)

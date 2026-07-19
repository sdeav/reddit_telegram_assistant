from __future__ import annotations

from assistant.logging_config import safe_error_detail, sanitize_log_message


def test_safe_logging_redacts_secrets() -> None:
    message = sanitize_log_message(
        "token=telegram-token refresh=refresh-token title=public",
        secrets=("telegram-token", "refresh-token"),
    )

    assert "telegram-token" not in message
    assert "refresh-token" not in message
    assert "[REDACTED]" in message


def test_safe_error_details_do_not_include_exception_message() -> None:
    exc = RuntimeError("secret token and reddit content")

    detail = safe_error_detail(exc)

    assert detail == "RuntimeError"
    assert "secret token" not in detail
    assert "reddit content" not in detail

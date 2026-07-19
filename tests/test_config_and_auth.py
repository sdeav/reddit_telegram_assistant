from __future__ import annotations

from pathlib import Path

import pytest

from assistant.auth import build_authorization_url, parse_callback_url
from assistant.config import AppConfig, ConfigError, REQUIRED_REDDIT_SCOPES


def valid_env(tmp_path: Path) -> dict[str, str]:
    return {
        "REDDIT_CLIENT_ID": "client-id",
        "REDDIT_CLIENT_SECRET": "client-secret",
        "REDDIT_REDIRECT_URI": "http://localhost:8080",
        "REDDIT_REFRESH_TOKEN": "refresh-token",
        "EXPECTED_REDDIT_USERNAME": "u/ExpectedUser",
        "REDDIT_USER_AGENT": "private:reddit-telegram-assistant:v0.1.0 (by u/ExpectedUser)",
        "TELEGRAM_BOT_TOKEN": "telegram-token",
        "TELEGRAM_ALLOWED_USER_ID": "123",
        "TELEGRAM_ALLOWED_CHAT_ID": "456",
        "SUBREDDITS": "islam, another_subreddit",
        "CHECK_INTERVAL_MINUTES": "15",
        "REDDIT_NEW_POST_LIMIT": "25",
        "AUTO_SAVE_MATCHES": "false",
        "DATABASE_PATH": str(tmp_path / "state.sqlite3"),
        "SEEN_POST_RETENTION_HOURS": "48",
        "MAX_SEEN_POST_IDS": "5000",
        "LOG_LEVEL": "INFO",
    }


def test_configuration_validation_accepts_expected_values(tmp_path: Path) -> None:
    config = AppConfig.from_env(valid_env(tmp_path), base_dir=tmp_path)

    assert config.expected_reddit_username == "expecteduser"
    assert config.subreddits == ("islam", "another_subreddit")
    assert config.telegram_allowed_user_id == 123
    assert config.telegram_allowed_chat_id == 456
    assert config.auto_save_matches is False
    assert config.seen_post_retention_hours == 48
    assert config.max_seen_post_ids == 5000


def test_configuration_accepts_legacy_seen_post_retention_names(tmp_path: Path) -> None:
    env = valid_env(tmp_path)
    env.pop("SEEN_POST_RETENTION_HOURS")
    env.pop("MAX_SEEN_POST_IDS")
    env["PROCESSED_ID_RETENTION_HOURS"] = "24"
    env["MAX_PROCESSED_IDS"] = "250"

    config = AppConfig.from_env(env, base_dir=tmp_path)

    assert config.seen_post_retention_hours == 24
    assert config.max_seen_post_ids == 250


def test_configuration_validation_reports_missing_required_settings(tmp_path: Path) -> None:
    env = valid_env(tmp_path)
    env["TELEGRAM_BOT_TOKEN"] = ""

    with pytest.raises(ConfigError, match="TELEGRAM_BOT_TOKEN"):
        AppConfig.from_env(env, base_dir=tmp_path)


def test_oauth_scope_configuration_is_exact() -> None:
    assert REQUIRED_REDDIT_SCOPES == ("identity", "read", "save", "history")


def test_oauth_authorization_url_uses_permanent_exact_scopes() -> None:
    class FakeAuth:
        def __init__(self) -> None:
            self.call = None

        def url(self, *, scopes, state, duration):  # type: ignore[no-untyped-def]
            self.call = (tuple(scopes), state, duration)
            return "https://reddit.test/auth"

    class FakeReddit:
        def __init__(self) -> None:
            self.auth = FakeAuth()

    reddit = FakeReddit()
    url = build_authorization_url(reddit, "secure-state")

    assert url == "https://reddit.test/auth"
    assert reddit.auth.call == (REQUIRED_REDDIT_SCOPES, "secure-state", "permanent")


def test_oauth_callback_verifies_state() -> None:
    callback = "http://localhost:8080/?state=secure-state&code=abc123"

    assert parse_callback_url(callback, "secure-state") == "abc123"


def test_oauth_callback_rejects_wrong_state() -> None:
    callback = "http://localhost:8080/?state=wrong&code=abc123"

    with pytest.raises(Exception, match="state"):
        parse_callback_url(callback, "secure-state")

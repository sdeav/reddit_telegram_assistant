from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

REQUIRED_REDDIT_SCOPES: tuple[str, ...] = ("identity", "read", "save", "history")


class ConfigError(ValueError):
    """Raised when configuration is missing or invalid."""


@dataclass(frozen=True)
class AppConfig:
    reddit_client_id: str
    reddit_client_secret: str
    reddit_redirect_uri: str
    reddit_refresh_token: str
    expected_reddit_username: str
    reddit_user_agent: str
    telegram_bot_token: str
    telegram_allowed_user_id: int
    telegram_allowed_chat_id: int
    subreddits: tuple[str, ...]
    check_interval_minutes: int
    reddit_new_post_limit: int
    auto_save_matches: bool
    database_path: Path
    processed_id_retention_hours: int
    max_processed_ids: int
    log_level: str
    keywords_path: Path

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        base_dir: Path | None = None,
        load_dotenv_file: bool = True,
    ) -> "AppConfig":
        base = base_dir or Path.cwd()
        if environ is None:
            if load_dotenv_file:
                try:
                    from dotenv import load_dotenv

                    load_dotenv(base / ".env")
                except ModuleNotFoundError:
                    pass
            environ = os.environ

        required = (
            "REDDIT_CLIENT_ID",
            "REDDIT_CLIENT_SECRET",
            "REDDIT_REDIRECT_URI",
            "REDDIT_REFRESH_TOKEN",
            "EXPECTED_REDDIT_USERNAME",
            "REDDIT_USER_AGENT",
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_ALLOWED_USER_ID",
            "TELEGRAM_ALLOWED_CHAT_ID",
        )
        missing = [key for key in required if not _clean(environ.get(key))]
        if missing:
            raise ConfigError(f"Missing required configuration: {', '.join(missing)}")

        subreddits = parse_csv(environ.get("SUBREDDITS", "islam"))
        if not subreddits:
            raise ConfigError("SUBREDDITS must contain at least one subreddit name")
        for subreddit in subreddits:
            if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_]{1,20}", subreddit):
                raise ConfigError(f"Invalid subreddit name: {subreddit}")

        check_interval = parse_positive_int(
            environ.get("CHECK_INTERVAL_MINUTES", "15"),
            "CHECK_INTERVAL_MINUTES",
        )
        new_post_limit = parse_positive_int(
            environ.get("REDDIT_NEW_POST_LIMIT", "25"),
            "REDDIT_NEW_POST_LIMIT",
        )
        retention_hours = parse_positive_int(
            environ.get("PROCESSED_ID_RETENTION_HOURS", "48"),
            "PROCESSED_ID_RETENTION_HOURS",
        )
        max_processed_ids = parse_positive_int(
            environ.get("MAX_PROCESSED_IDS", "5000"),
            "MAX_PROCESSED_IDS",
        )
        user_id = parse_int(environ["TELEGRAM_ALLOWED_USER_ID"], "TELEGRAM_ALLOWED_USER_ID")
        chat_id = parse_int(environ["TELEGRAM_ALLOWED_CHAT_ID"], "TELEGRAM_ALLOWED_CHAT_ID")

        database_path = Path(environ.get("DATABASE_PATH", "reddit_telegram_assistant.sqlite3"))
        if not database_path.is_absolute():
            database_path = base / database_path

        log_level = environ.get("LOG_LEVEL", "INFO").strip().upper()
        if log_level not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}:
            raise ConfigError("LOG_LEVEL must be a standard Python logging level")

        return cls(
            reddit_client_id=environ["REDDIT_CLIENT_ID"].strip(),
            reddit_client_secret=environ["REDDIT_CLIENT_SECRET"].strip(),
            reddit_redirect_uri=environ["REDDIT_REDIRECT_URI"].strip(),
            reddit_refresh_token=environ["REDDIT_REFRESH_TOKEN"].strip(),
            expected_reddit_username=normalize_reddit_username(
                environ["EXPECTED_REDDIT_USERNAME"]
            ),
            reddit_user_agent=environ["REDDIT_USER_AGENT"].strip(),
            telegram_bot_token=environ["TELEGRAM_BOT_TOKEN"].strip(),
            telegram_allowed_user_id=user_id,
            telegram_allowed_chat_id=chat_id,
            subreddits=tuple(subreddits),
            check_interval_minutes=check_interval,
            reddit_new_post_limit=new_post_limit,
            auto_save_matches=parse_bool(environ.get("AUTO_SAVE_MATCHES", "false")),
            database_path=database_path,
            processed_id_retention_hours=retention_hours,
            max_processed_ids=max_processed_ids,
            log_level=log_level,
            keywords_path=base / "config" / "keywords.txt",
        )

    @property
    def configured_oauth_scopes(self) -> tuple[str, ...]:
        return REQUIRED_REDDIT_SCOPES


@dataclass(frozen=True)
class OAuthConfig:
    reddit_client_id: str
    reddit_client_secret: str
    reddit_redirect_uri: str
    reddit_user_agent: str

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        base_dir: Path | None = None,
        load_dotenv_file: bool = True,
    ) -> "OAuthConfig":
        base = base_dir or Path.cwd()
        if environ is None:
            if load_dotenv_file:
                try:
                    from dotenv import load_dotenv

                    load_dotenv(base / ".env")
                except ModuleNotFoundError:
                    pass
            environ = os.environ

        required = (
            "REDDIT_CLIENT_ID",
            "REDDIT_CLIENT_SECRET",
            "REDDIT_REDIRECT_URI",
            "REDDIT_USER_AGENT",
        )
        missing = [key for key in required if not _clean(environ.get(key))]
        if missing:
            raise ConfigError(f"Missing required OAuth configuration: {', '.join(missing)}")

        return cls(
            reddit_client_id=environ["REDDIT_CLIENT_ID"].strip(),
            reddit_client_secret=environ["REDDIT_CLIENT_SECRET"].strip(),
            reddit_redirect_uri=environ["REDDIT_REDIRECT_URI"].strip(),
            reddit_user_agent=environ["REDDIT_USER_AGENT"].strip(),
        )


def parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ConfigError(f"Invalid boolean value: {value}")


def parse_int(value: str, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be an integer") from exc


def parse_positive_int(value: str, name: str) -> int:
    parsed = parse_int(value, name)
    if parsed <= 0:
        raise ConfigError(f"{name} must be greater than zero")
    return parsed


def normalize_reddit_username(username: str) -> str:
    normalized = username.strip()
    if normalized.lower().startswith("u/"):
        normalized = normalized[2:]
    return normalized.strip().lower()


def load_keywords(path: Path) -> tuple[str, ...]:
    if not path.exists():
        raise ConfigError(f"Keyword file does not exist: {path}")
    keywords: list[str] = []
    seen: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = normalize_whitespace(raw_line)
        if not line or line.startswith("#"):
            continue
        key = line.casefold()
        if key not in seen:
            keywords.append(line)
            seen.add(key)
    return tuple(keywords)


def normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


def _clean(value: str | None) -> str:
    return (value or "").strip()

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class StatusView:
    reddit_authentication_ok: bool
    reddit_username_verified: bool
    monitoring_running: bool
    subreddit_count: int
    keyword_count: int
    last_successful_check: datetime | None
    last_check_result: str
    next_scheduled_check: datetime | None


def format_status_response(status: StatusView) -> str:
    return (
        "Status\n"
        f"Reddit authentication: {_yes_no(status.reddit_authentication_ok)}\n"
        f"Reddit username verified: {_yes_no(status.reddit_username_verified)}\n"
        f"Monitoring running: {_yes_no(status.monitoring_running)}\n"
        f"Configured subreddits: {status.subreddit_count}\n"
        f"Configured keywords: {status.keyword_count}\n"
        f"Last successful check: {_format_datetime(status.last_successful_check)}\n"
        f"Last check result: {status.last_check_result}\n"
        f"Next scheduled check: {_format_datetime(status.next_scheduled_check)}"
    )


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _format_datetime(value: datetime | None) -> str:
    return value.isoformat() if value is not None else "never"

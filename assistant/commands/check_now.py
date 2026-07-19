from __future__ import annotations

from assistant.models import CheckResult


def format_check_result(result: CheckResult) -> str:
    if result.skipped_overlap:
        return "A Reddit check is already running."
    return (
        "Reddit check complete\n"
        f"Subreddits checked: {result.subreddits_checked}\n"
        f"Posts inspected: {result.posts_inspected}\n"
        f"Matches found: {result.matches_found}\n"
        f"Notifications sent: {result.notifications_sent}\n"
        f"Errors: {len(result.errors)}"
    )

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from assistant.commands.comments import filter_comments, format_comments_page
from assistant.commands.saved import format_saved_page, has_next, has_previous
from assistant.commands.status import StatusView, format_status_response
from assistant.config import AppConfig
from assistant.models import RecentComment, RedditAccountVerification, RedditPost, SavedItem
from assistant.telegram_bot import TelegramAccessGuard, TelegramBot, format_match_alert


def make_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        reddit_client_id="client-id",
        reddit_client_secret="client-secret",
        reddit_redirect_uri="http://localhost:8080",
        reddit_refresh_token="refresh-token",
        expected_reddit_username="expecteduser",
        reddit_user_agent="private:reddit-telegram-assistant:v0.1.0",
        telegram_bot_token="telegram-token",
        telegram_allowed_user_id=1,
        telegram_allowed_chat_id=2,
        subreddits=("islam",),
        check_interval_minutes=15,
        reddit_new_post_limit=25,
        auto_save_matches=False,
        database_path=tmp_path / "state.sqlite3",
        seen_post_retention_hours=48,
        max_seen_post_ids=5000,
        log_level="INFO",
        keywords_path=tmp_path / "keywords.txt",
    )


class FakeMessage:
    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply_text(self, text: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.replies.append(text)


class FakeUpdate:
    def __init__(self, *, user_id: int, chat_id: int) -> None:
        self.effective_user = SimpleNamespace(id=user_id)
        self.effective_chat = SimpleNamespace(id=chat_id)
        self.effective_message = FakeMessage()
        self.callback_query = None


class RedditThatMustNotBeCalled:
    def verify_expected_username(self, expected: str):  # type: ignore[no-untyped-def]
        raise AssertionError("Reddit API must not be called for unauthorized users")


class FakeMonitor:
    def status(self):  # type: ignore[no-untyped-def]
        return SimpleNamespace(
            is_running=False,
            last_result="not run yet",
            last_successful_check_utc=None,
        )


class FakeScheduler:
    def status(self):  # type: ignore[no-untyped-def]
        return SimpleNamespace(next_scheduled_check=None)


def test_unauthorized_telegram_user_is_rejected_without_reddit_call(tmp_path: Path) -> None:
    bot = TelegramBot(
        config=make_config(tmp_path),
        reddit_client=RedditThatMustNotBeCalled(),  # type: ignore[arg-type]
        monitor=FakeMonitor(),
        scheduler=FakeScheduler(),  # type: ignore[arg-type]
        verification=RedditAccountVerification("ExpectedUser", "expecteduser", True, ("identity",)),
        matcher_keyword_count=1,
    )
    update = FakeUpdate(user_id=999, chat_id=2)

    asyncio.run(bot.account(update, SimpleNamespace(args=[])))

    assert update.effective_message.replies == ["Unauthorized."]


def test_unauthorized_telegram_chat_is_rejected() -> None:
    guard = TelegramAccessGuard(allowed_user_id=1, allowed_chat_id=2)

    assert not guard.is_authorized_ids(1, 999)


def test_permalink_only_alert_excludes_post_content() -> None:
    post = RedditPost(
        id="abc",
        subreddit="islam",
        permalink="https://www.reddit.com/r/islam/comments/abc/example/",
        title="Secret title",
        selftext="Sensitive post body",
    )

    alert = format_match_alert(post)

    assert alert == (
        "New matching post found in r/islam:\n"
        "https://www.reddit.com/r/islam/comments/abc/example/"
    )
    assert "Secret title" not in alert
    assert "Sensitive post body" not in alert


def test_saved_item_pagination() -> None:
    items = [
        SavedItem(str(index), "post", "Saved post", f"https://www.reddit.com/{index}")
        for index in range(6)
    ]

    page_1 = format_saved_page(items, 0)
    page_2 = format_saved_page(items, 1)

    assert "1. Saved post" in page_1
    assert "5. Saved post" in page_1
    assert "6. Saved post" in page_2
    assert not has_previous(0)
    assert has_next(items, 0)


def test_comment_search_and_display() -> None:
    comments = [
        RecentComment("c1", "alpha needle", "https://www.reddit.com/c1"),
        RecentComment("c2", "beta", "https://www.reddit.com/c2"),
    ]

    filtered = filter_comments(comments, "needle")
    rendered = format_comments_page(comments, 0, query="needle")

    assert [comment.item_id for comment in filtered] == ["c1"]
    assert "alpha needle" in rendered
    assert "not an unlimited history search" in rendered


def test_status_output_contains_required_fields() -> None:
    rendered = format_status_response(
        StatusView(
            reddit_authentication_ok=True,
            reddit_username_verified=True,
            monitoring_running=False,
            subreddit_count=1,
            keyword_count=2,
            last_successful_check=datetime(2026, 7, 19, tzinfo=UTC),
            last_check_result="checked=1 inspected=2 matches=1 errors=0",
            next_scheduled_check=None,
        )
    )

    assert "Reddit authentication: yes" in rendered
    assert "Configured subreddits: 1" in rendered
    assert "Configured keywords: 2" in rendered

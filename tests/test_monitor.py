from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from assistant.config import AppConfig
from assistant.matcher import KeywordMatcher
from assistant.models import RedditPost
from assistant.monitor import RedditMonitor
from assistant.reddit_client import RedditTemporaryError
from assistant.storage import Storage


def make_config(tmp_path: Path, *, auto_save_matches: bool = False) -> AppConfig:
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
        auto_save_matches=auto_save_matches,
        database_path=tmp_path / "state.sqlite3",
        seen_post_retention_hours=48,
        max_seen_post_ids=5000,
        log_level="INFO",
        keywords_path=tmp_path / "keywords.txt",
    )


def make_storage(tmp_path: Path) -> Storage:
    storage = Storage(tmp_path / "state.sqlite3", retention_hours=48, max_seen_post_ids=5000)
    storage.connect()
    return storage


class FakeReddit:
    def __init__(self, posts: list[RedditPost], *, fail_save: bool = False) -> None:
        self.posts = posts
        self.fail_save = fail_save
        self.fetch_calls = 0
        self.saved_ids: list[str] = []

    def fetch_new_posts(self, subreddit_name: str, limit: int) -> list[RedditPost]:
        self.fetch_calls += 1
        return self.posts[:limit]

    def save_submission_by_id(self, post_id: str) -> None:
        if self.fail_save:
            raise RuntimeError("Sensitive save detail should not be logged")
        self.saved_ids.append(post_id)


class TemporaryThenSuccessReddit(FakeReddit):
    def fetch_new_posts(self, subreddit_name: str, limit: int) -> list[RedditPost]:
        self.fetch_calls += 1
        if self.fetch_calls == 1:
            raise RedditTemporaryError("temporary")
        return self.posts[:limit]


class BlockingReddit(FakeReddit):
    def __init__(self, posts: list[RedditPost], started: threading.Event, release: threading.Event) -> None:
        super().__init__(posts)
        self.started = started
        self.release = release

    def fetch_new_posts(self, subreddit_name: str, limit: int) -> list[RedditPost]:
        self.started.set()
        self.release.wait(timeout=2)
        return super().fetch_new_posts(subreddit_name, limit)


class FakeNotifier:
    def __init__(self, *, failures_before_success: int = 0) -> None:
        self.failures_before_success = failures_before_success
        self.sent: list[RedditPost] = []

    async def send_match_alert(self, post: RedditPost) -> None:
        if self.failures_before_success:
            self.failures_before_success -= 1
            raise RuntimeError("Sensitive post body should not be logged")
        self.sent.append(post)


async def noop_sleep(delay: float) -> None:
    return None


def test_non_matching_post_is_marked_seen(tmp_path: Path) -> None:
    post = RedditPost(
        id="p1",
        subreddit="islam",
        permalink="https://www.reddit.com/r/islam/comments/p1/example/",
        title="general discussion",
        selftext="",
    )
    storage = make_storage(tmp_path)
    monitor = RedditMonitor(
        config=make_config(tmp_path),
        reddit_client=FakeReddit([post]),
        matcher=KeywordMatcher.from_keywords(["zakat"]),
        storage=storage,
        notifier=FakeNotifier(),
        sleep=noop_sleep,
    )

    result = asyncio.run(monitor.run_check())

    assert result.matches_found == 0
    assert storage.has_seen("p1")


def test_matching_post_is_marked_seen_after_telegram_success(tmp_path: Path) -> None:
    post = RedditPost(
        id="p1",
        subreddit="islam",
        permalink="https://www.reddit.com/r/islam/comments/p1/example/",
        title="zakat question",
        selftext="",
    )
    storage = make_storage(tmp_path)
    notifier = FakeNotifier()
    monitor = RedditMonitor(
        config=make_config(tmp_path),
        reddit_client=FakeReddit([post]),
        matcher=KeywordMatcher.from_keywords(["zakat"]),
        storage=storage,
        notifier=notifier,
        sleep=noop_sleep,
    )

    result = asyncio.run(monitor.run_check())

    assert result.notifications_sent == 1
    assert len(notifier.sent) == 1
    assert storage.has_seen("p1")


def test_matching_post_is_not_marked_seen_when_telegram_fails(tmp_path: Path) -> None:
    post = RedditPost(
        id="p1",
        subreddit="islam",
        permalink="https://www.reddit.com/r/islam/comments/p1/example/",
        title="zakat question",
        selftext="",
    )
    storage = make_storage(tmp_path)
    monitor = RedditMonitor(
        config=make_config(tmp_path),
        reddit_client=FakeReddit([post]),
        matcher=KeywordMatcher.from_keywords(["zakat"]),
        storage=storage,
        notifier=FakeNotifier(failures_before_success=1),
        sleep=noop_sleep,
    )

    result = asyncio.run(monitor.run_check())

    assert result.notifications_sent == 0
    assert result.errors
    assert not storage.has_seen("p1")


def test_failed_telegram_notification_is_retried_and_success_marks_seen(tmp_path: Path) -> None:
    post = RedditPost(
        id="p1",
        subreddit="islam",
        permalink="https://www.reddit.com/r/islam/comments/p1/example/",
        title="zakat question",
        selftext="",
    )
    storage = make_storage(tmp_path)
    notifier = FakeNotifier(failures_before_success=1)
    monitor = RedditMonitor(
        config=make_config(tmp_path),
        reddit_client=FakeReddit([post]),
        matcher=KeywordMatcher.from_keywords(["zakat"]),
        storage=storage,
        notifier=notifier,
        sleep=noop_sleep,
    )

    first = asyncio.run(monitor.run_check())
    assert first.notifications_sent == 0
    assert not storage.has_seen("p1")

    second = asyncio.run(monitor.run_check())

    assert second.notifications_sent == 1
    assert len(notifier.sent) == 1
    assert storage.has_seen("p1")


def test_auto_save_failure_does_not_prevent_notification_or_cause_duplicates(tmp_path: Path) -> None:
    post = RedditPost(
        id="p1",
        subreddit="islam",
        permalink="https://www.reddit.com/r/islam/comments/p1/example/",
        title="zakat question",
        selftext="",
    )
    storage = make_storage(tmp_path)
    notifier = FakeNotifier()
    monitor = RedditMonitor(
        config=make_config(tmp_path, auto_save_matches=True),
        reddit_client=FakeReddit([post], fail_save=True),
        matcher=KeywordMatcher.from_keywords(["zakat"]),
        storage=storage,
        notifier=notifier,
        sleep=noop_sleep,
    )

    first = asyncio.run(monitor.run_check())
    second = asyncio.run(monitor.run_check())

    assert first.notifications_sent == 1
    assert first.auto_saved == 0
    assert second.notifications_sent == 0
    assert len(notifier.sent) == 1
    assert storage.has_seen("p1")


def test_duplicate_notifications_are_prevented(tmp_path: Path) -> None:
    post = RedditPost(
        id="p1",
        subreddit="islam",
        permalink="https://www.reddit.com/r/islam/comments/p1/example/",
        title="zakat question",
        selftext="",
    )
    reddit = FakeReddit([post])
    notifier = FakeNotifier()
    monitor = RedditMonitor(
        config=make_config(tmp_path),
        reddit_client=reddit,
        matcher=KeywordMatcher.from_keywords(["zakat"]),
        storage=make_storage(tmp_path),
        notifier=notifier,
        sleep=noop_sleep,
    )

    first = asyncio.run(monitor.run_check())
    second = asyncio.run(monitor.run_check())

    assert first.notifications_sent == 1
    assert second.notifications_sent == 0
    assert len(notifier.sent) == 1


def test_saving_matched_posts_when_auto_save_enabled(tmp_path: Path) -> None:
    post = RedditPost("p1", "islam", "https://www.reddit.com/r/islam/comments/p1/example/", "zakat", "")
    reddit = FakeReddit([post])
    monitor = RedditMonitor(
        config=make_config(tmp_path, auto_save_matches=True),
        reddit_client=reddit,
        matcher=KeywordMatcher.from_keywords(["zakat"]),
        storage=make_storage(tmp_path),
        notifier=FakeNotifier(),
        sleep=noop_sleep,
    )

    result = asyncio.run(monitor.run_check())

    assert result.auto_saved == 1
    assert reddit.saved_ids == ["p1"]


def test_preventing_overlapping_checks(tmp_path: Path) -> None:
    started = threading.Event()
    release = threading.Event()
    reddit = BlockingReddit([], started, release)
    monitor = RedditMonitor(
        config=make_config(tmp_path),
        reddit_client=reddit,
        matcher=KeywordMatcher.from_keywords(["zakat"]),
        storage=make_storage(tmp_path),
        notifier=FakeNotifier(),
        sleep=noop_sleep,
    )

    async def scenario():
        first_task = asyncio.create_task(monitor.run_check())
        await asyncio.to_thread(started.wait, 1)
        second_result = await monitor.run_check()
        release.set()
        first_result = await first_task
        return first_result, second_result

    first, second = asyncio.run(scenario())

    assert not first.skipped_overlap
    assert second.skipped_overlap


def test_reddit_temporary_errors_are_retried(tmp_path: Path) -> None:
    post = RedditPost("p1", "islam", "https://www.reddit.com/r/islam/comments/p1/example/", "zakat", "")
    reddit = TemporaryThenSuccessReddit([post])
    monitor = RedditMonitor(
        config=make_config(tmp_path),
        reddit_client=reddit,
        matcher=KeywordMatcher.from_keywords(["zakat"]),
        storage=make_storage(tmp_path),
        notifier=FakeNotifier(),
        sleep=noop_sleep,
    )

    result = asyncio.run(monitor.run_check())

    assert result.errors == ()
    assert reddit.fetch_calls == 2


def test_telegram_delivery_errors_are_safe_and_recorded(tmp_path: Path, caplog) -> None:
    post = RedditPost(
        id="p1",
        subreddit="islam",
        permalink="https://www.reddit.com/r/islam/comments/p1/example/",
        title="Secret title",
        selftext="Sensitive post body",
    )
    monitor = RedditMonitor(
        config=make_config(tmp_path),
        reddit_client=FakeReddit([post]),
        matcher=KeywordMatcher.from_keywords(["Secret"]),
        storage=make_storage(tmp_path),
        notifier=FakeNotifier(failures_before_success=1),
        sleep=noop_sleep,
    )

    result = asyncio.run(monitor.run_check())
    logs = caplog.text

    assert result.notifications_sent == 0
    assert result.errors
    assert "Secret title" not in logs
    assert "Sensitive post body" not in logs

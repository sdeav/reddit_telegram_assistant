from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from .config import AppConfig
from .logging_config import safe_error_detail
from .matcher import KeywordMatcher
from .models import CheckResult, RedditPost
from .reddit_client import (
    RedditAuthenticationError,
    RedditConfigurationError,
    RedditTemporaryError,
    is_temporary_error,
)
from .storage import Storage

logger = logging.getLogger(__name__)


class RedditReader(Protocol):
    def fetch_new_posts(self, subreddit_name: str, limit: int) -> list[RedditPost]:
        ...

    def save_submission_by_id(self, post_id: str):
        ...


class MatchNotifier(Protocol):
    async def send_match_alert(self, post: RedditPost) -> None:
        ...


SleepFunc = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class MonitorRuntimeStatus:
    is_running: bool
    last_result: str
    last_successful_check_utc: datetime | None


class RedditMonitor:
    def __init__(
        self,
        *,
        config: AppConfig,
        reddit_client: RedditReader,
        matcher: KeywordMatcher,
        storage: Storage,
        notifier: MatchNotifier | None = None,
        sleep: SleepFunc = asyncio.sleep,
        max_retries: int = 3,
    ) -> None:
        self.config = config
        self.reddit_client = reddit_client
        self.matcher = matcher
        self.storage = storage
        self.notifier = notifier
        self._sleep = sleep
        self._max_retries = max_retries
        self._lock = asyncio.Lock()
        self._last_result = "not run yet"
        self._last_successful_check_utc: datetime | None = None

    async def run_check(self) -> CheckResult:
        if self._lock.locked():
            now = utc_now()
            self._last_result = "skipped: check already running"
            return CheckResult(
                started_at_utc=now,
                completed_at_utc=now,
                subreddits_checked=0,
                posts_inspected=0,
                matches_found=0,
                notifications_sent=0,
                auto_saved=0,
                errors=(),
                skipped_overlap=True,
            )

        async with self._lock:
            return await self._run_check_locked()

    def status(self) -> MonitorRuntimeStatus:
        return MonitorRuntimeStatus(
            is_running=self._lock.locked(),
            last_result=self._last_result,
            last_successful_check_utc=self._last_successful_check_utc,
        )

    async def _run_check_locked(self) -> CheckResult:
        started = utc_now()
        logger.info("Reddit check started subreddit_count=%s", len(self.config.subreddits))
        errors: list[str] = []
        posts_inspected = 0
        matches_found = 0
        notifications_sent = 0
        auto_saved = 0
        subreddits_checked = 0

        self.storage.cleanup_seen()

        for subreddit in self.config.subreddits:
            try:
                posts = await self._fetch_posts_with_retry(subreddit)
                subreddits_checked += 1
            except (RedditAuthenticationError, RedditConfigurationError) as exc:
                detail = safe_error_detail(exc)
                logger.error("Reddit check stopped for configuration/authentication error detail=%s", detail)
                errors.append(detail)
                break
            except Exception as exc:
                detail = safe_error_detail(exc)
                logger.warning("Reddit check failed for one subreddit detail=%s", detail)
                errors.append(detail)
                continue

            for post in posts:
                if self.storage.has_seen(post.id):
                    continue

                posts_inspected += 1
                if self.matcher.matches(post.title, post.selftext):
                    matches_found += 1
                    if self.notifier is not None:
                        try:
                            await self.notifier.send_match_alert(post)
                            notifications_sent += 1
                            logger.info("Telegram notification sent post_id=%s", post.id)
                        except Exception as exc:
                            detail = safe_error_detail(exc)
                            logger.warning("Telegram notification failed detail=%s", detail)
                            errors.append(f"telegram:{detail}")
                            continue

                    self.storage.mark_seen(post.id)

                    if self.config.auto_save_matches:
                        try:
                            self.reddit_client.save_submission_by_id(post.id)
                            auto_saved += 1
                            logger.info("Matched Reddit post saved post_id=%s", post.id)
                        except Exception as exc:
                            detail = safe_error_detail(exc)
                            logger.warning("Matched Reddit post save failed detail=%s", detail)
                else:
                    self.storage.mark_seen(post.id)

        completed = utc_now()
        if not errors:
            self._last_successful_check_utc = completed
        self._last_result = (
            f"checked={subreddits_checked} inspected={posts_inspected} "
            f"matches={matches_found} errors={len(errors)}"
        )
        logger.info(
            "Reddit check completed subreddit_count=%s posts_inspected=%s matches=%s errors=%s",
            subreddits_checked,
            posts_inspected,
            matches_found,
            len(errors),
        )
        return CheckResult(
            started_at_utc=started,
            completed_at_utc=completed,
            subreddits_checked=subreddits_checked,
            posts_inspected=posts_inspected,
            matches_found=matches_found,
            notifications_sent=notifications_sent,
            auto_saved=auto_saved,
            errors=tuple(errors),
        )

    async def _fetch_posts_with_retry(self, subreddit: str) -> list[RedditPost]:
        attempt = 0
        while True:
            try:
                return await asyncio.to_thread(
                    self.reddit_client.fetch_new_posts,
                    subreddit,
                    self.config.reddit_new_post_limit,
                )
            except (RedditAuthenticationError, RedditConfigurationError):
                raise
            except Exception as exc:
                if not is_temporary_error(exc) or attempt >= self._max_retries:
                    raise
                delay = min(2**attempt, 30)
                attempt += 1
                logger.warning(
                    "Temporary Reddit error; retrying attempt=%s delay_seconds=%s detail=%s",
                    attempt,
                    delay,
                    safe_error_detail(exc),
                )
                await self._sleep(float(delay))


def utc_now() -> datetime:
    return datetime.now(UTC)

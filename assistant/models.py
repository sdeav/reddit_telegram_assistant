from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class RedditPost:
    id: str
    subreddit: str
    permalink: str
    title: str = ""
    selftext: str = ""


@dataclass(frozen=True)
class SaveResult:
    item_id: str
    item_kind: str
    permalink: str
    already_saved_ok: bool = True


@dataclass(frozen=True)
class SavedItem:
    item_id: str
    item_kind: str
    label: str
    permalink: str


@dataclass(frozen=True)
class RecentComment:
    item_id: str
    body: str
    permalink: str


@dataclass(frozen=True)
class RedditAccountVerification:
    authenticated_username: str
    expected_username: str
    matches_expected: bool
    configured_scopes: tuple[str, ...]
    granted_scopes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CheckResult:
    started_at_utc: datetime
    completed_at_utc: datetime
    subreddits_checked: int
    posts_inspected: int
    matches_found: int
    notifications_sent: int
    auto_saved: int
    errors: tuple[str, ...] = field(default_factory=tuple)
    skipped_overlap: bool = False

    @property
    def ok(self) -> bool:
        return not self.skipped_overlap and not self.errors

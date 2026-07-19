from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .config import AppConfig, REQUIRED_REDDIT_SCOPES, normalize_reddit_username
from .logging_config import safe_error_detail
from .models import RecentComment, RedditAccountVerification, RedditPost, SavedItem, SaveResult

REDDIT_HOSTS = {"reddit.com", "www.reddit.com", "old.reddit.com", "np.reddit.com"}
REDDIT_ID_RE = re.compile(r"^[A-Za-z0-9_]+$")


class RedditClientError(RuntimeError):
    """Base Reddit integration error with safe details."""


class RedditAuthenticationError(RedditClientError):
    """Raised for authentication or authorization failures."""


class RedditConfigurationError(RedditClientError):
    """Raised for invalid Reddit configuration or URL input."""


class RedditTemporaryError(RedditClientError):
    """Raised for retryable Reddit failures."""


@dataclass(frozen=True)
class ParsedRedditUrl:
    kind: str
    item_id: str


class RedditClient:
    def __init__(self, reddit: Any) -> None:
        self._reddit = reddit

    @classmethod
    def from_config(cls, config: AppConfig) -> "RedditClient":
        try:
            import praw
        except ModuleNotFoundError as exc:
            raise RedditConfigurationError(
                "PRAW is not installed. Install project dependencies first."
            ) from exc

        reddit = praw.Reddit(
            client_id=config.reddit_client_id,
            client_secret=config.reddit_client_secret,
            refresh_token=config.reddit_refresh_token,
            user_agent=config.reddit_user_agent,
        )
        return cls(reddit)

    def verify_expected_username(self, expected_username: str) -> RedditAccountVerification:
        try:
            username = self.authenticated_username()
            granted_scopes = self.granted_scopes()
        except Exception as exc:
            raise RedditAuthenticationError(safe_error_detail(exc)) from exc

        normalized_user = normalize_reddit_username(username)
        normalized_expected = normalize_reddit_username(expected_username)
        return RedditAccountVerification(
            authenticated_username=username,
            expected_username=normalized_expected,
            matches_expected=normalized_user == normalized_expected,
            configured_scopes=REQUIRED_REDDIT_SCOPES,
            granted_scopes=granted_scopes,
        )

    def authenticated_username(self) -> str:
        user = self._reddit.user.me()
        return str(user)

    def granted_scopes(self) -> tuple[str, ...]:
        auth = getattr(self._reddit, "auth", None)
        scopes_method = getattr(auth, "scopes", None)
        if scopes_method is None:
            return ()
        scopes = scopes_method()
        return tuple(sorted(str(scope) for scope in scopes))

    def fetch_new_posts(self, subreddit_name: str, limit: int) -> list[RedditPost]:
        subreddit = self._reddit.subreddit(subreddit_name)
        posts: list[RedditPost] = []
        for raw_post in subreddit.new(limit=limit):
            post = make_reddit_post(raw_post, fallback_subreddit=subreddit_name)
            if post is not None:
                posts.append(post)
        return posts

    def save_submission_by_id(self, post_id: str) -> SaveResult:
        if not REDDIT_ID_RE.fullmatch(post_id):
            raise RedditConfigurationError("Invalid Reddit post id")
        try:
            submission = self._reddit.submission(id=post_id)
            submission.save()
            permalink = normalize_permalink(getattr(submission, "permalink", ""))
            return SaveResult(item_id=post_id, item_kind="post", permalink=permalink)
        except Exception as exc:
            raise classify_reddit_exception(exc) from exc

    def save_url(self, reddit_url: str) -> SaveResult:
        parsed = parse_reddit_url(reddit_url)
        try:
            if parsed.kind == "comment":
                item = self._reddit.comment(id=parsed.item_id)
                item.save()
                return SaveResult(
                    item_id=parsed.item_id,
                    item_kind="comment",
                    permalink=normalize_permalink(getattr(item, "permalink", "")),
                )
            item = self._reddit.submission(id=parsed.item_id)
            item.save()
            return SaveResult(
                item_id=parsed.item_id,
                item_kind="post",
                permalink=normalize_permalink(getattr(item, "permalink", "")),
            )
        except Exception as exc:
            raise classify_reddit_exception(exc) from exc

    def list_saved(self, *, limit: int = 50) -> list[SavedItem]:
        try:
            user = self._reddit.user.me()
            items = []
            for raw_item in user.saved(limit=limit):
                saved = make_saved_item(raw_item)
                if saved is not None:
                    items.append(saved)
            return items
        except Exception as exc:
            raise classify_reddit_exception(exc) from exc

    def list_my_recent_comments(self, *, limit: int = 50) -> list[RecentComment]:
        try:
            user = self._reddit.user.me()
            comments = []
            for raw_comment in user.comments.new(limit=limit):
                comment = make_recent_comment(raw_comment)
                if comment is not None:
                    comments.append(comment)
            return comments
        except Exception as exc:
            raise classify_reddit_exception(exc) from exc


def make_reddit_post(raw_post: Any, *, fallback_subreddit: str) -> RedditPost | None:
    post_id = str(getattr(raw_post, "id", "") or "")
    if not post_id:
        return None
    subreddit = str(getattr(raw_post, "subreddit", "") or fallback_subreddit)
    return RedditPost(
        id=post_id,
        subreddit=subreddit,
        permalink=normalize_permalink(str(getattr(raw_post, "permalink", "") or "")),
        title=str(getattr(raw_post, "title", "") or ""),
        selftext=str(getattr(raw_post, "selftext", "") or ""),
    )


def make_saved_item(raw_item: Any) -> SavedItem | None:
    item_id = str(getattr(raw_item, "id", "") or "")
    if not item_id:
        return None
    item_kind = classify_listing_item(raw_item)
    label = "Saved comment" if item_kind == "comment" else "Saved post"
    return SavedItem(
        item_id=item_id,
        item_kind=item_kind,
        label=label,
        permalink=normalize_permalink(str(getattr(raw_item, "permalink", "") or "")),
    )


def make_recent_comment(raw_comment: Any) -> RecentComment | None:
    item_id = str(getattr(raw_comment, "id", "") or "")
    if not item_id:
        return None
    body = str(getattr(raw_comment, "body", "") or "")
    return RecentComment(
        item_id=item_id,
        body=body,
        permalink=normalize_permalink(str(getattr(raw_comment, "permalink", "") or "")),
    )


def classify_listing_item(item: Any) -> str:
    type_name = type(item).__name__.lower()
    if "comment" in type_name or hasattr(item, "body"):
        return "comment"
    return "post"


def normalize_permalink(permalink: str) -> str:
    if not permalink:
        return "https://www.reddit.com/"
    if permalink.startswith("http://") or permalink.startswith("https://"):
        return permalink
    if not permalink.startswith("/"):
        permalink = f"/{permalink}"
    return f"https://www.reddit.com{permalink}"


def parse_reddit_url(reddit_url: str) -> ParsedRedditUrl:
    parsed = urlparse(reddit_url.strip())
    host = parsed.netloc.lower()
    if parsed.scheme not in {"http", "https"} or host not in REDDIT_HOSTS:
        raise RedditConfigurationError("Only Reddit URLs are supported")

    segments = [segment for segment in parsed.path.split("/") if segment]
    if len(segments) >= 4 and segments[0].lower() == "r" and segments[2].lower() == "comments":
        submission_id = segments[3]
        if not REDDIT_ID_RE.fullmatch(submission_id):
            raise RedditConfigurationError("Invalid Reddit submission URL")
        if len(segments) >= 6 and REDDIT_ID_RE.fullmatch(segments[5]):
            return ParsedRedditUrl(kind="comment", item_id=segments[5])
        return ParsedRedditUrl(kind="post", item_id=submission_id)

    if len(segments) >= 2 and segments[0].lower() == "comments":
        submission_id = segments[1]
        if REDDIT_ID_RE.fullmatch(submission_id):
            return ParsedRedditUrl(kind="post", item_id=submission_id)

    raise RedditConfigurationError("Unsupported Reddit URL format")


def classify_reddit_exception(exc: Exception) -> RedditClientError:
    if is_auth_error(exc):
        return RedditAuthenticationError(safe_error_detail(exc))
    if is_temporary_error(exc):
        return RedditTemporaryError(safe_error_detail(exc))
    return RedditClientError(safe_error_detail(exc))


def is_temporary_error(exc: BaseException) -> bool:
    if isinstance(exc, RedditTemporaryError):
        return True
    status = getattr(exc, "status", None) or getattr(exc, "status_code", None)
    if status in {408, 429, 500, 502, 503, 504}:
        return True
    name = exc.__class__.__name__.lower()
    return any(
        fragment in name
        for fragment in (
            "timeout",
            "temporarilyunavailable",
            "servererror",
            "toomanyrequests",
            "requestexception",
            "connectionerror",
        )
    )


def is_auth_error(exc: BaseException) -> bool:
    if isinstance(exc, RedditAuthenticationError):
        return True
    status = getattr(exc, "status", None) or getattr(exc, "status_code", None)
    if status in {401, 403}:
        return True
    name = exc.__class__.__name__.lower()
    return any(fragment in name for fragment in ("invalidtoken", "forbidden", "unauthorized"))

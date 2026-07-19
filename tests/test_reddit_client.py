from __future__ import annotations

from types import SimpleNamespace

import pytest

from assistant.config import REQUIRED_REDDIT_SCOPES
from assistant.reddit_client import RedditClient, RedditConfigurationError, make_reddit_post, parse_reddit_url


class FakeSubmission:
    def __init__(self, item_id: str, permalink: str = "/r/islam/comments/post/slug/") -> None:
        self.id = item_id
        self.permalink = permalink
        self.saved = False

    def save(self) -> None:
        self.saved = True


class FakeComment:
    def __init__(self, item_id: str, body: str = "recent comment", permalink: str = "/r/islam/comments/post/slug/comment/") -> None:
        self.id = item_id
        self.body = body
        self.permalink = permalink
        self.saved = False

    def save(self) -> None:
        self.saved = True


class FakeCommentsListing:
    def __init__(self, comments: list[FakeComment]) -> None:
        self._comments = comments

    def new(self, *, limit: int):
        return self._comments[:limit]


class FakeUser:
    def __init__(self) -> None:
        self.comments = FakeCommentsListing([FakeComment("c1", "needle in haystack")])
        self._saved = [
            FakeSubmission("s1", "/r/islam/comments/s1/slug/"),
            FakeComment("c1", "saved body", "/r/islam/comments/s1/slug/c1/"),
        ]

    def __str__(self) -> str:
        return "ExpectedUser"

    def saved(self, *, limit: int):
        return self._saved[:limit]


class FakeUserService:
    def __init__(self) -> None:
        self.me_obj = FakeUser()

    def me(self) -> FakeUser:
        return self.me_obj


class FakeAuth:
    def scopes(self):
        return set(REQUIRED_REDDIT_SCOPES)


class FakeReddit:
    def __init__(self) -> None:
        self.user = FakeUserService()
        self.auth = FakeAuth()
        self.saved_submissions: dict[str, FakeSubmission] = {}
        self.saved_comments: dict[str, FakeComment] = {}

    def submission(self, *, id: str) -> FakeSubmission:
        submission = FakeSubmission(id)
        self.saved_submissions[id] = submission
        return submission

    def comment(self, *, id: str) -> FakeComment:
        comment = FakeComment(id)
        self.saved_comments[id] = comment
        return comment


def test_reddit_username_verification_accepts_u_prefix() -> None:
    client = RedditClient(FakeReddit())

    result = client.verify_expected_username("u/expecteduser")

    assert result.authenticated_username == "ExpectedUser"
    assert result.matches_expected is True
    assert result.configured_scopes == REQUIRED_REDDIT_SCOPES


def test_make_reddit_post_handles_missing_author_and_empty_selftext() -> None:
    class RawPost:
        id = "abc123"
        title = "safe title"
        selftext = None
        permalink = "/r/islam/comments/abc123/slug/"
        subreddit = "islam"

        @property
        def author(self):  # pragma: no cover - failure would prove it was accessed
            raise AssertionError("author must not be inspected")

    post = make_reddit_post(RawPost(), fallback_subreddit="fallback")

    assert post is not None
    assert post.id == "abc123"
    assert post.selftext == ""


def test_saving_by_reddit_post_url() -> None:
    reddit = FakeReddit()
    client = RedditClient(reddit)

    result = client.save_url("https://www.reddit.com/r/islam/comments/postid/example/")

    assert result.item_kind == "post"
    assert reddit.saved_submissions["postid"].saved is True


def test_saving_by_reddit_comment_url() -> None:
    reddit = FakeReddit()
    client = RedditClient(reddit)

    result = client.save_url("https://www.reddit.com/r/islam/comments/postid/example/commentid/")

    assert result.item_kind == "comment"
    assert reddit.saved_comments["commentid"].saved is True


def test_invalid_reddit_urls_are_rejected() -> None:
    with pytest.raises(RedditConfigurationError):
        parse_reddit_url("https://example.com/r/islam/comments/postid/example/")


def test_listing_saved_posts_and_comments() -> None:
    client = RedditClient(FakeReddit())

    items = client.list_saved(limit=10)

    assert [item.item_kind for item in items] == ["post", "comment"]
    assert items[0].label == "Saved post"
    assert items[1].label == "Saved comment"


def test_retrieving_authenticated_users_recent_comments() -> None:
    client = RedditClient(FakeReddit())

    comments = client.list_my_recent_comments(limit=10)

    assert len(comments) == 1
    assert comments[0].body == "needle in haystack"

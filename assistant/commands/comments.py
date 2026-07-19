from __future__ import annotations

from collections.abc import Sequence

from assistant.config import normalize_whitespace
from assistant.models import RecentComment

PAGE_SIZE = 5
EXCERPT_LENGTH = 120


def filter_comments(comments: Sequence[RecentComment], query: str | None) -> list[RecentComment]:
    normalized_query = normalize_whitespace(query or "").casefold()
    if not normalized_query:
        return list(comments)
    return [
        comment
        for comment in comments
        if normalized_query in normalize_whitespace(comment.body).casefold()
    ]


def page_comments(
    comments: Sequence[RecentComment],
    page: int,
    *,
    page_size: int = PAGE_SIZE,
) -> list[RecentComment]:
    start = max(page, 0) * page_size
    return list(comments[start : start + page_size])


def make_excerpt(body: str) -> str:
    text = normalize_whitespace(body)
    if not text or text == "[deleted]":
        return "(deleted comment)"
    if len(text) <= EXCERPT_LENGTH:
        return text
    return f"{text[: EXCERPT_LENGTH - 3]}..."


def format_comments_page(
    comments: Sequence[RecentComment],
    page: int,
    *,
    query: str | None = None,
    page_size: int = PAGE_SIZE,
) -> str:
    filtered = filter_comments(comments, query)
    visible = page_comments(filtered, page, page_size=page_size)
    title = "Your recent Reddit comments"
    if query:
        title += " matching search"
    lines = [f"{title} - page {page + 1}"]
    lines.append("Limited to recently fetched comments; this is not an unlimited history search.")
    if not visible:
        lines.append("No recent comments found.")
        return "\n".join(lines)
    offset = page * page_size
    for index, comment in enumerate(visible, start=1):
        lines.append(f"{offset + index}. {make_excerpt(comment.body)}")
        lines.append(comment.permalink)
    return "\n".join(lines)


def has_previous(page: int) -> bool:
    return page > 0


def has_next(
    comments: Sequence[RecentComment],
    page: int,
    *,
    query: str | None = None,
    page_size: int = PAGE_SIZE,
) -> bool:
    filtered = filter_comments(comments, query)
    return (page + 1) * page_size < len(filtered)

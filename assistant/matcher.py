from __future__ import annotations

import re
from dataclasses import dataclass

from .config import normalize_whitespace

WORD_BOUNDARY_LEFT = r"(?<![A-Za-z0-9_])"
WORD_BOUNDARY_RIGHT = r"(?![A-Za-z0-9_])"


@dataclass(frozen=True)
class KeywordMatcher:
    keywords: tuple[str, ...]
    patterns: tuple[re.Pattern[str], ...]

    @classmethod
    def from_keywords(cls, keywords: tuple[str, ...] | list[str]) -> "KeywordMatcher":
        normalized: list[str] = []
        seen: set[str] = set()
        for keyword in keywords:
            value = normalize_whitespace(keyword)
            if not value:
                continue
            key = value.casefold()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(value)
        patterns = tuple(_compile_keyword(value) for value in normalized)
        return cls(keywords=tuple(normalized), patterns=patterns)

    def matches(self, title: str | None, selftext: str | None) -> bool:
        haystack = normalize_whitespace(f"{title or ''} {selftext or ''}")
        if not haystack:
            return False
        return any(pattern.search(haystack) for pattern in self.patterns)


def _compile_keyword(keyword: str) -> re.Pattern[str]:
    tokens = [re.escape(token) for token in normalize_whitespace(keyword).split()]
    phrase = r"\s+".join(tokens)
    return re.compile(f"{WORD_BOUNDARY_LEFT}{phrase}{WORD_BOUNDARY_RIGHT}", re.IGNORECASE)

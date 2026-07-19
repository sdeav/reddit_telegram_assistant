from __future__ import annotations

from assistant.matcher import KeywordMatcher


def test_keyword_matching_is_case_insensitive() -> None:
    matcher = KeywordMatcher.from_keywords(["Zakat"])

    assert matcher.matches("question about zakat", "")


def test_phrase_matching_normalizes_whitespace() -> None:
    matcher = KeywordMatcher.from_keywords(["charity work"])

    assert matcher.matches("charity    work opportunity", "")


def test_partial_word_prevention() -> None:
    matcher = KeywordMatcher.from_keywords(["islam"])

    assert not matcher.matches("islamic architecture", "")
    assert matcher.matches("a question about islam", "")


def test_empty_self_text_is_supported() -> None:
    matcher = KeywordMatcher.from_keywords(["mosque"])

    assert matcher.matches("local mosque", None)

import app.text as text

from app.text import (
    estimate_tokens,
    fts_query,
    has_update_marker,
    lexical_overlap,
    lexical_terms,
    temporal_intent,
)


def test_lexical_terms_drop_question_scaffolding() -> None:
    terms = lexical_terms("What drink does Alice prefer?")
    assert "alice" in terms
    assert "drink" in terms
    assert "what" not in terms


def test_cjk_terms_include_bigrams() -> None:
    terms = lexical_terms("我的居住城市是京都")
    assert "居住" in terms
    assert "京都" in terms


def test_fts_query_is_safe() -> None:
    assert fts_query(['alpha', 'quote"value']) == '"alpha" OR "quote""value"'


def test_temporal_intent_marks_latest_and_earliest() -> None:
    assert temporal_intent("What is the latest value?") == "latest"
    assert temporal_intent("What was the first value?") == "earliest"
    assert temporal_intent("Where did Alice move?") == "none"


def test_temporal_intent_ignores_marker_substrings() -> None:
    assert temporal_intent("What do you know about Alice?") == "none"
    assert temporal_intent("Describe the blast radius.") == "none"


def test_update_marker_ignores_substrings() -> None:
    assert has_update_marker("Alice visited the known landmark.") is False


def test_cjk_token_estimate_does_not_under_count() -> None:
    assert estimate_tokens("京都") == 2
    assert estimate_tokens("Kyoto") == 2


def test_lexical_overlap_accepts_cjk_bigrams() -> None:
    assert lexical_overlap(["居住", "京都"], "我的居住城市是京都")


def test_explicit_iso_date_returns_utc_day_bounds() -> None:
    assert text.parse_explicit_date_range_ms("Where was I on 2024-02-29?") == (
        1_709_164_800_000,
        1_709_251_200_000,
    )


def test_explicit_chinese_date_returns_utc_day_bounds() -> None:
    assert text.parse_explicit_date_range_ms("2024年2月9日我住在哪里？") == (
        1_707_436_800_000,
        1_707_523_200_000,
    )


def test_explicit_date_parser_rejects_invalid_or_ambiguous_dates() -> None:
    assert text.parse_explicit_date_range_ms("What happened on 2023-02-29?") is None
    assert text.parse_explicit_date_range_ms("What changed from 2024-01-01 to 2024-02-01?") is None
    assert text.parse_explicit_date_range_ms("What happened yesterday or 上周三？") is None
    assert text.parse_explicit_date_range_ms("Who owns ticket PR-2024-01-01?") is None

from app.text import estimate_tokens, fts_query, lexical_overlap, lexical_terms, temporal_intent


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


def test_cjk_token_estimate_does_not_under_count() -> None:
    assert estimate_tokens("京都") == 2
    assert estimate_tokens("Kyoto") == 2


def test_lexical_overlap_accepts_cjk_bigrams() -> None:
    assert lexical_overlap(["居住", "京都"], "我的居住城市是京都")

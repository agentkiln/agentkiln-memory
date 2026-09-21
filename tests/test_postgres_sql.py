from app.postgres_schema import SCHEMA_SQL, to_tsquery


def test_to_tsquery_converts_quoted_or_terms() -> None:
    assert to_tsquery('"alpha" OR "beta"') == "alpha:* | beta:*"


def test_to_tsquery_keeps_cjk_terms_without_prefix_operator() -> None:
    assert to_tsquery('"京都"') == "京都"


def test_to_tsquery_returns_empty_for_no_terms() -> None:
    assert to_tsquery("") == ""
    assert to_tsquery('"***"') == ""


def test_to_tsquery_marks_cjk_terms_for_like_fallback() -> None:
    from app.postgres_schema import cjk_terms

    assert cjk_terms('"居住" OR "京都"') == ["居住", "京都"]
    assert cjk_terms('"alpha"') == []


def test_schema_sql_avoids_sqlite_only_features() -> None:
    lowered = SCHEMA_SQL.lower()
    assert "autoincrement" not in lowered
    assert "fts5" not in lowered
    assert "pragma" not in lowered
    assert "to_tsvector" in lowered

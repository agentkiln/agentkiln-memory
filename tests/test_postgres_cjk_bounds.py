from app.postgres_db import PostgresMemoryDatabase


def _captured_query(monkeypatch, query: str) -> tuple[str, tuple[object, ...]]:
    captured: list[tuple[str, tuple[object, ...]]] = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, params):
            captured.append((sql, params))

        def fetchall(self):
            return []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return Cursor()

    database = PostgresMemoryDatabase("postgresql://unused")
    monkeypatch.setattr(database, "_connect", Connection)
    assert database.lexical_search("user-a", query, 100) == []
    return captured[0]


def test_postgres_cjk_like_clauses_are_bounded_for_expanded_query(monkeypatch) -> None:
    single_characters = [chr(0x4E00 + index) for index in range(80)]
    query = " OR ".join(f'"{term}"' for term in ["北京", *single_characters])

    sql, params = _captured_query(monkeypatch, query)

    assert sql.count("m.content LIKE %s") <= 12
    assert "%北京%" in params


def test_postgres_single_cjk_query_keeps_legacy_content_fallback(monkeypatch) -> None:
    sql, params = _captured_query(monkeypatch, '"猫" OR "宠物"')

    assert sql.count("m.content LIKE %s") >= 1
    assert "%猫%" in params


def test_postgres_single_cjk_fallback_is_independent_of_query_term_order(monkeypatch) -> None:
    sql, params = _captured_query(monkeypatch, '"宠物" OR "猫"')

    assert sql.count("m.content LIKE %s") >= 1
    assert "%猫%" in params


def test_postgres_cjk_fallback_keeps_multiple_single_characters_with_many_terms(monkeypatch) -> None:
    multi_character = [chr(0x4E00 + index) + chr(0x4E20 + index) for index in range(12)]
    query = " OR ".join(f'"{term}"' for term in [*multi_character, "猫", "狗"])

    sql, params = _captured_query(monkeypatch, query)

    assert sql.count("m.content LIKE %s") <= 12
    assert "%猫%" in params
    assert "%狗%" in params

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.db import memory_id_for
from app.main import create_app
from app.postgres_db import PostgresMemoryDatabase
from app.service import _event_day_range


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "memory.db",
        api_key=None,
        llm_mode="off",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o-mini",
        embedding_model="text-embedding-v4",
        embedding_api_key=None,
        embedding_base_url="https://api.openai.com/v1",
        timeout_seconds=1,
        candidate_limit=100,
        max_output_tokens=8000,
        max_output_items=24,
        vector_min_similarity=0.35,
        vector_only_min_similarity=0.65,
        search_concurrency=4,
        add_concurrency=4,
    )


def test_explicit_day_finds_source_by_timestamp_without_date_in_content(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    for request_id, session_id, timestamp in (
        ("depot-jan-2", "depot-session-2", 1704153600000),
        ("depot-jan-1", "depot-session-1", 1704067200000),
    ):
        response = client.post(
            "/add",
            json={
                "request_id": request_id,
                "user_id": "depot-user",
                "session_id": session_id,
                "messages": [
                    {"role": "user", "timestamp": timestamp, "content": "The depot update is ready."}
                ],
            },
        )
        assert response.status_code == 200

    result = client.post(
        "/search",
        json={
            "user_id": "depot-user",
            "query": "Which depot update was on 2024-01-01?",
            "top_k": 1,
        },
    )

    assert result.status_code == 200
    assert result.json()["data"][0]["id"] == memory_id_for("depot-user", "depot-jan-1", 0)


def test_postgres_date_lookup_uses_user_and_half_open_day_bounds(monkeypatch) -> None:
    captured = {}

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, params):
            captured["sql"] = sql
            captured["params"] = params

        def fetchall(self):
            return []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return Cursor()

    database = object.__new__(PostgresMemoryDatabase)
    monkeypatch.setattr(database, "_connect", Connection)

    assert database.date_search("depot-user", 1704067200000, 1704153600000, 20) == []
    assert "m.user_id = %s" in captured["sql"]
    assert "m.occurred_at >= %s" in captured["sql"]
    assert "m.occurred_at < %s" in captured["sql"]
    assert captured["params"] == ("depot-user", 1704067200000, 1704153600000, 20)


def test_date_in_project_name_is_not_used_as_event_timestamp() -> None:
    assert _event_day_range("Who approved project milestone 2024-01-01?") is None
    assert _event_day_range("Who owns ticket PR-2024-01-01?") is None
    assert _event_day_range("What happened after 2024-01-01?") is None
    assert _event_day_range("Which ticket was due on 2024-01-01?") is None
    assert _event_day_range("What deadline was scheduled on 2024-01-01?") is None
    assert _event_day_range("What happened on 2024-01-01?") == (
        1704067200000,
        1704153600000,
    )
    assert _event_day_range("在2024年1月1日我住在哪里？") == (
        1704067200000,
        1704153600000,
    )
    assert _event_day_range("2024年1月1日我住在哪里？") == (
        1704067200000,
        1704153600000,
    )


def test_date_named_milestone_keeps_matching_content_ahead_of_timestamp(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    for request_id, timestamp, content in (
        ("milestone-target", 1703980800000, "Alice approved project milestone 2024-01-01."),
        ("milestone-decoy", 1704067200000, "Bob approved project milestone soon."),
    ):
        assert client.post(
            "/add",
            json={
                "request_id": request_id,
                "user_id": "milestone-user",
                "session_id": request_id,
                "messages": [{"role": "user", "timestamp": timestamp, "content": content}],
            },
        ).status_code == 200

    result = client.post(
        "/search",
        json={
            "user_id": "milestone-user",
            "query": "Who approved project milestone 2024-01-01?",
            "top_k": 1,
        },
    )

    assert result.status_code == 200
    assert result.json()["data"][0]["id"] == memory_id_for(
        "milestone-user", "milestone-target", 0
    )

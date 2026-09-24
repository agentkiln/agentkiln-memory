from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.db import MemoryDatabase
from app.llm import QueryPlan
from app.main import create_app
from app.text import lexical_terms


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


def test_single_character_cjk_term_is_indexed_from_compound_word() -> None:
    assert "猫" in lexical_terms("我养猫", index_cjk_characters=True)
    assert lexical_terms("猫") == ["猫"]


def test_multi_character_cjk_query_avoids_single_character_flood() -> None:
    assert all(len(term) > 1 for term in lexical_terms("我喜欢北京"))


def test_single_character_cjk_query_finds_memory(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    added = client.post(
        "/add",
        json={
            "request_id": "cat-1",
            "user_id": "cat-user",
            "session_id": "cat-session",
            "messages": [{"role": "user", "content": "我养猫"}],
        },
    )
    assert added.status_code == 200

    response = client.post(
        "/search",
        json={"user_id": "cat-user", "query": "猫", "top_k": 5},
    )

    assert response.status_code == 200
    assert response.json()["data"]
    assert "我养猫" in response.json()["data"][0]["content"]


def test_single_character_cjk_query_finds_existing_memory_with_old_index(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    with patch("app.db.lexical_terms", return_value=["养猫"]):
        added = client.post(
            "/add",
            json={
                "request_id": "old-cat-1",
                "user_id": "cat-user",
                "session_id": "cat-session",
                "messages": [{"role": "user", "content": "我养猫"}],
            },
        )
    assert added.status_code == 200

    response = client.post(
        "/search",
        json={"user_id": "cat-user", "query": "猫", "top_k": 5},
    )

    assert response.status_code == 200
    assert response.json()["data"]
    assert "我养猫" in response.json()["data"][0]["content"]


@pytest.mark.parametrize("expansion", ["pet", "宠物"])
def test_single_character_cjk_query_with_expansion_finds_old_index(
    tmp_path: Path, expansion: str
) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    with patch("app.db.lexical_terms", return_value=["养猫"]):
        added = client.post(
            "/add",
            json={
                "request_id": "old-cat-expanded",
                "user_id": "cat-user",
                "session_id": "cat-session",
                "messages": [{"role": "user", "content": "我养猫"}],
            },
        )
    assert added.status_code == 200

    with patch(
        "app.service.MemoryLLM.analyze_query",
        return_value=QueryPlan(terms=[expansion], facets=[], intent="none"),
    ):
        response = client.post(
            "/search",
            json={"user_id": "cat-user", "query": "猫", "top_k": 5},
        )

    assert response.status_code == 200
    assert response.json()["data"]
    assert "我养猫" in response.json()["data"][0]["content"]


def test_single_character_cjk_fallback_respects_user_and_limit(tmp_path: Path) -> None:
    config = _settings(tmp_path)
    client = TestClient(create_app(config))
    with patch("app.db.lexical_terms", return_value=["养猫"]):
        for user_id in ("cat-user", "other-user"):
            added = client.post(
                "/add",
                json={
                    "request_id": f"old-cat-{user_id}",
                    "user_id": user_id,
                    "session_id": "cat-session",
                    "messages": [{"role": "user", "content": "我养猫"}],
                },
            )
            assert added.status_code == 200
    added = client.post(
        "/add",
        json={
            "request_id": "new-cat-1",
            "user_id": "cat-user",
            "session_id": "cat-session",
            "messages": [{"role": "user", "content": "我养猫"}],
        },
    )
    assert added.status_code == 200

    rows = MemoryDatabase(config.database_path).lexical_search("cat-user", '"猫"', limit=2)

    assert len(rows) == 2
    assert len({row.id for row in rows}) == 2
    assert {row.user_id for row in rows} == {"cat-user"}

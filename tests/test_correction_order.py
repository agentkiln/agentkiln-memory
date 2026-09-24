from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.db import MemoryRow, memory_id_for
from app.main import create_app
from app.service import MemoryService


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


def _row(memory_id: str, content: str, created_at: str, ordinal: int = 0) -> MemoryRow:
    return MemoryRow(
        id=memory_id,
        row_id=0,
        user_id="user-a",
        session_id="session-a",
        request_id="request-a",
        ordinal=ordinal,
        role="user",
        content=content,
        occurred_at=None,
        created_at=created_at,
        search_text="",
        fts_rank=0.0,
    )


def test_search_retains_later_untimed_correction(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    for request_id, code in (("correction-1", "alpha"), ("correction-2", "beta")):
        response = client.post(
            "/add",
            json={
                "request_id": request_id,
                "user_id": "correction-user",
                "session_id": "correction-session",
                "messages": [{"role": "user", "content": f"Correction launch code {code}"}],
            },
        )
        assert response.status_code == 200

    response = client.post(
        "/search",
        json={"user_id": "correction-user", "query": "launch code", "top_k": 1},
    )

    assert response.status_code == 200
    assert response.json()["data"]
    assert response.json()["data"][0]["id"] == memory_id_for("correction-user", "correction-2", 0)


def test_untimed_corrections_use_creation_order_without_row_ids() -> None:
    older = _row("older", "Correction launch code alpha", "2026-01-01T00:00:00+00:00")
    newer = _row("newer", "Correction launch code beta", "2026-01-01T00:00:01+00:00")

    assert MemoryService._suppress_superseded([newer, older]) == [newer]


def test_untimed_corrections_in_one_request_use_message_order() -> None:
    created_at = "2026-01-01T00:00:00+00:00"
    older = _row("older", "Correction launch code alpha", created_at, ordinal=0)
    newer = _row("newer", "Correction launch code beta", created_at, ordinal=1)

    assert MemoryService._suppress_superseded([newer, older]) == [newer]

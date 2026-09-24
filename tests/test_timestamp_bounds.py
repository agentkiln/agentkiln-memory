import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


MIN_TIMESTAMP_MS = -62_135_596_800_000
MAX_TIMESTAMP_MS = 253_402_300_799_999


def client_for(tmp_path: Path) -> TestClient:
    settings = Settings(
        database_path=tmp_path / "memory.db",
        api_key=None,
        llm_mode="off",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o-mini",
        embedding_model="test-embedding",
        embedding_api_key=None,
        embedding_base_url="https://api.openai.com/v1",
        timeout_seconds=1,
        candidate_limit=100,
        max_output_tokens=8000,
        max_output_items=24,
        vector_min_similarity=0.35,
        vector_only_min_similarity=0.65,
        search_concurrency=2,
        add_concurrency=2,
    )
    return TestClient(create_app(settings))


def add_payload(timestamp: int | None) -> dict:
    return {
        "request_id": "timestamp-request",
        "user_id": "timestamp-user",
        "session_id": "timestamp-session",
        "messages": [
            {"role": "user", "content": "The ancient relic code is ember.", "timestamp": timestamp}
        ],
    }


@pytest.mark.parametrize("timestamp", [MIN_TIMESTAMP_MS - 1, MAX_TIMESTAMP_MS + 1])
def test_add_rejects_timestamps_outside_datetime_range(tmp_path: Path, timestamp: int) -> None:
    client = client_for(tmp_path)

    response = client.post("/add", json=add_payload(timestamp))

    assert response.status_code == 422


def test_earliest_valid_timestamp_is_rendered_on_windows(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    assert client.post("/add", json=add_payload(MIN_TIMESTAMP_MS)).status_code == 200

    response = client.post(
        "/search", json={"query": "ancient relic code", "user_id": "timestamp-user", "top_k": 1}
    )

    assert response.status_code == 200
    assert "0001-01-01T00:00:00Z" in response.json()["data"][0]["content"]


def test_previously_stored_out_of_range_timestamp_does_not_break_search(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    assert client.post("/add", json=add_payload(None)).status_code == 200
    with sqlite3.connect(tmp_path / "memory.db") as connection:
        connection.execute("UPDATE memories SET occurred_at = ?", (MAX_TIMESTAMP_MS + 1,))

    response = client.post(
        "/search", json={"query": "ancient relic code", "user_id": "timestamp-user", "top_k": 1}
    )

    assert response.status_code == 200
    assert str(MAX_TIMESTAMP_MS + 1) in response.json()["data"][0]["content"]

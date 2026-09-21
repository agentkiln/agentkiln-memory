from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def settings(tmp_path: Path, api_key: str | None = None) -> Settings:
    return Settings(
        database_path=tmp_path / "memory.db",
        api_key=api_key,
        llm_mode="off",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o-mini",
        embedding_model="text-embedding-v4",
        timeout_seconds=1,
        candidate_limit=100,
        max_output_tokens=8000,
        max_output_items=24,
        vector_min_similarity=0.35,
        vector_only_min_similarity=0.65,
        search_concurrency=32,
        add_concurrency=16,
    )


def add_payload(user_id: str = "user-a") -> dict:
    return {
        "request_id": f"req-{user_id}",
        "messages": [
            {
                "role": "user",
                "timestamp": 1704067200000,
                "content": "My favorite drink is jasmine tea.",
            },
            {
                "role": "assistant",
                "timestamp": 1704067260000,
                "content": "I will remember that you prefer jasmine tea.",
            },
        ],
        "user_id": user_id,
        "session_id": "session-1",
    }


def test_health_add_search_contract(tmp_path: Path) -> None:
    client = TestClient(create_app(settings(tmp_path)))
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    payload = add_payload()
    added = client.post("/add", json=payload)
    assert added.status_code == 200
    assert added.json() == {
        "success": True,
        "request_id": payload["request_id"],
        "user_id": payload["user_id"],
        "session_id": payload["session_id"],
    }
    found = client.post(
        "/search",
        json={"query": "What drink do I prefer?", "user_id": "user-a", "top_k": 5},
    )
    assert found.status_code == 200
    assert set(found.json()) == {"data"}
    assert found.json()["data"]
    assert "jasmine tea" in found.json()["data"][0]["content"]


def test_idempotent_add_and_conflict(tmp_path: Path) -> None:
    client = TestClient(create_app(settings(tmp_path)))
    payload = add_payload()
    assert client.post("/add", json=payload).status_code == 200
    assert client.post("/add", json=payload).status_code == 200
    changed = add_payload()
    changed["messages"][0]["content"] = "My favorite drink is coffee."
    assert client.post("/add", json=changed).status_code == 409


def test_idempotent_retry_skips_model_calls(tmp_path: Path) -> None:
    client = TestClient(create_app(settings(tmp_path)))
    payload = add_payload()
    assert client.post("/add", json=payload).status_code == 200
    with patch("app.service.MemoryLLM.annotate_messages", side_effect=AssertionError("model called")):
        with patch("app.service.MemoryLLM.embed_texts", side_effect=AssertionError("embedding called")):
            assert client.post("/add", json=payload).status_code == 200


def test_user_scope_isolation(tmp_path: Path) -> None:
    client = TestClient(create_app(settings(tmp_path)))
    for user_id, city in (("user-a", "Kyoto"), ("user-b", "Osaka")):
        payload = {
            "request_id": f"alice-{user_id}",
            "messages": [{"role": "user", "timestamp": 1704067200000, "content": f"Alice moved to {city}."}],
            "user_id": user_id,
            "session_id": "alice-session",
        }
        assert client.post("/add", json=payload).status_code == 200
    first = client.post(
        "/search",
        json={"query": "Where did Alice move?", "user_id": "user-a", "top_k": 10},
    ).json()["data"]
    second = client.post(
        "/search",
        json={"query": "Where did Alice move?", "user_id": "user-b", "top_k": 10},
    ).json()["data"]
    assert "Kyoto" in " ".join(item["content"] for item in first)
    assert "Osaka" not in " ".join(item["content"] for item in first)
    assert "Osaka" in " ".join(item["content"] for item in second)


def test_top_k_and_options_contract(tmp_path: Path) -> None:
    client = TestClient(create_app(settings(tmp_path)))
    assert client.post("/add", json=add_payload()).status_code == 200
    too_large = client.post(
        "/search",
        json={"query": "jasmine", "user_id": "user-a", "top_k": 101},
    )
    assert too_large.status_code == 422
    result = client.post(
        "/search",
        json={
            "query": "What drink do I prefer?",
            "options": ["coffee", "jasmine tea", "water"],
            "user_id": "user-a",
            "top_k": 1,
        },
    ).json()["data"]
    assert len(result) == 1
    assert "jasmine tea" in result[0]["content"]


def test_authentication_and_restart_persistence(tmp_path: Path) -> None:
    configured = settings(tmp_path, api_key="secret")
    first = TestClient(create_app(configured))
    assert first.post("/add", json=add_payload()).status_code == 401
    assert first.post("/add", json=add_payload(), headers={"X-Api-Key": "secret"}).status_code == 200
    second = TestClient(create_app(configured))
    found = second.post(
        "/search",
        json={"query": "jasmine tea", "user_id": "user-a", "top_k": 5},
        headers={"Authorization": "Bearer secret"},
    ).json()["data"]
    assert "jasmine tea" in " ".join(item["content"] for item in found)


def test_latest_update_prefers_corrected_value(tmp_path: Path) -> None:
    client = TestClient(create_app(settings(tmp_path)))
    for request_id, timestamp, content in (
        ("update-1", 1704067200000, "My favorite drink is coffee."),
        ("update-2", 1735689600000, "Actually, I changed my favorite drink to jasmine tea."),
    ):
        response = client.post(
            "/add",
            json={
                "request_id": request_id,
                "messages": [{"role": "user", "timestamp": timestamp, "content": content}],
                "user_id": "update-user",
                "session_id": "update-session",
            },
        )
        assert response.status_code == 200
    latest = client.post(
        "/search",
        json={"query": "What is my latest favorite drink?", "user_id": "update-user", "top_k": 1},
    ).json()["data"][0]
    assert "jasmine tea" in latest["content"]


def test_streaming_prefix_visibility(tmp_path: Path) -> None:
    client = TestClient(create_app(settings(tmp_path)))
    first = {
        "request_id": "stream-1",
        "messages": [{"role": "user", "timestamp": 1704067200000, "content": "The launch code is alpha."}],
        "user_id": "stream-user",
        "session_id": "stream-session",
    }
    second = {
        "request_id": "stream-2",
        "messages": [{"role": "user", "timestamp": 1704153600000, "content": "Correction: the launch code is beta."}],
        "user_id": "stream-user",
        "session_id": "stream-session",
    }
    assert client.post("/add", json=first).status_code == 200
    before = client.post(
        "/search",
        json={"query": "What is the launch code?", "user_id": "stream-user", "top_k": 10},
    ).json()["data"]
    assert "alpha" in " ".join(item["content"] for item in before)
    assert "beta" not in " ".join(item["content"] for item in before)
    assert client.post("/add", json=second).status_code == 200
    after = client.post(
        "/search",
        json={"query": "What is the latest launch code?", "user_id": "stream-user", "top_k": 10},
    ).json()["data"]
    assert "beta" in " ".join(item["content"] for item in after)


def test_unrelated_query_does_not_backfill_random_evidence(tmp_path: Path) -> None:
    client = TestClient(create_app(settings(tmp_path)))
    assert client.post("/add", json=add_payload()).status_code == 200
    result = client.post(
        "/search",
        json={
            "query": "What is the launch authorization code?",
            "user_id": "user-a",
            "top_k": 100,
        },
    ).json()
    assert result == {"data": []}


def test_vector_only_candidates_require_strong_similarity(tmp_path: Path) -> None:
    def embeddings(texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            if "favorite drink" in text or "remember" in text:
                vectors.append([1.0, 0.0])
            else:
                vectors.append([0.5, 0.8660254])
        return vectors

    with patch("app.service.MemoryLLM.embed_texts", side_effect=embeddings):
        client = TestClient(create_app(settings(tmp_path)))
        assert client.post("/add", json=add_payload()).status_code == 200
        result = client.post(
            "/search",
            json={
                "query": "What is the launch authorization code?",
                "user_id": "user-a",
                "top_k": 100,
            },
        ).json()
    assert result == {"data": []}


def test_production_mode_requires_competition(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AML_PRODUCTION", "1")
    monkeypatch.setenv("AML_LLM_MODE", "dev_mock")
    monkeypatch.setenv("AML_API_KEY", "production-secret")
    monkeypatch.setenv("AML_DATABASE_PATH", str(tmp_path / "memory.db"))
    try:
        Settings.from_env()
    except ValueError as exc:
        assert "AML_LLM_MODE=competition" in str(exc)
    else:
        raise AssertionError("expected production mode to reject dev_mock")


def test_production_mode_requires_api_key(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AML_PRODUCTION", "1")
    monkeypatch.setenv("AML_LLM_MODE", "competition")
    monkeypatch.setenv("AML_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "runtime-model-key")
    monkeypatch.setenv("AML_DATABASE_PATH", str(tmp_path / "memory.db"))
    try:
        Settings.from_env()
    except ValueError as exc:
        assert "AML_API_KEY" in str(exc)
    else:
        raise AssertionError("expected production mode to require API key")


def test_production_mode_requires_model_credential(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AML_PRODUCTION", "1")
    monkeypatch.setenv("AML_LLM_MODE", "competition")
    monkeypatch.setenv("AML_API_KEY", "production-api-key-value")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("AML_DATABASE_PATH", str(tmp_path / "memory.db"))
    try:
        Settings.from_env()
    except ValueError as exc:
        assert "OPENAI_API_KEY" in str(exc)
    else:
        raise AssertionError("expected production mode to require model credential")


def test_production_mode_requires_https_model_endpoint(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AML_PRODUCTION", "1")
    monkeypatch.setenv("AML_LLM_MODE", "competition")
    monkeypatch.setenv("AML_API_KEY", "production-api-key-value")
    monkeypatch.setenv("OPENAI_API_KEY", "runtime-model-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://api.example.test/v1")
    monkeypatch.setenv("AML_DATABASE_PATH", str(tmp_path / "memory.db"))
    try:
        Settings.from_env()
    except ValueError as exc:
        assert "HTTPS" in str(exc)
    else:
        raise AssertionError("expected production mode to require HTTPS model endpoint")


def test_add_write_failure_rolls_back_all_message_rows(tmp_path: Path) -> None:
    client = TestClient(create_app(settings(tmp_path)))
    payload = {
        "request_id": "rollback-1",
        "messages": [
            {"role": "user", "content": "The rollback marker is alpha."},
            {"role": "user", "content": "The rollback marker is beta."},
        ],
        "user_id": "rollback-user",
        "session_id": "rollback-session",
    }
    with patch("app.db.MemoryDatabase.add", side_effect=RuntimeError("write failed")):
        try:
            client.post("/add", json=payload)
        except RuntimeError:
            pass
    result = client.post(
        "/search",
        json={"query": "rollback marker", "user_id": "rollback-user", "top_k": 10},
    ).json()
    assert result == {"data": []}

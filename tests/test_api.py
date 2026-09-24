import io
from dataclasses import replace
from pathlib import Path
import urllib.error
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import Settings
from app.db import MemoryRow
from app.llm import MemoryLLM, QueryPlan
from app.main import create_app
from app.schemas import SearchRequest
from app.service import MemoryService


def settings(tmp_path: Path, api_key: str | None = None) -> Settings:
    return Settings(
        database_path=tmp_path / "memory.db",
        api_key=api_key,
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


def test_rerank_changes_search_output_order(tmp_path: Path) -> None:
    client = TestClient(create_app(settings(tmp_path)))
    for word in ("alpha", "beta"):
        added = client.post(
            "/add",
            json={
                "request_id": f"rerank-{word}",
                "messages": [{"role": "user", "content": f"The launch code is {word}."}],
                "user_id": "rerank-user",
                "session_id": f"session-{word}",
            },
        )
        assert added.status_code == 200

    query = {"query": "What is the launch code?", "user_id": "rerank-user", "top_k": 1}
    baseline = client.post("/search", json=query).json()["data"][0]
    preferred = "beta" if "alpha" in baseline["content"] else "alpha"

    def fake_rerank(_query: str, documents: list[str]) -> list[float]:
        return [0.9 if preferred in document else 0.1 for document in documents]

    configured = replace(
        settings(tmp_path),
        llm_mode="competition",
        openai_api_key="test-key",
        embedding_api_key="test-key",
        rerank_model="qwen3.7-text-rerank",
        rerank_api_key="test-key",
        rerank_base_url="https://workspace.cn-beijing.maas.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
    )
    with (
        patch("app.service.MemoryLLM.analyze_query", return_value=QueryPlan([], [], "none")),
        patch(
            "app.service.MemoryLLM.embed_texts",
            side_effect=lambda texts: [MemoryLLM._mock_embedding(text) for text in texts],
        ),
        patch("app.service.MemoryLLM.rerank", side_effect=fake_rerank),
    ):
        reranked = TestClient(create_app(configured)).post("/search", json=query)

    assert reranked.status_code == 200
    assert preferred in reranked.json()["data"][0]["content"]


def test_rerank_limits_documents_before_call(tmp_path: Path) -> None:
    configured = replace(
        settings(tmp_path),
        llm_mode="competition",
        openai_api_key="test-key",
        embedding_api_key="test-key",
        rerank_model="qwen3.7-text-rerank",
        rerank_api_key="test-key",
        candidate_limit=600,
        max_output_items=5,
    )
    service = MemoryService(configured)
    rows = [
        MemoryRow(
            id=f"memory-{index}", row_id=index, user_id="rerank-user",
            session_id=f"session-{index}", request_id=f"request-{index}",
            ordinal=0, role="user", content=f"launch code {index}",
            occurred_at=None, created_at="2026-01-01T00:00:00Z",
            search_text="", fts_rank=0.0,
        )
        for index in range(501)
    ]

    def fake_rerank(_query: str, documents: list[str]) -> list[float]:
        assert len(documents) == 500
        assert "launch code 500" not in documents
        return [0.9 if document == "launch code 499" else 0.1 for document in documents]

    with (
        patch.object(service.database, "revision", return_value=1),
        patch.object(service.database, "lexical_search", return_value=rows),
        patch.object(service.database, "vector_search", return_value=[]),
        patch.object(service.llm, "analyze_query", return_value=QueryPlan([], [], "none")),
        patch.object(service.llm, "embed_texts", return_value=[[1.0, 0.0]]),
        patch.object(service, "_fuse", return_value=rows),
        patch.object(service, "_expand_neighbors", return_value=rows),
        patch.object(service, "_suppress_superseded", return_value=rows),
        patch.object(service, "_rank", return_value=[(1.0 - i / 1000, row) for i, row in enumerate(rows)]),
        patch.object(service, "_windows", side_effect=lambda _user, ranked: [(score, row, [row]) for score, row in ranked[:5]]),
        patch.object(service.llm, "rerank", side_effect=fake_rerank),
    ):
        result = service.search(SearchRequest(query="launch code", user_id="rerank-user", top_k=1))

    assert result[0].id == "memory-499"


def test_rerank_failure_is_retried_on_next_search(tmp_path: Path) -> None:
    writer = TestClient(create_app(settings(tmp_path)))
    assert writer.post("/add", json=add_payload()).status_code == 200
    configured = replace(
        settings(tmp_path),
        llm_mode="competition",
        openai_api_key="test-key",
        embedding_api_key="test-key",
        rerank_model="qwen3.7-text-rerank",
        rerank_api_key="test-key",
        rerank_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    client = TestClient(create_app(configured))
    query = {"query": "jasmine tea", "user_id": "user-a", "top_k": 5}

    with (
        patch("app.service.MemoryLLM.analyze_query", return_value=QueryPlan([], [], "none")),
        patch(
            "app.service.MemoryLLM.embed_texts",
            side_effect=lambda texts: [MemoryLLM._mock_embedding(text) for text in texts],
        ),
        patch("app.service.MemoryLLM.rerank", return_value=None) as rerank,
    ):
        assert client.post("/search", json=query).status_code == 200
        assert client.post("/search", json=query).status_code == 200

    assert rerank.call_count == 2


def test_add_malformed_embedding_is_service_unavailable(tmp_path: Path) -> None:
    configured = replace(
        settings(tmp_path),
        llm_mode="competition",
        openai_api_key="test-key",
        embedding_api_key="test-key",
    )
    client = TestClient(create_app(configured))
    payload = {
        "request_id": "malformed-vector",
        "messages": [{"role": "user", "content": "Remember the launch code."}],
        "user_id": "vector-user",
        "session_id": "vector-session",
    }

    with (
        patch("app.service.MemoryLLM.annotate_messages", return_value=[""]),
        patch(
            "app.service.MemoryLLM._post",
            return_value={"data": [{"index": 0, "embedding": [1.0, float("nan")]}]},
        ),
    ):
        response = client.post("/add", json=payload)

    assert response.status_code == 503


def test_add_does_not_reflect_upstream_error_body(tmp_path: Path) -> None:
    configured = replace(
        settings(tmp_path),
        llm_mode="competition",
        openai_api_key="test-key",
        embedding_api_key="test-key",
    )
    client = TestClient(create_app(configured))
    error = urllib.error.HTTPError(
        url="https://provider.example/v1/chat/completions",
        code=422,
        msg="Unprocessable Entity",
        hdrs={},
        fp=io.BytesIO(b'{"error":{"code":"InvalidParameter","message":"secret memory"}}'),
    )

    with patch("app.llm.urllib.request.urlopen", side_effect=error):
        response = client.post(
            "/add",
            json={
                "request_id": "upstream-error",
                "messages": [{"role": "user", "content": "secret memory"}],
                "user_id": "private-user",
                "session_id": "private-session",
            },
        )

    assert response.status_code == 503
    assert "InvalidParameter" in response.text
    assert "secret memory" not in response.text


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


def test_earliest_query_keeps_superseded_evidence(tmp_path: Path) -> None:
    client = TestClient(create_app(settings(tmp_path)))
    for request_id, timestamp, value in (
        ("history-old", 1704067200000, "alpha"),
        ("history-new", 1735689600000, "beta"),
    ):
        marker = "Correction: " if value == "beta" else ""
        response = client.post(
            "/add",
            json={
                "request_id": request_id,
                "messages": [
                    {
                        "role": "user",
                        "timestamp": timestamp,
                        "content": f"{marker}The launch code for project zephyr is {value}.",
                    }
                ],
                "user_id": "history-user",
                "session_id": f"session-{value}",
            },
        )
        assert response.status_code == 200

    earliest = client.post(
        "/search",
        json={
            "query": "What was the first launch code for project zephyr?",
            "user_id": "history-user",
            "top_k": 1,
        },
    )

    assert earliest.status_code == 200
    assert "alpha" in earliest.json()["data"][0]["content"]

    with patch("app.service.MemoryLLM.rerank", side_effect=AssertionError("temporal rerank called")):
        repeated = TestClient(create_app(settings(tmp_path))).post(
            "/search",
            json={
                "query": "What was the first launch code for project zephyr?",
                "user_id": "history-user",
                "top_k": 1,
            },
        )
    assert "alpha" in repeated.json()["data"][0]["content"]


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


def test_api_key_is_normalized_before_authentication(monkeypatch, tmp_path: Path) -> None:
    key = "normalized-key-value-1234"
    monkeypatch.setenv("AML_PRODUCTION", "1")
    monkeypatch.setenv("AML_LLM_MODE", "competition")
    monkeypatch.setenv("AML_API_KEY", f"  {key}  ")
    monkeypatch.setenv("OPENAI_API_KEY", "runtime-model-key")
    monkeypatch.setenv("AML_DATABASE_PATH", str(tmp_path / "memory.db"))
    resolved = Settings.from_env()
    assert resolved.api_key == key
    client = TestClient(create_app(resolved))
    wrong_key = client.post(
        "/add",
        json=add_payload(),
        headers={"Authorization": "Bearer " + ("wrong-" + key)},
    )
    assert wrong_key.status_code == 401
    accepted = client.post(
        "/add",
        json=add_payload(),
        headers={"Authorization": "Bearer " + key},
    )
    assert accepted.status_code != 401


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


def test_search_output_skips_unknown_packed_source_ids(tmp_path: Path) -> None:
    client = TestClient(create_app(settings(tmp_path)))
    assert client.post("/add", json=add_payload()).status_code == 200
    with patch("app.service.pack_windows") as packer:
        packer.return_value = [
            type(
                "Packed",
                (),
                {
                    "source_id": "mem_missing",
                    "content": "orphan",
                    "score": 1.0,
                },
            )()
        ]
        result = client.post(
            "/search",
            json={"query": "jasmine tea", "user_id": "user-a", "top_k": 5},
        )
    assert result.status_code == 200
    assert result.json() == {"data": []}


def test_window_repairs_out_of_order_concurrent_chunks(tmp_path: Path) -> None:
    client = TestClient(create_app(settings(tmp_path)))
    common = {"user_id": "chunk-user", "session_id": "shared-session"}
    chunk_one = {
        **common,
        "request_id": "eval:sample:chunk-1",
        "messages": [{"role": "assistant", "content": "The answer is zebra."}],
    }
    chunk_zero = {
        **common,
        "request_id": "eval:sample:chunk-0",
        "messages": [{"role": "user", "content": "The checkpoint question is ready."}],
    }
    assert client.post("/add", json=chunk_one).status_code == 200
    assert client.post("/add", json=chunk_zero).status_code == 200
    content = client.post(
        "/search",
        json={
            "query": "What answer follows the checkpoint question?",
            "user_id": "chunk-user",
            "top_k": 1,
        },
    ).json()["data"][0]["content"]
    assert content.index("checkpoint question") < content.index("answer is zebra")


def test_multi_hop_returns_both_relation_ends(tmp_path: Path) -> None:
    client = TestClient(create_app(settings(tmp_path)))
    for request_id, content in (
        ("hop-1", "Alice's mentor is Bob."),
        ("hop-2", "Bob lives in Kyoto."),
        ("hop-3", "Alice likes jazz music."),
    ):
        response = client.post(
            "/add",
            json={
                "request_id": request_id,
                "messages": [{"role": "user", "timestamp": 1704067200000, "content": content}],
                "user_id": "hop-user",
                "session_id": "hop-session",
            },
        )
        assert response.status_code == 200
    evidence = " ".join(
        item["content"]
        for item in client.post(
            "/search",
            json={
                "query": "Where does Alice's mentor live?",
                "user_id": "hop-user",
                "top_k": 2,
            },
        ).json()["data"]
    )
    assert "mentor is Bob" in evidence
    assert "Bob lives in Kyoto" in evidence


def test_search_cache_invalidates_when_add_concurrency_changes(tmp_path: Path) -> None:
    configured = settings(tmp_path)
    limited = Settings(
        database_path=configured.database_path,
        api_key=configured.api_key,
        llm_mode=configured.llm_mode,
        openai_api_key=configured.openai_api_key,
        openai_base_url=configured.openai_base_url,
        openai_model=configured.openai_model,
        embedding_model=configured.embedding_model,
        embedding_api_key=configured.embedding_api_key,
        embedding_base_url=configured.embedding_base_url,
        timeout_seconds=configured.timeout_seconds,
        candidate_limit=configured.candidate_limit,
        max_output_tokens=configured.max_output_tokens,
        max_output_items=configured.max_output_items,
        vector_min_similarity=configured.vector_min_similarity,
        vector_only_min_similarity=configured.vector_only_min_similarity,
        search_concurrency=configured.search_concurrency,
        add_concurrency=1,
    )
    client = TestClient(create_app(limited))
    payload = add_payload()
    assert client.post("/add", json=payload).status_code == 200
    first = client.post(
        "/search",
        json={"query": "jasmine tea", "user_id": "user-a", "top_k": 5},
    ).json()
    assert first["data"]
    changed = add_payload()
    changed["request_id"] = "req-added-later"
    changed["messages"][0]["content"] = "A new unrelated note."
    assert client.post("/add", json=changed).status_code == 200
    second = client.post(
        "/search",
        json={"query": "jasmine tea", "user_id": "user-a", "top_k": 5},
    ).json()
    assert second["data"]


def test_identifier_fields_reject_unbounded_values(tmp_path: Path) -> None:
    client = TestClient(create_app(settings(tmp_path)))
    payload = add_payload()
    payload["request_id"] = "x" * 513
    assert client.post("/add", json=payload).status_code == 422
    payload = add_payload()
    payload["user_id"] = "u" * 513
    assert client.post("/add", json=payload).status_code == 422


def test_add_rejects_oversized_message_batch(tmp_path: Path) -> None:
    client = TestClient(create_app(settings(tmp_path)))
    payload = add_payload()
    payload["messages"] = [
        {"role": "user", "content": f"memory item {index}"} for index in range(201)
    ]
    assert client.post("/add", json=payload).status_code == 422


def test_search_rejects_oversized_query_and_options(tmp_path: Path) -> None:
    client = TestClient(create_app(settings(tmp_path)))
    assert client.post(
        "/search",
        json={"query": "q" * 8_001, "user_id": "user-a", "top_k": 5},
    ).status_code == 422


def test_options_do_not_override_query_evidence(tmp_path: Path) -> None:
    client = TestClient(create_app(settings(tmp_path)))
    assert client.post(
        "/add",
        json={
            "request_id": "option-noise",
            "messages": [
                {
                    "role": "assistant",
                    "timestamp": 1704067200000,
                    "content": "The backup job runs every 12 hours.",
                }
            ],
            "user_id": "option-user",
            "session_id": "option-session",
        },
    ).status_code == 200
    result = client.post(
        "/search",
        json={
            "query": "How long does the access token last?",
            "options": ["12 hours", "24 hours", "48 hours"],
            "user_id": "option-user",
            "top_k": 3,
        },
    ).json()["data"]
    assert result == []


def test_search_scores_are_bounded_and_ordered(tmp_path: Path) -> None:
    client = TestClient(create_app(settings(tmp_path)))
    add_payload_data = add_payload()
    assert client.post("/add", json=add_payload_data).status_code == 200
    items = client.post(
        "/search",
        json={"query": "jasmine tea", "user_id": "user-a", "top_k": 10},
    ).json()["data"]
    assert items
    scores = [item["score"] for item in items]
    assert all(score is not None and 0.0 <= score <= 1.0 for score in scores)
    assert scores == sorted(scores, reverse=True)
    assert client.post(
        "/search",
        json={
            "query": "bounded",
            "options": ["x" * 2_001],
            "user_id": "user-a",
            "top_k": 5,
        },
    ).status_code == 422
    assert client.post(
        "/search",
        json={
            "query": "bounded",
            "options": ["option"] * 101,
            "user_id": "user-a",
            "top_k": 5,
        },
    ).status_code == 422


def test_implicit_recency_prefers_newer_state_when_dates_are_available(tmp_path: Path) -> None:
    client = TestClient(create_app(settings(tmp_path)))
    for request_id, timestamp, content in (
        ("recency-old", 1704067200000, "My backup contact is Alice."),
        ("recency-new", 1735689600000, "My backup contact is Bob."),
    ):
        assert client.post(
            "/add",
            json={
                "request_id": request_id,
                "messages": [{"role": "user", "timestamp": timestamp, "content": content}],
                "user_id": "recency-user",
                "session_id": "recency-session",
            },
        ).status_code == 200
    result = client.post(
        "/search",
        json={"query": "Who is my backup contact?", "user_id": "recency-user", "top_k": 1},
    ).json()["data"][0]
    assert "Bob" in result["content"]


def test_vector_index_filter_columns_exist(tmp_path: Path) -> None:
    configured = settings(tmp_path)
    client = TestClient(create_app(configured))
    assert client.post("/add", json=add_payload()).status_code == 200
    import sqlite3

    connection = sqlite3.connect(configured.database_path)
    try:
        indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(embeddings)").fetchall()
        }
    finally:
        connection.close()
    assert "idx_embeddings_user_model_dimensions" in indexes

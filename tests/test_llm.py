import io
import json
from dataclasses import replace
from pathlib import Path
import urllib.error
import urllib.request
from unittest.mock import patch

import pytest

from app.config import Settings
from app.llm import LLMUnavailable, MemoryLLM
from app.schemas import MemoryMessage


def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "memory.db",
        api_key=None,
        llm_mode="competition",
        openai_api_key="secret",
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o-mini",
        embedding_model="text-embedding-v4",
        embedding_api_key="secret",
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


def test_post_retries_transient_failure(tmp_path: Path) -> None:
    llm = MemoryLLM(settings(tmp_path))
    responses = [OSError("temporary"), {"data": [{"index": 0, "embedding": [1.0, 0.0]}]}]
    calls = 0

    class Response:
        def __init__(self, payload: dict):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self) -> bytes:
            import json

            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(*args, **kwargs):
        nonlocal calls
        calls += 1
        value = responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return Response(value)

    with patch("app.llm.urllib.request.urlopen", side_effect=fake_urlopen):
        result = llm._post("/embeddings", {"model": "x", "input": ["hello"]})
    assert result["data"][0]["embedding"] == [1.0, 0.0]
    assert calls == 2


@pytest.mark.parametrize(
    ("base_url", "expected_origin"),
    [
        (
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "https://dashscope.aliyuncs.com",
        ),
        (
            "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
            "https://workspace.cn-beijing.maas.aliyuncs.com",
        ),
    ],
)
def test_dashscope_qwen_rerank_uses_native_api(
    tmp_path: Path, base_url: str, expected_origin: str
) -> None:
    llm = MemoryLLM(
        replace(
            settings(tmp_path),
            rerank_model="qwen3.7-text-rerank",
            rerank_api_key="rerank-secret",
            rerank_base_url=base_url,
        )
    )
    response = {
        "output": {
            "results": [
                {"index": 1, "relevance_score": 0.9},
                {"index": 0, "relevance_score": 0.2},
            ]
        }
    }

    with patch.object(llm, "_post", return_value=response) as post:
        scores = llm.rerank("tea preference", ["coffee", "jasmine tea"])

    assert scores == [0.2, 0.9]
    post.assert_called_once_with(
        "/api/v1/services/rerank/text-rerank/text-rerank",
        {
            "model": "qwen3.7-text-rerank",
            "input": {"query": "tea preference", "documents": ["coffee", "jasmine tea"]},
        },
        base_url=expected_origin,
        api_key="rerank-secret",
    )


def test_dev_mock_mode_never_calls_rerank_provider(tmp_path: Path) -> None:
    llm = MemoryLLM(
        replace(
            settings(tmp_path),
            llm_mode="dev_mock",
            rerank_model="qwen3.7-text-rerank",
            rerank_api_key="test-key",
            rerank_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
    )

    with patch.object(llm, "_post", side_effect=AssertionError("external call")):
        assert llm.rerank("tea", ["jasmine tea"]) is None


def test_annotation_ignores_non_list_items_from_model(tmp_path: Path) -> None:
    llm = MemoryLLM(settings(tmp_path))
    response = {"choices": [{"message": {"content": json.dumps({"items": None})}}]}

    with patch.object(llm, "_post", return_value=response):
        assert llm.annotate_messages([MemoryMessage(role="user", content="hello")]) == [""]


def test_annotation_batches_200_messages_and_maps_local_indices(tmp_path: Path) -> None:
    llm = MemoryLLM(settings(tmp_path))
    messages = [MemoryMessage(role="user", content=f"marker-{index:03d}") for index in range(200)]
    calls: list[dict] = []

    def fake_post(path: str, payload: dict) -> dict:
        assert path == "/chat/completions"
        calls.append(payload)
        assert len(json.dumps(payload).encode("utf-8")) <= 32 * 1024
        batch = json.loads(payload["messages"][1]["content"])["messages"]
        assert len(batch) <= 16
        assert [item["index"] for item in batch] == list(range(len(batch)))
        items = [
            {"index": item["index"], "terms": [f"term-{item['content'].split('-')[1]}"]}
            for item in reversed(batch)
        ]
        return {"choices": [{"message": {"content": json.dumps({"items": items})}}]}

    with patch.object(llm, "_post", side_effect=fake_post):
        result = llm.annotate_messages(messages)

    assert len(calls) > 1
    assert sum(call["max_tokens"] for call in calls) > 1024
    assert result == [f"term-{index:03d}" for index in range(200)]


def test_annotation_splits_long_multibyte_message_and_merges_terms(tmp_path: Path) -> None:
    llm = MemoryLLM(settings(tmp_path))
    content = "start-tag:" + "界" * 10_000 + ":end-tag"
    fragments: list[str] = []
    expected_terms: list[str] = []

    def fake_post(path: str, payload: dict) -> dict:
        assert path == "/chat/completions"
        assert len(json.dumps(payload).encode("utf-8")) <= 32 * 1024
        batch = json.loads(payload["messages"][1]["content"])["messages"]
        items = []
        for item in batch:
            assert item["index"] in range(len(batch))
            fragments.append(item["content"])
            term = f"fragment-{len(fragments)}"
            expected_terms.append(term)
            items.append({"index": item["index"], "terms": ["shared", term]})
        return {"choices": [{"message": {"content": json.dumps({"items": items})}}]}

    with patch.object(llm, "_post", side_effect=fake_post):
        result = llm.annotate_messages([MemoryMessage(role="user", content=content)])

    assert len(fragments) > 1
    assert "".join(fragments) == content
    assert result == [" ".join(["shared", *expected_terms])]


def test_query_analysis_ignores_non_string_temporal_intent(tmp_path: Path) -> None:
    llm = MemoryLLM(settings(tmp_path))
    response = {
        "choices": [{"message": {"content": json.dumps({"temporal_intent": []})}}]
    }

    with patch.object(llm, "_post", return_value=response):
        assert llm.analyze_query("hello", None).intent == "none"


def test_post_logs_request_lifecycle_without_payload_content(tmp_path: Path) -> None:
    llm = MemoryLLM(settings(tmp_path))
    payload = {"model": "x", "input": ["secret memory"]}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self) -> bytes:
            return b'{"data": [{"index": 0, "embedding": [1.0, 0.0]}]}'

    with patch("app.llm.logger") as logger:
        with patch("app.llm.urllib.request.urlopen", return_value=Response()):
            result = llm._post("/embeddings", payload)

    assert result["data"][0]["embedding"] == [1.0, 0.0]
    messages = [call.args[0] % call.args[1:] for call in logger.info.call_args_list]
    assert any("llm call start" in message for message in messages)
    assert any("llm call success" in message for message in messages)
    assert "secret memory" not in repr(logger.mock_calls)


def test_http_error_logs_safe_identifiers_without_upstream_body(tmp_path: Path) -> None:
    llm = MemoryLLM(settings(tmp_path))
    error = urllib.error.HTTPError(
        url="https://example.test",
        code=422,
        msg="Unprocessable Entity",
        hdrs={},
        fp=io.BytesIO(
            b'{"error":{"code":"InvalidParameter","message":"secret memory is invalid"},'
            b'"request_id":"request-123"}'
        ),
    )
    with patch("app.llm.logger") as logger:
        with patch("app.llm.urllib.request.urlopen", side_effect=error):
            try:
                llm._post("/chat/completions", {"model": "x"})
            except Exception:
                pass

    error_messages = [
        call.args[0] % call.args[1:] for call in logger.error.call_args_list
    ]
    assert error_messages
    assert any("llm call failed" in message for message in error_messages)
    assert any("status=422" in message for message in error_messages)
    assert any("InvalidParameter" in message for message in error_messages)
    assert any("request-123" in message for message in error_messages)
    assert "secret memory" not in repr(logger.mock_calls)


def test_retry_after_header_is_bounded(tmp_path: Path) -> None:
    llm = MemoryLLM(settings(tmp_path))
    error = urllib.error.HTTPError(
        url="https://example.test",
        code=429,
        msg="rate limited",
        hdrs={"Retry-After": "120"},
        fp=None,
    )
    assert llm._retry_delay(error, attempt=0) == 60.0


def test_retry_after_accepts_numeric_seconds(tmp_path: Path) -> None:
    llm = MemoryLLM(settings(tmp_path))
    error = urllib.error.HTTPError(
        url="https://example.test",
        code=429,
        msg="rate limited",
        hdrs={"Retry-After": "5"},
        fp=None,
    )
    assert llm._retry_delay(error, attempt=0) == 5.0


def test_embedding_vectors_are_checked_for_consistency(tmp_path: Path) -> None:
    llm = MemoryLLM(settings(tmp_path))
    with patch.object(
        MemoryLLM,
        "_post",
        return_value={
            "data": [
                {"index": 0, "embedding": [1.0, 0.0]},
                {"index": 1, "embedding": [0.0]},
            ]
        },
    ):
        try:
            llm.embed_texts(["one", "two"])
        except Exception as exc:
            assert "dimension" in str(exc).lower()
        else:
            raise AssertionError("expected inconsistent dimensions to fail")


def test_embedding_requests_are_batched_at_ten_and_preserve_order(tmp_path: Path) -> None:
    llm = MemoryLLM(settings(tmp_path))
    texts = [f"text-{index}" for index in range(23)]
    batch_sizes: list[int] = []

    def fake_post(path: str, payload: dict, **kwargs) -> dict:
        assert path == "/embeddings"
        batch = payload["input"]
        batch_sizes.append(len(batch))
        if len(batch) > 10:
            raise LLMUnavailable("batch size is invalid")
        return {
            "data": [
                {"index": index, "embedding": [float(text.split("-")[1]), 1.0]}
                for index, text in reversed(list(enumerate(batch)))
            ]
        }

    with patch.object(llm, "_post", side_effect=fake_post):
        vectors = llm.embed_texts(texts)

    assert batch_sizes == [10, 10, 3]
    assert vectors == [[float(index), 1.0] for index in range(23)]


@pytest.mark.parametrize(
    ("base_url", "max_bytes", "expected_sizes"),
    [
        ("https://embedding.example.com/v1", 8000, [2, 2, 2, 2, 2]),
        ("https://dashscope.aliyuncs.com/compatible-mode/v1", 32000, [8, 2]),
    ],
)
def test_embedding_batches_respect_total_byte_budget(
    tmp_path: Path, base_url: str, max_bytes: int, expected_sizes: list[int]
) -> None:
    llm = MemoryLLM(replace(settings(tmp_path), embedding_base_url=base_url))
    texts = [str(index) + "x" * 3899 for index in range(10)]
    batches: list[list[str]] = []

    def fake_post(path: str, payload: dict, **kwargs) -> dict:
        batch = payload["input"]
        batches.append(batch)
        return {
            "data": [
                {"index": index, "embedding": [float(text[0]), 1.0]}
                for index, text in enumerate(batch)
            ]
        }

    with patch.object(llm, "_post", side_effect=fake_post):
        vectors = llm.embed_texts(texts)

    assert [len(batch) for batch in batches] == expected_sizes
    assert all(sum(len(text.encode("utf-8")) for text in batch) <= max_bytes for batch in batches)
    assert vectors == [[float(index), 1.0] for index in range(10)]


def test_long_embedding_preserves_text_and_returns_one_combined_vector(tmp_path: Path) -> None:
    llm = MemoryLLM(settings(tmp_path))
    long_text = "a" * 8190 + "🫖" + "tail"
    inputs: list[str] = []

    def fake_post(path: str, payload: dict, **kwargs) -> dict:
        assert path == "/embeddings"
        batch = payload["input"]
        assert all(len(chunk.encode("utf-8")) <= 4096 for chunk in batch)
        inputs.extend(batch)
        return {
            "data": [
                {
                    "index": index,
                    "embedding": [0.0, 1.0] if "🫖" in chunk else [1.0, 0.0],
                }
                for index, chunk in enumerate(batch)
            ]
        }

    with patch.object(llm, "_post", side_effect=fake_post):
        vectors = llm.embed_texts(["short", long_text, "last"])

    assert len(vectors) == 3
    assert vectors[0] == [1.0, 0.0]
    assert vectors[2] == [1.0, 0.0]
    long_chunks = inputs[1:-1]
    assert len(long_chunks) > 1
    assert "".join(long_chunks) == long_text
    total_bytes = sum(len(chunk.encode("utf-8")) for chunk in long_chunks)
    emoji_bytes = sum(len(chunk.encode("utf-8")) for chunk in long_chunks if "🫖" in chunk)
    assert vectors[1] == pytest.approx([1 - emoji_bytes / total_bytes, emoji_bytes / total_bytes])


def test_long_embedding_chunks_still_use_bounded_batches(tmp_path: Path) -> None:
    llm = MemoryLLM(settings(tmp_path))
    long_text = "甲" * 30_000
    batches: list[list[str]] = []

    def fake_post(path: str, payload: dict, **kwargs) -> dict:
        batch = payload["input"]
        batches.append(batch)
        return {
            "data": [
                {"index": index, "embedding": [1.0, 0.0]}
                for index, _chunk in enumerate(batch)
            ]
        }

    with patch.object(llm, "_post", side_effect=fake_post):
        assert llm.embed_texts([long_text]) == [[1.0, 0.0]]

    assert len(batches) >= 2
    assert all(1 <= len(batch) <= 10 for batch in batches)
    assert "".join(chunk for batch in batches for chunk in batch) == long_text
    assert all(len(chunk.encode("utf-8")) <= 4096 for batch in batches for chunk in batch)


def test_long_embedding_streams_batches_before_generating_all_chunks(tmp_path: Path) -> None:
    llm = MemoryLLM(settings(tmp_path))
    produced = 0
    requests = 0

    def chunks(_text: str):
        nonlocal produced
        for index in range(23):
            produced += 1
            if produced > 10 and requests == 0:
                raise AssertionError("all chunks generated before first request")
            yield f"part-{index}"

    def fake_post(path: str, payload: dict, **kwargs) -> dict:
        nonlocal requests
        requests += 1
        return {
            "data": [
                {"index": index, "embedding": [1.0, 0.0]}
                for index, _chunk in enumerate(payload["input"])
            ]
        }

    with patch.object(llm, "_embedding_chunks", side_effect=chunks):
        with patch.object(llm, "_post", side_effect=fake_post):
            assert llm.embed_texts(["long text"]) == [[1.0, 0.0]]

    assert produced == 23
    assert requests == 3


def test_embedding_rejects_invalid_index_in_later_batch(tmp_path: Path) -> None:
    llm = MemoryLLM(settings(tmp_path))
    calls = 0

    def fake_post(path: str, payload: dict, **kwargs) -> dict:
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "data": [
                    {"index": index, "embedding": [1.0, 0.0]}
                    for index in range(10)
                ]
            }
        return {"data": [{"index": 1, "embedding": [1.0, 0.0]}]}

    with patch.object(llm, "_post", side_effect=fake_post):
        with pytest.raises(LLMUnavailable, match="index"):
            llm.embed_texts([f"text-{index}" for index in range(11)])


@pytest.mark.parametrize(
    "embedding",
    [None, "not-a-vector", [1.0, "bad"], [1.0, float("nan")], [True, 0.0]],
)
def test_embedding_rejects_malformed_vectors(tmp_path: Path, embedding: object) -> None:
    llm = MemoryLLM(settings(tmp_path))

    with patch.object(
        llm,
        "_post",
        return_value={"data": [{"index": 0, "embedding": embedding}]},
    ):
        with pytest.raises(LLMUnavailable, match="invalid vector"):
            llm.embed_texts(["remember this"])


def test_competition_requires_embedding_credential(tmp_path: Path) -> None:
    llm = MemoryLLM(replace(settings(tmp_path), embedding_api_key=None))

    assert llm.ready is False
    with pytest.raises(LLMUnavailable, match="OPENAI_EMBEDDING_API_KEY"):
        llm.embed_texts(["remember this"])


def test_http_error_exposes_only_safe_identifiers(tmp_path: Path) -> None:
    llm = MemoryLLM(settings(tmp_path))
    error = urllib.error.HTTPError(
        url="https://example.test",
        code=422,
        msg="Unprocessable Entity",
        hdrs={},
        fp=io.BytesIO(
            b'{"error":{"code":"InvalidParameter","message":"secret memory leaked"},'
            b'"request_id":"11223344-5566-7788-99aa-bbccddeeff00"}'
        ),
    )
    with patch("app.llm.urllib.request.urlopen", side_effect=error):
        try:
            llm._post("/chat/completions", {"model": "x"})
        except Exception as exc:
            message = str(exc)
        else:
            raise AssertionError("expected failure")
    assert "422" in message
    assert "InvalidParameter" in message
    assert "11223344-5566-7788-99aa-bbccddeeff00" in message
    assert "secret memory" not in message


def test_model_redirect_does_not_forward_authorization(tmp_path: Path) -> None:
    llm = MemoryLLM(settings(tmp_path))
    captured = []

    def fake_urlopen(request, timeout):
        captured.append(request)
        return io.BytesIO(b"{}")

    with patch("app.llm.urllib.request.urlopen", side_effect=fake_urlopen):
        llm._post("/embeddings", {"model": "text-embedding-v4", "input": ["secret memory"]})

    assert captured[0].get_header("Authorization") == "Bearer secret"
    redirected = urllib.request.HTTPRedirectHandler().redirect_request(
        captured[0], None, 302, "Found", {}, "http://other.example/collect"
    )
    assert redirected is not None
    assert redirected.get_header("Authorization") is None

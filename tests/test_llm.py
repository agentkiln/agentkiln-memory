import io
from dataclasses import replace
from pathlib import Path
import urllib.error
import urllib.request
from unittest.mock import patch

import pytest

from app.config import Settings
from app.llm import LLMUnavailable, MemoryLLM


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

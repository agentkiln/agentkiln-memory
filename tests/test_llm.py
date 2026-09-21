import io
from pathlib import Path
import urllib.error
from unittest.mock import patch

from app.config import Settings
from app.llm import MemoryLLM


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


def test_http_error_includes_upstream_body(tmp_path: Path) -> None:
    llm = MemoryLLM(settings(tmp_path))
    error = urllib.error.HTTPError(
        url="https://example.test",
        code=422,
        msg="Unprocessable Entity",
        hdrs={},
        fp=io.BytesIO(b'{"error":"response_format is not supported"}'),
    )
    with patch("app.llm.urllib.request.urlopen", side_effect=error):
        try:
            llm._post("/chat/completions", {"model": "x"})
        except Exception as exc:
            message = str(exc)
        else:
            raise AssertionError("expected failure")
    assert "422" in message
    assert "response_format is not supported" in message

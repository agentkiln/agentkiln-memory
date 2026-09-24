from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


PRODUCTION_ENV_VALUES = {"1", "true", "yes", "on"}


def _require_https_endpoint(name: str, value: str) -> None:
    try:
        parsed = urlparse(value)
        valid = (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
        )
        _port = parsed.port
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(f"AML_PRODUCTION requires an HTTPS {name}")


def _require_postgresql_database(value: str | None) -> None:
    try:
        parsed = urlparse(value or "")
        valid = (
            parsed.scheme in {"postgresql", "postgres"}
            and bool(parsed.hostname)
            and bool(parsed.path.strip("/"))
        )
        _port = parsed.port
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("AML_PRODUCTION requires a PostgreSQL DATABASE_URL")


@dataclass(frozen=True)
class Settings:
    database_path: Path
    api_key: str | None
    llm_mode: str
    openai_api_key: str | None
    openai_base_url: str
    openai_model: str
    embedding_model: str
    embedding_api_key: str | None
    embedding_base_url: str
    timeout_seconds: float
    candidate_limit: int
    max_output_tokens: int
    max_output_items: int
    vector_min_similarity: float
    vector_only_min_similarity: float
    search_concurrency: int
    add_concurrency: int
    rerank_model: str | None = None
    rerank_api_key: str | None = None
    rerank_base_url: str = ""
    database_url: str | None = None
    query_model_max_chars: int = 16_000

    @classmethod
    def from_env(cls) -> "Settings":
        mode = os.getenv("AML_LLM_MODE", "off").strip().lower()
        if mode not in {"off", "dev_mock", "competition"}:
            raise ValueError("AML_LLM_MODE must be off, dev_mock, or competition")
        production = os.getenv("AML_PRODUCTION", "").strip().lower() in PRODUCTION_ENV_VALUES
        if production and mode != "competition":
            raise ValueError("AML_PRODUCTION requires AML_LLM_MODE=competition")
        if production and not (os.getenv("AML_API_KEY") or "").strip():
            raise ValueError("AML_PRODUCTION requires AML_API_KEY")
        production_api_key = (os.getenv("AML_API_KEY") or "").strip()
        if production and len(production_api_key) < 16:
            raise ValueError("AML_PRODUCTION requires AML_API_KEY with at least 16 characters")
        if production and not (os.getenv("OPENAI_API_KEY") or "").strip():
            raise ValueError("AML_PRODUCTION requires OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        openai_api_key = (os.getenv("OPENAI_API_KEY") or "").strip() or None
        embedding_api_key = (
            os.getenv("OPENAI_EMBEDDING_API_KEY") or openai_api_key or ""
        ).strip() or None
        embedding_base_url = (
            os.getenv("OPENAI_EMBEDDING_BASE_URL") or base_url
        ).strip().rstrip("/")
        rerank_model = (os.getenv("RERANK_MODEL") or "").strip() or None
        rerank_api_key = (
            os.getenv("RERANK_API_KEY") or embedding_api_key or ""
        ).strip() or None
        rerank_base_url = (
            os.getenv("RERANK_BASE_URL") or embedding_base_url
        ).strip().rstrip("/")
        database_url = (os.getenv("DATABASE_URL") or "").strip() or None
        if production:
            for name, value in (
                ("OPENAI_BASE_URL", base_url),
                ("OPENAI_EMBEDDING_BASE_URL", embedding_base_url),
                ("RERANK_BASE_URL", rerank_base_url),
            ):
                _require_https_endpoint(name, value)
            _require_postgresql_database(database_url)
        return cls(
            database_path=Path(os.getenv("AML_DATABASE_PATH", "data/memory.db")),
            api_key=production_api_key or None,
            llm_mode=mode,
            openai_api_key=openai_api_key,
            openai_base_url=base_url,
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            embedding_model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-v4"),
            embedding_api_key=embedding_api_key,
            embedding_base_url=embedding_base_url,
            rerank_model=rerank_model,
            rerank_api_key=rerank_api_key,
            rerank_base_url=rerank_base_url,
            timeout_seconds=float(os.getenv("AML_TIMEOUT_SECONDS", "90")),
            candidate_limit=max(40, min(2000, int(os.getenv("AML_CANDIDATE_LIMIT", "300")))),
            max_output_tokens=max(1000, int(os.getenv("AML_MAX_OUTPUT_TOKENS", "32000"))),
            max_output_items=max(1, min(100, int(os.getenv("AML_MAX_OUTPUT_ITEMS", "100")))),
            vector_min_similarity=float(os.getenv("AML_VECTOR_MIN_SIMILARITY", "0.35")),
            vector_only_min_similarity=float(os.getenv("AML_VECTOR_ONLY_MIN_SIMILARITY", "0.65")),
            search_concurrency=max(1, min(256, int(os.getenv("AML_SEARCH_CONCURRENCY", "32")))),
            add_concurrency=max(1, min(64, int(os.getenv("AML_ADD_CONCURRENCY", "16")))),
            database_url=database_url,
            query_model_max_chars=max(512, int(os.getenv("AML_QUERY_MODEL_MAX_CHARS", "16000"))),
        )

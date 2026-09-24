import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import Settings


def test_environment_values_are_bounded(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AML_DATABASE_PATH", str(tmp_path / "memory.db"))
    monkeypatch.setenv("AML_LLM_MODE", "off")
    monkeypatch.setenv("AML_CANDIDATE_LIMIT", "999999")
    monkeypatch.setenv("AML_MAX_OUTPUT_ITEMS", "999")
    monkeypatch.setenv("AML_SEARCH_CONCURRENCY", "9999")
    settings = Settings.from_env()
    assert settings.candidate_limit == 2000
    assert settings.max_output_items == 100
    assert settings.search_concurrency == 256


def test_default_max_output_items_matches_deployment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AML_DATABASE_PATH", str(tmp_path / "memory.db"))
    monkeypatch.setenv("AML_LLM_MODE", "off")
    monkeypatch.delenv("AML_MAX_OUTPUT_ITEMS", raising=False)
    settings = Settings.from_env()
    assert settings.max_output_items == 24


def test_embedding_reuses_chat_credentials_by_default(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AML_DATABASE_PATH", str(tmp_path / "memory.db"))
    monkeypatch.setenv("AML_LLM_MODE", "competition")
    monkeypatch.setenv("OPENAI_API_KEY", "chat-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://chat.example.com/v1")
    monkeypatch.delenv("OPENAI_EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_EMBEDDING_BASE_URL", raising=False)
    settings = Settings.from_env()
    assert settings.embedding_api_key == "chat-key"
    assert settings.embedding_base_url == "https://chat.example.com/v1"


def test_embedding_can_use_separate_endpoint(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AML_DATABASE_PATH", str(tmp_path / "memory.db"))
    monkeypatch.setenv("AML_LLM_MODE", "competition")
    monkeypatch.setenv("OPENAI_API_KEY", "chat-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://chat.example.com/v1")
    monkeypatch.setenv("OPENAI_EMBEDDING_API_KEY", "embed-key")
    monkeypatch.setenv("OPENAI_EMBEDDING_BASE_URL", "https://embed.example.com/v1/")
    settings = Settings.from_env()
    assert settings.embedding_api_key == "embed-key"
    assert settings.embedding_base_url == "https://embed.example.com/v1"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("OPENAI_BASE_URL", "https://"),
        ("OPENAI_EMBEDDING_BASE_URL", "http://embed.example.com/v1"),
        ("RERANK_BASE_URL", "http://rerank.example.com/native"),
    ],
)
def test_production_rejects_insecure_model_endpoints(key: str, value: str) -> None:
    env = {
        "AML_PRODUCTION": "1",
        "AML_LLM_MODE": "competition",
        "AML_API_KEY": "long-local-test-api-key",
        "OPENAI_API_KEY": "chat-key",
        "OPENAI_BASE_URL": "https://chat.example.com/v1",
        "OPENAI_EMBEDDING_BASE_URL": "https://embed.example.com/v1",
        "RERANK_MODEL": "qwen3.7-text-rerank",
        "RERANK_BASE_URL": "https://rerank.example.com/native",
        "DATABASE_URL": "postgresql://user:pass@db.example.com/memory?sslmode=require",
    }
    env[key] = value

    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(ValueError, match=key):
            Settings.from_env()


@pytest.mark.parametrize(
    "database_url",
    [None, "sqlite:///memory.db", "https://db.example.com/memory", "postgresql://"],
)
def test_production_requires_postgresql_database_url(database_url: str | None) -> None:
    env = {
        "AML_PRODUCTION": "1",
        "AML_LLM_MODE": "competition",
        "AML_API_KEY": "long-local-test-api-key",
        "OPENAI_API_KEY": "chat-key",
        "OPENAI_BASE_URL": "https://chat.example.com/v1",
    }
    if database_url is not None:
        env["DATABASE_URL"] = database_url

    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(ValueError, match="DATABASE_URL"):
            Settings.from_env()


def test_production_accepts_postgresql_database_url() -> None:
    with patch.dict(
        os.environ,
        {
            "AML_PRODUCTION": "1",
            "AML_LLM_MODE": "competition",
            "AML_API_KEY": "long-local-test-api-key",
            "OPENAI_API_KEY": "chat-key",
            "OPENAI_BASE_URL": "https://chat.example.com/v1",
            "DATABASE_URL": "postgresql://user:pass@db.example.com/memory?sslmode=require",
        },
        clear=True,
    ):
        assert Settings.from_env().database_url == (
            "postgresql://user:pass@db.example.com/memory?sslmode=require"
        )

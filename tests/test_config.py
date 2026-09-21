from pathlib import Path

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

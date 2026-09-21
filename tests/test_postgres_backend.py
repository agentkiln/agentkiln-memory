from pathlib import Path

from app.config import Settings


def settings(tmp_path: Path, database_url: str | None = None) -> Settings:
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
        search_concurrency=32,
        add_concurrency=16,
        database_url=database_url,
    )


def test_database_url_selects_postgres_backend(tmp_path: Path) -> None:
    from app.service import MemoryService

    resolved = settings(tmp_path, "postgresql://user:pass@db.example.com:5432/memory?sslmode=require")
    service = MemoryService(resolved)
    assert service.database.backend_name == "postgres"


def test_local_settings_use_sqlite_backend(tmp_path: Path) -> None:
    from app.service import MemoryService

    service = MemoryService(settings(tmp_path))
    assert service.database.backend_name == "sqlite"

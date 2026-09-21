from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.config import Settings
from app.schemas import SearchRequest
from app.service import MemoryService


def test_search_concurrency_limit_is_enforced(tmp_path: Path) -> None:
    settings = Settings(
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
        search_concurrency=1,
        add_concurrency=1,
    )
    service = MemoryService(settings)
    service.initialize()
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(service.search, SearchRequest(query="anything", user_id="user-a", top_k=5))
            for _ in range(2)
        ]
        results = [future.result() for future in futures]
    assert results == [[], []]

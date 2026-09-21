#!/usr/bin/env python3
"""Run Add/Search contract checks directly against the PostgreSQL backend."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.schemas import AddRequest, MemoryMessage, SearchRequest
from app.service import MemoryService


def main() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required")
    settings = Settings(
        database_path=Path("data/memory.db"),
        api_key=None,
        llm_mode="off",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o-mini",
        embedding_model="text-embedding-v4",
        timeout_seconds=30,
        candidate_limit=300,
        max_output_tokens=8000,
        max_output_items=24,
        vector_min_similarity=0.35,
        vector_only_min_similarity=0.65,
        search_concurrency=32,
        add_concurrency=16,
        database_url=database_url,
    )
    service = MemoryService(settings)
    service.initialize()
    assert service.database.backend_name == "postgres"

    user_id = "postgres-verify-user"
    request = AddRequest(
        request_id="postgres-verify-1",
        messages=[
            MemoryMessage(role="user", content="My favorite drink is jasmine tea."),
            MemoryMessage(role="assistant", content="I will remember jasmine tea."),
        ],
        user_id=user_id,
        session_id="postgres-verify-session",
    )
    service.add(request)
    service.add(request)  # idempotent retry

    results = service.search(
        SearchRequest(query="What drink do I prefer?", user_id=user_id, top_k=5)
    )
    assert results, "search returned no evidence"
    assert "jasmine tea" in " ".join(item.content for item in results)

    cjk_user = "postgres-verify-cjk"
    cjk_request = AddRequest(
        request_id="postgres-verify-cjk-1",
        messages=[MemoryMessage(role="user", content="我的居住城市是京都。")],
        user_id=cjk_user,
        session_id="postgres-verify-cjk-session",
    )
    service.add(cjk_request)
    cjk_results = service.search(
        SearchRequest(query="我的居住城市在哪里？", user_id=cjk_user, top_k=5)
    )
    assert cjk_results, "CJK search returned no evidence"
    print(
        f"PostgreSQL verify passed: {len(results)} evidence items, "
        f"{len(cjk_results)} CJK items"
    )


if __name__ == "__main__":
    main()

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.db import MemoryRow, memory_id_for
from app.main import create_app
from app.service import MemoryService


def _settings(tmp_path: Path) -> Settings:
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
        search_concurrency=4,
        add_concurrency=4,
    )


def _row(memory_id: str, content: str, created_at: str, ordinal: int = 0) -> MemoryRow:
    return MemoryRow(
        id=memory_id,
        row_id=0,
        user_id="user-a",
        session_id="session-a",
        request_id="request-a",
        ordinal=ordinal,
        role="user",
        content=content,
        occurred_at=None,
        created_at=created_at,
        search_text="",
        fts_rank=0.0,
    )


def test_search_retains_later_untimed_correction(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    for request_id, code in (("correction-1", "alpha"), ("correction-2", "beta")):
        response = client.post(
            "/add",
            json={
                "request_id": request_id,
                "user_id": "correction-user",
                "session_id": "correction-session",
                "messages": [{"role": "user", "content": f"Correction launch code {code}"}],
            },
        )
        assert response.status_code == 200

    response = client.post(
        "/search",
        json={"user_id": "correction-user", "query": "launch code", "top_k": 1},
    )

    assert response.status_code == 200
    assert response.json()["data"]
    assert response.json()["data"][0]["id"] == memory_id_for("correction-user", "correction-2", 0)


def test_untimed_corrections_use_creation_order_without_row_ids() -> None:
    older = _row("older", "Correction launch code alpha", "2026-01-01T00:00:00+00:00")
    newer = _row("newer", "Correction launch code beta", "2026-01-01T00:00:01+00:00")

    assert MemoryService._suppress_superseded([newer, older]) == [newer]


def test_untimed_corrections_in_one_request_use_message_order() -> None:
    created_at = "2026-01-01T00:00:00+00:00"
    older = _row("older", "Correction launch code alpha", created_at, ordinal=0)
    newer = _row("newer", "Correction launch code beta", created_at, ordinal=1)

    assert MemoryService._suppress_superseded([newer, older]) == [newer]


def test_correction_preserves_unrelated_fact_in_older_message() -> None:
    older = _row(
        "older",
        "Correction launch code alpha. Backup contact Alice.",
        "2026-01-01T00:00:00+00:00",
    )
    newer = _row(
        "newer", "Correction launch code beta.", "2026-01-02T00:00:00+00:00"
    )

    assert MemoryService._suppress_superseded([newer, older]) == [newer, older]


def test_correction_preserves_older_fact_requested_by_query() -> None:
    older = _row(
        "older",
        "Correction launch code alpha and backup contact Alice",
        "2026-01-01T00:00:00+00:00",
    )
    newer = _row(
        "newer", "Correction launch code beta", "2026-01-02T00:00:00+00:00"
    )

    assert MemoryService._suppress_superseded(
        [newer, older], query_terms=["backup", "contact"]
    ) == [newer, older]


def test_mentioning_old_value_does_not_restore_superseded_single_fact() -> None:
    older = _row("older", "Correction launch code alpha", "2026-01-01T00:00:00+00:00")
    newer = _row("newer", "Correction launch code beta", "2026-01-02T00:00:00+00:00")

    assert MemoryService._suppress_superseded(
        [newer, older], query_terms=["alpha", "launch", "code"]
    ) == [newer]


def test_mixed_old_message_is_suppressed_when_query_asks_corrected_fact() -> None:
    older = _row(
        "older",
        "Correction launch code alpha. Backup contact Alice.",
        "2026-01-01T00:00:00+00:00",
    )
    newer = _row("newer", "Correction launch code beta", "2026-01-02T00:00:00+00:00")

    assert MemoryService._suppress_superseded(
        [newer, older], query_terms=["launch", "code"]
    ) == [newer]


def test_decimal_point_does_not_make_single_fact_look_independent() -> None:
    older = _row("older", "Correction budget is $1.5 million", "2026-01-01T00:00:00+00:00")
    newer = _row("newer", "Correction budget is $2 million", "2026-01-02T00:00:00+00:00")

    assert MemoryService._suppress_superseded([newer, older]) == [newer]


def test_mixed_message_keeps_other_fact_without_restoring_old_value(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    for request_id, session_id, content in (
        ("mixed-old", "session-old", "Correction launch code alpha. Backup contact Alice."),
        ("mixed-new", "session-new", "Correction launch code beta."),
    ):
        assert client.post(
            "/add",
            json={
                "request_id": request_id,
                "user_id": "mixed-user",
                "session_id": session_id,
                "messages": [{"role": "user", "content": content}],
            },
        ).status_code == 200

    backup = client.post(
        "/search",
        json={"user_id": "mixed-user", "query": "Who is the backup contact?", "top_k": 1},
    ).json()["data"]
    current_code = client.post(
        "/search",
        json={"user_id": "mixed-user", "query": "Is alpha still the launch code?", "top_k": 1},
    ).json()["data"]

    assert backup and backup[0]["id"] == memory_id_for("mixed-user", "mixed-old", 0)
    assert current_code and current_code[0]["id"] == memory_id_for("mixed-user", "mixed-new", 0)

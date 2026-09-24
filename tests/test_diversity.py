import pytest

from app.db import MemoryRow


def _row(memory_id: str, session_id: str) -> MemoryRow:
    return MemoryRow(
        id=memory_id,
        row_id=0,
        user_id="history-user",
        session_id=session_id,
        request_id=f"request-{memory_id}",
        ordinal=0,
        role="user",
        content=f"Project note {memory_id}",
        occurred_at=None,
        created_at="2026-01-01T00:00:00+00:00",
        search_text="",
        fts_rank=0.0,
    )


def _select(query: str, ranked: list[tuple[float, MemoryRow]], limit: int, *, intent: str = "none"):
    from app.diversity import select_diverse_evidence

    return select_diverse_evidence(query, ranked, limit, intent=intent)


def test_global_summary_retains_top_match_and_covers_other_sessions() -> None:
    ranked = [
        (0.95, _row("a1", "session-a")),
        (0.92, _row("a2", "session-a")),
        (0.87, _row("b1", "session-b")),
        (0.82, _row("c1", "session-c")),
    ]

    selected = _select("Summarize the entire project history", ranked, 3)

    assert [row.id for _score, row in selected] == ["a1", "b1", "c1"]
    assert [score for score, _row in selected] == [0.95, 0.87, 0.82]


def test_global_summary_fills_remaining_slots_in_relevance_order() -> None:
    ranked = [
        (0.95, _row("a1", "session-a")),
        (0.90, _row("a2", "session-a")),
        (0.80, _row("b1", "session-b")),
        (0.75, _row("a3", "session-a")),
    ]

    selected = _select("Give an overview of the whole history", ranked, 3)

    assert [row.id for _score, row in selected] == ["a1", "a2", "b1"]


def test_explicit_chinese_stage_summary_covers_multiple_sessions() -> None:
    ranked = [
        (0.95, _row("a1", "session-a")),
        (0.90, _row("a2", "session-a")),
        (0.80, _row("b1", "session-b")),
    ]

    selected = _select("请总结项目各阶段的变化", ranked, 2)

    assert [row.id for _score, row in selected] == ["a1", "b1"]


@pytest.mark.parametrize(
    ("query", "intent"),
    [
        ("Where does Alice live?", "none"),
        ("Where does Alice's mentor live?", "none"),
        ("Summarize Alice's mentor.", "none"),
        ("What is the summary report title?", "none"),
        ("What is the latest status?", "none"),
        ("What was the earliest plan?", "none"),
        ("Summarize the entire history", "latest"),
    ],
)
def test_non_global_or_temporal_questions_keep_existing_order(query: str, intent: str) -> None:
    ranked = [
        (0.95, _row("a1", "session-a")),
        (0.90, _row("a2", "session-a")),
        (0.80, _row("b1", "session-b")),
    ]

    assert _select(query, ranked, 2, intent=intent) == ranked[:2]


def test_global_summary_with_one_result_keeps_top_match() -> None:
    ranked = [(0.95, _row("a1", "session-a")), (0.90, _row("b1", "session-b"))]

    assert _select("Summarize all sessions", ranked, 1) == ranked[:1]
    assert _select("Summarize all sessions", ranked, 0) == []


def test_weak_other_session_does_not_replace_strong_evidence() -> None:
    ranked = [
        (0.95, _row("a1", "session-a")),
        (0.90, _row("a2", "session-a")),
        (0.05, _row("b1", "session-b")),
    ]

    assert _select("Summarize the entire project history", ranked, 2) == ranked[:2]
    assert _select("Across all sessions, which team handled this?", ranked, 2) == ranked[:2]
    assert _select("Summarize the full reason for the decision", ranked, 2) == ranked[:2]

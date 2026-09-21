from pathlib import Path

from app.db import MemoryRow
from app.pack import pack_windows


def row(memory_id: str, content: str, ordinal: int = 0) -> MemoryRow:
    return MemoryRow(
        id=memory_id,
        row_id=ordinal + 1,
        user_id="user-a",
        session_id="session-a",
        request_id=f"req-{memory_id}",
        ordinal=ordinal,
        role="user",
        content=content,
        occurred_at=1704067200000 + ordinal,
        created_at="2024-01-01T00:00:00+00:00",
        search_text=content,
        fts_rank=1.0,
    )


def test_pack_windows_deduplicates_sources() -> None:
    first = row("mem_1", "alpha")
    second = row("mem_2", "beta")
    packed = pack_windows(
        [(0.9, first, [first, second]), (0.8, second, [second])],
        top_k=10,
        max_tokens=100,
        max_items=10,
    )
    assert len(packed) == 1
    assert packed[0].source_ids == ("mem_1", "mem_2")


def test_pack_windows_respects_max_items() -> None:
    packed = pack_windows(
        [(0.9, row("mem_1", "alpha"), [row("mem_1", "alpha")])],
        top_k=10,
        max_tokens=100,
        max_items=0,
    )
    assert packed == []


def test_pack_windows_does_not_drop_second_relation_end() -> None:
    first = row("mem_1", "Alice's mentor is Bob.")
    second = row("mem_2", "Bob lives in Kyoto.", ordinal=1)
    packed = pack_windows(
        [
            (0.9, first, [first]),
            (0.8, second, [second]),
        ],
        top_k=2,
        max_tokens=100,
        max_items=2,
    )
    assert [window.source_id for window in packed] == ["mem_1", "mem_2"]


def test_pack_windows_truncates_single_oversized_source() -> None:
    oversized = row("mem_long", "x" * 400)
    packed = pack_windows(
        [(0.9, oversized, [oversized])],
        top_k=1,
        max_tokens=10,
        max_items=1,
    )
    assert len(packed) == 1
    assert packed[0].source_id == "mem_long"
    assert packed[0].content.endswith("...")
    assert len(packed[0].content) <= 40


def test_pack_windows_truncates_oversized_cjk_source_within_budget() -> None:
    oversized = row("mem_cjk", "京都" * 200)
    packed = pack_windows(
        [(0.9, oversized, [oversized])],
        top_k=1,
        max_tokens=10,
        max_items=1,
    )
    assert len(packed) == 1
    assert packed[0].content.endswith("...")


def test_pack_windows_does_not_return_seen_anchor_without_its_content() -> None:
    anchor = row("mem_anchor", "anchor content")
    first_neighbor = row("mem_first", "first neighbor", ordinal=1)
    later_neighbor = row("mem_later", "later neighbor", ordinal=2)
    packed = pack_windows(
        [
            (0.9, anchor, [anchor, first_neighbor]),
            (0.8, anchor, [anchor, later_neighbor]),
        ],
        top_k=3,
        max_tokens=200,
        max_items=3,
    )
    assert all(window.source_id in window.source_ids for window in packed)


def test_pack_windows_orders_chunks_before_timestamps() -> None:
    later_time_but_chunk_zero = MemoryRow(
        id="mem_chunk_0",
        row_id=2,
        user_id="user-a",
        session_id="session-a",
        request_id="eval:sample:chunk-0",
        ordinal=0,
        role="user",
        content="The checkpoint question is ready.",
        occurred_at=1704067201000,
        created_at="2024-01-01T00:00:00+00:00",
        search_text="checkpoint",
        fts_rank=1.0,
    )
    earlier_time_but_chunk_one = MemoryRow(
        id="mem_chunk_1",
        row_id=1,
        user_id="user-a",
        session_id="session-a",
        request_id="eval:sample:chunk-1",
        ordinal=0,
        role="assistant",
        content="The answer is zebra.",
        occurred_at=1704067200000,
        created_at="2024-01-01T00:00:00+00:00",
        search_text="answer",
        fts_rank=1.0,
    )
    packed = pack_windows(
        [(0.9, later_time_but_chunk_zero, [later_time_but_chunk_zero, earlier_time_but_chunk_one])],
        top_k=1,
        max_tokens=100,
        max_items=1,
    )
    assert packed[0].source_ids == ("mem_chunk_0", "mem_chunk_1")

from types import SimpleNamespace
from unittest.mock import patch

from app.db import memory_id_for
from app.postgres_db import PostgresMemoryDatabase
from app.service import MemoryService


def _database_with_rows(monkeypatch, rows):
    class Cursor:
        def __init__(self):
            self.result = []

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, _params):
            if "SELECT DISTINCT session_id" in sql:
                self.result = [("session-a",)]
            else:
                self.result = rows

        def fetchall(self):
            return self.result

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return Cursor()

    database = PostgresMemoryDatabase("postgresql://unused")
    monkeypatch.setattr(database, "_connect", Connection)
    return database


def test_postgres_neighbors_follow_chunk_order_when_timestamps_are_missing(monkeypatch) -> None:
    rows = [
        (
            memory_id_for("user-a", f"eval:sample:chunk-{index}", 0),
            "user-a",
            "session-a",
            f"eval:sample:chunk-{index}",
            0,
            "user",
            f"chunk {index}",
            None,
            "2026-01-01T00:00:00Z",
            f"chunk {index}",
        )
        for index in range(6)
    ]
    database = _database_with_rows(monkeypatch, sorted(rows, key=lambda row: row[0]))

    neighbors = database.neighbors("user-a", [rows[0][0]], radius=1)

    assert [row.request_id for row, _distance, _seed_rank in neighbors] == [
        "eval:sample:chunk-0",
        "eval:sample:chunk-1",
    ]


def test_postgres_neighbors_keep_add_message_order_without_timestamps(monkeypatch) -> None:
    rows = [
        (
            memory_id_for("user-a", request_id, ordinal),
            "user-a",
            "session-a",
            request_id,
            ordinal,
            "user",
            f"{request_id} message {ordinal}",
            None,
            created_at,
            f"{request_id} message {ordinal}",
        )
        for request_id, created_at in (
            ("request-a", "2026-01-01T00:00:00Z"),
            ("request-b", "2026-01-01T00:00:01Z"),
        )
        for ordinal in range(2)
    ]
    database = _database_with_rows(monkeypatch, rows)

    neighbors = database.neighbors("user-a", [rows[1][0]], radius=1)

    assert [(row.request_id, row.ordinal) for row, _distance, _seed_rank in neighbors] == [
        ("request-a", 0),
        ("request-a", 1),
        ("request-b", 0),
    ]


def test_postgres_search_windows_batch_overlapping_anchors_in_one_borrow(monkeypatch) -> None:
    rows = [
        (
            memory_id_for("user-a", f"eval:sample:chunk-{index}", 0),
            "user-a",
            "session-a",
            f"eval:sample:chunk-{index}",
            0,
            "user",
            f"chunk {index}",
            None,
            "2026-01-01T00:00:00Z",
            f"chunk {index}",
        )
        for index in range(4)
    ]
    database = _database_with_rows(monkeypatch, rows)
    anchors = [
        # Rank order differs from source order; adjacent anchors share context rows.
        (
            score,
            next(
                row
                for row, _distance, _seed_rank in database.neighbors("user-a", [rows[index][0]])
                if row.id == rows[index][0]
            ),
        )
        for score, index in ((0.9, 2), (0.8, 1))
    ]
    service = MemoryService.__new__(MemoryService)
    service.settings = SimpleNamespace(max_output_items=2)
    service.database = database

    with patch.object(database, "_connect", wraps=database._connect) as connect:
        windows = service._windows("user-a", anchors)

    assert connect.call_count == 1
    assert [[row.request_id for row in context] for _score, _anchor, context in windows] == [
        ["eval:sample:chunk-1", "eval:sample:chunk-2", "eval:sample:chunk-3"],
        ["eval:sample:chunk-0", "eval:sample:chunk-1", "eval:sample:chunk-2"],
    ]

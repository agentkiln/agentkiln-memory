from pathlib import Path

from app.db import MemoryDatabase
from app.postgres_db import PostgresMemoryDatabase
from app.schemas import AddRequest, MemoryMessage


def colliding_requests() -> tuple[AddRequest, AddRequest]:
    first = AddRequest(
        user_id="a:b",
        request_id="c",
        session_id="first",
        messages=[MemoryMessage(role="user", content="First user's distinct memory")],
    )
    second = AddRequest(
        user_id="a",
        request_id="b:c",
        session_id="second",
        messages=[MemoryMessage(role="user", content="Second user's distinct memory")],
    )
    return first, second


def test_sqlite_memory_ids_keep_identifier_boundaries(tmp_path: Path) -> None:
    database = MemoryDatabase(tmp_path / "memory.db")
    database.initialize()
    first, second = colliding_requests()

    database.add(first, [""], [[1.0]], "test-model")
    database.add(second, [""], [[1.0]], "test-model")

    first_rows = database.vector_search(first.user_id, [1.0], 10, "test-model")
    second_rows = database.vector_search(second.user_id, [1.0], 10, "test-model")
    assert [row.content for row in first_rows] == ["First user's distinct memory"]
    assert [row.content for row in second_rows] == ["Second user's distinct memory"]
    assert first_rows[0].id != second_rows[0].id
    assert database.revision(first.user_id) == database.revision(second.user_id) == 1


def test_postgres_memory_ids_keep_identifier_boundaries(monkeypatch) -> None:
    inserted_ids: list[str] = []

    class FakeCursor:
        rowcount = 1

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, params):
            if "INSERT INTO memories" in sql:
                inserted_ids.append(params[0])

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return FakeCursor()

    database = PostgresMemoryDatabase("postgresql://unused")
    monkeypatch.setattr(database, "_connect", FakeConnection)
    first, second = colliding_requests()

    database.add(first, [""], [[1.0]], "test-model")
    database.add(second, [""], [[1.0]], "test-model")

    assert len(inserted_ids) == 2
    assert inserted_ids[0] != inserted_ids[1]

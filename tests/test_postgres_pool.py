from contextlib import contextmanager
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as main
import app.postgres_db as postgres_db
from app.schemas import AddRequest


def test_postgres_operations_borrow_a_bounded_reusable_connection(monkeypatch) -> None:
    pools = []

    class FakeConnection:
        def cursor(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, _sql, _params):
            pass

        def fetchone(self):
            return None

    class FakePool:
        check_connection = staticmethod(lambda _connection: None)

        def __init__(self, **kwargs):
            self.options = kwargs
            self.connection_count = 0
            self.shared_connection = FakeConnection()
            pools.append(self)

        @contextmanager
        def connection(self):
            self.connection_count += 1
            yield self.shared_connection

    monkeypatch.setattr(postgres_db, "ConnectionPool", FakePool, raising=False)
    database = postgres_db.PostgresMemoryDatabase("postgresql://unused")
    request = AddRequest(
        request_id="request-a",
        user_id="user-a",
        session_id="session-a",
        messages=[{"role": "user", "content": "hello"}],
    )

    with patch("psycopg.connect", side_effect=AssertionError("opened a direct connection")):
        assert database.request_status(request) == "new"
        assert database.request_status(request) == "new"

    assert len(pools) == 1
    assert pools[0].connection_count == 2
    assert pools[0].options["max_size"] == 5
    assert pools[0].options["min_size"] == 0
    assert pools[0].options["check"] is FakePool.check_connection


def test_app_shutdown_closes_database_pool(monkeypatch) -> None:
    closed = []

    class FakeService:
        def __init__(self, _settings):
            pass

        def initialize(self):
            pass

        def close(self):
            closed.append(True)

    monkeypatch.setattr(main, "MemoryService", FakeService)
    with TestClient(main.create_app(object())):
        pass

    assert closed == [True]

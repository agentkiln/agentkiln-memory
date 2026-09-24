from __future__ import annotations

from types import SimpleNamespace

from scripts import verify_postgres


def test_postgres_verification_script_reaches_backend_checks(monkeypatch, capsys) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")

    class FakeService:
        def __init__(self, settings):
            assert settings.database_url == "postgresql://unused"
            assert settings.embedding_base_url == "https://api.openai.com/v1"
            self.database = SimpleNamespace(backend_name="postgres")

        def initialize(self):
            pass

        def add(self, request):
            pass

        def search(self, request):
            return [SimpleNamespace(content="jasmine tea" if request.user_id == "postgres-verify-user" else "京都")]

    monkeypatch.setattr(verify_postgres, "MemoryService", FakeService)

    verify_postgres.main()

    assert "PostgreSQL verify passed" in capsys.readouterr().out

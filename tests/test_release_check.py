from datetime import timedelta, timezone

from scripts.release_check import MATERIALS_DEADLINE, check_public_url


def test_public_url_rejects_localhost() -> None:
    errors: list[str] = []
    check_public_url("https://localhost/add", "Add URL", errors)
    assert errors


def test_public_url_accepts_https_domain() -> None:
    errors: list[str] = []
    check_public_url("https://memory.example.com/add", "Add URL", errors)
    assert errors == []


def test_materials_deadline_uses_china_standard_time() -> None:
    assert MATERIALS_DEADLINE.utcoffset() == timedelta(hours=8)

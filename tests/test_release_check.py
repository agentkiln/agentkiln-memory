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


def test_public_url_rejects_private_ipv4() -> None:
    errors: list[str] = []
    check_public_url("https://10.0.0.5/add", "Add URL", errors)
    assert errors
    errors = []
    check_public_url("https://172.20.1.5/add", "Add URL", errors)
    assert errors


def test_public_url_rejects_embedded_credentials() -> None:
    errors: list[str] = []
    check_public_url("https://user:pass@example.com/add", "Add URL", errors)
    assert errors


def test_public_url_rejects_query_strings() -> None:
    errors: list[str] = []
    check_public_url("https://example.com/add?token=secret", "Add URL", errors)
    assert errors

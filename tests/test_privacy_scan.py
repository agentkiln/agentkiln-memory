from pathlib import Path

from scripts.privacy_scan import scan


def test_privacy_scan_finds_literal_key(tmp_path: Path) -> None:
    path = tmp_path / "config.txt"
    path.write_text("token = sk-" + "a" * 32, encoding="utf-8")
    findings = scan([path])
    assert findings
    assert "openai_key" in findings[0]


def test_privacy_scan_rejects_tracked_database(tmp_path: Path) -> None:
    path = tmp_path / "memory.db"
    path.write_bytes(b"SQLite format 3")
    findings = scan([path])
    assert findings == [f"blocked file type: {path}"]


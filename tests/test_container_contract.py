"""Deployment contracts that can be checked without a Docker daemon."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_docker_image_contains_root_page_logo() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert (ROOT / "docs/assets/agentkiln-logo.svg").is_file()
    assert "COPY docs/assets ./docs/assets" in dockerfile
    assert "docs" not in dockerignore.splitlines()


def test_container_server_and_healthcheck_use_runtime_port() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "${PORT:-8000}" in dockerfile
    assert "os.environ.get('PORT', '8000')" in dockerfile

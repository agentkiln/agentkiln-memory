#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse


CHINA_STANDARD_TIME = timezone(timedelta(hours=8))
MATERIALS_DEADLINE = datetime(2026, 10, 31, 23, 59, tzinfo=CHINA_STANDARD_TIME)
EVALUATION_DEADLINE = datetime(2026, 11, 4, 23, 59, tzinfo=CHINA_STANDARD_TIME)


def check_public_url(value: str, name: str, errors: list[str]) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        errors.append(f"{name} must be an HTTPS URL")
        return
    if parsed.username or parsed.password:
        errors.append(f"{name} must not contain embedded credentials")
        return
    host = parsed.hostname or ""
    if (
        host in {"localhost", "127.0.0.1", "::1"}
        or host.endswith(".local")
        or host.startswith("10.")
        or host.startswith("192.168.")
        or host.startswith("169.254.")
    ):
        errors.append(f"{name} must not use a local or private host")
        return
    octets = host.split(".")
    if len(octets) == 4 and all(part.isdigit() for part in octets):
        first, second = int(octets[0]), int(octets[1])
        if first == 172 and 16 <= second <= 31:
            errors.append(f"{name} must not use a private IPv4 address")


def check_repository(root: Path, errors: list[str]) -> dict[str, object]:
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        status = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        errors.append("repository must be a Git checkout")
        return {"commit": "unavailable", "clean": False}
    if status:
        errors.append("repository must be committed and clean before release")
    return {"commit": commit, "clean": not status}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-url")
    parser.add_argument("--add-url")
    parser.add_argument("--search-url")
    parser.add_argument("--health-url")
    parser.add_argument("--now", help="ISO-8601 timestamp for deterministic checks")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    errors: list[str] = []
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if now >= MATERIALS_DEADLINE:
        errors.append("materials deadline has passed")
    if now >= EVALUATION_DEADLINE:
        errors.append("evaluation deadline has passed")

    repository = check_repository(Path.cwd(), errors)
    if not args.repository_url:
        errors.append("repository URL is required")
    else:
        check_public_url(args.repository_url, "repository URL", errors)
    for name, value in (("Add URL", args.add_url), ("Search URL", args.search_url), ("Health URL", args.health_url)):
        if not value:
            errors.append(f"{name} is required")
        else:
            check_public_url(value, name, errors)

    report = {
        "status": "frozen" if not errors else "incomplete",
        "checked_at": now.isoformat(),
        "materials_deadline": MATERIALS_DEADLINE.isoformat(),
        "evaluation_deadline": EVALUATION_DEADLINE.isoformat(),
        "repository": repository,
        "errors": errors,
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"status: {report['status']}")
        for error in errors:
            print(f"- {error}")
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

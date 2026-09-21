#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


PATTERNS = {
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "bearer_literal": re.compile(r"\bBearer\s+(?!\$)[A-Za-z0-9._-]{20,}"),
    "aws_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
}

BLOCKED_NAMES = {".env", "credentials.json", "secrets.json", "id_rsa", "id_ed25519"}
BLOCKED_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".pem", ".key", ".p12", ".pfx", ".log"}


def repository_files() -> list[Path]:
    output = subprocess.check_output(["git", "ls-files"], text=True)
    return [Path(line) for line in output.splitlines() if line.strip()]


def scan(paths: list[Path]) -> list[str]:
    findings: list[str] = []
    for path in paths:
        if path.name in BLOCKED_NAMES or path.suffix.casefold() in BLOCKED_SUFFIXES:
            findings.append(f"blocked file type: {path}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{label}: {path}")
    return findings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    root = args.root.resolve()
    original = Path.cwd()
    try:
        __import__("os").chdir(root)
        paths = repository_files()
    finally:
        __import__("os").chdir(original)
    findings = scan([root / path for path in paths])
    if findings:
        print("\n".join(findings))
        raise SystemExit(1)
    print(f"Privacy scan passed for {len(paths)} tracked files")


if __name__ == "__main__":
    main()


#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from ops_contract import Endpoint, run_contract


def wait_health(endpoint: Endpoint, timeout_seconds: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            health = endpoint.call("/health", timeout=3)
            if health.get("status") == "ok":
                return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("service did not become healthy")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8123)
    parser.add_argument("--concurrency", type=int, default=16)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="agentkiln-local-verify-") as temp_dir:
        env = {
            **os.environ,
            "AML_DATABASE_PATH": str(Path(temp_dir) / "memory.db"),
            "AML_LLM_MODE": "dev_mock",
            "AML_API_KEY": "local-verify-key",
        }
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.port),
                "--workers",
                "1",
            ],
            cwd=repo_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            endpoint = Endpoint(f"http://127.0.0.1:{args.port}", "local-verify-key")
            wait_health(endpoint)
            report = run_contract(endpoint, "local-verify", args.concurrency)
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

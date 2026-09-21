#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request

from ops_contract import Endpoint, validate_search_response


def wait_health(endpoint: Endpoint, timeout_seconds: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            health = endpoint.call("/health", timeout=5)
            if health.get("status") == "ok":
                return
        except Exception:
            time.sleep(1)
    raise RuntimeError("service did not become healthy")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key")
    parser.add_argument("--container", required=True)
    parser.add_argument("--run-id", default="recovery-check")
    args = parser.parse_args()
    endpoint = Endpoint(args.base_url, args.api_key)
    wait_health(endpoint)
    user_id = f"recovery:{args.run_id}"
    request = {
        "request_id": f"recovery:{args.run_id}:before",
        "messages": [
            {
                "role": "user",
                "timestamp": 1704067200000,
                "content": f"Recovery marker {args.run_id} is durable.",
            }
        ],
        "user_id": user_id,
        "session_id": f"recovery:{args.run_id}:session",
    }
    endpoint.call("/add", request)
    subprocess.run(["docker", "restart", args.container], check=True)
    wait_health(endpoint)
    found = endpoint.call(
        "/search",
        {"query": f"What is recovery marker {args.run_id}?", "user_id": user_id, "top_k": 10},
    )
    validate_search_response(found, top_k=10)
    if not found["data"] or args.run_id not in " ".join(item["content"] for item in found["data"]):
        raise RuntimeError("committed memory was not recoverable after restart")
    print(json.dumps({"status": "ok", "run_id": args.run_id, "items": len(found["data"])}, sort_keys=True))


if __name__ == "__main__":
    main()


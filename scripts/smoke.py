#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.request


BASE_URL = os.getenv("AML_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
API_KEY = os.getenv("AML_API_KEY") or os.getenv("MEMORY_SYSTEM_KEY")


def request(path: str, payload: dict | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers=headers,
        method="GET" if payload is None else "POST",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    health = request("/health")
    assert health["status"] == "ok"
    added = request(
        "/add",
        {
            "request_id": "smoke-1",
            "messages": [
                {
                    "role": "user",
                    "timestamp": 1704067200000,
                    "content": "The deployment color is indigo.",
                }
            ],
            "user_id": "smoke-user",
            "session_id": "smoke-session",
        },
    )
    assert added["success"] is True
    found = request(
        "/search",
        {"query": "What was the deployment color?", "user_id": "smoke-user", "top_k": 5},
    )
    assert found["data"] and "indigo" in found["data"][0]["content"]
    print("Smoke test passed")


if __name__ == "__main__":
    main()


#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


class ContractError(RuntimeError):
    pass


@dataclass(frozen=True)
class Endpoint:
    base_url: str
    api_key: str | None

    def call(self, path: str, payload: dict | None = None, timeout: float = 60.0) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}{path}",
            data=data,
            headers=headers,
            method="GET" if payload is None else "POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ContractError(f"{path} returned HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise ContractError(f"{path} failed: {exc}") from exc
        if not isinstance(body, dict):
            raise ContractError(f"{path} must return a JSON object")
        return body


def validate_health_response(body: dict) -> None:
    if body.get("status") != "ok":
        raise ContractError("health response must contain status=ok")


def validate_add_response(request: dict, body: dict) -> None:
    if body.get("success") is not True:
        raise ContractError("Add response must contain success=true")
    for field in ("request_id", "user_id", "session_id"):
        if body.get(field) != request[field]:
            raise ContractError(f"Add response must echo {field} exactly")


def validate_search_response(body: dict, top_k: int) -> None:
    data = body.get("data")
    if not isinstance(data, list):
        raise ContractError("Search response must contain a data array")
    if len(data) > top_k:
        raise ContractError("Search response must not exceed top_k")
    for item in data:
        if not isinstance(item, dict):
            raise ContractError("Search data items must be objects")
        if not isinstance(item.get("id"), str) or not item["id"]:
            raise ContractError("Search data items must contain a non-empty string id")
        if not isinstance(item.get("content"), str) or not item["content"]:
            raise ContractError("Search data items must contain a non-empty string content")


def run_contract(endpoint: Endpoint, run_id: str, concurrency: int) -> dict:
    health = endpoint.call("/health")
    validate_health_response(health)
    user_id = f"ops:{run_id}"
    session_id = f"ops:{run_id}:session"
    def add_one(index: int) -> None:
        request_id = f"ops:{run_id}:chunk-{index}"
        request = {
            "request_id": request_id,
            "messages": [
                {
                    "role": "assistant" if index % 2 else "user",
                    "timestamp": 1704067200000 + index * 1000,
                    "content": f"Run {run_id} fact {index}: marker value {index * 7}.",
                }
            ],
            "user_id": user_id,
            "session_id": session_id,
        }
        response = endpoint.call("/add", request)
        validate_add_response(request, response)

    started_adds = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
        futures = [executor.submit(add_one, index) for index in range(concurrency)]
        for future in futures:
            future.result()
    add_seconds = time.perf_counter() - started_adds
    query = f"What marker value belongs to run {run_id}?"
    started = time.perf_counter()
    search = endpoint.call("/search", {"query": query, "user_id": user_id, "top_k": 100})
    elapsed = time.perf_counter() - started
    validate_search_response(search, top_k=100)
    if not search["data"]:
        raise ContractError("Search returned no evidence for an inserted fact")
    return {
        "run_id": run_id,
        "adds": concurrency,
        "add_concurrency": concurrency,
        "add_seconds": round(add_seconds, 6),
        "search_latency_seconds": round(elapsed, 6),
        "returned_items": len(search["data"]),
        "health": health,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.getenv("AML_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--api-key", default=os.getenv("AML_API_KEY") or os.getenv("MEMORY_SYSTEM_KEY"))
    parser.add_argument("--run-id", default=os.getenv("AML_OPS_RUN_ID", "ops-contract"))
    parser.add_argument("--concurrency", type=int, default=16)
    args = parser.parse_args()
    report = run_contract(Endpoint(args.base_url, args.api_key), args.run_id, args.concurrency)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

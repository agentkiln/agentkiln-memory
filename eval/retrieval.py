from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

from app.config import Settings
from app.schemas import AddRequest, MemoryMessage, SearchRequest
from app.service import MemoryService


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def evaluate(path: Path, top_k: int, limit: int | None) -> dict:
    records = read_jsonl(path)
    if limit is not None:
        records = records[:limit]
    temporary = tempfile.TemporaryDirectory(prefix="agentkiln-eval-")
    settings = Settings(
        database_path=Path(temporary.name) / "memory.db",
        api_key=None,
        llm_mode="off",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o-mini",
        embedding_model="text-embedding-v4",
        timeout_seconds=30,
        candidate_limit=300,
        max_output_tokens=8000,
        max_output_items=32,
        vector_min_similarity=0.35,
        vector_only_min_similarity=0.65,
        search_concurrency=32,
        add_concurrency=16,
    )
    service = MemoryService(settings)
    service.initialize()
    hits = 0
    latencies: list[float] = []
    for index, record in enumerate(records):
        user_id = f"eval:{index}"
        messages = [
            MemoryMessage(role="user", content=str(item), timestamp=None)
            for item in record.get("memory", record.get("messages", []))
        ]
        if messages:
            service.add(
                AddRequest(
                    request_id=f"eval:{index}:add",
                    messages=messages,
                    user_id=user_id,
                    session_id=f"eval:{index}:session",
                )
            )
        query = str(record.get("question") or record.get("query") or "")
        if not query:
            continue
        started = time.perf_counter()
        result = service.search(SearchRequest(query=query, user_id=user_id, top_k=top_k))
        latencies.append(time.perf_counter() - started)
        expected = {str(item) for item in record.get("evidence_ids", [])}
        returned = {item.id for item in result}
        if expected and returned & expected:
            hits += 1
    total = sum(1 for record in records if record.get("question") or record.get("query"))
    temporary.cleanup()
    return {
        "records": len(records),
        "scored_questions": total,
        "hit_count": hits,
        "hit_rate": hits / total if total else 0.0,
        "p50_seconds": sorted(latencies)[len(latencies) // 2] if latencies else 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--top-k", type=int, default=100)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate(args.dataset, args.top_k, args.limit)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()

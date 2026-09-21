import json
from pathlib import Path

from eval.retrieval import evaluate


def test_evaluate_retrieval_persists_memory_between_connections(tmp_path: Path) -> None:
    dataset = tmp_path / "panel.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "memory": ["My favorite drink is jasmine tea."],
                "question": "What drink do I prefer?",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    report = evaluate(dataset, top_k=5, limit=1)
    assert report["records"] == 1
    assert report["scored_questions"] == 1
    assert report["hit_count"] == 0


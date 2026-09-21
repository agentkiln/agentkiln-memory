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


def test_evaluate_retrieval_matches_evidence_text(tmp_path: Path) -> None:
    dataset = tmp_path / "panel.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "memory": ["My favorite drink is jasmine tea."],
                "question": "What drink do I prefer?",
                "evidence": ["jasmine tea"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    report = evaluate(dataset, top_k=5, limit=1)
    assert report["hit_count"] == 1


def test_evaluate_retrieval_isolates_multiple_histories(tmp_path: Path) -> None:
    dataset = tmp_path / "panel.jsonl"
    rows = [
        {
            "history_id": "a",
            "memory": ["Alice likes jasmine tea."],
            "question": "What tea does Alice like?",
            "evidence": ["jasmine tea"],
        },
        {
            "history_id": "b",
            "memory": ["Bob likes coffee."],
            "question": "What tea does Alice like?",
            "evidence": ["jasmine tea"],
        },
    ]
    dataset.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    report = evaluate(dataset, top_k=5, limit=2)
    assert report["scored_questions"] == 2
    assert report["hit_count"] == 1

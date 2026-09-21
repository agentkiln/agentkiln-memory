from __future__ import annotations

from collections.abc import Iterable


def recall_at_k(retrieved: Iterable[str], relevant: Iterable[str], k: int) -> float:
    relevant_set = set(relevant)
    if not relevant_set:
        return 0.0
    retrieved_set = set(list(retrieved)[:k])
    return len(retrieved_set & relevant_set) / len(relevant_set)


def mean(values: Iterable[float]) -> float:
    values = list(values)
    if not values:
        return 0.0
    return sum(values) / len(values)


def percentile(values: list[float], value: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((value / 100) * len(ordered) + 0.5)) - 1))
    return ordered[index]


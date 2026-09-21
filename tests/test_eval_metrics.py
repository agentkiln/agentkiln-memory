from eval.metrics import mean, percentile, recall_at_k


def test_recall_at_k_counts_relevant_hits() -> None:
    assert recall_at_k(["a", "b", "c"], ["b", "d"], 2) == 0.5


def test_mean_and_percentile_handle_empty_inputs() -> None:
    assert mean([]) == 0.0
    assert percentile([], 50) == 0.0
    assert percentile([1.0, 2.0, 3.0], 50) == 2.0


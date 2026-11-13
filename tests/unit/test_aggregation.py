"""Unit tests for distribution aggregation (Sprint 3).

Percentile semantics match the v0.1 prototype (linear interpolation);
summaries follow the scenario-lab ensemble shape plus loss probability.
"""

from __future__ import annotations

import pytest

from planagent.services.distributions import (
    paired_delta_stats,
    percentile,
    summarize_samples,
)


def test_percentile_linear_interpolation_matches_prototype() -> None:
    values = [0.0, 10.0, 20.0, 30.0]
    assert percentile(values, 0.0) == 0.0
    assert percentile(values, 1.0) == 30.0
    assert percentile(values, 0.5) == 15.0
    assert percentile(values, 0.25) == 7.5
    assert percentile([], 0.5) == 0.0
    assert percentile([7.0], 0.9) == 7.0


def test_summarize_samples_shape_and_loss_probability() -> None:
    summary = summarize_samples([-5.0, 0.0, 5.0, 10.0, 15.0], loss_threshold=0.0)
    assert summary["n"] == 5
    assert summary["mean"] == 5.0
    assert summary["min"] == -5.0
    assert summary["max"] == 15.0
    assert summary["p10"] == -3.0
    assert summary["p50"] == 5.0
    assert summary["p90"] == 13.0
    assert summary["p_loss"] == 0.2
    assert summary["stddev"] > 0


def test_summarize_samples_empty_and_single() -> None:
    empty = summarize_samples([])
    assert empty["n"] == 0
    assert empty["p50"] == 0.0
    single = summarize_samples([3.0])
    assert single["n"] == 1
    assert single["p10"] == single["p50"] == single["p90"] == 3.0
    assert single["stddev"] == 0.0
    assert single["p_loss"] == 0.0


def test_summarize_samples_loss_threshold_is_explicit() -> None:
    summary = summarize_samples([1.0, 2.0, 3.0], loss_threshold=2.5)
    assert summary["p_loss"] == pytest.approx(2 / 3, abs=1e-4)


def test_paired_delta_stats_pairs_by_index() -> None:
    paired = paired_delta_stats([10.0, 10.0, 10.0], [12.0, 9.0, 10.0])
    assert paired["n"] == 3
    assert paired["mean_delta"] == pytest.approx(1 / 3, abs=1e-4)
    assert paired["p50"] == 0.0
    assert paired["p_strategy_better"] == pytest.approx(1 / 3, abs=1e-4)


def test_paired_delta_stats_rejects_mismatched_counts() -> None:
    with pytest.raises(ValueError, match="equal trial counts"):
        paired_delta_stats([1.0, 2.0], [1.0])


def test_paired_delta_stats_empty() -> None:
    paired = paired_delta_stats([], [])
    assert paired["n"] == 0
    assert paired["mean_delta"] == 0.0

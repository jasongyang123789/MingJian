"""Unit tests for the Sprint 4 pure robustness methods (PRD delta D6).

Covers expected shortfall (known distributions, tails, small n),
bootstrap intervals (seed reproducibility, sanity, method), threshold
bisection (synthetic monotone cases, unreachable targets, direction),
decision-gate evaluation (operators, arm/paired metrics, loud failures),
and distribution quantiles (analytic cases, beta_pert empirics).
"""

from __future__ import annotations

import pytest

from planagent.services.distributions import distribution_median, distribution_quantile
from planagent.services.robustness import (
    apply_gate_operator,
    bisect_threshold,
    bootstrap_intervals,
    expected_shortfall,
    gate_observed_value,
)
from planagent.services.robustness.models import GateArm, GateDefinition, GateMetric, GateOperator
from planagent.services.variables.models import VariableDistribution


# ---------------------------------------------------------------- ES
def test_expected_shortfall_known_distribution() -> None:
    values = [float(i) for i in range(1, 101)]
    result = expected_shortfall(values, 0.05)
    assert result == {"value": 3.0, "threshold": 5.0, "tail_count": 5, "n": 100}


def test_expected_shortfall_upper_tail() -> None:
    values = [float(i) for i in range(1, 101)]
    result = expected_shortfall(values, 0.05, "upper")
    assert result == {"value": 98.0, "threshold": 96.0, "tail_count": 5, "n": 100}


def test_expected_shortfall_small_n_uses_single_trial_tail() -> None:
    result = expected_shortfall([30.0, 10.0, 20.0], 0.05)
    assert result["tail_count"] == 1
    assert result["value"] == 10.0
    assert result["threshold"] == 10.0


def test_expected_shortfall_alpha_one_is_the_mean() -> None:
    result = expected_shortfall([1.0, 2.0, 3.0, 4.0], 1.0)
    assert result["value"] == 2.5
    assert result["tail_count"] == 4


def test_expected_shortfall_rejects_empty_and_bad_alpha() -> None:
    with pytest.raises(ValueError, match="at least one"):
        expected_shortfall([], 0.05)
    with pytest.raises(ValueError, match="alpha"):
        expected_shortfall([1.0], 0.0)
    with pytest.raises(ValueError, match="alpha"):
        expected_shortfall([1.0], 1.5)
    with pytest.raises(ValueError, match="tail"):
        expected_shortfall([1.0], 0.05, "middle")


# ---------------------------------------------------------------- bootstrap
def test_bootstrap_seed_reproducible_and_sane() -> None:
    values = [float(i) for i in range(1, 51)]
    first = bootstrap_intervals(
        values, ["mean", "median", "p_loss"], draws=200, seed=42, level=0.90,
        loss_threshold=25.0,
    )
    second = bootstrap_intervals(
        values, ["mean", "median", "p_loss"], draws=200, seed=42, level=0.90,
        loss_threshold=25.0,
    )
    assert first == second
    by_statistic = {item["statistic"]: item for item in first}
    assert by_statistic["mean"]["estimate"] == 25.5
    assert by_statistic["median"]["estimate"] == 25.5
    assert by_statistic["p_loss"]["estimate"] == pytest.approx(24 / 50)
    for item in first:
        assert item["low"] <= item["estimate"] <= item["high"]
        assert item["method"] == "percentile"
        assert item["draws"] == 200
        assert item["seed"] == 42
        assert item["level"] == 0.90


def test_bootstrap_different_seeds_differ() -> None:
    values = [float(i) for i in range(1, 101)]
    first = bootstrap_intervals(values, ["mean"], draws=200, seed=1, level=0.90)
    second = bootstrap_intervals(values, ["mean"], draws=200, seed=2, level=0.90)
    assert first != second


def test_bootstrap_rejects_empty_and_bad_params() -> None:
    with pytest.raises(ValueError, match="at least one"):
        bootstrap_intervals([], ["mean"], draws=100, seed=1, level=0.9)
    with pytest.raises(ValueError, match="draws"):
        bootstrap_intervals([1.0], ["mean"], draws=0, seed=1, level=0.9)
    with pytest.raises(ValueError, match="level"):
        bootstrap_intervals([1.0], ["mean"], draws=100, seed=1, level=1.0)
    with pytest.raises(ValueError, match="Unknown bootstrap statistic"):
        bootstrap_intervals([1.0], ["mode"], draws=100, seed=1, level=0.9)


# ---------------------------------------------------------------- bisection
def test_bisection_converges_on_increasing_case() -> None:
    result = bisect_threshold(
        lambda x: 2.0 * x,
        target=10.0,
        bounds=(0.0, 10.0),
        direction="increasing",
        tolerance=0.01,
        max_iterations=20,
    )
    assert result["reachable"] is True
    assert result["threshold"] == pytest.approx(5.0, abs=0.01)
    assert result["achieved_statistic"] == pytest.approx(10.0, abs=0.02)
    assert result["iterations"] > 0
    evaluations = result["evaluations"]
    assert evaluations[0]["value"] == 0.0
    assert evaluations[1]["value"] == 10.0
    assert evaluations[-1]["value"] == result["threshold"]


def test_bisection_converges_on_decreasing_case() -> None:
    result = bisect_threshold(
        lambda x: 100.0 - 3.0 * x,
        target=40.0,
        bounds=(0.0, 30.0),
        direction="decreasing",
        tolerance=0.01,
        max_iterations=20,
    )
    assert result["reachable"] is True
    assert result["threshold"] == pytest.approx(20.0, abs=0.01)


def test_bisection_unreachable_target_reports_honestly() -> None:
    result = bisect_threshold(
        lambda x: 2.0 * x,
        target=100.0,
        bounds=(0.0, 10.0),
        direction="increasing",
        tolerance=0.01,
        max_iterations=10,
    )
    assert result["reachable"] is False
    assert result["threshold"] is None
    assert result["achieved_statistic"] is None
    assert result["iterations"] == 0
    assert len(result["evaluations"]) == 2


def test_bisection_respects_iteration_cap() -> None:
    result = bisect_threshold(
        lambda x: 2.0 * x,
        target=10.0,
        bounds=(0.0, 10.0),
        direction="increasing",
        tolerance=1e-9,
        max_iterations=3,
    )
    assert result["reachable"] is True
    assert result["iterations"] == 3
    # Final interval width is 10 / 2**3 = 1.25; the threshold sits inside it.
    assert 5.0 - 1.25 <= result["threshold"] <= 5.0 + 1.25


def test_bisection_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError, match="direction"):
        bisect_threshold(lambda x: x, target=1, bounds=(0, 1), direction="sideways",
                         tolerance=0.1, max_iterations=5)
    with pytest.raises(ValueError, match="bounds"):
        bisect_threshold(lambda x: x, target=1, bounds=(1, 1), direction="increasing",
                         tolerance=0.1, max_iterations=5)
    with pytest.raises(ValueError, match="tolerance"):
        bisect_threshold(lambda x: x, target=1, bounds=(0, 1), direction="increasing",
                         tolerance=0, max_iterations=5)


# ---------------------------------------------------------------- gates
def _gate(**overrides: object) -> GateDefinition:
    payload: dict[str, object] = {
        "name": "g1",
        "metric": "mean",
        "operator": ">",
        "threshold": 0.0,
    }
    payload.update(overrides)
    return GateDefinition.model_validate(payload)


def test_gate_operators_apply_at_boundaries() -> None:
    assert apply_gate_operator(GateOperator.GT, 1.0, 1.0) is False
    assert apply_gate_operator(GateOperator.GTE, 1.0, 1.0) is True
    assert apply_gate_operator(GateOperator.LT, 1.0, 1.0) is False
    assert apply_gate_operator(GateOperator.LTE, 1.0, 1.0) is True


def test_gate_arm_metrics_on_known_values() -> None:
    baseline = [10.0, 20.0, 30.0, 40.0]
    strategy = [15.0, 25.0, 35.0, 45.0]
    assert gate_observed_value(_gate(metric="mean"), baseline, strategy, 0.0) == 25.0
    assert gate_observed_value(_gate(metric="p50"), baseline, strategy, 0.0) == 25.0
    assert gate_observed_value(_gate(metric="min"), baseline, strategy, 0.0) == 10.0
    assert gate_observed_value(_gate(metric="max"), baseline, strategy, 0.0) == 40.0
    assert gate_observed_value(_gate(metric="p_loss"), baseline, strategy, 25.0) == 0.5
    assert gate_observed_value(
        _gate(metric="mean", arm="strategy"), baseline, strategy, 0.0
    ) == 30.0
    assert gate_observed_value(
        _gate(metric="expected_shortfall", alpha=0.25), baseline, strategy, 0.0
    ) == 10.0


def test_gate_paired_metrics() -> None:
    baseline = [10.0, 20.0, 30.0]
    strategy = [12.0, 18.0, 33.0]
    assert gate_observed_value(
        _gate(metric="mean_delta", arm="paired"), baseline, strategy, 0.0
    ) == pytest.approx((2.0 - 2.0 + 3.0) / 3)
    assert gate_observed_value(
        _gate(metric="p_strategy_better", arm="paired"), baseline, strategy, 0.0
    ) == pytest.approx(2 / 3)


def test_gate_definition_rejects_metric_arm_mismatch() -> None:
    with pytest.raises(ValueError, match="paired"):
        _gate(metric="mean_delta", arm="baseline")
    with pytest.raises(ValueError, match="paired"):
        _gate(metric="mean", arm="paired")


def test_gate_evaluation_fails_loudly_on_empty_values() -> None:
    with pytest.raises(ValueError, match="at least one"):
        gate_observed_value(_gate(), [], [], 0.0)


# ---------------------------------------------------------------- quantiles
def test_quantile_fixed_and_bernoulli() -> None:
    fixed = VariableDistribution(type="fixed", value=7.0)
    assert distribution_quantile(fixed, 0.1) == 7.0
    assert distribution_quantile(fixed, 0.9) == 7.0
    bernoulli = VariableDistribution(type="bernoulli", p=0.7)
    assert distribution_quantile(bernoulli, 0.1) == 0.0
    assert distribution_quantile(bernoulli, 0.5) == 1.0
    assert distribution_median(bernoulli) == 1.0


def test_quantile_normal_is_symmetric() -> None:
    normal = VariableDistribution(type="normal", mean=10.0, std=2.0)
    assert distribution_median(normal) == pytest.approx(10.0)
    low = distribution_quantile(normal, 0.10)
    high = distribution_quantile(normal, 0.90)
    assert low < 10.0 < high
    assert low + high == pytest.approx(20.0)


def test_quantile_triangular_analytic() -> None:
    triangular = VariableDistribution(type="triangular", min=60.0, mode=100.0, max=140.0)
    assert distribution_median(triangular) == pytest.approx(100.0)
    assert distribution_quantile(triangular, 0.10) == pytest.approx(77.88854382)
    assert distribution_quantile(triangular, 0.90) == pytest.approx(122.11145618)


def test_quantile_beta_pert_seeded_reproducible_and_bounded() -> None:
    beta = VariableDistribution(type="beta_pert", min=0.0, mode=30.0, max=100.0)
    first = distribution_quantile(beta, 0.90, seed=42)
    second = distribution_quantile(beta, 0.90, seed=42)
    assert first == second
    assert 0.0 <= first <= 100.0
    assert distribution_quantile(beta, 0.10, seed=42) < distribution_quantile(beta, 0.5, seed=42)
    assert distribution_quantile(beta, 0.5, seed=42) < distribution_quantile(beta, 0.90, seed=42)


def test_quantile_rejects_bad_inputs() -> None:
    fixed = VariableDistribution(type="fixed", value=7.0)
    with pytest.raises(ValueError, match="Quantile"):
        distribution_quantile(fixed, 0.0)
    with pytest.raises(ValueError, match="Quantile"):
        distribution_quantile(fixed, 1.0)
    incomplete = VariableDistribution(type="normal", mean=1.0, std=None)
    with pytest.raises(ValueError, match="requires mean and std"):
        distribution_quantile(incomplete, 0.5)

"""Unit tests for the ridge-to-prior calibration estimator (Sprint 5).

Covers synthetic recovery, the shrinkage extremes (strong stays near
the prior, weak follows the data), non-negative clipping, input
validation, LOO RMSE, seeded bootstrap determinism, and the two
calibration entry points (policy thresholds, rule weights) including
the ordering guard and unmatched-rule prior preservation.
"""

from __future__ import annotations

import pytest

from planagent.services.calibration import (
    bootstrap_coefficient_intervals,
    calibrate_policy_thresholds,
    calibrate_rule_weights,
    fit_ridge_to_prior,
    leave_one_out_rmse,
    ridge_location_fit,
)

# ---------------------------------------------------------------- fit_ridge_to_prior


def test_ridge_recovers_known_coefficients() -> None:
    # y = 2*x1 + 3*x2 exactly; weak shrinkage should recover ~[2, 3].
    features = [[1.0, 0.0], [0.0, 1.0], [1.0, 1.0], [2.0, 1.0]]
    target = [2.0, 3.0, 5.0, 7.0]
    fitted = fit_ridge_to_prior(features, target, [0.0, 0.0], 1e-6, clip_nonnegative=False)
    assert fitted == pytest.approx([2.0, 3.0], abs=1e-4)


def test_ridge_shrinkage_extremes() -> None:
    features = [[1.0], [1.0], [1.0], [1.0]]
    target = [100.0, 100.0, 100.0, 100.0]
    prior = [0.0]
    weak = fit_ridge_to_prior(features, target, prior, 1e-6, clip_nonnegative=False)
    strong = fit_ridge_to_prior(features, target, prior, 1e6, clip_nonnegative=False)
    assert weak[0] == pytest.approx(100.0, abs=1e-3)
    assert strong[0] == pytest.approx(0.0, abs=1e-3)
    middle = fit_ridge_to_prior(features, target, prior, 4.0, clip_nonnegative=False)
    # Closed form: (400 + 4*0) / (4 + 4) = 50.
    assert middle[0] == pytest.approx(50.0)


def test_ridge_clips_negative_coefficients_by_default() -> None:
    features = [[1.0], [1.0]]
    target = [-5.0, -5.0]
    assert fit_ridge_to_prior(features, target, [1.0], 1e-6) == [0.0]
    assert fit_ridge_to_prior(features, target, [1.0], 1e-6, clip_nonnegative=False)[0] < 0


def test_ridge_unmatched_column_keeps_prior_exactly() -> None:
    # An all-zero column contributes nothing to X'y; the penalty term
    # alone decides, and it decides for the prior.
    features = [[1.0, 0.0], [2.0, 0.0], [3.0, 0.0]]
    target = [2.0, 4.0, 6.0]
    fitted = fit_ridge_to_prior(features, target, [0.0, 1.5], 5.0, clip_nonnegative=False)
    assert fitted[1] == pytest.approx(1.5)


def test_ridge_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError, match="at least 2 observations"):
        fit_ridge_to_prior([[1.0]], [1.0], [0.0], 5.0)
    with pytest.raises(ValueError, match="must align"):
        fit_ridge_to_prior([[1.0], [1.0]], [1.0], [0.0], 5.0)
    with pytest.raises(ValueError, match="must all have 1 columns"):
        fit_ridge_to_prior([[1.0, 2.0], [1.0]], [1.0, 2.0], [0.0], 5.0)
    with pytest.raises(ValueError, match="ridge_strength"):
        fit_ridge_to_prior([[1.0], [1.0]], [1.0, 2.0], [0.0], -1.0)
    with pytest.raises(ValueError, match="finite"):
        fit_ridge_to_prior([[float("inf")], [1.0]], [1.0, 2.0], [0.0], 5.0)


def test_ridge_singular_unpenalized_design_reports_plainly() -> None:
    with pytest.raises(ValueError, match="singular"):
        fit_ridge_to_prior([[1.0, 1.0], [2.0, 2.0]], [1.0, 2.0], [0.0, 0.0], 0.0)


# ---------------------------------------------------------------- location fit / LOO / bootstrap


def test_location_fit_closed_form() -> None:
    # (10 + 20 + 30 + 5*0) / (3 + 5) = 7.5.
    assert ridge_location_fit([10.0, 20.0, 30.0], 0.0, 5.0) == pytest.approx(7.5)
    # Single observation is well-defined: (10 + 5*0) / (1 + 5).
    assert ridge_location_fit([10.0], 0.0, 5.0) == pytest.approx(10.0 / 6.0)
    with pytest.raises(ValueError, match="at least one observed value"):
        ridge_location_fit([], 0.0, 5.0)


def test_loo_rmse_is_honest_out_of_sample_signal() -> None:
    features = [[1.0], [2.0], [3.0], [4.0]]
    target = [2.0, 4.0, 6.0, 8.0]
    rmse = leave_one_out_rmse(features, target, [0.0], 1e-6, clip_nonnegative=False)
    assert rmse is not None
    assert rmse == pytest.approx(0.0, abs=1e-3)
    assert leave_one_out_rmse(features[:2], target[:2], [0.0], 5.0) is None


def test_bootstrap_intervals_are_deterministic_and_sane() -> None:
    features = [[1.0], [2.0], [3.0], [4.0], [5.0]]
    target = [2.1, 3.9, 6.2, 7.8, 10.1]
    first = bootstrap_coefficient_intervals(
        features, target, [0.0], 5.0, draws=50, seed=42, level=0.90
    )
    second = bootstrap_coefficient_intervals(
        features, target, [0.0], 5.0, draws=50, seed=42, level=0.90
    )
    assert first == second
    interval = first[0]
    assert interval["low"] <= interval["estimate"] <= interval["high"]
    assert interval["draws"] == 50
    assert interval["seed"] == 42
    assert interval["method"] == "percentile"
    with pytest.raises(ValueError, match="draws"):
        bootstrap_coefficient_intervals(features, target, [0.0], 5.0, draws=0, seed=1, level=0.9)
    with pytest.raises(ValueError, match="level"):
        bootstrap_coefficient_intervals(features, target, [0.0], 5.0, draws=5, seed=1, level=1.0)


# ---------------------------------------------------------------- policy thresholds


def _policy(direction: str, alert: float, critical: float) -> dict[str, object]:
    return {
        "preferred_direction": direction,
        "alert_threshold": alert,
        "critical_threshold": critical,
    }


def test_policy_fit_moves_thresholds_toward_observed_values() -> None:
    result = calibrate_policy_thresholds(
        {"cash": _policy("increase", 50.0, 25.0)},
        {"cash": [80.0, 90.0, 100.0, 110.0]},
        ridge_strength=1.0,
        seed=7,
        bootstrap_draws=20,
    )
    policies = result["policies"]
    # Alert: (380 + 1*50) / (4 + 1) = 86. Tail: no value below 50, so the
    # worst quartile [80.0] anchors critical: (80 + 1*25) / (1 + 1) = 52.5.
    assert policies["cash"]["alert_threshold"] == pytest.approx(86.0)
    assert policies["cash"]["critical_threshold"] == pytest.approx(52.5)
    change = result["changes"]["cash"]
    assert change["unchanged_reason"] is None
    assert change["n_observations"] == 4
    assert change["n_tail"] == 1
    assert change["alert_bootstrap"]["estimate"] == pytest.approx(86.0)
    # One-observation tail: no bootstrap interval to report.
    assert change["critical_bootstrap"] is None


def test_policy_fit_shrinkage_extremes() -> None:
    observations = {"cash": [80.0, 90.0, 100.0]}
    weak = calibrate_policy_thresholds(
        {"cash": _policy("increase", 50.0, 25.0)},
        observations,
        ridge_strength=1e-6,
        seed=7,
        bootstrap_draws=10,
    )
    strong = calibrate_policy_thresholds(
        {"cash": _policy("increase", 50.0, 25.0)},
        observations,
        ridge_strength=1e6,
        seed=7,
        bootstrap_draws=10,
    )
    assert weak["policies"]["cash"]["alert_threshold"] == pytest.approx(90.0, abs=1e-3)
    assert strong["policies"]["cash"]["alert_threshold"] == pytest.approx(50.0, abs=1e-3)


def test_policy_fit_insufficient_observations_keeps_prior() -> None:
    result = calibrate_policy_thresholds(
        {"cash": _policy("increase", 50.0, 25.0)},
        {"cash": [80.0, 90.0]},
        ridge_strength=1.0,
        seed=7,
        bootstrap_draws=10,
    )
    assert result["policies"]["cash"]["alert_threshold"] == 50.0
    assert result["policies"]["cash"]["critical_threshold"] == 25.0
    change = result["changes"]["cash"]
    assert change["unchanged_reason"] == "insufficient_observations"
    assert change["alert_bootstrap"] is None


def test_policy_fit_ordering_guard_rejects_pair_wholesale() -> None:
    # With valid priors the fitted pair provably preserves ordering
    # (the tail mean is on the bad side of the overall mean), so the
    # guard fires only when the priors themselves are inverted: the
    # fitted pair inherits the inversion and must be rejected
    # wholesale (both priors kept, rejected fit recorded) rather than
    # clamped or propagated into a template the validator would refuse.
    result = calibrate_policy_thresholds(
        {"cash": _policy("increase", 25.0, 50.0)},
        {"cash": [10.0, 10.0, 10.0, 10.0]},
        ridge_strength=1.0,
        seed=7,
        bootstrap_draws=10,
    )
    change = result["changes"]["cash"]
    assert change["unchanged_reason"] == "ordering_guard"
    assert result["policies"]["cash"]["alert_threshold"] == 25.0
    assert result["policies"]["cash"]["critical_threshold"] == 50.0
    # Fitted alert (40 + 25) / 5 = 13 < fitted critical (40 + 50) / 5 = 18.
    assert change["rejected_fit"]["alert_threshold"] == pytest.approx(13.0)
    assert change["rejected_fit"]["critical_threshold"] == pytest.approx(18.0)


def test_policy_fit_decrease_direction_uses_upper_tail() -> None:
    result = calibrate_policy_thresholds(
        {"cost": _policy("decrease", 1.05, 1.15)},
        {"cost": [0.9, 1.0, 1.1, 1.3]},
        ridge_strength=1.0,
        seed=7,
        bootstrap_draws=10,
    )
    policies = result["policies"]
    # Alert: (4.3 + 1.05) / 5 = 1.07. Tail above 1.05: [1.1, 1.3];
    # critical: (2.4 + 1.15) / 3 = 1.1833...; ordering 1.07 < 1.1833 holds.
    assert policies["cost"]["alert_threshold"] == pytest.approx(1.07)
    assert policies["cost"]["critical_threshold"] == pytest.approx(1.1833333333)
    assert result["changes"]["cost"]["n_tail"] == 2


def test_policy_fit_is_deterministic() -> None:
    kwargs = dict(
        policies={"cash": _policy("increase", 50.0, 25.0)},
        observations={"cash": [80.0, 90.0, 100.0, 110.0]},
        ridge_strength=5.0,
        seed=20260727,
        bootstrap_draws=30,
    )
    assert calibrate_policy_thresholds(**kwargs) == calibrate_policy_thresholds(**kwargs)


# ---------------------------------------------------------------- rule weights


def test_rule_weight_fit_moves_toward_observed_outcomes() -> None:
    result = calibrate_rule_weights(
        ["a", "b"],
        [[1.0, 0.0], [2.0, 0.0], [3.0, 0.0], [0.0, 1.0], [0.0, 2.0]],
        [2.0, 4.0, 6.0, 3.0, 6.0],
        [1.0, 1.0],
        ridge_strength=1e-6,
        seed=7,
        bootstrap_draws=10,
        min_observations=2,
    )
    assert result["weights"]["a"] == pytest.approx(2.0, abs=1e-3)
    assert result["weights"]["b"] == pytest.approx(3.0, abs=1e-3)
    assert result["loo_rmse"] == pytest.approx(0.0, abs=1e-2)
    assert result["n_observations"] == 5


def test_rule_weight_fit_unmatched_rule_keeps_prior() -> None:
    result = calibrate_rule_weights(
        ["a", "never"],
        [[1.0, 0.0], [2.0, 0.0], [3.0, 0.0]],
        [2.0, 4.0, 6.0],
        [1.0, 1.0],
        ridge_strength=5.0,
        seed=7,
        bootstrap_draws=10,
    )
    change = result["changes"]["never"]
    assert change["fitted_weight"] == pytest.approx(1.0)
    assert change["total_matches"] == 0.0


def test_rule_weight_fit_requires_minimum_observations() -> None:
    with pytest.raises(ValueError, match="at least 3 observations"):
        calibrate_rule_weights(
            ["a"],
            [[1.0], [2.0]],
            [2.0, 4.0],
            [1.0],
            ridge_strength=5.0,
            seed=7,
            bootstrap_draws=10,
        )


def test_rule_weight_fit_is_deterministic() -> None:
    kwargs = dict(
        rule_ids=["a", "b"],
        match_counts=[[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]],
        outcomes=[2.0, 3.0, 5.0],
        priors=[1.0, 1.0],
        ridge_strength=5.0,
        seed=20260727,
        bootstrap_draws=20,
    )
    assert calibrate_rule_weights(**kwargs) == calibrate_rule_weights(**kwargs)

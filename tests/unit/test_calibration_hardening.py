"""Unit tests for Sprint 10 calibration hardening (pure estimator).

Covers target centering (the intercept fix, with closed-form
expectations), row weights (family weighting exactness), the
fit-quality gate inputs (LOO on the original scale, prior-only
baseline), and the per-metric correlation diagnostics. Every expected
value below is hand-computed in the test comments — none is "whatever
the code outputs".
"""

from __future__ import annotations

import pytest

from planagent.services.calibration import (
    bootstrap_coefficient_intervals,
    calibrate_policy_thresholds,
    calibrate_rule_weights,
    fit_centered_ridge_to_prior,
    fit_ridge_to_prior,
    leave_one_out_rmse,
    pairwise_metric_correlations,
    prior_only_rmse,
    ridge_location_fit,
)

# ---------------------------------------------------------------- centering


def test_centered_fit_recovers_coefficients_and_intercept() -> None:
    # y = 10 + 2*x1 + 3*x2 exactly; weak shrinkage recovers all three.
    features = [[1.0, 0.0], [0.0, 1.0], [1.0, 1.0], [2.0, 1.0], [1.0, 2.0]]
    target = [12.0, 13.0, 15.0, 17.0, 18.0]
    fitted = fit_centered_ridge_to_prior(features, target, [0.0, 0.0], 1e-6)
    assert fitted["coefficients"] == pytest.approx([2.0, 3.0], abs=1e-4)
    assert fitted["intercept"] == pytest.approx(10.0, abs=1e-4)
    assert fitted["target_mean"] == pytest.approx(15.0)
    assert fitted["feature_means"] == pytest.approx([1.0, 1.0])


def test_centered_fit_does_not_absorb_the_level() -> None:
    # y = 100 + x: the level is 100, the slope is 1. Through the
    # origin the single coefficient absorbs the level:
    # (1030 + 5*1) / (30 + 5) = 29.5714. Centered, the intercept
    # carries the level and the weight carries the slope:
    # x_mean 2.5, y_mean 102.5, centered X'X = 5, X'y = 5, so
    # beta = (5 + 5*1) / (5 + 5) = 1.0, intercept = 102.5 - 2.5 = 100.
    features = [[1.0], [2.0], [3.0], [4.0]]
    target = [101.0, 102.0, 103.0, 104.0]
    through_origin = fit_ridge_to_prior(features, target, [1.0], 5.0)
    assert through_origin[0] == pytest.approx(29.5714, abs=1e-3)
    centered = fit_centered_ridge_to_prior(features, target, [1.0], 5.0)
    assert centered["coefficients"] == pytest.approx([1.0])
    assert centered["intercept"] == pytest.approx(100.0)
    assert centered["target_mean"] == pytest.approx(102.5)
    assert centered["feature_means"] == pytest.approx([2.5])


def test_centered_fit_unmatched_rule_keeps_prior_and_intercept_derived() -> None:
    # Centered: x_mean [2, 0], y_mean 4; centered X'X = 2, X'y = 4,
    # so beta_a = (4 + 5*1) / (2 + 5) = 9/7, the never-matched column
    # stays zero after centering and keeps its prior exactly, and the
    # intercept is 4 - 2*(9/7) = 10/7.
    result = calibrate_rule_weights(
        ["a", "never"],
        [[1.0, 0.0], [2.0, 0.0], [3.0, 0.0]],
        [2.0, 4.0, 6.0],
        [1.0, 1.0],
        ridge_strength=5.0,
        seed=7,
        bootstrap_draws=10,
    )
    assert result["weights"]["a"] == pytest.approx(9.0 / 7.0)
    assert result["weights"]["never"] == pytest.approx(1.0)
    assert result["intercept"] == pytest.approx(10.0 / 7.0)
    centering = result["centering"]
    assert centering["mode"] == "centered"
    assert centering["center_target"] is True
    assert centering["target_mean"] == pytest.approx(4.0)
    assert centering["feature_means"] == pytest.approx([2.0, 0.0])


def test_through_origin_mode_reproduces_sprint5_exactly() -> None:
    # Same inputs as the centered test above, through the origin:
    # X'X = 14, X'y = 28, beta_a = (28 + 5) / (14 + 5) = 33/19.
    result = calibrate_rule_weights(
        ["a", "never"],
        [[1.0, 0.0], [2.0, 0.0], [3.0, 0.0]],
        [2.0, 4.0, 6.0],
        [1.0, 1.0],
        ridge_strength=5.0,
        seed=7,
        bootstrap_draws=10,
        center_target=False,
    )
    assert result["weights"]["a"] == pytest.approx(33.0 / 19.0)
    assert result["weights"]["never"] == pytest.approx(1.0)
    assert result["intercept"] == 0.0
    centering = result["centering"]
    assert centering["mode"] == "through_origin"
    assert centering["center_target"] is False
    assert centering["target_mean"] is None
    assert centering["feature_means"] is None
    # And it equals the raw Sprint 5 estimator call exactly.
    direct = fit_ridge_to_prior(
        [[1.0, 0.0], [2.0, 0.0], [3.0, 0.0]], [2.0, 4.0, 6.0], [1.0, 1.0], 5.0
    )
    assert result["weights"] == {"a": direct[0], "never": direct[1]}


def test_intercept_has_no_shrinkage() -> None:
    # Strong shrinkage pulls the weight to its prior; the intercept
    # stays derived (y_mean - x_mean . prior), unpenalized: with
    # prior 1.0 the intercept tends to 102.5 - 2.5 = 100, not to 0.
    fitted = fit_centered_ridge_to_prior(
        [[1.0], [2.0], [3.0], [4.0]], [101.0, 102.0, 103.0, 104.0], [1.0], 1e6
    )
    assert fitted["coefficients"][0] == pytest.approx(1.0, abs=1e-3)
    assert fitted["intercept"] == pytest.approx(100.0, abs=1e-3)


def test_centered_loo_rmse_is_on_the_original_scale() -> None:
    # y = 100 + x exactly: centered LOO refits recover the line in
    # every fold, so the original-scale LOO error is ~0. The
    # through-origin LOO on the same data is large (the level is
    # absorbed differently per fold), proving the two are not the
    # same number and the centered one is the honest one.
    features = [[1.0], [2.0], [3.0], [4.0]]
    target = [101.0, 102.0, 103.0, 104.0]
    centered_loo = leave_one_out_rmse(
        features, target, [1.0], 1e-6, clip_nonnegative=False, center_target=True
    )
    assert centered_loo is not None
    assert centered_loo == pytest.approx(0.0, abs=1e-3)
    origin_loo = leave_one_out_rmse(features, target, [1.0], 1e-6, clip_nonnegative=False)
    assert origin_loo is not None
    assert origin_loo > 1.0


def test_centered_bootstrap_recentered_per_resample_and_deterministic() -> None:
    features = [[1.0], [2.0], [3.0], [4.0], [5.0]]
    target = [101.0, 102.0, 103.0, 104.0, 105.0]
    kwargs = {
        "features": features,
        "target": target,
        "prior": [1.0],
        "ridge_strength": 5.0,
        "draws": 30,
        "seed": 42,
        "level": 0.90,
        "center_target": True,
    }
    first = bootstrap_coefficient_intervals(**kwargs)
    second = bootstrap_coefficient_intervals(**kwargs)
    assert first == second
    # Estimate is the centered fit's coefficient (slope ~1), not the
    # through-origin level-absorbing value (~20+).
    centered = fit_centered_ridge_to_prior(features, target, [1.0], 5.0)
    assert first[0]["estimate"] == pytest.approx(centered["coefficients"][0])
    assert first[0]["low"] <= first[0]["estimate"] <= first[0]["high"]


def test_centered_fit_with_constant_feature_keeps_prior() -> None:
    # A constant feature is collinear with the intercept: centering
    # zeroes it, the penalty decides for the prior, and the intercept
    # absorbs the whole level.
    fitted = fit_centered_ridge_to_prior([[1.0], [1.0], [1.0]], [10.0, 20.0, 30.0], [1.5], 5.0)
    assert fitted["coefficients"][0] == pytest.approx(1.5)
    assert fitted["intercept"] == pytest.approx(20.0 - 1.5)


# ---------------------------------------------------------------- row weights


def test_weighted_ridge_closed_form() -> None:
    # Weights [1, 1, 2], ones column, prior 0, lambda 1:
    # beta = (10 + 20 + 60) / (1 + 1 + 2 + 1) = 18. Unweighted it is
    # 60 / 4 = 15.
    weighted = fit_ridge_to_prior(
        [[1.0], [1.0], [1.0]],
        [10.0, 20.0, 30.0],
        [0.0],
        1.0,
        clip_nonnegative=False,
        sample_weights=[1.0, 1.0, 2.0],
    )
    assert weighted[0] == pytest.approx(18.0)
    unweighted = fit_ridge_to_prior(
        [[1.0], [1.0], [1.0]], [10.0, 20.0, 30.0], [0.0], 1.0, clip_nonnegative=False
    )
    assert unweighted[0] == pytest.approx(15.0)


def test_weighted_location_fit_closed_form() -> None:
    assert ridge_location_fit(
        [10.0, 20.0, 30.0], 0.0, 1.0, sample_weights=[1.0, 1.0, 2.0]
    ) == pytest.approx(18.0)
    # Single observation: (2*10 + 1*0) / (2 + 1) = 20/3.
    assert ridge_location_fit([10.0], 0.0, 1.0, sample_weights=[2.0]) == pytest.approx(20.0 / 3.0)


def test_family_weighting_is_exact() -> None:
    # A family of 3 identical rows at weight 1/3 each must fit exactly
    # like one representative row at weight 1: both give
    # beta = (10 + 40) / (1 + 4 + 1) = 50/6. The unweighted fit over
    # all 4 rows gives 70/8 = 8.75 — the family would count triple.
    family = fit_ridge_to_prior(
        [[1.0], [1.0], [1.0], [2.0]],
        [10.0, 10.0, 10.0, 20.0],
        [0.0],
        1.0,
        clip_nonnegative=False,
        sample_weights=[1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0, 1.0],
    )
    representative = fit_ridge_to_prior(
        [[1.0], [2.0]], [10.0, 20.0], [0.0], 1.0, clip_nonnegative=False
    )
    assert family[0] == pytest.approx(50.0 / 6.0)
    assert family == representative
    unweighted = fit_ridge_to_prior(
        [[1.0], [1.0], [1.0], [2.0]],
        [10.0, 10.0, 10.0, 20.0],
        [0.0],
        1.0,
        clip_nonnegative=False,
    )
    assert unweighted[0] == pytest.approx(8.75)


def test_zero_weight_silences_a_row() -> None:
    silenced = fit_ridge_to_prior(
        [[1.0], [2.0], [3.0]],
        [100.0, 4.0, 6.0],
        [0.0],
        1e-6,
        clip_nonnegative=False,
        sample_weights=[0.0, 1.0, 1.0],
    )
    dropped = fit_ridge_to_prior([[2.0], [3.0]], [4.0, 6.0], [0.0], 1e-6, clip_nonnegative=False)
    assert silenced == pytest.approx(dropped, abs=1e-6)


def test_sample_weights_reject_bad_inputs() -> None:
    with pytest.raises(ValueError, match="must align"):
        fit_ridge_to_prior([[1.0], [1.0]], [1.0, 2.0], [0.0], 5.0, sample_weights=[1.0])
    with pytest.raises(ValueError, match="non-negative"):
        fit_ridge_to_prior([[1.0], [1.0]], [1.0, 2.0], [0.0], 5.0, sample_weights=[1.0, -1.0])
    with pytest.raises(ValueError, match="positive"):
        fit_ridge_to_prior([[1.0], [1.0]], [1.0, 2.0], [0.0], 5.0, sample_weights=[0.0, 0.0])
    with pytest.raises(ValueError, match="finite"):
        fit_ridge_to_prior(
            [[1.0], [1.0]], [1.0, 2.0], [0.0], 5.0, sample_weights=[1.0, float("inf")]
        )


# ---------------------------------------------------------------- gate inputs


def test_prior_only_rmse_hand_computed() -> None:
    # Predictions X.prior = [1, 1, 2]; errors [-1, -2, -3];
    # RMSE = sqrt(14/3).
    assert prior_only_rmse(
        [[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]], [2.0, 3.0, 5.0], [1.0, 1.0]
    ) == pytest.approx((14.0 / 3.0) ** 0.5)
    # Weighted [2, 1, 1]: (2*1 + 4 + 9) / 4 = 15/4.
    assert prior_only_rmse(
        [[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]],
        [2.0, 3.0, 5.0],
        [1.0, 1.0],
        [2.0, 1.0, 1.0],
    ) == pytest.approx((15.0 / 4.0) ** 0.5)


def test_rule_weight_fit_records_prior_only_baseline() -> None:
    result = calibrate_rule_weights(
        ["a"],
        [[1.0], [2.0], [3.0]],
        [2.0, 4.0, 6.0],
        [1.0],
        ridge_strength=5.0,
        seed=7,
        bootstrap_draws=10,
    )
    # Prior-only predictions [1, 2, 3]; errors [-1, -2, -3].
    assert result["prior_only_rmse"] == pytest.approx((14.0 / 3.0) ** 0.5)
    assert result["loo_rmse"] is not None
    assert result["loo_rmse"] < result["prior_only_rmse"]


def _policy(direction: str, alert: float, critical: float) -> dict[str, object]:
    return {
        "preferred_direction": direction,
        "alert_threshold": alert,
        "critical_threshold": critical,
    }


def test_policy_gate_refuses_worse_than_prior() -> None:
    # The decrease-direction fixture: prior-only RMSE is exactly 0.15
    # (errors 0.15/0.05/0.05/0.25); fitted LOO RMSE is sqrt(0.03421875)
    # ~= 0.185 (fold errors 0.2125/0.0875/0.0375/0.2875). The fitted
    # location is worse than doing nothing, so the gate keeps both
    # priors and records the rejected fit.
    result = calibrate_policy_thresholds(
        {"cost": _policy("decrease", 1.05, 1.15)},
        {"cost": [0.9, 1.0, 1.1, 1.3]},
        ridge_strength=1.0,
        seed=7,
        bootstrap_draws=10,
    )
    change = result["changes"]["cost"]
    assert change["unchanged_reason"] == "quality_gate"
    assert change["fitted_alert_threshold"] == 1.05
    assert change["fitted_critical_threshold"] == 1.15
    assert change["rejected_fit"]["alert_threshold"] == pytest.approx(1.07)
    assert change["quality_gate_passed"] is False
    assert change["fitted_loo_rmse"] == pytest.approx(0.18498, abs=1e-4)
    assert change["prior_only_rmse"] == pytest.approx(0.15)
    assert result["policies"]["cost"]["alert_threshold"] == 1.05


def test_policy_gate_passes_demo_fixture_and_records_numbers() -> None:
    # Fitted LOO: fold errors 7.5/5/17.5/30 -> sqrt(321.875) ~= 17.94.
    # Prior-only: errors 30/40/50/60 -> sqrt(2150) ~= 46.37.
    result = calibrate_policy_thresholds(
        {"cash": _policy("increase", 50.0, 25.0)},
        {"cash": [80.0, 90.0, 100.0, 110.0]},
        ridge_strength=1.0,
        seed=7,
        bootstrap_draws=10,
    )
    change = result["changes"]["cash"]
    assert change["unchanged_reason"] is None
    assert change["quality_gate_passed"] is True
    assert change["fitted_loo_rmse"] == pytest.approx(17.9412, abs=1e-3)
    assert change["prior_only_rmse"] == pytest.approx(46.3681, abs=1e-3)
    assert change["fitted_alert_threshold"] == pytest.approx(86.0)


def test_policy_gate_disabled_records_numbers_without_refusing() -> None:
    result = calibrate_policy_thresholds(
        {"cost": _policy("decrease", 1.05, 1.15)},
        {"cost": [0.9, 1.0, 1.1, 1.3]},
        ridge_strength=1.0,
        seed=7,
        bootstrap_draws=10,
        quality_gate=False,
    )
    change = result["changes"]["cost"]
    assert change["unchanged_reason"] is None
    assert change["quality_gate_passed"] is None
    assert change["fitted_loo_rmse"] == pytest.approx(0.18498, abs=1e-4)
    assert change["prior_only_rmse"] == pytest.approx(0.15)
    assert change["fitted_alert_threshold"] == pytest.approx(1.07)


def test_policy_gate_not_evaluated_below_three_observations() -> None:
    result = calibrate_policy_thresholds(
        {"cash": _policy("increase", 50.0, 25.0)},
        {"cash": [80.0, 90.0]},
        ridge_strength=1.0,
        seed=7,
        bootstrap_draws=10,
    )
    change = result["changes"]["cash"]
    assert change["unchanged_reason"] == "insufficient_observations"
    assert change["fitted_loo_rmse"] is None
    assert change["prior_only_rmse"] is None
    assert change["quality_gate_passed"] is None


def test_policy_fit_with_weights_uses_weighted_location() -> None:
    # Weights [3, 1, 1, 1] on [80, 90, 100, 110], prior 50, lambda 1:
    # alert = (240 + 90 + 100 + 110 + 50) / (6 + 1) = 590/7 ~= 84.29.
    result = calibrate_policy_thresholds(
        {"cash": _policy("increase", 50.0, 25.0)},
        {"cash": [80.0, 90.0, 100.0, 110.0]},
        ridge_strength=1.0,
        seed=7,
        bootstrap_draws=10,
        observation_weights={"cash": [3.0, 1.0, 1.0, 1.0]},
        quality_gate=False,
    )
    assert result["policies"]["cash"]["alert_threshold"] == pytest.approx(590.0 / 7.0)


# ---------------------------------------------------------------- correlations


def test_correlation_perfect_positive_warns() -> None:
    result = pairwise_metric_correlations(
        {
            "cash": {"r1": 1.0, "r2": 2.0, "r3": 3.0, "r4": 4.0, "r5": 5.0},
            "pipeline": {"r1": 2.0, "r2": 4.0, "r3": 6.0, "r4": 8.0, "r5": 10.0},
        }
    )
    assert result["method"] == "pearson_pairwise_complete"
    assert result["pairs"] == [
        {"metric_a": "cash", "metric_b": "pipeline", "n": 5, "r": pytest.approx(1.0)}
    ]
    assert result["warning"] is True
    assert result["warned_pairs"] == ["cash/pipeline"]
    assert result["warning_threshold"] == 0.8
    assert result["warning_min_n"] == 5


def test_correlation_perfect_negative_warns() -> None:
    result = pairwise_metric_correlations(
        {
            "a": {"r1": 1.0, "r2": 2.0, "r3": 3.0, "r4": 4.0, "r5": 5.0},
            "b": {"r1": 5.0, "r2": 4.0, "r3": 3.0, "r4": 2.0, "r5": 1.0},
        }
    )
    assert result["pairs"][0]["r"] == pytest.approx(-1.0)
    assert result["warning"] is True


def test_correlation_uncorrelated_is_zero_and_quiet() -> None:
    # Cross-products cancel exactly: dx [-1.5, -.5, .5, 1.5] against
    # dy [-.5, .5, .5, -.5] sum to 0, so r = 0.
    result = pairwise_metric_correlations(
        {
            "a": {"r1": 1.0, "r2": 2.0, "r3": 3.0, "r4": 4.0},
            "b": {"r1": 1.0, "r2": 2.0, "r3": 2.0, "r4": 1.0},
        }
    )
    assert result["pairs"][0]["r"] == pytest.approx(0.0)
    assert result["warning"] is False


def test_correlation_uses_pairwise_complete_observations() -> None:
    # Shared keys are r2/r3/r4 only: a [1, 2, 3] against b [2, 4, 6]
    # gives r = 1 with n = 3 — below the warning minimum, so quiet.
    result = pairwise_metric_correlations(
        {
            "a": {"r1": 0.0, "r2": 1.0, "r3": 2.0, "r4": 3.0},
            "b": {"r2": 2.0, "r3": 4.0, "r4": 6.0, "r5": 8.0},
        }
    )
    assert result["pairs"][0]["n"] == 3
    assert result["pairs"][0]["r"] == pytest.approx(1.0)
    assert result["warning"] is False


def test_correlation_zero_variance_is_null_not_zero() -> None:
    result = pairwise_metric_correlations(
        {
            "a": {"r1": 5.0, "r2": 5.0, "r3": 5.0, "r4": 5.0, "r5": 5.0},
            "b": {"r1": 1.0, "r2": 2.0, "r3": 3.0, "r4": 4.0, "r5": 5.0},
        }
    )
    assert result["pairs"][0]["r"] is None
    assert result["warning"] is False


def test_correlation_single_metric_has_no_pairs() -> None:
    result = pairwise_metric_correlations({"a": {"r1": 1.0, "r2": 2.0}})
    assert result["pairs"] == []
    assert result["warning"] is False


def test_correlation_rejects_non_finite() -> None:
    with pytest.raises(ValueError, match="finite"):
        pairwise_metric_correlations(
            {"a": {"r1": 1.0, "r2": float("inf")}, "b": {"r1": 1.0, "r2": 2.0}}
        )


def test_correlation_pairs_are_deterministically_ordered() -> None:
    series = {
        "zeta": {"r1": 1.0, "r2": 2.0},
        "alpha": {"r1": 1.0, "r2": 2.0},
        "mid": {"r1": 2.0, "r2": 1.0},
    }
    first = pairwise_metric_correlations(series)
    second = pairwise_metric_correlations(dict(reversed(list(series.items()))))
    assert first == second
    assert [(p["metric_a"], p["metric_b"]) for p in first["pairs"]] == [
        ("alpha", "mid"),
        ("alpha", "zeta"),
        ("mid", "zeta"),
    ]

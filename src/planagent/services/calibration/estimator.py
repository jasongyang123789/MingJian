"""Ridge-to-prior calibration estimator (Sprint 5, PRD delta D8).

Ports jasonrkeen's ``backtesting.fit_ridge_to_prior``: coefficients are
fit by solving the ridge normal equations with the penalty centered on
a prior,

    beta = (X'X + lambda * I)^-1 (X'y + lambda * prior),

so strong shrinkage stays near the prior and weak shrinkage follows
the data. The reference clips coefficients at zero (transmission
coefficients are non-negative); clipping is optional here because
policy thresholds can legitimately be negative for some metrics.

Deliberate deviations from the reference, all documented:

- No numpy/pandas: this codebase's new modules are stdlib-only, so the
  normal equations are solved with Gaussian elimination and partial
  pivoting. Feature counts are small (rules per domain, one threshold
  per metric), so the cubic solve is cheap.
- The location fit (a single threshold) goes through the same general
  solver with a ones-column design, so there is exactly one estimator
  code path. The closed form is ``(sum(y) + lambda * prior) / (n +
  lambda)``; going through the solver keeps the shrinkage semantics
  identical by construction.
- Bootstrap intervals reuse the Sprint 4 seeded-resampling primitive
  (:func:`bootstrap_index_draws` in ``robustness.methods``) and the
  Sprint 3 linear-interpolation percentile: resample row indices with
  replacement, refit, report percentile intervals — the reference's
  ``_bootstrap_coefficients`` pattern.
- Leave-one-out predictions (the reference's ``_leave_one_out_``
  check) are reported as LOO RMSE: an honest fit-quality signal that
  does not reuse the fitted row.

Everything here is deterministic given its inputs: no LLM, no I/O,
and the only randomness is bootstrap resampling from an explicitly
seeded RNG.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from planagent.services.distributions.aggregation import percentile
from planagent.services.distributions.canonical import derive_sub_seed
from planagent.services.robustness.methods import bootstrap_index_draws

#: Default ridge strength, matching the reference (``DEFAULT_RIDGE_STRENGTH``).
DEFAULT_RIDGE_STRENGTH = 5.0

#: Default bootstrap draws. The reference uses 1000; 200 keeps API
#: latency sane for the pure-Python solver while staying stable for
#: percentile intervals. Callers may raise it (capped by the request model).
DEFAULT_BOOTSTRAP_DRAWS = 200

#: Default bootstrap seed, matching the reference model's seed.
DEFAULT_CALIBRATION_SEED = 20260727

#: Minimum observations for a calibration fit, matching the reference's
#: ``calibrate_brent_transmission`` eligibility rule (at least 3).
MIN_OBSERVATIONS = 3


def _require_finite_matrix(
    features: list[list[float]], target: list[float], prior: list[float]
) -> tuple[list[list[float]], list[float], list[float]]:
    if len(features) < 2:
        raise ValueError(f"Ridge fit requires at least 2 observations; got {len(features)}.")
    if len(features) != len(target):
        raise ValueError(f"Feature rows ({len(features)}) and targets ({len(target)}) must align.")
    width = len(prior)
    if width < 1:
        raise ValueError("Ridge fit requires at least one coefficient.")
    rows: list[list[float]] = []
    for row in features:
        if len(row) != width:
            raise ValueError(f"Feature rows must all have {width} columns; got {len(row)}.")
        values = [float(value) for value in row]
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Ridge fit requires finite feature values.")
        rows.append(values)
    targets = [float(value) for value in target]
    priors = [float(value) for value in prior]
    if not all(math.isfinite(value) for value in targets):
        raise ValueError("Ridge fit requires finite target values.")
    if not all(math.isfinite(value) for value in priors):
        raise ValueError("Ridge fit requires a finite prior.")
    return rows, targets, priors


def _solve_linear_system(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    """Solve a dense linear system by Gaussian elimination.

    Partial pivoting keeps the solve stable for the small, well-scaled
    systems here. Raises ``ValueError`` on a (numerically) singular
    matrix — with ridge_strength > 0 the penalized system is positive
    definite and this cannot happen; with ridge_strength == 0 a
    rank-deficient design is the caller's error, reported plainly.
    """

    n = len(rhs)
    augmented = [list(matrix[i]) + [rhs[i]] for i in range(n)]
    for column in range(n):
        pivot = max(range(column, n), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise ValueError(
                "Ridge system is singular; increase ridge_strength or remove collinear features."
            )
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        pivot_value = augmented[column][column]
        for row in range(column + 1, n):
            factor = augmented[row][column] / pivot_value
            if factor == 0.0:
                continue
            for j in range(column, n + 1):
                augmented[row][j] -= factor * augmented[column][j]
    solution = [0.0] * n
    for i in range(n - 1, -1, -1):
        residual = augmented[i][n] - sum(augmented[i][j] * solution[j] for j in range(i + 1, n))
        solution[i] = residual / augmented[i][i]
    return solution


def fit_ridge_to_prior(
    features: list[list[float]],
    target: list[float],
    prior: list[float],
    ridge_strength: float,
    *,
    clip_nonnegative: bool = True,
) -> list[float]:
    """Fit coefficients with quadratic shrinkage toward a prior.

    Solves ``(X'X + lambda * I) beta = X'y + lambda * prior``. The
    reference clips at zero; ``clip_nonnegative`` keeps that default
    (rule weights are non-negative multipliers) and lets threshold
    fits opt out (thresholds may be negative). ``ridge_strength`` must
    be >= 0; 0 is the unpenalized least-squares fit and requires a
    full-rank design.
    """

    if not math.isfinite(ridge_strength) or ridge_strength < 0:
        raise ValueError(f"ridge_strength must be finite and >= 0; got {ridge_strength}.")
    rows, targets, priors = _require_finite_matrix(features, target, prior)
    width = len(priors)
    xtx = [[0.0] * width for _ in range(width)]
    xty = [0.0] * width
    for row, outcome in zip(rows, targets):
        for i in range(width):
            xty[i] += row[i] * outcome
            for j in range(width):
                xtx[i][j] += row[i] * row[j]
    for i in range(width):
        xtx[i][i] += ridge_strength
        xty[i] += ridge_strength * priors[i]
    coefficients = _solve_linear_system(xtx, xty)
    if clip_nonnegative:
        coefficients = [max(0.0, value) for value in coefficients]
    return coefficients


def ridge_location_fit(
    values: list[float],
    prior: float,
    ridge_strength: float,
    *,
    clip_nonnegative: bool = False,
) -> float:
    """Ridge-shrunk location fit: one threshold from observed values.

    The threshold is a location parameter, so the design is a column of
    ones and the single coefficient is the threshold itself. Unlike the
    general fit, a single observation is well-defined here (the normal
    equation is ``(n + lambda) * beta = sum(y) + lambda * prior``,
    nonsingular for any n >= 1 when lambda > 0), so n >= 1 is accepted.
    Empty input raises.
    """

    if not values:
        raise ValueError("Location fit requires at least one observed value.")
    if not math.isfinite(prior):
        raise ValueError("Location fit requires a finite prior.")
    if not math.isfinite(ridge_strength) or ridge_strength < 0:
        raise ValueError(f"ridge_strength must be finite and >= 0; got {ridge_strength}.")
    if len(values) == 1:
        fitted = (float(values[0]) + ridge_strength * float(prior)) / (1.0 + ridge_strength)
        return max(0.0, fitted) if clip_nonnegative else fitted
    return fit_ridge_to_prior(
        [[1.0] for _ in values],
        [float(value) for value in values],
        [float(prior)],
        ridge_strength,
        clip_nonnegative=clip_nonnegative,
    )[0]


def leave_one_out_rmse(
    features: list[list[float]],
    target: list[float],
    prior: list[float],
    ridge_strength: float,
    *,
    clip_nonnegative: bool = True,
) -> float | None:
    """LOO root-mean-square error of the ridge fit.

    Each observation is predicted by a fit trained on the others, so
    the error is an honest out-of-sample signal. Returns ``None`` when
    fewer than 3 observations make LOO refits (each needing >= 2 rows)
    impossible.
    """

    if len(target) < 3:
        return None
    squared_errors: list[float] = []
    for position in range(len(target)):
        keep = [i for i in range(len(target)) if i != position]
        coefficients = fit_ridge_to_prior(
            [features[i] for i in keep],
            [target[i] for i in keep],
            prior,
            ridge_strength,
            clip_nonnegative=clip_nonnegative,
        )
        predicted = sum(
            coefficient * value for coefficient, value in zip(coefficients, features[position])
        )
        squared_errors.append((predicted - float(target[position])) ** 2)
    return math.sqrt(sum(squared_errors) / len(squared_errors))


def bootstrap_coefficient_intervals(
    features: list[list[float]],
    target: list[float],
    prior: list[float],
    ridge_strength: float,
    *,
    draws: int,
    seed: int,
    level: float,
    clip_nonnegative: bool = True,
) -> list[dict[str, float | int | str]]:
    """Seeded bootstrap percentile intervals for fitted coefficients.

    Each draw resamples row indices with replacement (the shared Sprint 4
    primitive), refits, and records the coefficients; the interval is the
    percentile interval of the bootstrap distribution at ``level``.
    ``estimate`` is the coefficient on the observed rows, not the
    bootstrap median. Deterministic given (inputs, seed).
    """

    if draws < 1:
        raise ValueError(f"Bootstrap draws must be >= 1; got {draws}.")
    if not 0.0 < level < 1.0:
        raise ValueError(f"Bootstrap level must lie in (0, 1); got {level}.")
    estimates = fit_ridge_to_prior(
        features, target, prior, ridge_strength, clip_nonnegative=clip_nonnegative
    )
    distributions: list[list[float]] = [[] for _ in prior]
    for indices in bootstrap_index_draws(len(target), draws, seed):
        refit = fit_ridge_to_prior(
            [features[i] for i in indices],
            [target[i] for i in indices],
            prior,
            ridge_strength,
            clip_nonnegative=clip_nonnegative,
        )
        for position, value in enumerate(refit):
            distributions[position].append(value)
    tail = (1.0 - level) / 2.0
    return [
        {
            "estimate": estimates[position],
            "low": percentile(sorted(distribution), tail),
            "high": percentile(sorted(distribution), 1.0 - tail),
            "draws": draws,
            "seed": seed,
            "level": level,
            "method": "percentile",
        }
        for position, distribution in enumerate(distributions)
    ]


def _worst_tail(
    values: list[float], preferred_direction: str, alert_threshold: float
) -> list[float]:
    """Observations on the bad side of the current alert threshold.

    For ``increase`` metrics (higher is better) the bad side is below
    the alert line; for ``decrease`` metrics it is above. When no
    observation crossed the line, the worst quartile stands in — the
    critical line still needs a data-driven anchor, and the fallback is
    recorded by the caller via the tail count, not hidden.
    """

    if preferred_direction == "increase":
        tail = [value for value in values if value < alert_threshold]
        if tail:
            return tail
        ordered = sorted(values)
        return ordered[: max(1, math.ceil(len(ordered) / 4))]
    if preferred_direction == "decrease":
        tail = [value for value in values if value > alert_threshold]
        if tail:
            return tail
        ordered = sorted(values, reverse=True)
        return ordered[: max(1, math.ceil(len(ordered) / 4))]
    raise ValueError(
        f"preferred_direction must be 'increase' or 'decrease'; got {preferred_direction!r}."
    )


def _ordering_holds(
    preferred_direction: str, alert_threshold: float, critical_threshold: float
) -> bool:
    if preferred_direction == "increase":
        return alert_threshold > critical_threshold
    return alert_threshold < critical_threshold


def calibrate_policy_thresholds(
    policies: Mapping[str, Mapping[str, Any]],
    observations: Mapping[str, list[float]],
    *,
    ridge_strength: float,
    seed: int,
    bootstrap_draws: int,
    level: float = 0.95,
    min_observations: int = MIN_OBSERVATIONS,
) -> dict[str, Any]:
    """Fit calibrated alert/critical thresholds for template policies.

    Estimator, per metric: the alert threshold is a ridge-shrunk
    location fit over all observed final values (prior: the current
    alert threshold); the critical threshold is the same fit over the
    worst-side tail (prior: the current critical threshold). Both go
    through :func:`fit_ridge_to_prior` with a ones-column design, so
    the shrinkage semantics are the reference's, and bootstrap
    intervals come from the shared resampling primitive.

    Metrics with too few observations keep their priors and record
    ``unchanged_reason``; a fitted pair that would break the
    direction's threshold ordering is rejected wholesale for that
    metric (both priors kept, reason ``ordering_guard``, rejected fit
    recorded) rather than silently clamped. Returns the fitted policy
    specs plus per-metric change records.
    """

    if not math.isfinite(ridge_strength) or ridge_strength < 0:
        raise ValueError(f"ridge_strength must be finite and >= 0; got {ridge_strength}.")
    fitted_policies: dict[str, dict[str, Any]] = {}
    changes: dict[str, Any] = {}
    for metric, spec in policies.items():
        direction = str(spec["preferred_direction"])
        prior_alert = float(spec["alert_threshold"])
        prior_critical = float(spec["critical_threshold"])
        values = [float(value) for value in observations.get(metric, [])]
        values = [value for value in values if math.isfinite(value)]
        base_change: dict[str, Any] = {
            "metric": metric,
            "preferred_direction": direction,
            "prior_alert_threshold": prior_alert,
            "prior_critical_threshold": prior_critical,
            "n_observations": len(values),
            "n_tail": 0,
            "unchanged_reason": None,
        }
        if len(values) < min_observations:
            base_change.update(
                {
                    "fitted_alert_threshold": prior_alert,
                    "fitted_critical_threshold": prior_critical,
                    "alert_bootstrap": None,
                    "critical_bootstrap": None,
                    "unchanged_reason": "insufficient_observations",
                }
            )
            fitted_policies[metric] = dict(spec)
            changes[metric] = base_change
            continue
        tail = _worst_tail(values, direction, prior_alert)
        alert_seed = derive_sub_seed(seed, "calibration", metric, "alert")
        critical_seed = derive_sub_seed(seed, "calibration", metric, "critical")
        fitted_alert = ridge_location_fit(values, prior_alert, ridge_strength)
        fitted_critical = ridge_location_fit(tail, prior_critical, ridge_strength)
        alert_interval = bootstrap_coefficient_intervals(
            [[1.0] for _ in values],
            values,
            [prior_alert],
            ridge_strength,
            draws=bootstrap_draws,
            seed=alert_seed,
            level=level,
            clip_nonnegative=False,
        )[0]
        critical_interval = bootstrap_coefficient_intervals(
            [[1.0] for _ in tail],
            tail,
            [prior_critical],
            ridge_strength,
            draws=bootstrap_draws,
            seed=critical_seed,
            level=level,
            clip_nonnegative=False,
        )[0]
        base_change.update(
            {
                "fitted_alert_threshold": fitted_alert,
                "fitted_critical_threshold": fitted_critical,
                "alert_bootstrap": alert_interval,
                "critical_bootstrap": critical_interval,
                "n_tail": len(tail),
            }
        )
        if not _ordering_holds(direction, fitted_alert, fitted_critical):
            base_change.update(
                {
                    "fitted_alert_threshold": prior_alert,
                    "fitted_critical_threshold": prior_critical,
                    "unchanged_reason": "ordering_guard",
                    "rejected_fit": {
                        "alert_threshold": fitted_alert,
                        "critical_threshold": fitted_critical,
                    },
                }
            )
            fitted_policies[metric] = dict(spec)
            changes[metric] = base_change
            continue
        fitted_policies[metric] = {
            **dict(spec),
            "alert_threshold": fitted_alert,
            "critical_threshold": fitted_critical,
        }
        changes[metric] = base_change
    return {"policies": fitted_policies, "changes": changes}


def calibrate_rule_weights(
    rule_ids: list[str],
    match_counts: list[list[float]],
    outcomes: list[float],
    priors: list[float],
    *,
    ridge_strength: float,
    seed: int,
    bootstrap_draws: int,
    level: float = 0.95,
    min_observations: int = MIN_OBSERVATIONS,
) -> dict[str, Any]:
    """Fit calibrated rule weights from observed outcomes.

    Each observation is one completed run: features are per-rule match
    counts across the run's decision records, the target is the run's
    final value of the chosen outcome metric, and the prior is the
    registry's current weight per rule. Coefficients are clipped at
    zero (the reference's rule: weights are non-negative multipliers).
    Rules that never matched keep their prior exactly — an all-zero
    column contributes nothing to ``X'y``, so the penalty term alone
    decides, and it decides for the prior.

    The fitted weights are an association signal (rule activation vs
    outcome), shrunk toward current weights — not causal estimates.
    That limitation is stated on the fit record, not buried.
    """

    if len(outcomes) < min_observations:
        raise ValueError(
            f"Rule-weight fit requires at least {min_observations} observations; "
            f"got {len(outcomes)}."
        )
    if len(rule_ids) != len(priors):
        raise ValueError(f"Rule ids ({len(rule_ids)}) and priors ({len(priors)}) must align.")
    if len(match_counts) != len(outcomes):
        raise ValueError(
            f"Match-count rows ({len(match_counts)}) and outcomes ({len(outcomes)}) must align."
        )
    fitted = fit_ridge_to_prior(
        match_counts, outcomes, priors, ridge_strength, clip_nonnegative=True
    )
    intervals = bootstrap_coefficient_intervals(
        match_counts,
        outcomes,
        priors,
        ridge_strength,
        draws=bootstrap_draws,
        seed=derive_sub_seed(seed, "calibration", "rule-weights"),
        level=level,
        clip_nonnegative=True,
    )
    loo = leave_one_out_rmse(match_counts, outcomes, priors, ridge_strength, clip_nonnegative=True)
    changes: dict[str, Any] = {}
    for position, rule_id in enumerate(rule_ids):
        changes[rule_id] = {
            "rule_id": rule_id,
            "prior_weight": float(priors[position]),
            "fitted_weight": fitted[position],
            "bootstrap": intervals[position],
            "total_matches": sum(float(row[position]) for row in match_counts),
        }
    return {
        "weights": {rule_id: fitted[position] for position, rule_id in enumerate(rule_ids)},
        "changes": changes,
        "loo_rmse": loo,
        "n_observations": len(outcomes),
    }

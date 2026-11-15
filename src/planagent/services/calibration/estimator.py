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

Sprint 10 hardening (same file, same discipline):

- Row weights: every fit accepts optional per-observation weights
  (the scenario-family mode downweights correlated runs). Weights
  default to uniform and are validated finite and non-negative.
- Target centering: rule-weight fits center features and target by
  default, fitting weights on deviations with an unpenalized derived
  intercept carrying the level (see
  :func:`fit_centered_ridge_to_prior` for the prior semantics of the
  intercept — it has none, deliberately). The through-origin fit is
  kept exactly and selected explicitly, so old fits stay reproducible.
- Fit-quality gate inputs: LOO RMSE stays on the original scale for
  centered fits, and :func:`prior_only_rmse` gives the do-nothing
  baseline both gates compare against.
- Correlation diagnostics: :func:`pairwise_metric_correlations`
  reports Pearson correlations of per-metric observation vectors;
  diagnostics only, never a fit input.
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

#: Correlation-warning threshold for the Sprint 10 diagnostics: a pair
#: of metrics with |r| at or above this value (and enough paired
#: observations) is flagged. A documented choice for this codebase,
#: not a universal constant; warnings are recorded, never refusing.
CORRELATION_WARNING_THRESHOLD = 0.8

#: Minimum paired observations for a correlation warning to fire.
CORRELATION_WARNING_MIN_N = 5


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


def _normalize_weights(count: int, sample_weights: list[float] | None) -> list[float]:
    """Per-observation weights, uniform when none are given.

    Weights must be finite, non-negative, aligned with the rows, and
    sum to something positive (all-zero weights fit nothing). A zero
    weight silences a row exactly; family weights are 1/family-size,
    never zero.
    """

    if sample_weights is None:
        return [1.0] * count
    if len(sample_weights) != count:
        raise ValueError(
            f"Sample weights ({len(sample_weights)}) and observations ({count}) must align."
        )
    weights = [float(value) for value in sample_weights]
    if not all(math.isfinite(value) for value in weights):
        raise ValueError("Sample weights must be finite.")
    if any(value < 0.0 for value in weights):
        raise ValueError("Sample weights must be non-negative.")
    if sum(weights) <= 0.0:
        raise ValueError("Sample weights must sum to a positive value.")
    return weights


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
    sample_weights: list[float] | None = None,
) -> list[float]:
    """Fit coefficients with quadratic shrinkage toward a prior.

    Solves ``(X'X + lambda * I) beta = X'y + lambda * prior``. The
    reference clips at zero; ``clip_nonnegative`` keeps that default
    (rule weights are non-negative multipliers) and lets threshold
    fits opt out (thresholds may be negative). ``ridge_strength`` must
    be >= 0; 0 is the unpenalized least-squares fit and requires a
    full-rank design.

    With ``sample_weights`` the normal equations are weighted,
    ``(X'WX + lambda * I) beta = X'Wy + lambda * prior``; the penalty
    is deliberately NOT scaled by the total weight, so downweighted
    observations carry less evidence against the same prior. Uniform
    weights reproduce the unweighted fit exactly.
    """

    if not math.isfinite(ridge_strength) or ridge_strength < 0:
        raise ValueError(f"ridge_strength must be finite and >= 0; got {ridge_strength}.")
    rows, targets, priors = _require_finite_matrix(features, target, prior)
    weights = _normalize_weights(len(rows), sample_weights)
    width = len(priors)
    xtx = [[0.0] * width for _ in range(width)]
    xty = [0.0] * width
    for row, outcome, weight in zip(rows, targets, weights):
        for i in range(width):
            xty[i] += weight * row[i] * outcome
            for j in range(width):
                xtx[i][j] += weight * row[i] * row[j]
    for i in range(width):
        xtx[i][i] += ridge_strength
        xty[i] += ridge_strength * priors[i]
    coefficients = _solve_linear_system(xtx, xty)
    if clip_nonnegative:
        coefficients = [max(0.0, value) for value in coefficients]
    return coefficients


def fit_centered_ridge_to_prior(
    features: list[list[float]],
    target: list[float],
    prior: list[float],
    ridge_strength: float,
    *,
    clip_nonnegative: bool = True,
    sample_weights: list[float] | None = None,
) -> dict[str, Any]:
    """Ridge-to-prior fit with an unpenalized intercept, via centering.

    The Sprint 5 estimator is ridge through the origin: for a
    level-dominated target (final cash ~100) the fitted weights absorb
    the target's level, which is why the Sprint 5 demo fit produced
    weights of 32.70 / 21.44 that the apply-time clip then bounded.
    Centering fixes the level absorption without changing the
    shrinkage semantics: features and target are centered at their
    (weighted) means, weights are fit on the centered data with the
    same ridge-to-prior penalty, and the intercept is derived as
    ``y_mean - x_mean . beta``.

    Intercept prior semantics (stated explicitly because Sprint 5
    deferred this item for exactly this reason): the intercept has NO
    prior and NO shrinkage. It is not a registry quantity, it is
    never penalized toward anything, and the apply step still applies
    weights only — the intercept exists so the fit's predictions live
    on the original scale and the weights carry deviations, not the
    level. The intercept is computed from the FINAL (post-clip)
    coefficients, so predictions ``intercept + x . beta`` are
    consistent with the weights actually recorded.

    The all-zero-column property survives centering: a column that is
    zero everywhere has mean zero, stays zero after centering, and its
    coefficient is decided by the penalty term alone — the prior,
    exactly. A constant non-zero column is likewise absorbed by the
    intercept (it is collinear with it) and keeps its prior.

    Returns the coefficients, the intercept, and the means used, so
    the fit record can pin exactly what was centered.
    """

    if not math.isfinite(ridge_strength) or ridge_strength < 0:
        raise ValueError(f"ridge_strength must be finite and >= 0; got {ridge_strength}.")
    rows, targets, priors = _require_finite_matrix(features, target, prior)
    weights = _normalize_weights(len(rows), sample_weights)
    total_weight = sum(weights)
    width = len(priors)
    feature_means = [
        sum(weight * row[j] for row, weight in zip(rows, weights)) / total_weight
        for j in range(width)
    ]
    target_mean = sum(weight * value for value, weight in zip(targets, weights)) / total_weight
    centered_rows = [[row[j] - feature_means[j] for j in range(width)] for row in rows]
    centered_targets = [value - target_mean for value in targets]
    coefficients = fit_ridge_to_prior(
        centered_rows,
        centered_targets,
        priors,
        ridge_strength,
        clip_nonnegative=clip_nonnegative,
        sample_weights=weights,
    )
    intercept = target_mean - sum(mean * beta for mean, beta in zip(feature_means, coefficients))
    return {
        "coefficients": coefficients,
        "intercept": intercept,
        "feature_means": feature_means,
        "target_mean": target_mean,
    }


def ridge_location_fit(
    values: list[float],
    prior: float,
    ridge_strength: float,
    *,
    clip_nonnegative: bool = False,
    sample_weights: list[float] | None = None,
) -> float:
    """Ridge-shrunk location fit: one threshold from observed values.

    The threshold is a location parameter, so the design is a column of
    ones and the single coefficient is the threshold itself. Unlike the
    general fit, a single observation is well-defined here (the normal
    equation is ``(n + lambda) * beta = sum(y) + lambda * prior``,
    nonsingular for any n >= 1 when lambda > 0), so n >= 1 is accepted.
    Empty input raises. With ``sample_weights`` the closed form is
    ``(sum(w*y) + lambda * prior) / (sum(w) + lambda)`` — the location
    coefficient IS the location here, so centering does not apply:
    there is no separate intercept to carry the level.
    """

    if not values:
        raise ValueError("Location fit requires at least one observed value.")
    if not math.isfinite(prior):
        raise ValueError("Location fit requires a finite prior.")
    if not math.isfinite(ridge_strength) or ridge_strength < 0:
        raise ValueError(f"ridge_strength must be finite and >= 0; got {ridge_strength}.")
    weights = _normalize_weights(len(values), sample_weights)
    if len(values) == 1:
        fitted = (weights[0] * float(values[0]) + ridge_strength * float(prior)) / (
            weights[0] + ridge_strength
        )
        return max(0.0, fitted) if clip_nonnegative else fitted
    return fit_ridge_to_prior(
        [[1.0] for _ in values],
        [float(value) for value in values],
        [float(prior)],
        ridge_strength,
        clip_nonnegative=clip_nonnegative,
        sample_weights=weights,
    )[0]


def _fit_coefficients(
    features: list[list[float]],
    target: list[float],
    prior: list[float],
    ridge_strength: float,
    *,
    clip_nonnegative: bool,
    center_target: bool,
    sample_weights: list[float] | None,
) -> tuple[list[float], float]:
    """Coefficients + intercept for one fit, honoring the center mode.

    The single refit path shared by LOO and bootstrap, so centering is
    part of every refit (means recomputed from the refit rows), never
    one-time preprocessing. Through-origin fits carry intercept 0.0.
    """

    if center_target:
        fitted = fit_centered_ridge_to_prior(
            features,
            target,
            prior,
            ridge_strength,
            clip_nonnegative=clip_nonnegative,
            sample_weights=sample_weights,
        )
        return fitted["coefficients"], fitted["intercept"]
    return (
        fit_ridge_to_prior(
            features,
            target,
            prior,
            ridge_strength,
            clip_nonnegative=clip_nonnegative,
            sample_weights=sample_weights,
        ),
        0.0,
    )


def _weighted_rmse(errors: list[float], weights: list[float]) -> float:
    total = sum(weights)
    return math.sqrt(sum(w * e * e for w, e in zip(weights, errors)) / total)


def prior_only_rmse(
    features: list[list[float]],
    target: list[float],
    prior: list[float],
    sample_weights: list[float] | None = None,
) -> float:
    """RMSE of the do-nothing predictor: ``y_hat = X . prior``.

    The fit-quality gate's baseline. No fitting happens, so the
    leave-one-out error of this predictor equals its in-sample error
    exactly — the comparison in the gate is LOO-vs-LOO with no
    adjustment needed. For location fits the design is a ones column
    and the prior is the threshold constant, so this is the RMSE of
    predicting the prior threshold for every observation.
    """

    rows, targets, priors = _require_finite_matrix(features, target, prior)
    weights = _normalize_weights(len(rows), sample_weights)
    errors = [
        sum(beta * value for beta, value in zip(priors, row)) - outcome
        for row, outcome in zip(rows, targets)
    ]
    return _weighted_rmse(errors, weights)


def leave_one_out_rmse(
    features: list[list[float]],
    target: list[float],
    prior: list[float],
    ridge_strength: float,
    *,
    clip_nonnegative: bool = True,
    center_target: bool = False,
    sample_weights: list[float] | None = None,
) -> float | None:
    """LOO root-mean-square error of the ridge fit.

    Each observation is predicted by a fit trained on the others, so
    the error is an honest out-of-sample signal. Returns ``None`` when
    fewer than 3 observations make LOO refits (each needing >= 2 rows)
    impossible.

    The error is always on the ORIGINAL scale: centered fits predict
    ``intercept + x . beta`` with the intercept refit on the training
    fold (centering is part of the fit, recomputed per fold), so the
    number stays comparable with the prior-only baseline and with
    Sprint 5 numbers. Row weights are fixed per observation (computed
    on the full set); the held-out row's weight drops with it, and
    the RMSE is the weighted mean of squared held-out errors.
    """

    if len(target) < 3:
        return None
    weights = _normalize_weights(len(target), sample_weights)
    squared_errors: list[float] = []
    held_out_weights: list[float] = []
    for position in range(len(target)):
        keep = [i for i in range(len(target)) if i != position]
        coefficients, intercept = _fit_coefficients(
            [features[i] for i in keep],
            [target[i] for i in keep],
            prior,
            ridge_strength,
            clip_nonnegative=clip_nonnegative,
            center_target=center_target,
            sample_weights=[weights[i] for i in keep],
        )
        predicted = intercept + sum(
            coefficient * value for coefficient, value in zip(coefficients, features[position])
        )
        squared_errors.append((predicted - float(target[position])) ** 2)
        held_out_weights.append(weights[position])
    return math.sqrt(
        sum(w * e for w, e in zip(held_out_weights, squared_errors)) / sum(held_out_weights)
    )


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
    center_target: bool = False,
    sample_weights: list[float] | None = None,
) -> list[dict[str, float | int | str]]:
    """Seeded bootstrap percentile intervals for fitted coefficients.

    Each draw resamples row indices with replacement (the shared Sprint 4
    primitive), refits, and records the coefficients; the interval is the
    percentile interval of the bootstrap distribution at ``level``.
    ``estimate`` is the coefficient on the observed rows, not the
    bootstrap median. Deterministic given (inputs, seed). Centered
    fits re-center within each resample (centering is part of the
    fit); row weights travel with their rows into each resample.
    """

    if draws < 1:
        raise ValueError(f"Bootstrap draws must be >= 1; got {draws}.")
    if not 0.0 < level < 1.0:
        raise ValueError(f"Bootstrap level must lie in (0, 1); got {level}.")
    weights = _normalize_weights(len(target), sample_weights)
    estimates, _ = _fit_coefficients(
        features,
        target,
        prior,
        ridge_strength,
        clip_nonnegative=clip_nonnegative,
        center_target=center_target,
        sample_weights=weights,
    )
    distributions: list[list[float]] = [[] for _ in prior]
    for indices in bootstrap_index_draws(len(target), draws, seed):
        refit, _ = _fit_coefficients(
            [features[i] for i in indices],
            [target[i] for i in indices],
            prior,
            ridge_strength,
            clip_nonnegative=clip_nonnegative,
            center_target=center_target,
            sample_weights=[weights[i] for i in indices],
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


def _worst_tail_positions(
    values: list[float], preferred_direction: str, alert_threshold: float
) -> list[int]:
    """Positions of observations on the bad side of the alert threshold.

    For ``increase`` metrics (higher is better) the bad side is below
    the alert line; for ``decrease`` metrics it is above. When no
    observation crossed the line, the worst quartile stands in — the
    critical line still needs a data-driven anchor, and the fallback is
    recorded by the caller via the tail count, not hidden. Positions
    (not values) so per-observation weights stay aligned with the tail.
    """

    if preferred_direction == "increase":
        positions = [i for i, value in enumerate(values) if value < alert_threshold]
        if positions:
            return positions
        ordered = sorted(range(len(values)), key=lambda i: values[i])
        return ordered[: max(1, math.ceil(len(ordered) / 4))]
    if preferred_direction == "decrease":
        positions = [i for i, value in enumerate(values) if value > alert_threshold]
        if positions:
            return positions
        ordered = sorted(range(len(values)), key=lambda i: values[i], reverse=True)
        return ordered[: max(1, math.ceil(len(ordered) / 4))]
    raise ValueError(
        f"preferred_direction must be 'increase' or 'decrease'; got {preferred_direction!r}."
    )


def _worst_tail(
    values: list[float], preferred_direction: str, alert_threshold: float
) -> list[float]:
    positions = _worst_tail_positions(values, preferred_direction, alert_threshold)
    return [values[i] for i in positions]


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation, or None when it is undefined.

    Undefined below 2 pairs or when either side has zero variance —
    recorded as null, never faked with a zero.
    """

    n = len(xs)
    if n < 2:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    syy = sum((y - mean_y) ** 2 for y in ys)
    if sxx <= 0.0 or syy <= 0.0:
        return None
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    return sxy / math.sqrt(sxx * syy)


def pairwise_metric_correlations(
    series: Mapping[str, Mapping[str, float]],
) -> dict[str, Any]:
    """Pairwise Pearson correlations of per-metric observation vectors.

    DIAGNOSTIC ONLY (Sprint 10): threshold fits remain per-metric
    independent location fits — no correlation modeling, no joint
    multivariate fit, and fitted values are untouched by this
    function. Its only job is to record, on the policy fit, whether
    the metrics being fit independently move together, so a reader
    can judge how much the independence assumption costs.

    ``series`` maps metric -> {observation key: value}; pairs use
    pairwise-complete observations (keys present for both metrics),
    so a run missing one metric still contributes to pairs it has.
    Pairs are ordered by (metric_a, metric_b) in sorted metric order
    for determinism. ``warning`` fires when any pair has |r| >=
    :data:`CORRELATION_WARNING_THRESHOLD` with at least
    :data:`CORRELATION_WARNING_MIN_N` paired observations — a
    documented choice, not a universal constant. Warnings are
    recorded, never refusing.
    """

    metrics = sorted(series)
    pairs: list[dict[str, Any]] = []
    warning = False
    warned_pairs: list[str] = []
    for left in range(len(metrics)):
        for right in range(left + 1, len(metrics)):
            metric_a, metric_b = metrics[left], metrics[right]
            keys = sorted(set(series[metric_a]) & set(series[metric_b]))
            xs = [float(series[metric_a][key]) for key in keys]
            ys = [float(series[metric_b][key]) for key in keys]
            if not all(math.isfinite(v) for v in xs + ys):
                raise ValueError("Correlation diagnostics require finite values.")
            r = _pearson(xs, ys)
            pairs.append(
                {
                    "metric_a": metric_a,
                    "metric_b": metric_b,
                    "n": len(keys),
                    "r": r,
                }
            )
            if (
                r is not None
                and len(keys) >= CORRELATION_WARNING_MIN_N
                and abs(r) >= (CORRELATION_WARNING_THRESHOLD)
            ):
                warning = True
                warned_pairs.append(f"{metric_a}/{metric_b}")
    return {
        "method": "pearson_pairwise_complete",
        "pairs": pairs,
        "warning": warning,
        "warned_pairs": warned_pairs,
        "warning_threshold": CORRELATION_WARNING_THRESHOLD,
        "warning_min_n": CORRELATION_WARNING_MIN_N,
    }


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
    observation_weights: Mapping[str, list[float]] | None = None,
    quality_gate: bool = True,
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
    recorded) rather than silently clamped. A one-observation tail
    yields no bootstrap interval for the critical threshold (there is
    no resampling variability to report); the fitted value is still
    recorded and the tail count makes the reason visible.

    Fit-quality gate (Sprint 10, per metric — metrics have different
    scales, so averaging RMSEs across metrics would be meaningless):
    the fitted location fit's LOO RMSE is compared against the
    prior-only predictor (the prior alert threshold constant for
    every observation). A metric whose fitted LOO is worse keeps its
    priors with ``unchanged_reason: quality_gate`` and the rejected
    fit recorded, the same pattern as the ordering guard. The gate is
    evaluated on the alert (location) fit; the critical threshold
    inherits the verdict, since the pair is accepted or rejected
    wholesale. Gate numbers are recorded for every fittable metric
    whether the gate is enabled or not; ``quality_gate_passed`` is
    None when the gate did not evaluate (disabled, or too few
    observations for LOO). The ordering guard takes precedence over
    the gate for ``unchanged_reason`` when both fire. Location fits
    take no centering: the coefficient IS the location (see
    :func:`ridge_location_fit`).

    ``observation_weights`` (per metric, aligned with the observation
    lists) weights the location fits, bootstraps, and gate errors;
    uniform when omitted.
    """

    if not math.isfinite(ridge_strength) or ridge_strength < 0:
        raise ValueError(f"ridge_strength must be finite and >= 0; got {ridge_strength}.")
    fitted_policies: dict[str, dict[str, Any]] = {}
    changes: dict[str, Any] = {}
    for metric, spec in policies.items():
        direction = str(spec["preferred_direction"])
        prior_alert = float(spec["alert_threshold"])
        prior_critical = float(spec["critical_threshold"])
        raw_values = [float(value) for value in observations.get(metric, [])]
        raw_weights = None
        if observation_weights is not None and metric in observation_weights:
            raw_weights = list(observation_weights[metric])
            if len(raw_weights) != len(raw_values):
                raise ValueError(
                    f"Observation weights for metric {metric!r} ({len(raw_weights)}) "
                    f"and observations ({len(raw_values)}) must align."
                )
        # Non-finite values are dropped with their weights, so the
        # weight alignment survives the filter.
        paired = [
            (value, raw_weights[i] if raw_weights is not None else 1.0)
            for i, value in enumerate(raw_values)
            if math.isfinite(value)
        ]
        values = [value for value, _ in paired]
        metric_weights = (
            _normalize_weights(len(values), [weight for _, weight in paired])
            if raw_weights is not None
            else None
        )
        base_change: dict[str, Any] = {
            "metric": metric,
            "preferred_direction": direction,
            "prior_alert_threshold": prior_alert,
            "prior_critical_threshold": prior_critical,
            "n_observations": len(values),
            "n_tail": 0,
            "unchanged_reason": None,
            "fitted_loo_rmse": None,
            "prior_only_rmse": None,
            "quality_gate_passed": None,
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
        tail_positions = _worst_tail_positions(values, direction, prior_alert)
        tail = [values[i] for i in tail_positions]
        tail_weights = (
            [metric_weights[i] for i in tail_positions] if metric_weights is not None else None
        )
        alert_seed = derive_sub_seed(seed, "calibration", metric, "alert")
        critical_seed = derive_sub_seed(seed, "calibration", metric, "critical")
        fitted_alert = ridge_location_fit(
            values, prior_alert, ridge_strength, sample_weights=metric_weights
        )
        fitted_critical = ridge_location_fit(
            tail, prior_critical, ridge_strength, sample_weights=tail_weights
        )
        alert_interval = bootstrap_coefficient_intervals(
            [[1.0] for _ in values],
            values,
            [prior_alert],
            ridge_strength,
            draws=bootstrap_draws,
            seed=alert_seed,
            level=level,
            clip_nonnegative=False,
            sample_weights=metric_weights,
        )[0]
        critical_interval = None
        if len(tail) >= 2:
            critical_interval = bootstrap_coefficient_intervals(
                [[1.0] for _ in tail],
                tail,
                [prior_critical],
                ridge_strength,
                draws=bootstrap_draws,
                seed=critical_seed,
                level=level,
                clip_nonnegative=False,
                sample_weights=tail_weights,
            )[0]
        fitted_loo = leave_one_out_rmse(
            [[1.0] for _ in values],
            values,
            [prior_alert],
            ridge_strength,
            clip_nonnegative=False,
            sample_weights=metric_weights,
        )
        prior_rmse = prior_only_rmse([[1.0] for _ in values], values, [prior_alert], metric_weights)
        gate_passed = None
        if quality_gate and fitted_loo is not None:
            gate_passed = fitted_loo <= prior_rmse
        base_change.update(
            {
                "fitted_alert_threshold": fitted_alert,
                "fitted_critical_threshold": fitted_critical,
                "alert_bootstrap": alert_interval,
                "critical_bootstrap": critical_interval,
                "n_tail": len(tail),
                "fitted_loo_rmse": fitted_loo,
                "prior_only_rmse": prior_rmse,
                "quality_gate_passed": gate_passed,
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
        if gate_passed is False:
            base_change.update(
                {
                    "fitted_alert_threshold": prior_alert,
                    "fitted_critical_threshold": prior_critical,
                    "unchanged_reason": "quality_gate",
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
    center_target: bool = True,
    sample_weights: list[float] | None = None,
) -> dict[str, Any]:
    """Fit calibrated rule weights from observed outcomes.

    Each observation is one completed run: features are per-rule match
    counts across the run's decision records, the target is the run's
    final value of the chosen outcome metric, and the prior is the
    registry's current weight per rule. Coefficients are clipped at
    zero (the reference's rule: weights are non-negative multipliers).
    Rules that never matched keep their prior exactly — an all-zero
    column contributes nothing to ``X'y``, so the penalty term alone
    decides, and it decides for the prior. Centering preserves this
    property (see :func:`fit_centered_ridge_to_prior`).

    By default (``center_target=True``) the fit centers features and
    target and derives an unpenalized intercept carrying the level,
    so the weights carry deviations rather than absorbing a
    level-dominated target. ``center_target=False`` reproduces the
    exact Sprint 5 through-origin fit for reproducibility of old
    fits. The centering mode, intercept, and means used are recorded
    on the result. LOO RMSE is on the original scale in both modes,
    and ``prior_only_rmse`` is the do-nothing baseline (``X . prior``)
    the fit-quality gate compares against.

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
    weights = _normalize_weights(len(outcomes), sample_weights)
    if center_target:
        centered = fit_centered_ridge_to_prior(
            match_counts,
            outcomes,
            priors,
            ridge_strength,
            clip_nonnegative=True,
            sample_weights=weights,
        )
        fitted = centered["coefficients"]
        intercept = centered["intercept"]
        centering: dict[str, Any] = {
            "mode": "centered",
            "center_target": True,
            "intercept": centered["intercept"],
            "target_mean": centered["target_mean"],
            "feature_means": centered["feature_means"],
        }
    else:
        fitted = fit_ridge_to_prior(
            match_counts,
            outcomes,
            priors,
            ridge_strength,
            clip_nonnegative=True,
            sample_weights=weights,
        )
        intercept = 0.0
        centering = {
            "mode": "through_origin",
            "center_target": False,
            "intercept": 0.0,
            "target_mean": None,
            "feature_means": None,
        }
    intervals = bootstrap_coefficient_intervals(
        match_counts,
        outcomes,
        priors,
        ridge_strength,
        draws=bootstrap_draws,
        seed=derive_sub_seed(seed, "calibration", "rule-weights"),
        level=level,
        clip_nonnegative=True,
        center_target=center_target,
        sample_weights=weights,
    )
    loo = leave_one_out_rmse(
        match_counts,
        outcomes,
        priors,
        ridge_strength,
        clip_nonnegative=True,
        center_target=center_target,
        sample_weights=weights,
    )
    prior_rmse = prior_only_rmse(match_counts, outcomes, priors, weights)
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
        "prior_only_rmse": prior_rmse,
        "intercept": intercept,
        "centering": centering,
        "n_observations": len(outcomes),
    }

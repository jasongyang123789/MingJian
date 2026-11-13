"""Pure robustness methods over stored trial values (Sprint 4, PRD delta D6).

All functions here are deterministic given their inputs: no LLM, no I/O,
and the only randomness is bootstrap resampling from an explicitly seeded
``random.Random``. Values are returned at full precision (no rounding);
gate evaluation must see the unrounded statistic.

Method references:

- Expected shortfall ports taylanakgn's ``risk.expected_shortfall``: the
  mean of the worst ``alpha`` fraction of trials, with the tail count
  ``max(1, floor(alpha * n))`` so small ensembles still yield a defined
  (single-trial) tail instead of an empty mean.
- Bootstrap intervals follow jasonrkeen's ``_bootstrap_coefficients``:
  resample with replacement from a seeded RNG, recompute the statistic
  per draw, and report percentile intervals (p05/p50/p95 there; the
  level is configurable here). The interval method is the percentile
  method, stated on every result; BCa is not implemented.
- Threshold search ports taylanakgn's ``sensitivity.threshold_search``:
  bisection over a frozen input, assuming monotonicity, with an honest
  unreachable result when the target is not bracketed by the bounds.
- Decision gates port taylanakgn's ``decision.evaluate``: metric +
  operator + threshold, failing loudly on an uncomputed metric.
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Callable, Generator, Mapping
from typing import TypedDict

from planagent.services.distributions.aggregation import percentile

from .models import GateArm, GateDefinition, GateMetric, GateOperator


class ThresholdSearchOutcome(TypedDict):
    """The result of a bisection threshold search."""

    threshold: float | None
    achieved_statistic: float | None
    reachable: bool
    iterations: int
    evaluations: list[dict[str, float]]

_OPERATORS: Mapping[GateOperator, Callable[[float, float], bool]] = {
    GateOperator.GT: lambda value, threshold: value > threshold,
    GateOperator.GTE: lambda value, threshold: value >= threshold,
    GateOperator.LT: lambda value, threshold: value < threshold,
    GateOperator.LTE: lambda value, threshold: value <= threshold,
}


def expected_shortfall(
    values: list[float], alpha: float = 0.05, tail: str = "lower"
) -> dict[str, float | int]:
    """Mean of the worst ``alpha`` fraction of trials.

    The lower tail (the default) is the mean of the smallest values — the
    losses, for metrics where lower is worse. The upper tail is the mean
    of the largest values, for harm metrics where higher is worse.
    ``threshold`` is the cutoff value (the VaR at the same level): the
    largest value inside the lower tail, or the smallest value inside the
    upper tail. Empty input raises; ``alpha`` must lie in (0, 1].
    """

    if not values:
        raise ValueError("Expected shortfall requires at least one trial value.")
    if not 0.0 < alpha <= 1.0:
        raise ValueError(f"alpha must lie in (0, 1]; got {alpha}.")
    if tail not in ("lower", "upper"):
        raise ValueError(f"tail must be 'lower' or 'upper'; got {tail!r}.")
    ordered = sorted(float(value) for value in values)
    tail_count = max(1, math.floor(alpha * len(ordered)))
    if tail == "lower":
        tail_values = ordered[:tail_count]
        threshold = ordered[tail_count - 1]
    else:
        tail_values = ordered[len(ordered) - tail_count :]
        threshold = ordered[len(ordered) - tail_count]
    return {
        "value": float(statistics.fmean(tail_values)),
        "threshold": float(threshold),
        "tail_count": tail_count,
        "n": len(ordered),
    }


def _statistic_value(statistic: str, values: list[float], loss_threshold: float) -> float:
    if statistic == "mean":
        return float(statistics.fmean(values))
    if statistic == "median":
        return float(statistics.median(values))
    if statistic == "p_loss":
        return sum(1 for value in values if value < loss_threshold) / len(values)
    raise ValueError(f"Unknown bootstrap statistic {statistic!r}.")


def bootstrap_intervals(
    values: list[float],
    statistics: list[str],
    *,
    draws: int,
    seed: int,
    level: float,
    loss_threshold: float = 0.0,
) -> list[dict[str, float | int | str]]:
    """Seeded bootstrap percentile intervals for headline statistics.

    Each draw resamples ``n`` values with replacement from the trial
    values (``random.Random(seed)``) and recomputes every requested
    statistic; the interval is the percentile interval of the bootstrap
    distribution at the requested level. ``estimate`` is the statistic on
    the observed values, not the bootstrap median.
    """

    if not values:
        raise ValueError("Bootstrap intervals require at least one trial value.")
    if draws < 1:
        raise ValueError(f"Bootstrap draws must be >= 1; got {draws}.")
    if not 0.0 < level < 1.0:
        raise ValueError(f"Bootstrap level must lie in (0, 1); got {level}.")
    ordered = sorted(float(value) for value in values)
    estimates: dict[str, list[float]] = {name: [] for name in statistics}
    rng = random.Random(seed)
    for _ in range(draws):
        resample = rng.choices(ordered, k=len(ordered))
        for name in statistics:
            estimates[name].append(_statistic_value(name, resample, loss_threshold))
    tail = (1.0 - level) / 2.0
    results: list[dict[str, float | int | str]] = []
    for name in statistics:
        distribution = sorted(estimates[name])
        results.append(
            {
                "statistic": name,
                "estimate": _statistic_value(name, ordered, loss_threshold),
                "low": percentile(distribution, tail),
                "high": percentile(distribution, 1.0 - tail),
                "draws": draws,
                "seed": seed,
                "level": level,
                "method": "percentile",
            }
        )
    return results


def bisect_threshold_search(
    *,
    target: float,
    bounds: tuple[float, float],
    direction: str,
    tolerance: float,
    max_iterations: int,
) -> Generator[float, float, ThresholdSearchOutcome]:
    """Generator-based bisection search for a statistic's crossing point.

    The generator owns all search logic; the caller supplies statistics.
    Drive it by sending each yielded probe value's statistic back in::

        search = bisect_threshold_search(...)
        value = next(search)
        while True:
            try:
                value = search.send(statistic_at(value))
            except StopIteration as done:
                result = done.value
                break

    The generator yields both bounds first; when the target is not
    bracketed (in the stated ``direction``), it returns ``reachable=False``
    with ``threshold=None`` instead of inventing a value. Otherwise it
    bisects until the interval is narrower than ``tolerance`` or
    ``max_iterations`` steps run out, then yields the reported threshold
    once so ``achieved_statistic`` is the statistic at that exact value.
    Monotonicity in the stated direction is assumed (as in the reference);
    a non-monotone statistic can converge to a crossing that is not the
    only one, and the evaluation trail records every probe so the search
    stays auditable.

    The generator form exists because probe evaluations are async service
    calls (they execute simulation runs); a synchronous caller can use
    :func:`bisect_threshold` instead.
    """

    if direction not in ("increasing", "decreasing"):
        raise ValueError(f"direction must be 'increasing' or 'decreasing'; got {direction!r}.")
    if tolerance <= 0:
        raise ValueError(f"tolerance must be positive; got {tolerance}.")
    if max_iterations < 1:
        raise ValueError(f"max_iterations must be >= 1; got {max_iterations}.")
    low, high = bounds
    if not low < high:
        raise ValueError(f"bounds must satisfy low < high; got {bounds}.")

    def oriented(statistic: float) -> float:
        return statistic if direction == "increasing" else -statistic

    evaluations: list[dict[str, float]] = []
    stat_low = yield low
    evaluations.append({"value": low, "statistic": stat_low})
    stat_high = yield high
    evaluations.append({"value": high, "statistic": stat_high})
    oriented_target = oriented(target)
    if not oriented(stat_low) <= oriented_target <= oriented(stat_high):
        return {
            "threshold": None,
            "achieved_statistic": None,
            "reachable": False,
            "iterations": 0,
            "evaluations": evaluations,
        }

    iterations = 0
    for _ in range(max_iterations):
        if high - low <= tolerance:
            break
        iterations += 1
        midpoint = (low + high) / 2.0
        stat_mid = yield midpoint
        evaluations.append({"value": midpoint, "statistic": stat_mid})
        if oriented(stat_mid) < oriented_target:
            low = midpoint
        else:
            high = midpoint
    threshold = (low + high) / 2.0
    achieved = yield threshold
    evaluations.append({"value": threshold, "statistic": achieved})
    return {
        "threshold": threshold,
        "achieved_statistic": achieved,
        "reachable": True,
        "iterations": iterations,
        "evaluations": evaluations,
    }


def bisect_threshold(
    statistic_at: Callable[[float], float],
    *,
    target: float,
    bounds: tuple[float, float],
    direction: str,
    tolerance: float,
    max_iterations: int,
) -> ThresholdSearchOutcome:
    """Synchronous driver for :func:`bisect_threshold_search`."""

    search = bisect_threshold_search(
        target=target,
        bounds=bounds,
        direction=direction,
        tolerance=tolerance,
        max_iterations=max_iterations,
    )
    value = next(search)
    while True:
        try:
            value = search.send(statistic_at(value))
        except StopIteration as done:
            return done.value


def _raw_arm_summary(values: list[float], loss_threshold: float) -> dict[str, float]:
    """Unrounded per-arm statistics for gate evaluation.

    Gates must see the raw statistic, not the 4-decimal rounded summary
    the API reports elsewhere: rounding could flip a gate at the boundary.
    """

    ordered = sorted(float(value) for value in values)
    count = len(ordered)
    if count == 0:
        raise ValueError("Gate evaluation requires at least one trial value.")
    return {
        "mean": float(statistics.fmean(ordered)),
        "p10": percentile(ordered, 0.10),
        "p50": percentile(ordered, 0.50),
        "p90": percentile(ordered, 0.90),
        "min": float(ordered[0]),
        "max": float(ordered[-1]),
        "stddev": float(statistics.pstdev(ordered)) if count > 1 else 0.0,
        "p_loss": sum(1 for value in ordered if value < loss_threshold) / count,
    }


def _raw_paired_summary(
    baseline_values: list[float], strategy_values: list[float]
) -> dict[str, float]:
    """Unrounded paired statistics for gate evaluation (same definitions as
    :func:`paired_delta_stats`, without its 4-decimal rounding)."""

    if len(baseline_values) != len(strategy_values):
        raise ValueError(
            f"Paired comparison requires equal trial counts; got {len(baseline_values)} "
            f"baseline and {len(strategy_values)} strategy values."
        )
    deltas = [float(s) - float(b) for b, s in zip(baseline_values, strategy_values)]
    if not deltas:
        raise ValueError("Gate evaluation requires at least one trial value.")
    return {
        "mean_delta": float(statistics.fmean(deltas)),
        "p_strategy_better": sum(1 for delta in deltas if delta > 0) / len(deltas),
    }


def gate_observed_value(
    definition: GateDefinition,
    baseline_values: list[float],
    strategy_values: list[float],
    loss_threshold: float,
) -> float:
    """The observed statistic for one gate definition.

    Arm metrics read one arm's trial values; paired metrics read the
    paired deltas. Statistics are unrounded (see :func:`_raw_arm_summary`
    and :func:`_raw_paired_summary`): rounding could flip a gate at the
    boundary, and the evaluation record carries the observed value so the
    verdict stays checkable. Failing loudly on an uncomputed metric is
    deliberate (the reference's rule): silently skipping a gate would
    produce a verdict that looks complete and is not.
    """

    if definition.arm is GateArm.PAIRED:
        paired = _raw_paired_summary(baseline_values, strategy_values)
        if definition.metric is GateMetric.MEAN_DELTA:
            return paired["mean_delta"]
        if definition.metric is GateMetric.P_STRATEGY_BETTER:
            return paired["p_strategy_better"]
        raise ValueError(f"Metric {definition.metric.value!r} is not a paired statistic.")
    values = baseline_values if definition.arm is GateArm.BASELINE else strategy_values
    if definition.metric is GateMetric.EXPECTED_SHORTFALL:
        result = expected_shortfall(values, definition.alpha, "lower")
        return float(result["value"])
    summary = _raw_arm_summary(values, loss_threshold)
    if definition.metric.value in summary:
        return summary[definition.metric.value]
    raise ValueError(f"Metric {definition.metric.value!r} is not an arm statistic.")


def apply_gate_operator(operator: GateOperator, value: float, threshold: float) -> bool:
    """Apply a gate comparison operator."""

    return bool(_OPERATORS[operator](value, threshold))


def tornado_swing(outcome_low: float, outcome_high: float) -> float:
    """The tornado bar length: the absolute outcome swing."""

    return abs(float(outcome_high) - float(outcome_low))

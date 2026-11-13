"""Distribution aggregation for Monte Carlo results (Sprint 3).

Percentiles use linear interpolation, matching the v0.1 prototype's
``percentile()`` semantics. The summary shape follows scenario-lab's
ensemble statistics (mean/p10/p50/p90/stddev) plus the prototype's loss
probability. Sprint 4 adds expected shortfall, tornado sensitivity,
threshold search, and bootstrap intervals on top of these summaries;
nothing in this module anticipates them beyond keeping the per-trial
values available to the caller.
"""

from __future__ import annotations

import statistics

#: Reported statistics are rounded to the engine's state precision.
ROUND_DECIMALS = 4


def _round(value: float) -> float:
    return round(float(value), ROUND_DECIMALS)


def percentile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolation percentile, ``q`` in [0, 1].

    Empty input yields 0.0 (same convention as the prototype).
    """

    if not sorted_values:
        return 0.0
    if q <= 0:
        return float(sorted_values[0])
    if q >= 1:
        return float(sorted_values[-1])
    position = q * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - lower
    return float(sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction)


def summarize_samples(values: list[float], loss_threshold: float = 0.0) -> dict[str, float]:
    """Distribution summary for one arm's per-trial metric values.

    ``p_loss`` is the fraction of trials whose value falls below
    ``loss_threshold`` (the prototype's loss-probability definition, with
    the threshold made explicit: 0.0 by default).
    """

    ordered = sorted(float(value) for value in values)
    count = len(ordered)
    if count == 0:
        return {
            "n": 0,
            "mean": 0.0,
            "min": 0.0,
            "max": 0.0,
            "p10": 0.0,
            "p50": 0.0,
            "p90": 0.0,
            "stddev": 0.0,
            "p_loss": 0.0,
        }
    return {
        "n": count,
        "mean": _round(statistics.fmean(ordered)),
        "min": _round(ordered[0]),
        "max": _round(ordered[-1]),
        "p10": _round(percentile(ordered, 0.10)),
        "p50": _round(percentile(ordered, 0.50)),
        "p90": _round(percentile(ordered, 0.90)),
        "stddev": _round(statistics.pstdev(ordered)) if count > 1 else 0.0,
        "p_loss": _round(sum(1 for value in ordered if value < loss_threshold) / count),
    }


def paired_delta_stats(baseline_values: list[float], strategy_values: list[float]) -> dict[str, float]:
    """Paired comparison between baseline and strategy trial values.

    Trials are paired by index (same seed, shared draws); the delta
    distribution is what the strategy changes, trial by trial.
    ``p_strategy_better`` is the fraction of pairs where the strategy
    value strictly exceeds the baseline value.
    """

    if len(baseline_values) != len(strategy_values):
        raise ValueError(
            f"Paired comparison requires equal trial counts; got {len(baseline_values)} "
            f"baseline and {len(strategy_values)} strategy values."
        )
    deltas = sorted(float(s) - float(b) for b, s in zip(baseline_values, strategy_values))
    count = len(deltas)
    if count == 0:
        return {
            "n": 0,
            "mean_delta": 0.0,
            "p10": 0.0,
            "p50": 0.0,
            "p90": 0.0,
            "p_strategy_better": 0.0,
        }
    return {
        "n": count,
        "mean_delta": _round(statistics.fmean(deltas)),
        "p10": _round(percentile(deltas, 0.10)),
        "p50": _round(percentile(deltas, 0.50)),
        "p90": _round(percentile(deltas, 0.90)),
        "p_strategy_better": _round(sum(1 for delta in deltas if delta > 0) / count),
    }

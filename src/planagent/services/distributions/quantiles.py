"""Distribution quantiles for sensitivity analysis (Sprint 4).

The tornado swings each input from its own P10 to its own P90 with the
others held at their median (the taylanakgn reference's approach: ranges,
not arbitrary percentages, so bars stay comparable). Quantiles are analytic
where the standard library allows it:

- ``fixed``: the value itself;
- ``normal``: ``statistics.NormalDist`` inverse CDF;
- ``triangular``: the analytic inverse CDF (piecewise quadratic);
- ``bernoulli``: ``0`` below ``1 - p``, else ``1`` (the reference's
  convention);
- ``beta_pert``: seeded empirical quantiles — the standard library has no
  beta inverse CDF, so a fixed number of draws from a seeded RNG are sorted
  and interpolated with the aggregation percentile. Deterministic given the
  seed; the draw count is part of the method and is recorded by callers.
"""

from __future__ import annotations

import math
import random
import statistics

from planagent.services.variables.models import DistributionType, VariableDistribution

from .aggregation import percentile

#: Draws for the beta_pert empirical quantile. Large enough that the P10/P90
#: estimates are stable to ~1e-3 of the range for typical shapes; the seed
#: makes them exactly reproducible.
BETA_PERT_QUANTILE_DRAWS = 8192


def _triangular_quantile(low: float, mode: float, high: float, q: float) -> float:
    span = high - low
    mode_fraction = (mode - low) / span
    if q < mode_fraction:
        return low + math.sqrt(q * span * (mode - low))
    return high - math.sqrt((1.0 - q) * span * (high - mode))


def _beta_pert_quantile(
    low: float, mode: float, high: float, q: float, seed: int
) -> float:
    ratio = (mode - low) / (high - low)
    alpha = 1.0 + 4.0 * ratio
    beta = 1.0 + 4.0 * (1.0 - ratio)
    rng = random.Random(seed)
    draws = sorted(low + (high - low) * rng.betavariate(alpha, beta) for _ in range(BETA_PERT_QUANTILE_DRAWS))
    return percentile(draws, q)


def distribution_quantile(
    distribution: VariableDistribution,
    q: float,
    *,
    seed: int = 0,
) -> float:
    """The ``q``-th quantile of a variable distribution, ``q`` in (0, 1).

    ``seed`` is used only for the beta_pert empirical quantile; the
    analytic distributions ignore it. Raises :class:`ValueError` for a
    quantile outside (0, 1) or a distribution missing its parameters
    (validated sets always carry them).
    """

    if not 0.0 < q < 1.0:
        raise ValueError(f"Quantile q must lie in (0, 1); got {q}.")
    params = distribution
    if distribution.type is DistributionType.FIXED:
        if params.value is None:
            raise ValueError("Fixed distribution requires a value.")
        return float(params.value)
    if distribution.type is DistributionType.NORMAL:
        if params.mean is None or params.std is None:
            raise ValueError("Normal distribution requires mean and std.")
        return float(statistics.NormalDist(params.mean, params.std).inv_cdf(q))
    if distribution.type is DistributionType.TRIANGULAR:
        if params.min is None or params.mode is None or params.max is None:
            raise ValueError("Triangular distribution requires min, mode, and max.")
        return _triangular_quantile(params.min, params.mode, params.max, q)
    if distribution.type is DistributionType.BETA_PERT:
        if params.min is None or params.mode is None or params.max is None:
            raise ValueError("Beta_pert distribution requires min, mode, and max.")
        return _beta_pert_quantile(params.min, params.mode, params.max, q, seed)
    if distribution.type is DistributionType.BERNOULLI:
        if params.p is None:
            raise ValueError("Bernoulli distribution requires p.")
        return 0.0 if q < 1.0 - params.p else 1.0
    raise ValueError(f"Unsupported distribution type: {distribution.type!r}.")


def distribution_median(distribution: VariableDistribution, *, seed: int = 0) -> float:
    """The median (P50) of a distribution — the tornado's base value."""

    return distribution_quantile(distribution, 0.5, seed=seed)

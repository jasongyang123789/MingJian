"""Seeded sampling over validated variable sets (Sprint 3, PRD delta D4).

The Sprint 2 validator's distribution vocabulary is the contract: this
module accepts exactly the variable sets the validator accepts — every
sampling entry point re-validates and raises on any issue — and samples
with stdlib :class:`random.Random` (MT19937). No numpy dependency is
introduced; the SimplifySimulation reference uses numpy PCG64, so raw
draw streams differ from that implementation by design, but the contract
(distribution vocabulary, bounds rules, paired-draw sharing) is the same.

Draw order is set order, one draw per variable. Strategy levers replace
drawn values AFTER the draw is consumed, so a baseline trial and its
strategy pair — same seed, same set — share identical draws for every
non-levered variable (the SimplifySimulation paired pattern). Sampling a
variable set twice from two RNGs built from the same seed yields identical
vectors; that is the seed contract the golden-run and replay tests rely
on.

Beta-PERT follows the reference parameterization: ``alpha = 1 + 4r``,
``beta = 1 + 4(1 - r)`` with ``r = (mode - min) / (max - min)``, scaled
into ``[min, max]``.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping
from typing import Any

from planagent.services.variables.models import DistributionType, VariableSet
from planagent.services.variables.validator import validate_variable_set

#: Configuration key holding the Monte Carlo fragment on a trial run.
MONTE_CARLO_CONFIGURATION_KEY = "monte_carlo"

#: Configuration key holding the variables fragment on a run.
VARIABLES_CONFIGURATION_KEY = "variables"


def rng_for_seed(seed: int) -> random.Random:
    """The seeded RNG for a run. Every stochastic draw in the simulation
    path comes from an RNG built here (or from a sub-seed derived from
    it); the tick loop itself has no stochasticity (see SPRINT3.md §2)."""

    return random.Random(seed)


def _sample_one(
    distribution_type: DistributionType, params: Mapping[str, Any], rng: random.Random
) -> float:
    if distribution_type is DistributionType.FIXED:
        return float(params["value"])
    if distribution_type is DistributionType.NORMAL:
        return float(rng.gauss(params["mean"], params["std"]))
    if distribution_type is DistributionType.TRIANGULAR:
        return float(rng.triangular(params["min"], params["max"], params["mode"]))
    if distribution_type is DistributionType.BETA_PERT:
        low, mode, high = params["min"], params["mode"], params["max"]
        ratio = (mode - low) / (high - low)
        alpha = 1.0 + 4.0 * ratio
        beta = 1.0 + 4.0 * (1.0 - ratio)
        return float(low + (high - low) * rng.betavariate(alpha, beta))
    if distribution_type is DistributionType.BERNOULLI:
        return 1.0 if rng.random() < params["p"] else 0.0
    raise ValueError(f"Unsupported distribution type: {distribution_type!r}.")


def sample_variable_set(
    variable_set: VariableSet,
    rng: random.Random,
    levers: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """Sample one value per variable, in set order.

    Raises :class:`ValueError` when the set fails validation (the
    validator's verdict is the contract: anything it rejects is rejected
    here too) or when a lever value is not finite. Lever values replace
    the drawn value for their variable id, after the draw is consumed, so
    paired runs on shared seeds keep identical streams for non-levered
    variables. Lever ids that name no variable in the set are ignored.
    """

    result = validate_variable_set(variable_set)
    if not result.is_valid:
        details = "; ".join(
            f"{issue.kind}({issue.variable}): {issue.message}" for issue in result.issues
        )
        raise ValueError(f"Variable set failed validation; refusing to sample: {details}")

    lever_values = dict(levers or {})
    for lever_id, lever_value in lever_values.items():
        if isinstance(lever_value, bool) or not isinstance(lever_value, (int, float)):
            raise TypeError(f"Lever {lever_id!r} must be a finite number.")
        if not math.isfinite(float(lever_value)):
            raise ValueError(f"Lever {lever_id!r} must be a finite number.")

    sampled: dict[str, float] = {}
    for variable in variable_set.variables:
        distribution = variable.distribution
        params = {
            "value": distribution.value,
            "mean": distribution.mean,
            "std": distribution.std,
            "min": distribution.min,
            "mode": distribution.mode,
            "max": distribution.max,
            "p": distribution.p,
        }
        sampled[variable.id] = _sample_one(distribution.type, params, rng)
    for lever_id, lever_value in lever_values.items():
        if lever_id in sampled:
            sampled[lever_id] = float(lever_value)
    return sampled


def resolve_run_samples(
    configuration: Mapping[str, Any] | None,
    seed: int,
    state_keys: set[str],
) -> tuple[dict[str, float], dict[str, float]]:
    """Sample a run's bound variables from its seed.

    Reads the ``variables`` fragment (bindings) and the ``monte_carlo``
    fragment (strategy levers, trial runs only) from the run's
    configuration. Returns ``(sampled, applied)``: every sampled value,
    and the subset whose variable id matches a state field (those are the
    values the executor applies to the initial state). Runs without
    bindings sample nothing.
    """

    if not isinstance(configuration, Mapping):
        return {}, {}
    fragment = configuration.get(VARIABLES_CONFIGURATION_KEY)
    if not isinstance(fragment, Mapping):
        return {}, {}
    bindings = fragment.get("bindings")
    if not isinstance(bindings, Mapping):
        return {}, {}
    variable_set = VariableSet.model_validate(bindings)
    if not variable_set.variables:
        return {}, {}

    levers: dict[str, float] = {}
    monte_carlo = configuration.get(MONTE_CARLO_CONFIGURATION_KEY)
    if isinstance(monte_carlo, Mapping) and isinstance(monte_carlo.get("levers"), Mapping):
        levers = dict(monte_carlo["levers"])

    sampled = sample_variable_set(variable_set, rng_for_seed(seed), levers)
    applied = {key: value for key, value in sampled.items() if key in state_keys}
    return sampled, applied

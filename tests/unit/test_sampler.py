"""Unit tests for the seeded sampler (Sprint 3).

Covers every distribution's sampling behavior, seed reproducibility (with
pinned golden draws), paired-seed draw sharing with levers, the
validator-contract rejection, and run-level sample resolution (bindings
+ levers + state-field application).
"""

from __future__ import annotations

import pytest

from planagent.services.distributions import (
    resolve_run_samples,
    rng_for_seed,
    sample_variable_set,
)
from planagent.services.variables.models import (
    VariableDefinition,
    VariableDistribution,
    VariableSet,
)


def _variable(var_id: str, distribution: VariableDistribution) -> VariableDefinition:
    return VariableDefinition(
        id=var_id, unit="x", distribution=distribution, evidence_ref="estimate: test"
    )


GOLDEN_SET = VariableSet(
    name="golden",
    variables=[
        _variable("tri", VariableDistribution(type="triangular", min=24, mode=36, max=60)),
        _variable("nrm", VariableDistribution(type="normal", mean=12, std=3)),
        _variable("pert", VariableDistribution(type="beta_pert", min=5, mode=12, max=25)),
        _variable("bern", VariableDistribution(type="bernoulli", p=0.35)),
        _variable("fix", VariableDistribution(type="fixed", value=42.5)),
    ],
)

# Pinned draws from random.Random(42) / random.Random(7), in set order.
# Any change to the sampler, draw order, or RNG breaks these on purpose.
GOLDEN_DRAWS_42 = {
    "tri": 42.34963892345574,
    "nrm": 14.376434222849372,
    "pert": 9.144163688773189,
    "bern": 1.0,
    "fix": 42.5,
}
GOLDEN_DRAWS_7 = {
    "tri": 35.827753565573055,
    "nrm": 14.539555877446718,
    "pert": 8.671464648432838,
    "bern": 0.0,
    "fix": 42.5,
}


def test_golden_draws_are_pinned_per_seed() -> None:
    assert sample_variable_set(GOLDEN_SET, rng_for_seed(42)) == GOLDEN_DRAWS_42
    assert sample_variable_set(GOLDEN_SET, rng_for_seed(7)) == GOLDEN_DRAWS_7


def test_same_seed_reproduces_and_different_seed_differs() -> None:
    first = sample_variable_set(GOLDEN_SET, rng_for_seed(123))
    second = sample_variable_set(GOLDEN_SET, rng_for_seed(123))
    assert first == second
    assert sample_variable_set(GOLDEN_SET, rng_for_seed(124)) != first


def test_fixed_returns_its_value_exactly() -> None:
    only_fixed = VariableSet(
        variables=[_variable("f", VariableDistribution(type="fixed", value=-3.25))]
    )
    assert sample_variable_set(only_fixed, rng_for_seed(1)) == {"f": -3.25}


def test_triangular_and_beta_pert_stay_within_bounds() -> None:
    bounded = VariableSet(
        variables=[
            _variable("tri", VariableDistribution(type="triangular", min=10, mode=12, max=20)),
            _variable("pert", VariableDistribution(type="beta_pert", min=10, mode=12, max=20)),
        ]
    )
    rng = rng_for_seed(99)
    for _ in range(200):
        drawn = sample_variable_set(bounded, rng)
        assert 10 <= drawn["tri"] <= 20
        assert 10 <= drawn["pert"] <= 20


def test_normal_draws_center_near_mean_over_many_samples() -> None:
    normal = VariableSet(
        variables=[_variable("n", VariableDistribution(type="normal", mean=50, std=2))]
    )
    rng = rng_for_seed(5)
    draws = [sample_variable_set(normal, rng)["n"] for _ in range(500)]
    assert 49.0 < sum(draws) / len(draws) < 51.0


def test_bernoulli_draws_are_zero_or_one_and_edges_are_exact() -> None:
    middle = VariableSet(variables=[_variable("b", VariableDistribution(type="bernoulli", p=0.5))])
    rng = rng_for_seed(3)
    draws = {sample_variable_set(middle, rng)["b"] for _ in range(50)}
    assert draws <= {0.0, 1.0}
    assert draws == {0.0, 1.0}
    never = VariableSet(variables=[_variable("b", VariableDistribution(type="bernoulli", p=0.0))])
    always = VariableSet(variables=[_variable("b", VariableDistribution(type="bernoulli", p=1.0))])
    assert sample_variable_set(never, rng_for_seed(3)) == {"b": 0.0}
    assert sample_variable_set(always, rng_for_seed(3)) == {"b": 1.0}


def test_levers_replace_draws_after_consumption_so_pairs_share_streams() -> None:
    baseline = sample_variable_set(GOLDEN_SET, rng_for_seed(42))
    levered = sample_variable_set(GOLDEN_SET, rng_for_seed(42), {"nrm": 99.0, "bern": 0.0})
    # Levered variables take the lever values...
    assert levered["nrm"] == 99.0
    assert levered["bern"] == 0.0
    # ...while every non-levered variable keeps the identical shared draw,
    # including variables drawn AFTER a levered one (stream consumption
    # is identical because the levered draw is still consumed).
    for var_id in ("tri", "pert", "fix"):
        assert levered[var_id] == baseline[var_id]


def test_levers_for_unknown_ids_are_ignored_and_non_finite_rejected() -> None:
    drawn = sample_variable_set(GOLDEN_SET, rng_for_seed(42), {"nope": 1.0})
    assert drawn == GOLDEN_DRAWS_42
    with pytest.raises(ValueError, match="finite"):
        sample_variable_set(GOLDEN_SET, rng_for_seed(42), {"tri": float("inf")})


def test_sampler_rejects_anything_the_validator_rejects() -> None:
    invalid_cases = [
        VariableSet(variables=[]),  # empty set
        VariableSet(
            variables=[
                _variable("t", VariableDistribution(type="triangular", min=20, mode=12, max=10))
            ]
        ),  # invalid bounds
        VariableSet(
            variables=[
                _variable("t", VariableDistribution(type="triangular", min=10, mode=10, max=10))
            ]
        ),  # degenerate bounds
        VariableSet(
            variables=[_variable("n", VariableDistribution(type="normal", mean=0, std=0))]
        ),  # invalid std
        VariableSet(
            variables=[_variable("b", VariableDistribution(type="bernoulli", p=1.5))]
        ),  # invalid probability
        VariableSet(
            variables=[_variable("f", VariableDistribution(type="fixed"))]
        ),  # missing parameter
        VariableSet(
            variables=[
                VariableDefinition(
                    id="u",
                    unit="",
                    distribution=VariableDistribution(type="fixed", value=1),
                    evidence_ref="estimate: x",
                )
            ]
        ),  # missing unit
        VariableSet(
            variables=[
                _variable("d", VariableDistribution(type="fixed", value=1)),
                _variable("d", VariableDistribution(type="fixed", value=2)),
            ]
        ),  # duplicate id
    ]
    for variable_set in invalid_cases:
        with pytest.raises(ValueError, match="validation"):
            sample_variable_set(variable_set, rng_for_seed(1))


def test_draw_order_matters_and_is_set_order() -> None:
    one = VariableSet(
        variables=[
            _variable("a", VariableDistribution(type="triangular", min=0, mode=5, max=10)),
            _variable("b", VariableDistribution(type="triangular", min=0, mode=5, max=10)),
        ]
    )
    swapped = VariableSet(variables=list(reversed(one.variables)))
    assert sample_variable_set(one, rng_for_seed(1)) != sample_variable_set(
        swapped, rng_for_seed(1)
    )


def test_resolve_run_samples_without_bindings_samples_nothing() -> None:
    assert resolve_run_samples({}, 7, {"cash"}) == ({}, {})
    assert resolve_run_samples({"variables": {"template": None}}, 7, {"cash"}) == ({}, {})
    assert resolve_run_samples(None, 7, {"cash"}) == ({}, {})


def test_resolve_run_samples_applies_only_state_field_matches() -> None:
    configuration = {
        "variables": {
            "bindings": {
                "name": "case",
                "variables": [
                    {
                        "id": "cash",
                        "unit": "k",
                        "distribution": {
                            "type": "triangular",
                            "min": 60,
                            "mode": 100,
                            "max": 140,
                        },
                        "evidence_ref": "estimate: test",
                    },
                    {
                        "id": "cac",
                        "unit": "yuan",
                        "distribution": {
                            "type": "triangular",
                            "min": 8000,
                            "mode": 12000,
                            "max": 20000,
                        },
                        "evidence_ref": "estimate: test",
                    },
                ],
            }
        }
    }
    sampled, applied = resolve_run_samples(configuration, 42, {"cash", "pipeline"})
    assert set(sampled) == {"cash", "cac"}
    assert set(applied) == {"cash"}
    assert applied["cash"] == sampled["cash"]
    # Same seed reproduces; the draw equals a direct sampler call.
    expected = sample_variable_set(
        VariableSet.model_validate(configuration["variables"]["bindings"]),
        rng_for_seed(42),
    )
    assert sampled == expected


def test_resolve_run_samples_reads_trial_levers_from_configuration() -> None:
    configuration = {
        "variables": {
            "bindings": {
                "name": "case",
                "variables": [
                    {
                        "id": "cash",
                        "unit": "k",
                        "distribution": {
                            "type": "triangular",
                            "min": 60,
                            "mode": 100,
                            "max": 140,
                        },
                        "evidence_ref": "estimate: test",
                    }
                ],
            }
        },
        "monte_carlo": {"levers": {"cash": 55.0}},
    }
    sampled, applied = resolve_run_samples(configuration, 42, {"cash"})
    assert sampled == {"cash": 55.0}
    assert applied == {"cash": 55.0}

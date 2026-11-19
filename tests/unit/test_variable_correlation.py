"""Tests for variable correlation (Phase 2, Track 3).

Covers the correlation spec format and its validator rules, the
Gaussian-copula sampler (a correlated pair produces approximately the
specified correlation, per marginal type), seeded determinism/replay,
paired lever behaviour under correlation, and the default-independent
contract (no spec = byte-identical golden draws, so existing behaviour
is unchanged).
"""

from __future__ import annotations

import math

import pytest

from planagent.services.distributions import resolve_run_values, rng_for_seed, sample_variable_set
from planagent.services.variables.models import (
    VariableCorrelation,
    VariableDefinition,
    VariableDistribution,
    VariableSet,
)
from planagent.services.variables.validator import (
    merge_variable_sets,
    validate_variable_set,
)
from tests.unit.test_sampler import GOLDEN_DRAWS_7, GOLDEN_DRAWS_42, GOLDEN_SET


def _variable(var_id: str, distribution: VariableDistribution) -> VariableDefinition:
    return VariableDefinition(
        id=var_id, unit="x", distribution=distribution, evidence_ref="estimate: test"
    )


def _normal(var_id: str, mean: float = 0.0, std: float = 1.0) -> VariableDefinition:
    return _variable(var_id, VariableDistribution(type="normal", mean=mean, std=std))


def _pair(rho: float, **kwargs) -> VariableSet:
    first = _normal("a", **kwargs)
    second = _normal("b", **kwargs)
    return VariableSet(
        variables=[first, second],
        correlations=[VariableCorrelation(variable_a="a", variable_b="b", correlation=rho)],
    )


def _pearson(xs: list[float], ys: list[float]) -> float:
    count = len(xs)
    mean_x = sum(xs) / count
    mean_y = sum(ys) / count
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    variance_x = sum((x - mean_x) ** 2 for x in xs)
    variance_y = sum((y - mean_y) ** 2 for y in ys)
    return covariance / math.sqrt(variance_x * variance_y)


def _sample_pair(
    variable_set: VariableSet, seed: int, trials: int = 2000
) -> tuple[list[float], list[float]]:
    rng = rng_for_seed(seed)
    xs: list[float] = []
    ys: list[float] = []
    for _ in range(trials):
        drawn = sample_variable_set(variable_set, rng)
        xs.append(drawn["a"])
        ys.append(drawn["b"])
    return xs, ys


# --- Spec validation -------------------------------------------------------


def test_valid_spec_passes_validation() -> None:
    result = validate_variable_set(_pair(0.8))
    assert result.is_valid
    assert any(check.check == "correlations" and check.status == "pass" for check in result.checks)


def test_empty_spec_passes_with_no_correlation_check_record() -> None:
    plain = VariableSet(variables=[_normal("a"), _normal("b")])
    result = validate_variable_set(plain)
    assert result.is_valid
    assert not any(check.check == "correlations" for check in result.checks)


@pytest.mark.parametrize(
    "correlations, kind",
    [
        (
            [VariableCorrelation(variable_a="a", variable_b="zzz", correlation=0.5)],
            "correlation_unknown_variable",
        ),
        (
            [VariableCorrelation(variable_a="a", variable_b="a", correlation=0.5)],
            "correlation_self_pair",
        ),
        (
            [VariableCorrelation(variable_a="a", variable_b="b", correlation=1.5)],
            "correlation_out_of_range",
        ),
        (
            [VariableCorrelation(variable_a="a", variable_b="b", correlation=-1.2)],
            "correlation_out_of_range",
        ),
        (
            [
                VariableCorrelation(variable_a="a", variable_b="b", correlation=0.5),
                VariableCorrelation(variable_a="b", variable_b="a", correlation=0.5),
            ],
            "correlation_duplicate_pair",
        ),
    ],
)
def test_invalid_specs_are_rejected(correlations: list[VariableCorrelation], kind: str) -> None:
    variable_set = VariableSet(variables=[_normal("a"), _normal("b")], correlations=correlations)
    result = validate_variable_set(variable_set)
    assert not result.is_valid
    assert any(issue.kind == kind for issue in result.issues)


def test_correlation_with_fixed_variable_is_rejected() -> None:
    variable_set = VariableSet(
        variables=[
            _variable("f", VariableDistribution(type="fixed", value=3.0)),
            _normal("b"),
        ],
        correlations=[VariableCorrelation(variable_a="f", variable_b="b", correlation=0.5)],
    )
    result = validate_variable_set(variable_set)
    assert not result.is_valid
    assert any(issue.kind == "correlation_with_fixed" for issue in result.issues)


def test_inconsistent_matrix_is_rejected() -> None:
    # Pairwise +0.9, +0.9, -0.9 cannot all hold at once: the matrix is
    # not positive semidefinite.
    variable_set = VariableSet(
        variables=[_normal("a"), _normal("b"), _normal("c")],
        correlations=[
            VariableCorrelation(variable_a="a", variable_b="b", correlation=0.9),
            VariableCorrelation(variable_a="a", variable_b="c", correlation=0.9),
            VariableCorrelation(variable_a="b", variable_b="c", correlation=-0.9),
        ],
    )
    result = validate_variable_set(variable_set)
    assert not result.is_valid
    assert any(
        issue.kind == "correlation_matrix_not_positive_semidefinite" for issue in result.issues
    )


def test_sampler_refuses_invalid_spec() -> None:
    variable_set = VariableSet(
        variables=[_normal("a"), _normal("b")],
        correlations=[VariableCorrelation(variable_a="a", variable_b="b", correlation=2.0)],
    )
    with pytest.raises(ValueError, match="validation"):
        sample_variable_set(variable_set, rng_for_seed(1))


# --- Achieved correlation --------------------------------------------------


def test_correlated_normal_pair_achieves_specified_correlation() -> None:
    xs, ys = _sample_pair(_pair(0.8), seed=42)
    measured = _pearson(xs, ys)
    assert abs(measured - 0.8) < 0.05, measured


def test_negative_correlation_is_achieved() -> None:
    xs, ys = _sample_pair(_pair(-0.6), seed=11)
    measured = _pearson(xs, ys)
    assert abs(measured - (-0.6)) < 0.05, measured


def test_perfect_correlation_draws_identical_uniforms() -> None:
    xs, ys = _sample_pair(_pair(1.0), seed=5)
    assert xs == ys


def test_triangular_pair_is_approximately_correlated() -> None:
    variable_set = VariableSet(
        variables=[
            _variable("a", VariableDistribution(type="triangular", min=0, mode=5, max=10)),
            _variable("b", VariableDistribution(type="triangular", min=0, mode=5, max=10)),
        ],
        correlations=[VariableCorrelation(variable_a="a", variable_b="b", correlation=0.8)],
    )
    xs, ys = _sample_pair(variable_set, seed=7)
    measured = _pearson(xs, ys)
    assert 0.65 < measured < 0.95, measured
    assert all(0.0 <= value <= 10.0 for value in xs + ys)


def test_beta_pert_pair_is_approximately_correlated_and_bounded() -> None:
    variable_set = VariableSet(
        variables=[
            _variable("a", VariableDistribution(type="beta_pert", min=10, mode=12, max=20)),
            _variable("b", VariableDistribution(type="beta_pert", min=10, mode=12, max=20)),
        ],
        correlations=[VariableCorrelation(variable_a="a", variable_b="b", correlation=0.7)],
    )
    xs, ys = _sample_pair(variable_set, seed=3)
    measured = _pearson(xs, ys)
    # Beta-PERT marginals attenuate Pearson somewhat; the dependence is
    # real (far from independent) and the marginals stay in bounds.
    assert 0.5 < measured < 0.9, measured
    assert all(10.0 <= value <= 20.0 for value in xs + ys)
    assert 11.0 < sum(xs) / len(xs) < 14.0


def test_three_variable_spec_correlates_each_pair() -> None:
    variable_set = VariableSet(
        variables=[_normal("a"), _normal("b"), _normal("c")],
        correlations=[
            VariableCorrelation(variable_a="a", variable_b="b", correlation=0.7),
            VariableCorrelation(variable_a="a", variable_b="c", correlation=0.0),
            VariableCorrelation(variable_a="b", variable_b="c", correlation=-0.5),
        ],
    )
    rng = rng_for_seed(21)
    rows = [sample_variable_set(variable_set, rng) for _ in range(2000)]
    assert abs(_pearson([r["a"] for r in rows], [r["b"] for r in rows]) - 0.7) < 0.06
    assert abs(_pearson([r["a"] for r in rows], [r["c"] for r in rows])) < 0.06
    assert abs(_pearson([r["b"] for r in rows], [r["c"] for r in rows]) + 0.5) < 0.06


def test_uncorrelated_variable_in_a_correlated_set_stays_independent() -> None:
    variable_set = VariableSet(
        variables=[_normal("a"), _normal("b"), _normal("c")],
        correlations=[VariableCorrelation(variable_a="a", variable_b="b", correlation=0.8)],
    )
    rng = rng_for_seed(31)
    rows = [sample_variable_set(variable_set, rng) for _ in range(2000)]
    assert abs(_pearson([r["a"] for r in rows], [r["c"] for r in rows])) < 0.06
    assert abs(_pearson([r["b"] for r in rows], [r["c"] for r in rows])) < 0.06


# --- Determinism / replay / pairing ----------------------------------------


def test_same_seed_reproduces_correlated_draws_and_other_seed_differs() -> None:
    variable_set = _pair(0.8)
    first = sample_variable_set(variable_set, rng_for_seed(123))
    second = sample_variable_set(variable_set, rng_for_seed(123))
    assert first == second
    assert sample_variable_set(variable_set, rng_for_seed(124)) != first


def test_correlated_stream_is_replayable_draw_by_draw() -> None:
    variable_set = _pair(0.8)
    first_run = [sample_variable_set(variable_set, rng_for_seed(9)) for _ in range(50)]
    second_run = [sample_variable_set(variable_set, rng_for_seed(9)) for _ in range(50)]
    assert first_run == second_run


def test_levers_replace_draws_after_consumption_under_correlation() -> None:
    variable_set = _pair(0.8)
    baseline = sample_variable_set(variable_set, rng_for_seed(42))
    levered = sample_variable_set(variable_set, rng_for_seed(42), {"a": 99.0})
    assert levered["a"] == 99.0
    # The non-levered partner keeps the identical shared draw, so paired
    # baseline/strategy arms still share the correlated stream.
    assert levered["b"] == baseline["b"]


# --- Default-independent contract ------------------------------------------


def test_no_spec_samples_exactly_like_the_golden_independent_draws() -> None:
    assert sample_variable_set(GOLDEN_SET, rng_for_seed(42)) == GOLDEN_DRAWS_42
    assert sample_variable_set(GOLDEN_SET, rng_for_seed(7)) == GOLDEN_DRAWS_7


def test_unspecified_pair_is_independent() -> None:
    variable_set = VariableSet(variables=[_normal("a"), _normal("b")])
    xs, ys = _sample_pair(variable_set, seed=42)
    assert abs(_pearson(xs, ys)) < 0.06


def test_correlated_bindings_flow_through_resolve_run_values() -> None:
    configuration = {
        "variables": {
            "bindings": {
                "name": "case",
                "variables": [
                    {
                        "id": "a",
                        "unit": "x",
                        "distribution": {"type": "normal", "mean": 0, "std": 1},
                        "evidence_ref": "estimate: test",
                    },
                    {
                        "id": "b",
                        "unit": "x",
                        "distribution": {"type": "normal", "mean": 0, "std": 1},
                        "evidence_ref": "estimate: test",
                    },
                ],
                "correlations": [{"variable_a": "a", "variable_b": "b", "correlation": 0.8}],
            }
        }
    }
    first, _, _ = resolve_run_values(configuration, 42, {"a", "b"})
    second, _, _ = resolve_run_values(configuration, 42, {"a", "b"})
    assert first == second
    assert set(first) == {"a", "b"}


def test_old_bindings_without_correlations_parse_as_independent() -> None:
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
        }
    }
    sampled, _, _ = resolve_run_values(configuration, 42, {"cash"})
    expected = sample_variable_set(
        VariableSet.model_validate(configuration["variables"]["bindings"]),
        rng_for_seed(42),
    )
    assert sampled == expected


def test_correlations_on_variable_less_template_are_rejected() -> None:
    from planagent.services.variables.models import VariableTemplate
    from planagent.services.variables.validator import validate_template

    template = VariableTemplate(
        id="t",
        name="empty",
        domain_id="corporate",
        correlations=[VariableCorrelation(variable_a="a", variable_b="b", correlation=0.5)],
    )
    result = validate_template(template)
    assert not result.is_valid
    assert any(issue.kind == "correlation_unknown_variable" for issue in result.issues)


def test_merge_variable_sets_merges_correlations_by_pair() -> None:
    base = _pair(0.5)
    override = VariableSet(
        variables=[_normal("a"), _normal("b"), _normal("c")],
        correlations=[
            VariableCorrelation(variable_a="a", variable_b="b", correlation=0.9),
            VariableCorrelation(variable_a="a", variable_b="c", correlation=0.3),
        ],
    )
    merged = merge_variable_sets(base, override)
    by_pair = {
        frozenset((spec.variable_a, spec.variable_b)): spec.correlation
        for spec in merged.correlations
    }
    assert by_pair[frozenset(("a", "b"))] == 0.9
    assert by_pair[frozenset(("a", "c"))] == 0.3
    assert validate_variable_set(merged).is_valid

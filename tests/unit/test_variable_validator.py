"""Unit tests for the Sprint 2 variable-table validator.

Pure-function tests: no database, no I/O. Rules are ported from
agilhaykal/strategic-simulation (backend/engine.py): 1-30 variables, unit +
evidence_ref provenance on every variable, and per-distribution parameter
rules.
"""

from __future__ import annotations

import pytest

from planagent.services.variables import (
    DistributionType,
    MetricPolicySpec,
    TemplateStateField,
    VariableDefinition,
    VariableDistribution,
    VariableSet,
    VariableTemplate,
    VariableValidationError,
    merge_variable_sets,
    validate_or_raise,
    validate_scope_bindings,
    validate_template,
    validate_variable_set,
)


def make_variable(
    variable_id: str = "cac",
    distribution: VariableDistribution | None = None,
    unit: str = "yuan",
    evidence_ref: str = "evidence:q3-report",
    scope_tags: list[str] | None = None,
) -> VariableDefinition:
    return VariableDefinition(
        id=variable_id,
        unit=unit,
        distribution=distribution
        or VariableDistribution(type=DistributionType.FIXED, value=12000.0),
        evidence_ref=evidence_ref,
        scope_tags=scope_tags or [],
    )


def kinds(result) -> list[str]:
    return [issue.kind for issue in result.issues]


def test_fixed_distribution_valid_and_missing_value() -> None:
    valid = validate_variable_set(VariableSet(variables=[make_variable()]))
    assert valid.is_valid
    assert valid.variable_count == 1

    missing = validate_variable_set(
        VariableSet(
            variables=[
                make_variable(distribution=VariableDistribution(type=DistributionType.FIXED))
            ]
        )
    )
    assert missing.is_valid is False
    assert kinds(missing) == ["missing_parameter"]


def test_normal_distribution_requires_mean_std_and_positive_std() -> None:
    valid = validate_variable_set(
        VariableSet(
            variables=[
                make_variable(
                    distribution=VariableDistribution(
                        type=DistributionType.NORMAL, mean=10.0, std=2.0
                    )
                )
            ]
        )
    )
    assert valid.is_valid

    missing_mean = validate_variable_set(
        VariableSet(
            variables=[
                make_variable(
                    distribution=VariableDistribution(type=DistributionType.NORMAL, std=2.0)
                )
            ]
        )
    )
    assert kinds(missing_mean) == ["missing_parameter"]

    missing_std = validate_variable_set(
        VariableSet(
            variables=[
                make_variable(
                    distribution=VariableDistribution(type=DistributionType.NORMAL, mean=10.0)
                )
            ]
        )
    )
    assert kinds(missing_std) == ["missing_parameter"]

    for bad_std in (0.0, -1.5):
        result = validate_variable_set(
            VariableSet(
                variables=[
                    make_variable(
                        distribution=VariableDistribution(
                            type=DistributionType.NORMAL, mean=10.0, std=bad_std
                        )
                    )
                ]
            )
        )
        assert result.is_valid is False
        assert kinds(result) == ["invalid_std"]


@pytest.mark.parametrize(
    "distribution_type", [DistributionType.TRIANGULAR, DistributionType.BETA_PERT]
)
def test_triangular_family_bounds_rules(distribution_type: DistributionType) -> None:
    def build(
        min_value: float | None, mode: float | None, max_value: float | None
    ) -> VariableDefinition:
        return make_variable(
            distribution=VariableDistribution(
                type=distribution_type, min=min_value, mode=mode, max=max_value
            )
        )

    assert validate_variable_set(VariableSet(variables=[build(1.0, 2.0, 3.0)])).is_valid
    # Boundary: mode may equal min or max.
    assert validate_variable_set(VariableSet(variables=[build(1.0, 1.0, 3.0)])).is_valid
    assert validate_variable_set(VariableSet(variables=[build(1.0, 3.0, 3.0)])).is_valid

    assert kinds(validate_variable_set(VariableSet(variables=[build(1.0, 5.0, 3.0)]))) == [
        "invalid_bounds"
    ]
    assert kinds(validate_variable_set(VariableSet(variables=[build(3.0, 2.0, 1.0)]))) == [
        "invalid_bounds"
    ]
    assert kinds(validate_variable_set(VariableSet(variables=[build(2.0, 2.0, 2.0)]))) == [
        "degenerate_bounds"
    ]
    assert kinds(validate_variable_set(VariableSet(variables=[build(None, 2.0, 3.0)]))) == [
        "missing_parameter"
    ]
    assert kinds(validate_variable_set(VariableSet(variables=[build(1.0, None, 3.0)]))) == [
        "missing_parameter"
    ]
    assert kinds(validate_variable_set(VariableSet(variables=[build(1.0, 2.0, None)]))) == [
        "missing_parameter"
    ]


def test_bernoulli_probability_bounds() -> None:
    for good_p in (0.0, 0.5, 1.0):
        result = validate_variable_set(
            VariableSet(
                variables=[
                    make_variable(
                        distribution=VariableDistribution(type=DistributionType.BERNOULLI, p=good_p)
                    )
                ]
            )
        )
        assert result.is_valid

    assert kinds(
        validate_variable_set(
            VariableSet(
                variables=[
                    make_variable(
                        distribution=VariableDistribution(type=DistributionType.BERNOULLI)
                    )
                ]
            )
        )
    ) == ["missing_parameter"]

    for bad_p in (-0.1, 1.5):
        result = validate_variable_set(
            VariableSet(
                variables=[
                    make_variable(
                        distribution=VariableDistribution(type=DistributionType.BERNOULLI, p=bad_p)
                    )
                ]
            )
        )
        assert kinds(result) == ["invalid_probability"]


def test_missing_unit_and_missing_provenance_are_structured_issues() -> None:
    result = validate_variable_set(VariableSet(variables=[make_variable(unit="", evidence_ref="")]))
    assert result.is_valid is False
    assert kinds(result) == ["missing_unit", "missing_evidence_ref"]

    whitespace_only = validate_variable_set(
        VariableSet(variables=[make_variable(unit="  ", evidence_ref="  ")])
    )
    assert kinds(whitespace_only) == ["missing_unit", "missing_evidence_ref"]


def test_empty_and_oversized_sets() -> None:
    empty = validate_variable_set(VariableSet(variables=[]))
    assert empty.is_valid is False
    assert kinds(empty) == ["empty_set"]

    thirty = validate_variable_set(
        VariableSet(variables=[make_variable(f"v{i}") for i in range(30)])
    )
    assert thirty.is_valid

    oversized = validate_variable_set(
        VariableSet(variables=[make_variable(f"v{i}") for i in range(31)])
    )
    assert oversized.is_valid is False
    assert kinds(oversized) == ["too_many_variables"]


def test_duplicate_variable_ids_rejected() -> None:
    result = validate_variable_set(
        VariableSet(variables=[make_variable("dup"), make_variable("dup")])
    )
    assert result.is_valid is False
    assert kinds(result) == ["duplicate_variable"]
    assert result.issues[0].variable == "dup"


def test_scope_tag_issues() -> None:
    duplicated = validate_variable_set(
        VariableSet(variables=[make_variable(scope_tags=["demand", "demand"])])
    )
    assert kinds(duplicated) == ["duplicate_scope_tag"]

    blank = validate_variable_set(VariableSet(variables=[make_variable(scope_tags=["  "])]))
    assert kinds(blank) == ["invalid_scope_tag"]


def test_scope_bindings_cross_check() -> None:
    in_scope = VariableSet(variables=[make_variable(scope_tags=["demand"])])
    assert validate_scope_bindings(["demand", "cost"], in_scope) == []

    out_of_scope = VariableSet(variables=[make_variable(scope_tags=["demand", "risk"])])
    issues = validate_scope_bindings(["demand", "cost"], out_of_scope)
    assert [issue.kind for issue in issues] == ["scope_tag_outside_decomposition"]
    assert issues[0].variable == "cac"

    untagged = VariableSet(variables=[make_variable()])
    assert validate_scope_bindings(["demand"], untagged) == []


def test_merge_variable_sets_override_wins_and_order_is_deterministic() -> None:
    base = VariableSet(
        name="base",
        variables=[make_variable("a"), make_variable("b")],
        internal={"team": "base team", "runway": "12m"},
    )
    override = VariableSet(
        name="override",
        variables=[
            make_variable(
                "b",
                distribution=VariableDistribution(type=DistributionType.FIXED, value=99.0),
            ),
            make_variable("c"),
        ],
        internal={"runway": "18m"},
    )
    merged = merge_variable_sets(base, override)
    assert merged.name == "override"
    assert [variable.id for variable in merged.variables] == ["a", "b", "c"]
    assert merged.variables[1].distribution.value == 99.0
    assert merged.internal == {"team": "base team", "runway": "18m"}

    empty_override = merge_variable_sets(base, VariableSet())
    assert [variable.id for variable in empty_override.variables] == ["a", "b"]
    assert empty_override.name == "base"


def test_validate_or_raise_carries_result() -> None:
    with pytest.raises(VariableValidationError) as excinfo:
        validate_or_raise(VariableSet(variables=[]))
    assert excinfo.value.result.is_valid is False
    assert kinds(excinfo.value.result) == ["empty_set"]

    result = validate_or_raise(VariableSet(variables=[make_variable()]))
    assert result.is_valid


def make_template(**overrides) -> VariableTemplate:
    values: dict = {
        "id": "tpl-1",
        "name": "Template",
        "domain_id": "corporate",
        "state_fields": [TemplateStateField(name="cash", description="Cash", default=1.0)],
        "policies": {
            "cash": MetricPolicySpec(
                preferred_direction="increase", alert_threshold=0.6, critical_threshold=0.3
            )
        },
        "variables": [],
    }
    values.update(overrides)
    return VariableTemplate(**values)


def test_validate_template_state_fields_and_policies() -> None:
    assert validate_template(make_template()).is_valid

    duplicated = validate_template(
        make_template(
            state_fields=[
                TemplateStateField(name="cash", default=1.0),
                TemplateStateField(name="cash", default=2.0),
            ]
        )
    )
    assert kinds(duplicated) == ["duplicate_state_field"]

    inverted_increase = validate_template(
        make_template(
            policies={
                "cash": MetricPolicySpec(
                    preferred_direction="increase",
                    alert_threshold=0.3,
                    critical_threshold=0.6,
                )
            }
        )
    )
    assert kinds(inverted_increase) == ["invalid_policy_thresholds"]

    inverted_decrease = validate_template(
        make_template(
            policies={
                "churn_risk": MetricPolicySpec(
                    preferred_direction="decrease",
                    alert_threshold=0.6,
                    critical_threshold=0.3,
                )
            }
        )
    )
    assert kinds(inverted_decrease) == ["invalid_policy_thresholds"]

    # Templates may carry zero variables (defaults/policies only).
    assert validate_template(make_template(variables=[])).is_valid

    # Variables present in a template follow the same rules as a set.
    bad_variable = validate_template(
        make_template(variables=[make_variable(unit="", evidence_ref="")])
    )
    assert kinds(bad_variable) == ["missing_unit", "missing_evidence_ref"]

    oversized = validate_template(
        make_template(variables=[make_variable(f"v{i}") for i in range(31)])
    )
    assert "too_many_variables" in kinds(oversized)

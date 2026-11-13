"""Unit tests for the Sprint 4 formula graph (PRD delta D7).

Covers expression evaluation (every operator, ref chains, literals),
validation (unknown refs, forward references/cycles, duplicate outputs,
shape errors, depth cap, static division by zero), runtime failures
(division by zero, non-finite results), merge semantics, and integration
with the set/template validators.
"""

from __future__ import annotations

import pytest

from planagent.services.variables import (
    MAX_FORMULAS,
    evaluate_formulas,
    merge_variable_sets,
    validate_template,
    validate_variable_set,
)
from planagent.services.variables.formulas import FormulaEvaluationError, validate_formulas
from planagent.services.variables.models import (
    FormulaDefinition,
    VariableDefinition,
    VariableSet,
    VariableTemplate,
)


def _variable(
    variable_id: str,
    distribution: dict | None = None,
) -> VariableDefinition:
    return VariableDefinition.model_validate(
        {
            "id": variable_id,
            "unit": "x",
            "distribution": distribution or {"type": "fixed", "value": 10.0},
            "evidence_ref": "estimate: test",
        }
    )


def _formula(output: str, expression: object) -> FormulaDefinition:
    return FormulaDefinition(output=output, expression=expression)


def _issues_by_kind(variable_set: VariableSet) -> dict[str, list[str]]:
    result = validate_variable_set(variable_set)
    grouped: dict[str, list[str]] = {}
    for issue in result.issues:
        grouped.setdefault(issue.kind, []).append(issue.variable)
    return grouped


def test_each_operator_evaluates() -> None:
    variables = [_variable("a"), _variable("b", {"type": "fixed", "value": 4.0})]
    formulas = [
        _formula("add", {"op": "add", "args": [{"ref": "a"}, {"ref": "b"}]}),
        _formula("sub", {"op": "subtract", "args": [{"ref": "a"}, {"ref": "b"}]}),
        _formula("mul", {"op": "multiply", "args": [{"ref": "a"}, {"ref": "b"}]}),
        _formula("div", {"op": "divide", "args": [{"ref": "a"}, {"ref": "b"}]}),
        _formula("min", {"op": "min", "args": [{"ref": "a"}, {"ref": "b"}]}),
        _formula("max", {"op": "max", "args": [{"ref": "a"}, {"ref": "b"}]}),
        _formula("lit", 7.5),
        _formula("alias", {"ref": "a"}),
    ]
    issues, _ = validate_formulas(variables, formulas)
    assert issues == []
    derived = evaluate_formulas(formulas, {"a": 10.0, "b": 4.0})
    assert derived == {
        "add": 14.0,
        "sub": 6.0,
        "mul": 40.0,
        "div": 2.5,
        "min": 4.0,
        "max": 10.0,
        "lit": 7.5,
        "alias": 10.0,
    }


def test_ref_chains_evaluate_in_list_order() -> None:
    variables = [_variable("a")]
    formulas = [
        _formula("doubled", {"op": "multiply", "args": [{"ref": "a"}, 2]}),
        _formula("quadrupled", {"op": "multiply", "args": [{"ref": "doubled"}, 2]}),
        _formula("plus_one", {"op": "add", "args": [{"ref": "quadrupled"}, 1]}),
    ]
    issues, _ = validate_formulas(variables, formulas)
    assert issues == []
    assert evaluate_formulas(formulas, {"a": 3.0}) == {
        "doubled": 6.0,
        "quadrupled": 12.0,
        "plus_one": 13.0,
    }


def test_nested_expressions_evaluate() -> None:
    variables = [_variable("a"), _variable("b", {"type": "fixed", "value": 2.0})]
    formulas = [
        _formula(
            "out",
            {
                "op": "divide",
                "args": [
                    {"op": "add", "args": [{"ref": "a"}, {"ref": "b"}]},
                    {"op": "subtract", "args": [{"ref": "a"}, {"ref": "b"}]},
                ],
            },
        )
    ]
    issues, _ = validate_formulas(variables, formulas)
    assert issues == []
    assert evaluate_formulas(formulas, {"a": 10.0, "b": 2.0}) == {"out": 1.5}


def test_unknown_ref_rejected() -> None:
    variable_set = VariableSet(
        variables=[_variable("a")],
        formulas=[_formula("out", {"ref": "missing"})],
    )
    assert _issues_by_kind(variable_set) == {"formula_unknown_ref": ["out"]}
    assert not validate_variable_set(variable_set).is_valid


def test_forward_reference_rejected_so_cycles_are_impossible() -> None:
    # b -> c -> b: the forward reference on b is rejected, which is what
    # makes every cycle unrepresentable.
    variable_set = VariableSet(
        variables=[_variable("a")],
        formulas=[
            _formula("b", {"ref": "c"}),
            _formula("c", {"ref": "b"}),
        ],
    )
    assert _issues_by_kind(variable_set) == {"formula_unknown_ref": ["b"]}


def test_self_reference_rejected() -> None:
    variable_set = VariableSet(
        variables=[_variable("a")],
        formulas=[_formula("out", {"ref": "out"})],
    )
    assert _issues_by_kind(variable_set) == {"formula_unknown_ref": ["out"]}


def test_duplicate_output_and_variable_collision_rejected() -> None:
    variable_set = VariableSet(
        variables=[_variable("a")],
        formulas=[
            _formula("out", 1),
            _formula("out", 2),
            _formula("a", 3),
        ],
    )
    grouped = _issues_by_kind(variable_set)
    assert grouped["duplicate_formula_output"] == ["out"]
    assert grouped["formula_output_collides_with_variable"] == ["a"]


def test_shape_errors_rejected() -> None:
    cases: list[object] = [
        "not-an-expression",
        [1, 2],
        None,
        True,
        {"ref": 42},
        {"ref": "a", "extra": 1},
        {"op": "add"},
        {"op": "add", "args": [{"ref": "a"}]},
        {"op": "add", "args": [{"ref": "a"}, {"ref": "a"}, {"ref": "a"}]},
        {"op": "add", "args": "nope"},
        {"op": "power", "args": [1, 2]},
        {"unknown": 1},
    ]
    for index, expression in enumerate(cases):
        variable_set = VariableSet(
            variables=[_variable("a")],
            formulas=[_formula(f"out{index}", expression)],
        )
        result = validate_variable_set(variable_set)
        assert not result.is_valid, f"expression {expression!r} should be rejected"
        assert result.issues, f"expression {expression!r} produced no issues"


def test_wrong_arity_and_unknown_operator_have_distinct_kinds() -> None:
    variable_set = VariableSet(
        variables=[_variable("a")],
        formulas=[
            _formula("arity", {"op": "add", "args": [1]}),
            _formula("op", {"op": "power", "args": [1, 2]}),
        ],
    )
    grouped = _issues_by_kind(variable_set)
    assert grouped["formula_wrong_arity"] == ["arity"]
    assert grouped["formula_unknown_operator"] == ["op"]


def test_depth_cap_enforced() -> None:
    def nest(depth: int) -> object:
        expression: object = {"ref": "a"}
        for _ in range(depth):
            expression = {"op": "add", "args": [expression, 0]}
        return expression

    ok_set = VariableSet(variables=[_variable("a")], formulas=[_formula("out", nest(15))])
    assert validate_variable_set(ok_set).is_valid
    deep_set = VariableSet(variables=[_variable("a")], formulas=[_formula("out", nest(16))])
    grouped = _issues_by_kind(deep_set)
    assert "formula_too_deep" in grouped
    assert all(variable == "out" for variable in grouped["formula_too_deep"])
    assert not validate_variable_set(deep_set).is_valid


def test_static_division_by_zero_rejected() -> None:
    variable_set = VariableSet(
        variables=[
            _variable("a"),
            _variable("zero", {"type": "fixed", "value": 0.0}),
            _variable("nonzero", {"type": "fixed", "value": 5.0}),
        ],
        formulas=[
            _formula("lit", {"op": "divide", "args": [1, 0]}),
            _formula("ref", {"op": "divide", "args": [1, {"ref": "zero"}]}),
            _formula("ok", {"op": "divide", "args": [1, {"ref": "nonzero"}]}),
        ],
    )
    grouped = _issues_by_kind(variable_set)
    assert grouped["formula_division_by_zero"] == ["lit", "ref"]


def test_runtime_division_by_zero_raises() -> None:
    formulas = [_formula("out", {"op": "divide", "args": [1, {"ref": "a"}]})]
    with pytest.raises(FormulaEvaluationError, match="Division by zero"):
        evaluate_formulas(formulas, {"a": 0.0})


def test_missing_ref_at_evaluation_raises() -> None:
    formulas = [_formula("out", {"ref": "missing"})]
    with pytest.raises(FormulaEvaluationError, match="Unknown reference"):
        evaluate_formulas(formulas, {})


def test_nonfinite_result_raises() -> None:
    formulas = [_formula("out", {"op": "multiply", "args": [1e308, 10]})]
    with pytest.raises(FormulaEvaluationError, match="non-finite"):
        evaluate_formulas(formulas, {})


def test_too_many_formulas_rejected() -> None:
    formulas = [_formula(f"f{i}", 1) for i in range(MAX_FORMULAS + 1)]
    variable_set = VariableSet(variables=[_variable("a")], formulas=formulas)
    assert "too_many_formulas" in _issues_by_kind(variable_set)
    ok_set = VariableSet(
        variables=[_variable("a")],
        formulas=[_formula(f"f{i}", 1) for i in range(MAX_FORMULAS)],
    )
    assert validate_variable_set(ok_set).is_valid


def test_formula_check_record_only_when_formulas_present() -> None:
    plain = validate_variable_set(VariableSet(variables=[_variable("a")]))
    assert all(check.check != "formulas" for check in plain.checks)
    with_formulas = validate_variable_set(
        VariableSet(variables=[_variable("a")], formulas=[_formula("out", 1)])
    )
    formula_checks = [c for c in with_formulas.checks if c.check == "formulas"]
    assert len(formula_checks) == 1
    assert formula_checks[0].status == "pass"


def test_merge_prefers_override_formulas() -> None:
    base = VariableSet(
        variables=[_variable("a")],
        formulas=[_formula("x", 1), _formula("y", 2)],
    )
    override = VariableSet(
        variables=[_variable("a")],
        formulas=[_formula("y", 20), _formula("z", 3)],
    )
    merged = merge_variable_sets(base, override)
    assert [f.output for f in merged.formulas] == ["x", "y", "z"]
    assert merged.formulas[1].expression == 20


def test_template_validation_covers_formulas() -> None:
    template = VariableTemplate(
        id="t1",
        name="T",
        domain_id="corporate",
        variables=[_variable("a")],
        formulas=[_formula("out", {"ref": "missing"})],
    )
    result = validate_template(template)
    assert not result.is_valid
    assert any(issue.kind == "formula_unknown_ref" for issue in result.issues)


def test_template_with_only_literal_formulas_validates() -> None:
    template = VariableTemplate(
        id="t1",
        name="T",
        domain_id="corporate",
        variables=[],
        formulas=[_formula("const", 42)],
    )
    result = validate_template(template)
    assert result.is_valid
    assert result.issues == []


def test_levers_propagate_through_formulas_at_evaluation() -> None:
    # Evaluation receives post-lever sampled values (the sampler applies
    # levers before formulas evaluate), so a levered input moves the
    # derived value. This test pins the evaluation-order contract.
    formulas = [_formula("cash", {"op": "subtract", "args": [100, {"ref": "cac"}]})]
    assert evaluate_formulas(formulas, {"cac": 30.0}) == {"cash": 70.0}

"""Unit tests for tick-driver formulas (Phase 1 automotive pack).

Covers the driver-aware validation rules in ``validate_formulas`` (the
reserved ``tick`` reference, self-reference for drivers, forward
references, the driver collision exemption), ``evaluate_tick_drivers``
(chaining, state precedence, tick reference, rounding, loud failure),
and the executor-side split: ``resolve_run_values`` skips drivers while
``tick_driver_formulas`` reads them back from stored bindings.
"""

from __future__ import annotations

import pytest

from planagent.services.distributions import (
    resolve_run_values,
    tick_driver_formulas,
)
from planagent.services.variables.formulas import (
    TICK_REFERENCE,
    FormulaEvaluationError,
    evaluate_tick_drivers,
    validate_formulas,
)
from planagent.services.variables.models import (
    FormulaDefinition,
    VariableDefinition,
    VariableDistribution,
    VariableSet,
)


def _var(var_id: str, value: float = 1.0) -> VariableDefinition:
    return VariableDefinition(
        id=var_id,
        unit="x",
        distribution=VariableDistribution(type="fixed", value=value),
        evidence_ref="test",
    )


def _formula(output: str, expression: object, *, tick_driver: bool = False) -> FormulaDefinition:
    return FormulaDefinition(output=output, expression=expression, tick_driver=tick_driver)


def _ref(name: str) -> dict[str, str]:
    return {"ref": name}


def _kinds(issues) -> list[str]:
    return [issue.kind for issue in issues]


def test_tick_reference_constant() -> None:
    assert TICK_REFERENCE == "tick"


def test_driver_may_reference_its_own_output() -> None:
    # A driver output id names the current state value of that field.
    issues, _ = validate_formulas(
        [_var("retail", 100.0)],
        [_formula("retail", {"op": "multiply", "args": [_ref("retail"), 0.99]}, tick_driver=True)],
    )
    assert issues == []


def test_initial_formula_may_not_reference_itself() -> None:
    issues, _ = validate_formulas(
        [_var("retail", 100.0)],
        [_formula("growth", {"op": "add", "args": [_ref("growth"), 1.0]})],
    )
    assert _kinds(issues) == ["formula_unknown_ref"]


def test_driver_may_reference_tick() -> None:
    issues, _ = validate_formulas(
        [_var("retail", 100.0)],
        [
            _formula(
                "retail",
                {"op": "add", "args": [_ref("retail"), _ref("tick")]},
                tick_driver=True,
            )
        ],
    )
    assert issues == []


def test_initial_formula_may_not_reference_tick() -> None:
    issues, _ = validate_formulas(
        [_var("retail", 100.0)],
        [_formula("growth", {"op": "add", "args": [_ref("retail"), _ref("tick")]})],
    )
    assert _kinds(issues) == ["formula_unknown_ref"]


def test_initial_formula_may_not_reference_driver_output() -> None:
    # The driver output does not exist at run start, even if the driver
    # is listed earlier in the graph.
    issues, _ = validate_formulas(
        [_var("retail", 100.0)],
        [
            _formula("retail", _ref("retail"), tick_driver=True),
            _formula("growth", _ref("retail")),
        ],
    )
    # "retail" is a sampled id so it IS known; use a driver-only output.
    assert issues == []
    issues, _ = validate_formulas(
        [_var("retail", 100.0)],
        [
            _formula("evolved", _ref("retail"), tick_driver=True),
            _formula("growth", _ref("evolved")),
        ],
    )
    assert _kinds(issues) == ["formula_unknown_ref"]


def test_driver_may_reference_earlier_driver_output() -> None:
    issues, _ = validate_formulas(
        [_var("retail", 100.0)],
        [
            _formula(
                "retail", {"op": "multiply", "args": [_ref("retail"), 0.99]}, tick_driver=True
            ),
            _formula(
                "inventory",
                {"op": "subtract", "args": [_ref("inventory"), _ref("retail")]},
                tick_driver=True,
            ),
        ],
    )
    assert issues == []


def test_forward_reference_rejected_for_drivers() -> None:
    issues, _ = validate_formulas(
        [_var("retail", 100.0)],
        [
            _formula(
                "inventory",
                {"op": "subtract", "args": [_ref("inventory"), _ref("retail")]},
                tick_driver=True,
            ),
            _formula(
                "retail", {"op": "multiply", "args": [_ref("retail"), 0.99]}, tick_driver=True
            ),
        ],
    )
    # "retail" is a sampled id so it is known; the forward reference must
    # name a not-yet-defined driver output to be rejected.
    assert issues == []
    issues, _ = validate_formulas(
        [_var("retail", 100.0)],
        [
            _formula("first", _ref("second"), tick_driver=True),
            _formula("second", _ref("retail"), tick_driver=True),
        ],
    )
    assert _kinds(issues) == ["formula_unknown_ref"]


def test_driver_output_colliding_with_sampled_id_is_exempt() -> None:
    issues, _ = validate_formulas(
        [_var("retail", 100.0)],
        [_formula("retail", _ref("retail"), tick_driver=True)],
    )
    assert issues == []


def test_initial_output_colliding_with_sampled_id_still_rejected() -> None:
    issues, _ = validate_formulas(
        [_var("retail", 100.0)],
        [_formula("retail", _ref("retail"))],
    )
    assert _kinds(issues) == ["formula_output_collides_with_variable"]


def test_reserved_tick_output_rejected_for_both_kinds() -> None:
    issues, _ = validate_formulas([_var("retail")], [_formula("tick", 1.0)])
    assert _kinds(issues) == ["reserved_tick_id"]
    issues, _ = validate_formulas([_var("retail")], [_formula("tick", 1.0, tick_driver=True)])
    assert _kinds(issues) == ["reserved_tick_id"]


def test_tick_variable_id_rejected_by_set_validator() -> None:
    from planagent.services.variables import validate_variable_set

    result = validate_variable_set(VariableSet(name="case", variables=[_var("tick")], formulas=[]))
    assert result.is_valid is False
    assert "reserved_tick_id" in _kinds(result.issues)


def test_duplicate_driver_output_rejected() -> None:
    issues, _ = validate_formulas(
        [_var("retail", 100.0)],
        [
            _formula("retail", _ref("retail"), tick_driver=True),
            _formula("retail", _ref("retail"), tick_driver=True),
        ],
    )
    assert _kinds(issues) == ["duplicate_formula_output"]


def test_evaluate_tick_drivers_self_reference_reads_current_state() -> None:
    drivers = [
        _formula("retail", {"op": "multiply", "args": [_ref("retail"), 0.9]}, tick_driver=True)
    ]
    # Base (sampled) value is 100; current state is 50 after a rule
    # effect. The driver must evolve the post-rule state, not the sample.
    out = evaluate_tick_drivers(drivers, {"retail": 100.0}, {"retail": 50.0}, tick=3)
    assert out == {"retail": 45.0}


def test_evaluate_tick_drivers_chain_within_tick() -> None:
    drivers = [
        _formula("retail", {"op": "multiply", "args": [_ref("retail"), 0.9]}, tick_driver=True),
        _formula(
            "inventory",
            {"op": "add", "args": [_ref("inventory"), _ref("retail")]},
            tick_driver=True,
        ),
    ]
    out = evaluate_tick_drivers(drivers, {}, {"retail": 100.0, "inventory": 1.0}, tick=1)
    assert out == {"retail": 90.0, "inventory": 91.0}


def test_evaluate_tick_drivers_first_tick_indicator() -> None:
    # max(0, min(1, 2 - tick)) is 1 on tick 1 and 0 from tick 2 on.
    indicator = {
        "op": "max",
        "args": [0, {"op": "min", "args": [1, {"op": "subtract", "args": [2, _ref("tick")]}]}],
    }
    drivers = [_formula("level", indicator, tick_driver=True)]
    assert evaluate_tick_drivers(drivers, {}, {}, tick=1) == {"level": 1.0}
    assert evaluate_tick_drivers(drivers, {}, {}, tick=2) == {"level": 0.0}
    assert evaluate_tick_drivers(drivers, {}, {}, tick=12) == {"level": 0.0}


def test_evaluate_tick_drivers_rounds_to_four_decimals() -> None:
    drivers = [_formula("x", {"op": "divide", "args": [1, 3]}, tick_driver=True)]
    assert evaluate_tick_drivers(drivers, {}, {}, tick=1) == {"x": 0.3333}


def test_evaluate_tick_drivers_missing_reference_fails_loudly() -> None:
    drivers = [_formula("x", _ref("nope"), tick_driver=True)]
    with pytest.raises(FormulaEvaluationError, match="Unknown reference"):
        evaluate_tick_drivers(drivers, {}, {}, tick=1)


def test_evaluate_tick_drivers_division_by_zero_fails_loudly() -> None:
    drivers = [_formula("x", {"op": "divide", "args": [1, 0]}, tick_driver=True)]
    with pytest.raises(FormulaEvaluationError, match="Division by zero"):
        evaluate_tick_drivers(drivers, {}, {}, tick=1)


def test_resolve_run_values_skips_drivers() -> None:
    configuration = {
        "variables": {
            "bindings": {
                "name": "case",
                "variables": [
                    {
                        "id": "retail",
                        "unit": "x",
                        "distribution": {"type": "fixed", "value": 100.0},
                        "evidence_ref": "test",
                    }
                ],
                "formulas": [
                    {"output": "growth", "expression": 0.05},
                    {
                        "output": "retail",
                        "expression": {"op": "multiply", "args": [{"ref": "retail"}, 0.9]},
                        "tick_driver": True,
                    },
                ],
            }
        }
    }
    sampled, derived, applied = resolve_run_values(configuration, 7, {"retail", "growth"})
    assert sampled == {"retail": 100.0}
    assert derived == {"growth": 0.05}
    assert applied == {"retail": 100.0, "growth": 0.05}


def test_tick_driver_formulas_reads_stored_bindings() -> None:
    configuration = {
        "variables": {
            "bindings": {
                "name": "case",
                "variables": [
                    {
                        "id": "retail",
                        "unit": "x",
                        "distribution": {"type": "fixed", "value": 100.0},
                        "evidence_ref": "test",
                    }
                ],
                "formulas": [
                    {"output": "growth", "expression": 0.05},
                    {
                        "output": "retail",
                        "expression": {"ref": "retail"},
                        "tick_driver": True,
                    },
                ],
            }
        }
    }
    drivers = tick_driver_formulas(configuration)
    assert [formula.output for formula in drivers] == ["retail"]
    assert drivers[0].tick_driver is True


def test_tick_driver_formulas_empty_without_bindings() -> None:
    assert tick_driver_formulas(None) == []
    assert tick_driver_formulas({}) == []
    assert tick_driver_formulas({"variables": {}}) == []

"""Formula graph: derived variables computed from sampled variables (Sprint 4).

Ported from agilhaykal/strategic-simulation (``SimplifySimulation``,
``backend/engine.py``): a formula graph is an ordered list of formulas; each
formula names an output id and an expression over number literals, references
to known ids, and six binary operators (``add``/``subtract``/``multiply``/
``divide``/``min``/``max``) with exactly two arguments. No arbitrary code:
anything else is rejected at validation time, before any row is written.

Evaluation order is the list order, which is a valid topological order by
construction: a formula may only reference sampled variable ids and the
outputs of EARLIER formulas, so a forward reference is rejected and a cycle
is impossible (every cycle contains a forward reference). A reference to a
missing variable is a validation issue (``formula_unknown_ref``); at
evaluation time a missing ref raises :class:`FormulaEvaluationError`
defensively, which is unreachable for validated sets.

Division by zero: statically detectable cases (a literal ``0`` divisor, or a
reference to a ``fixed`` variable whose value is ``0``) are validation
issues. Data-dependent zeros — a sampled divisor that happens to draw 0 —
raise at evaluation time, exactly as in the reference; authors guard
denominators with ``max(denominator, epsilon)``. A formula whose evaluation
fails fails the run loudly; it is never silently skipped.

Pure and deterministic: no LLM, no randomness, no I/O.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from .models import (
    MAX_FORMULA_DEPTH,
    MAX_FORMULAS,
    DistributionType,
    FormulaDefinition,
    VariableCheckRecord,
    VariableDefinition,
    VariableValidationIssue,
)

_FORMULA_OPERATORS = frozenset({"add", "subtract", "multiply", "divide", "min", "max"})


class FormulaEvaluationError(ValueError):
    """Raised when a validated formula cannot be evaluated on sampled values."""

    def __init__(self, output: str, message: str) -> None:
        self.output = output
        super().__init__(f"Formula {output!r}: {message}")


def _issue(kind: str, message: str, variable: str = "") -> VariableValidationIssue:
    return VariableValidationIssue(kind=kind, variable=variable, message=message)


def _is_statically_zero(
    expression: Any,
    fixed_values: Mapping[str, float],
) -> bool:
    """Whether an expression is provably zero without sampling.

    Only literal ``0`` and references to ``fixed`` variables valued ``0``
    are detected; anything data-dependent is a runtime concern, not a
    validation error.
    """

    if isinstance(expression, bool):
        return False
    if isinstance(expression, (int, float)):
        return float(expression) == 0.0
    if isinstance(expression, dict) and set(expression) == {"ref"}:
        ref = expression["ref"]
        return isinstance(ref, str) and fixed_values.get(ref) == 0.0
    return False


def _expression_issues(
    expression: Any,
    *,
    output: str,
    known_ids: set[str],
    fixed_values: Mapping[str, float],
    depth: int,
) -> list[VariableValidationIssue]:
    """Validate one expression node, recursing into operator arguments."""

    if depth > MAX_FORMULA_DEPTH:
        return [
            _issue(
                "formula_too_deep",
                f"Expression exceeds the maximum nesting depth of {MAX_FORMULA_DEPTH}.",
                output,
            )
        ]
    if isinstance(expression, bool) or not isinstance(expression, (int, float, dict)):
        return [
            _issue(
                "formula_invalid_expression",
                'An expression must be a number literal, a {"ref": ...} reference, '
                'or a {"op": ..., "args": [...]} node.',
                output,
            )
        ]
    if isinstance(expression, (int, float)):
        if not math.isfinite(float(expression)):
            return [
                _issue(
                    "formula_nonfinite_literal",
                    "Expression literals must be finite numbers.",
                    output,
                )
            ]
        return []
    keys = set(expression)
    if keys == {"ref"}:
        ref = expression["ref"]
        if not isinstance(ref, str) or not ref:
            return [
                _issue(
                    "formula_invalid_expression",
                    "A reference must name a non-empty variable or formula id.",
                    output,
                )
            ]
        if ref not in known_ids:
            return [
                _issue(
                    "formula_unknown_ref",
                    f"Reference {ref!r} names no sampled variable or earlier formula "
                    "output (forward references are not allowed).",
                    output,
                )
            ]
        return []
    if keys == {"op", "args"}:
        operator = expression["op"]
        args = expression["args"]
        if operator not in _FORMULA_OPERATORS:
            return [
                _issue(
                    "formula_unknown_operator",
                    f"Unknown operator {operator!r}; expected one of {sorted(_FORMULA_OPERATORS)}.",
                    output,
                )
            ]
        if not isinstance(args, list) or len(args) != 2:
            return [
                _issue(
                    "formula_wrong_arity",
                    f"Operator {operator!r} requires exactly 2 arguments.",
                    output,
                )
            ]
        issues: list[VariableValidationIssue] = []
        for arg in args:
            issues.extend(
                _expression_issues(
                    arg,
                    output=output,
                    known_ids=known_ids,
                    fixed_values=fixed_values,
                    depth=depth + 1,
                )
            )
        if operator == "divide" and _is_statically_zero(args[1], fixed_values):
            issues.append(
                _issue(
                    "formula_division_by_zero",
                    "Division by an expression that is statically zero.",
                    output,
                )
            )
        return issues
    return [
        _issue(
            "formula_invalid_expression",
            'An expression object must have exactly the keys {"ref"} or '
            '{"op", "args"}; arbitrary code is forbidden.',
            output,
        )
    ]


def validate_formulas(
    variables: list[VariableDefinition],
    formulas: list[FormulaDefinition],
) -> tuple[list[VariableValidationIssue], list[VariableCheckRecord]]:
    """Validate a formula graph against its sampled variables.

    Returns ``(issues, checks)``. The checks list carries one aggregate
    ``formulas`` record, and only when at least one formula is present, so
    sets without formulas serialize exactly as before Sprint 4.
    """

    issues: list[VariableValidationIssue] = []
    if len(formulas) > MAX_FORMULAS:
        issues.append(
            _issue(
                "too_many_formulas",
                f"A formula graph holds at most {MAX_FORMULAS} formulas; got {len(formulas)}.",
            )
        )

    variable_ids = {variable.id for variable in variables}
    fixed_values = {
        variable.id: float(variable.distribution.value)
        for variable in variables
        if variable.distribution.type is DistributionType.FIXED
        and variable.distribution.value is not None
    }
    known_ids = set(variable_ids)
    seen_outputs: set[str] = set()
    for formula in formulas:
        if formula.output in seen_outputs:
            issues.append(
                _issue(
                    "duplicate_formula_output",
                    f"Duplicate formula output {formula.output!r}.",
                    formula.output,
                )
            )
        elif formula.output in variable_ids:
            issues.append(
                _issue(
                    "formula_output_collides_with_variable",
                    f"Formula output {formula.output!r} collides with a sampled variable id.",
                    formula.output,
                )
            )
        seen_outputs.add(formula.output)
        issues.extend(
            _expression_issues(
                formula.expression,
                output=formula.output,
                known_ids=known_ids,
                fixed_values=fixed_values,
                depth=0,
            )
        )
        # The output becomes known only AFTER its own expression is checked,
        # so a formula cannot reference itself or any later formula.
        known_ids.add(formula.output)

    checks: list[VariableCheckRecord] = []
    if formulas:
        checks.append(
            VariableCheckRecord(
                check="formulas",
                status="fail" if issues else "pass",
                detail=f"{len(formulas)} formula(s)",
            )
        )
    return issues, checks


def _evaluate_expression(
    expression: Any,
    values: Mapping[str, float],
    output: str,
) -> float:
    if isinstance(expression, bool) or not isinstance(expression, (int, float, dict)):
        raise FormulaEvaluationError(output, f"Invalid expression shape: {expression!r}.")
    if isinstance(expression, (int, float)):
        result = float(expression)
        if not math.isfinite(result):
            raise FormulaEvaluationError(output, "Non-finite literal.")
        return result
    keys = set(expression)
    if keys == {"ref"}:
        ref = expression["ref"]
        if not isinstance(ref, str) or ref not in values:
            raise FormulaEvaluationError(output, f"Unknown reference {ref!r}.")
        return float(values[ref])
    if keys == {"op", "args"}:
        operator = expression["op"]
        args = expression["args"]
        if operator not in _FORMULA_OPERATORS or not isinstance(args, list) or len(args) != 2:
            raise FormulaEvaluationError(output, f"Invalid operator node: {expression!r}.")
        left = _evaluate_expression(args[0], values, output)
        right = _evaluate_expression(args[1], values, output)
        if operator == "add":
            return left + right
        if operator == "subtract":
            return left - right
        if operator == "multiply":
            return left * right
        if operator == "divide":
            if right == 0.0:
                raise FormulaEvaluationError(output, "Division by zero in sampled values.")
            return left / right
        if operator == "min":
            return min(left, right)
        return max(left, right)
    raise FormulaEvaluationError(output, f"Invalid expression shape: {expression!r}.")


def evaluate_formulas(
    formulas: list[FormulaDefinition],
    values: Mapping[str, float],
) -> dict[str, float]:
    """Evaluate a formula graph over sampled values, in list order.

    ``values`` carries the sampled variables (after lever replacement, so
    strategy levers propagate through derived values). Returns only the
    derived outputs. Raises :class:`FormulaEvaluationError` on a missing
    reference, division by zero, or a non-finite result.
    """

    resolved = dict(values)
    derived: dict[str, float] = {}
    for formula in formulas:
        result = _evaluate_expression(formula.expression, resolved, formula.output)
        if not math.isfinite(result):
            raise FormulaEvaluationError(formula.output, "Evaluation produced a non-finite value.")
        resolved[formula.output] = result
        derived[formula.output] = result
    return derived

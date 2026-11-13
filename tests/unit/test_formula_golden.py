"""Golden test: the MVP prototype's example case, with a formula graph.

``variable_formula_golden_case.json`` carries the prototype's four variables
plus four formulas deriving two state fields (``cash``, ``pipeline``) and
two intermediate values from them. The expected file pins the byte-stable
serialization of the validated set plus its validation result. A second
test pins the formula evaluation at the distributions' mode values, so the
golden case demonstrates that prototype-style variables now move outcomes
through the graph.
"""

from __future__ import annotations

import json
from pathlib import Path

from planagent.services.variables import VariableSet, evaluate_formulas, validate_variable_set

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _load_case() -> VariableSet:
    case = json.loads(
        (FIXTURES / "variable_formula_golden_case.json").read_text(encoding="utf-8")
    )
    return VariableSet.model_validate(case)


def test_prototype_case_with_formulas_validates_and_serializes_byte_stable() -> None:
    variable_set = _load_case()
    result = validate_variable_set(variable_set)
    assert result.is_valid
    assert result.variable_count == 4
    assert result.issues == []
    assert [formula.output for formula in variable_set.formulas] == [
        "获客成本(千元)",
        "cash",
        "净留存信号",
        "pipeline",
    ]

    payload = {
        "variable_set": variable_set.model_dump(mode="json"),
        "validation": result.model_dump(mode="json"),
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    expected = (FIXTURES / "variable_formula_golden_expected.json").read_text(encoding="utf-8")
    assert serialized == expected


def test_formula_graph_evaluates_at_mode_values() -> None:
    variable_set = _load_case()
    # Mode values from the prototype case: R&D 36 person-months, CAC 12000,
    # uplift 35%, churn 12%.
    sampled = {
        "研发投入(人月)": 36.0,
        "获客成本 CAC": 12000.0,
        "AI 功能客单价 uplift": 35.0,
        "12 个月客户流失率": 12.0,
    }
    derived = evaluate_formulas(variable_set.formulas, sampled)
    assert derived == {
        "获客成本(千元)": 12.0,
        "cash": 92.0,
        "净留存信号": 23.0,
        "pipeline": 1.15,
    }

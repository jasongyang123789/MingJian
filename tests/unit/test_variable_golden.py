"""Golden test: the MVP prototype's example case, ported verbatim.

``variable_golden_case.json`` carries the four variables and the
internal-situation table from ``~/workspace/strategy-engine/case_example.json``
(low/base/high mapped to triangular min/mode/max, with an explicit
``estimate:`` provenance reference). The expected file pins the byte-stable
serialization of the validated set plus its validation result: any change to
the model shape, the validator's checks, or the serialization order breaks
this test on purpose.
"""

from __future__ import annotations

import json
from pathlib import Path

from planagent.services.variables import VariableSet, validate_variable_set

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_prototype_case_validates_and_serializes_byte_stable() -> None:
    case = json.loads((FIXTURES / "variable_golden_case.json").read_text(encoding="utf-8"))
    variable_set = VariableSet.model_validate(case)
    result = validate_variable_set(variable_set)
    assert result.is_valid
    assert result.variable_count == 4
    assert result.issues == []

    # The prototype's values survive the port exactly.
    by_id = {variable.id: variable for variable in variable_set.variables}
    assert by_id["研发投入(人月)"].distribution.model_dump(mode="json") == {
        "type": "triangular",
        "value": None,
        "mean": None,
        "std": None,
        "min": 24.0,
        "mode": 36.0,
        "max": 60.0,
        "p": None,
    }
    assert by_id["获客成本 CAC"].distribution.mode == 12000.0
    assert by_id["AI 功能客单价 uplift"].unit == "%"
    assert by_id["12 个月客户流失率"].distribution.min == 5.0
    assert variable_set.internal["现金跑道"] == "18 个月,不接受裁员"
    assert len(variable_set.internal) == 5

    payload = {
        "variable_set": variable_set.model_dump(mode="json"),
        "validation": result.model_dump(mode="json"),
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    expected = (FIXTURES / "variable_golden_expected.json").read_text(encoding="utf-8")
    assert serialized == expected

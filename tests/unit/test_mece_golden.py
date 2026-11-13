"""Golden test: the v0.1 prototype's example case, byte-stable.

The fixture is the ``mece_tree`` + topic from the reference prototype
case (``~/workspace/strategy-engine/case_example.json``), copied
verbatim: 12 scope tags, 4 branches. The expected output is the
validator's serialized result; any change to validation semantics must
update the fixture deliberately, with review.
"""

from __future__ import annotations

import json
from pathlib import Path

from planagent.services.mece import DecompositionTree, validate_decomposition

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_golden_example_case_byte_stable() -> None:
    fixture = json.loads(
        (FIXTURES / "mece_golden_case.json").read_text(encoding="utf-8")
    )
    result = validate_decomposition(DecompositionTree.model_validate(fixture))
    serialized = (
        json.dumps(
            result.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    expected = (FIXTURES / "mece_golden_expected.json").read_text(encoding="utf-8")
    assert serialized == expected


def test_golden_example_case_summary() -> None:
    fixture = json.loads(
        (FIXTURES / "mece_golden_case.json").read_text(encoding="utf-8")
    )
    result = validate_decomposition(DecompositionTree.model_validate(fixture))
    assert result.is_mece is True
    assert result.issues == []
    assert result.scope_tag_count == 12
    assert result.branch_count == 5
    assert [(c.check, c.status) for c in result.checks] == [
        ("mutual_exclusion", "PASS"),
        ("exhaustiveness", "PASS"),
        ("structure", "PASS"),
    ]

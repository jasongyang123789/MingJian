"""Seminar contract tests (Sprint 16).

Reflection + FinalVerdict inherit the Sprint 15 _Contract base:
structured shapes coerce to canonical flat shapes, unknown keys are
forbidden, and the seminar contract version is 1.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from planagent.services.seminar.contracts import (
    SEMINAR_CONTRACT_VERSION,
    FinalVerdict,
    Reflection,
    parse_seminar_stage_output,
)
from planagent.services.skills.contracts import SkillContractError


def valid_reflection(**overrides: object) -> dict:
    payload: dict = {
        "critique": [{"weak_point": "Demand assumption untested", "reason": "No data"}],
        "responses": [
            {"model_id": "other", "stance": "oppose", "reason": "Evidence is thin"}
        ],
        "changes": [],
        "confidence": "medium",
        "confidence_basis": "Evidence is mixed.",
        "open_questions": ["What is true demand?"],
    }
    payload.update(overrides)
    return payload


def valid_verdict(**overrides: object) -> dict:
    payload: dict = {
        "recommendation": "Roll out in phases.",
        "ranked_alternatives": ["Phased rollout", "Full launch"],
        "confidence": "medium",
        "key_evidence": ["Runway is 14 months"],
        "load_bearing_assumptions": ["Demand grows 10%"],
        "kill_criteria": ["Fewer than six conversions"],
        "dissent_held": ["None"],
        "rounds_summary": "Stable across rounds.",
        "board_snapshot_seq": 4,
    }
    payload.update(overrides)
    return payload


def test_seminar_contract_version_is_1() -> None:
    assert SEMINAR_CONTRACT_VERSION == "1"


def test_reflection_validates_a_complete_payload() -> None:
    reflection = Reflection.model_validate(valid_reflection())
    assert reflection.confidence == "medium"
    assert reflection.critique[0].weak_point == "Demand assumption untested"
    assert reflection.responses[0].stance == "oppose"


def test_reflection_rejects_empty_critique_and_bad_confidence() -> None:
    with pytest.raises(ValidationError):
        Reflection.model_validate(valid_reflection(critique=[]))
    with pytest.raises(ValidationError):
        Reflection.model_validate(valid_reflection(confidence="certain"))


def test_reflection_critique_caps_at_three() -> None:
    points = [{"weak_point": f"w{i}", "reason": "r"} for i in range(4)]
    with pytest.raises(ValidationError):
        Reflection.model_validate(valid_reflection(critique=points))


def test_reflection_coerces_structured_shapes_like_skill_contracts() -> None:
    """Sprint 15 coercion applies: an object where a flat string is
    required renders deterministically instead of failing."""
    reflection = Reflection.model_validate(
        valid_reflection(confidence_basis={"basis": "mixed", "note": "thin"})
    )
    assert reflection.confidence_basis == "basis: mixed; note: thin"


def test_reflection_forbids_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        Reflection.model_validate(valid_reflection(surprise_field="x"))


def test_final_verdict_validates_a_complete_payload() -> None:
    verdict = FinalVerdict.model_validate(valid_verdict())
    assert verdict.recommendation == "Roll out in phases."
    assert verdict.board_snapshot_seq == 4


def test_final_verdict_caps_evidence_and_assumptions_at_five() -> None:
    with pytest.raises(ValidationError):
        FinalVerdict.model_validate(valid_verdict(key_evidence=[f"e{i}" for i in range(6)]))
    with pytest.raises(ValidationError):
        FinalVerdict.model_validate(
            valid_verdict(load_bearing_assumptions=[f"a{i}" for i in range(6)])
        )
    assert (
        FinalVerdict.model_validate(
            valid_verdict(key_evidence=[f"e{i}" for i in range(5)])
        ).key_evidence
        is not None
    )


def test_final_verdict_rejects_empty_dissent_held() -> None:
    """Dissent must be explicit: 'None' when the model holds none."""
    with pytest.raises(ValidationError):
        FinalVerdict.model_validate(valid_verdict(dissent_held=[]))


def test_final_verdict_forbids_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        FinalVerdict.model_validate(valid_verdict(extra="x"))


def test_parse_seminar_stage_output_rejects_non_dict_with_version_1() -> None:
    with pytest.raises(SkillContractError) as exc_info:
        parse_seminar_stage_output("seminar.reflect", ["not", "an", "object"])
    assert exc_info.value.contract_version == "1"
    assert "seminar-v1" in str(exc_info.value)


def test_parse_seminar_stage_output_rejects_contract_violations() -> None:
    with pytest.raises(SkillContractError) as exc_info:
        parse_seminar_stage_output("seminar.final_verdict", {"recommendation": "x"})
    assert exc_info.value.template_id == "seminar.final_verdict"
    assert exc_info.value.contract_version == "1"


def test_parse_seminar_stage_output_rejects_unknown_template() -> None:
    with pytest.raises(ValueError, match="No seminar output contract"):
        parse_seminar_stage_output("seminar.cluster", {})

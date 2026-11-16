"""Seminar stage contracts (Sprint 16).

Two new contracts for the seminar mechanism (design §5.1, §6):
``Reflection`` (the fixed end-of-round stage) and ``FinalVerdict``
(a model's final statement). Both inherit the Sprint 15 ``_Contract`` base,
so the mode="before" coercion (structured shapes normalized to
canonical flat shapes) and ``extra="forbid"`` apply uniformly. The
seminar contract version starts at 1 and is recorded in StageRecord
like existing stages.

These contracts are ADDITIVE: no existing template or contract is
modified, and the 17-template v2 pin is untouched.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from planagent.services.skills.contracts import SkillContractError, _Contract

SEMINAR_CONTRACT_VERSION = "1"

Confidence = Literal["low", "medium", "high"]


class CritiquePoint(_Contract):
    weak_point: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class BoardResponse(_Contract):
    model_id: str = Field(min_length=1)
    stance: Literal["agree", "oppose", "unsure"]
    reason: str = Field(min_length=1)


class Reflection(_Contract):
    """One round's reflection output (design §5.1).

    ``critique`` names the weakest points of the model's own prior
    output; ``responses`` answers each other model's latest digest;
    ``changes`` lists what moved vs the prior round (empty in round 1);
    ``confidence`` + ``confidence_basis`` state this round's confidence.
    """

    critique: list[CritiquePoint] = Field(min_length=1, max_length=3)
    responses: list[BoardResponse] = Field(default_factory=list)
    changes: list[str] = Field(default_factory=list)
    confidence: Confidence
    confidence_basis: str = Field(min_length=1)
    open_questions: list[str] = Field(default_factory=list)


class FinalVerdict(_Contract):
    """A model's final verdict (design §6 — fields exactly as specified).

    ``key_evidence`` and ``load_bearing_assumptions`` cap at 5.
    ``dissent_held`` must not be left silently empty: when the model
    holds no dissenting view it writes "None" (the template instructs
    this). ``board_snapshot_seq`` echoes the board version the model
    was shown; the service records the system-known version separately
    on the finals row.
    """

    recommendation: str = Field(min_length=1)
    ranked_alternatives: list[str] = Field(min_length=1)
    confidence: Confidence
    key_evidence: list[str] = Field(default_factory=list, max_length=5)
    load_bearing_assumptions: list[str] = Field(default_factory=list, max_length=5)
    kill_criteria: list[str] = Field(default_factory=list)
    dissent_held: list[str] = Field(min_length=1)
    rounds_summary: str = Field(min_length=1)
    board_snapshot_seq: int = Field(ge=0)


SEMINAR_CONTRACT_FOR_TEMPLATE: dict[str, type[BaseModel]] = {
    "seminar.reflect": Reflection,
    "seminar.final_verdict": FinalVerdict,
}


def parse_seminar_stage_output(template_id: str, raw: Any) -> BaseModel:
    """Validate one seminar stage's raw LLM output against its contract.

    Mirrors :func:`planagent.services.skills.contracts.parse_stage_output`
    with the seminar contract version (1). ``raw`` must be a JSON
    object; anything else, or any contract violation, raises
    :class:`SkillContractError`.
    """
    model = SEMINAR_CONTRACT_FOR_TEMPLATE.get(template_id)
    if model is None:
        raise ValueError(f"No seminar output contract registered for template {template_id!r}.")
    if not isinstance(raw, dict):
        raise SkillContractError(
            template_id,
            [{"loc": ("root",), "msg": f"expected a JSON object, got {type(raw).__name__}"}],
            contract_version=SEMINAR_CONTRACT_VERSION,
            contract_family="seminar",
        )
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        raise SkillContractError(
            template_id,
            exc.errors(),
            contract_version=SEMINAR_CONTRACT_VERSION,
            contract_family="seminar",
        ) from exc


__all__ = [
    "SEMINAR_CONTRACT_FOR_TEMPLATE",
    "SEMINAR_CONTRACT_VERSION",
    "BoardResponse",
    "CritiquePoint",
    "FinalVerdict",
    "Reflection",
    "parse_seminar_stage_output",
]

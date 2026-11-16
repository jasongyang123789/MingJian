"""Seminar stage contracts (Sprint 16–17).

Four contracts for the seminar mechanism (design §5.1, §6, §7):
``Reflection`` (the fixed end-of-round stage), ``FinalVerdict`` (a
model's final statement), ``ClaimClusters`` (the chair's semantic
clustering of verdict claims), and ``SeminarSynthesis`` (the chair's
unified synthesis). All inherit the Sprint 15 ``_Contract`` base, so
the mode="before" coercion (structured shapes normalized to canonical
flat shapes) and ``extra="forbid"`` apply uniformly. The seminar
contract version starts at 1 and is recorded in StageRecord like
existing stages.

These contracts are ADDITIVE: no existing template or contract is
modified, and the 17-template v2 pin is untouched.

Clustering shape note (design §7.1): the chair returns claims whose
sources reference deterministic pre-pass item ids (see
``clustering.py``); the service expands each source with the item's
stored facts (model, round, field, verbatim text) and builds the
merge map in code, so merge-map coverage is guaranteed by
construction rather than trusted from the model. Disagreements are
likewise DERIVED in code from mixed stances, never trusted from the
model's listing — clustering only identifies that items are the same
claim; it never resolves who is right.
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


Stance = Literal["support", "oppose", "uncertain"]


class ClusterSource(_Contract):
    """One clustered item: a pre-pass item id plus the source model's
    stance toward the canonical claim. The service expands the id to
    the item's stored facts; the model never re-states them."""

    item_id: str = Field(min_length=1)
    stance: Stance


class CanonicalClaim(_Contract):
    """One canonical claim: a normalized statement plus every original
    item merged into it. Every item id must appear in exactly one
    claim's sources (validated by the service, not the contract)."""

    claim: str = Field(min_length=1)
    sources: list[ClusterSource] = Field(min_length=1)


class ClaimClusters(_Contract):
    """The chair's semantic clustering output (design §7.1).

    ``claims`` only: the merge map and the disagreement list are
    derived in code from the claims + pre-pass items, so they cannot
    drift from what the model actually grouped.
    """

    claims: list[CanonicalClaim] = Field(default_factory=list)


class SynthesisEvidenceItem(_Contract):
    """One synthesis evidence/kill-criterion entry with provenance:
    the text must come from the clustered claims or verdicts, and
    ``source_models`` names the models it came from."""

    text: str = Field(min_length=1)
    source_models: list[str] = Field(min_length=1)


class SeminarSynthesis(_Contract):
    """The chair's unified synthesis (design §7.2).

    ``recommendation_basis`` states plainly whether the unified
    recommendation is a consensus or the chair's own judgment — the
    two wordings differ, and the report presents them distinctly.
    ``agreement_level`` is the chair's JUDGMENT, presented alongside
    (never instead of) the computed agreement metrics. ``minority_report``
    must preserve minority views verbatim, not summarized.
    """

    unified_recommendation: str = Field(min_length=1)
    recommendation_basis: Literal["consensus", "chair_judgment"]
    agreement_level: Literal["high", "moderate", "low"]
    alternatives_ranked: list[str] = Field(min_length=1)
    aggregation_rule: str = Field(min_length=1)
    key_evidence: list[SynthesisEvidenceItem] = Field(default_factory=list)
    kill_criteria: list[SynthesisEvidenceItem] = Field(default_factory=list)
    minority_report: str = Field(min_length=1)
    open_questions: list[str] = Field(default_factory=list)
    chair_notes: str = Field(min_length=1)


SEMINAR_CONTRACT_FOR_TEMPLATE: dict[str, type[BaseModel]] = {
    "seminar.reflect": Reflection,
    "seminar.final_verdict": FinalVerdict,
    "seminar.cluster": ClaimClusters,
    "seminar.synthesize": SeminarSynthesis,
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
    "CanonicalClaim",
    "ClaimClusters",
    "ClusterSource",
    "CritiquePoint",
    "FinalVerdict",
    "Reflection",
    "SeminarSynthesis",
    "Stance",
    "SynthesisEvidenceItem",
    "parse_seminar_stage_output",
]

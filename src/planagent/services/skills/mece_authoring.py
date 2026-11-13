"""MECE decomposition authoring assistance (Sprint 6, D9).

The flingjie strategic-issue-tree workflow grafted as an authoring AID:
the LLM proposes a decomposition tree, and the Sprint 1 code validator
disposes. Proposals are never trusted: every proposed tree goes through
:func:`planagent.services.mece.validator.validate_decomposition`, and a
failing tree is refused exactly like a hand-authored failing tree when
attached to a run (the existing creation gate is unchanged).

No persistence happens here: the proposal + validation verdict are
returned to the caller, who decides what to do with them.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from planagent.services.mece.models import DecompositionTree, MeceValidationResult
from planagent.services.mece.validator import validate_decomposition
from planagent.services.skills.orchestration import (
    SkillLLMPort,
    StageRecord,
    run_stage,
)

# Default suggested dimensions, adapted from the flingjie workflow's
# four-dimension checklist with original wording. They are suggestions
# only: the template instructs the model to adapt, drop, or rename them
# to fit the concrete topic.
DEFAULT_DIMENSIONS = (
    "Demand and market: who wants this, how much, and why now",
    "Internal capability and resources: what we can actually deliver",
    "Economics and value: what it costs, what it returns, and when",
    "Risk and execution: what could break it and how we would respond",
)


class MeceProposalResult(BaseModel):
    """A proposed tree, its Sprint 1 validation verdict, and provenance."""

    model_config = ConfigDict(extra="forbid")

    proposal: DecompositionTree
    validation: MeceValidationResult
    stage: StageRecord


async def propose_decomposition(
    port: SkillLLMPort,
    *,
    topic: str,
    context_lines: list[str] | None = None,
    suggested_dimensions: list[str] | None = None,
    existing_tree: DecompositionTree | None = None,
    output_language: str = "English",
) -> MeceProposalResult:
    """Propose a decomposition tree and validate it with the code validator."""
    context = "\n".join(f"- {line}" for line in (context_lines or []))
    dimensions = "\n".join(
        f"- {dimension}"
        for dimension in (suggested_dimensions or list(DEFAULT_DIMENSIONS))
    )
    existing = (
        existing_tree.model_dump_json(indent=2) if existing_tree is not None else "(none)"
    )
    record = await run_stage(
        port,
        stage="propose_tree",
        template_id="mece.propose_tree",
        inputs={
            "topic": topic,
            "context": context or "(no additional context)",
            "dimensions": dimensions,
            "existing_tree": existing,
            "output_language": output_language,
        },
    )
    proposal = DecompositionTree.model_validate(record.output)
    validation = validate_decomposition(proposal)
    return MeceProposalResult(proposal=proposal, validation=validation, stage=record)


__all__ = ["DEFAULT_DIMENSIONS", "MeceProposalResult", "propose_decomposition"]

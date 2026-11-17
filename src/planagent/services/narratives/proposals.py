"""LLM-proposed decision directions (option C, Sprint 14 follow-up).

The third direction source, alongside explicit per-request
definitions (Sprint 13) and deterministic rule derivation (Sprint
14): an LLM proposes 1-4 directions grounded in the anchor run's
stored artifacts. Proposing is an explicit user action only — no
background auto-proposal, no trigger from narrative generation
(Sprint 9 automation boundary).

Grounding discipline: the prompt context lists ONLY stored facts
(MECE branch names, scenario-family run ids with their stored
ensemble summaries, variable ids from the anchor run's bindings).
The service validates every proposal reference against the stored
artifacts and refuses the whole request before any write when any
proposal names a non-existent branch, scenario run, or variable
(see :mod:`planagent.services.narratives.service`). A proposal that
passes validation is stored as a ``direction_mappings`` row with
origin ``llm_proposal`` and status ``proposed``; it becomes usable
for generation only when a human explicitly accepts it.

The template and contract live in this package, NOT in the skills
registry — the Sprint 13 polish precedent. The skills registry's
17-template pin (``tests/unit/test_skill_templates.py``) is
untouched.

No live LLM verification is possible on this VM. Tests drive this
module through a scripted port, exactly like Sprint 6 and the
Sprint 13 polish hook. Live proposal quality is UNVERIFIED.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from planagent.services.narratives.models import MAX_DIRECTIONS
from planagent.services.skills.contracts import SkillContractError, SkillTruncatedError
from planagent.services.skills.orchestration import SkillLLMPort, SkillLLMUnavailable
from planagent.services.skills.templates import JSON_CONTRACT_MAX_TOKENS

PROPOSAL_TEMPLATE_ID = "narrative.direction_proposals"
PROPOSAL_TEMPLATE_VERSION = "1"
# Fix batch 2: proposals are small structured JSON, but the shared
# loose JSON-contract cap applies uniformly — a truncated proposal
# set is a structured failure, never a partial parse.
PROPOSAL_MAX_TOKENS = JSON_CONTRACT_MAX_TOKENS

PROPOSAL_SYSTEM_PROMPT = (
    "You propose decision directions for a strategic decision brief. "
    "You are given the decision topic, the MECE decomposition branches, "
    "the scenario-family runs with their stored Monte Carlo summaries, "
    "and the run's variable table. Propose 1 to 4 directions. "
    'Return valid JSON only, with exactly one key, "proposals": a list '
    "of 1 to 4 direction proposals. Each proposal has exactly these "
    'keys: "name", "source_run_id", "arm", "mece_branches", '
    '"key_variables", "rationale". '
    '"source_run_id" must be one of the run ids listed in the context. '
    "Never invent a run id. "
    '"arm" is "baseline" or "strategy". '
    '"mece_branches" must list at least one branch name from the '
    "context, exactly as spelled there. Never invent a branch name. "
    "Every direction must trace to at least one MECE branch. "
    '"key_variables" may only name variable ids listed in the context. '
    "Never invent a variable id. Use an empty list when no variable is "
    "central to the direction. "
    '"rationale" explains, in 1-3 sentences, why this direction '
    "deserves consideration, citing only the evidence shown in the "
    "context. Do not compute new numbers, do not quote numbers that "
    "are not in the context, and do not claim evidence the context "
    "does not contain. Direction names must be unique within one "
    "response and must be short decision labels, not sentences. "
    "Do not recommend for or against any direction beyond the "
    "rationale; the human chair decides what to accept."
)


class DirectionProposal(BaseModel):
    """One LLM-proposed direction, before grounding validation.

    Shape only: the service validates every reference (source run,
    MECE branches, variables) against stored artifacts before any
    row is written. ``mece_branches`` requires at least one entry —
    unlike inline definitions and derived mappings, a proposal must
    always trace to the MECE tree; that trace is what makes the
    proposal checkable.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    source_run_id: str = Field(min_length=1, max_length=36)
    arm: Literal["baseline", "strategy"] = "baseline"
    mece_branches: list[str] = Field(min_length=1, max_length=20)
    key_variables: list[str] = Field(default_factory=list, max_length=20)
    rationale: str = Field(min_length=1, max_length=2000)

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("mece_branches", "key_variables")
    @classmethod
    def _normalize_names(cls, names: list[str]) -> list[str]:
        normalized = [name.strip() for name in names]
        if any(not name for name in normalized):
            raise ValueError("entries must be non-empty strings")
        seen: list[str] = []
        for name in normalized:
            if name not in seen:
                seen.append(name)
        return seen


class DirectionProposals(BaseModel):
    """The LLM's proposal set: 1-4 uniquely named proposals."""

    model_config = ConfigDict(extra="forbid")

    proposals: list[DirectionProposal] = Field(min_length=1, max_length=MAX_DIRECTIONS)

    @model_validator(mode="after")
    def _check_unique_names(self) -> DirectionProposals:
        names = [proposal.name for proposal in self.proposals]
        if len(set(names)) != len(names):
            raise ValueError("proposal names must be unique within one proposal set")
        return self


@dataclass
class ProposalFamilyRun:
    """One scenario-family run with stored ensemble summaries."""

    run_id: str
    parent_run_id: str | None
    ensemble_id: str
    baseline_p50: float
    baseline_p_loss: float
    strategy_p50: float
    strategy_p_loss: float


@dataclass
class ProposalVariable:
    """One variable from the anchor run's stored bindings."""

    id: str
    unit: str
    description: str


@dataclass
class ProposalContext:
    """Everything the proposer may reference. Stored facts only."""

    topic: str
    branches: list[tuple[str, list[str]]] = field(default_factory=list)
    family_runs: list[ProposalFamilyRun] = field(default_factory=list)
    variables: list[ProposalVariable] = field(default_factory=list)
    guidance: str | None = None


def build_proposal_user_content(context: ProposalContext) -> str:
    """Render the proposal prompt's user content from stored facts.

    Pure and deterministic: the same context renders the same text.
    The context is the entire grounding surface — the model is told
    to reference nothing outside it, and the service enforces that.
    """
    lines = [f"Decision topic: {context.topic}", "", "MECE branches (name: scope tags):"]
    for name, scope in context.branches:
        lines.append(f"- {name}: {', '.join(scope) if scope else '(no scope tags)'}")
    lines.append("")
    lines.append("Scenario-family runs with stored Monte Carlo summaries:")
    for run in context.family_runs:
        lines.append(
            f"- run {run.run_id} (parent: {run.parent_run_id or 'none'}, "
            f"ensemble {run.ensemble_id}): baseline P50 {run.baseline_p50}, "
            f"loss probability {run.baseline_p_loss}; strategy P50 "
            f"{run.strategy_p50}, loss probability {run.strategy_p_loss}"
        )
    lines.append("")
    lines.append("Variables (id, unit, description):")
    if context.variables:
        for variable in context.variables:
            lines.append(
                f"- {variable.id} ({variable.unit or 'no unit'}): "
                f"{variable.description or '(no description)'}"
            )
    else:
        lines.append("- (no variables bound to the anchor run)")
    if context.guidance:
        lines.append("")
        lines.append(f"Chair guidance: {context.guidance}")
    lines.append("")
    lines.append(
        "Propose 1 to 4 decision directions. Each proposal must name a "
        "run id from the list above, an arm, at least one MECE branch "
        "name exactly as spelled above, and only variable ids from the "
        "list above."
    )
    return "\n".join(lines)


async def propose_directions(
    port: SkillLLMPort,
    user_content: str,
    *,
    max_tokens: int = PROPOSAL_MAX_TOKENS,
) -> tuple[DirectionProposals, str | None]:
    """Run one proposal pass. Returns (proposals, model name).

    Raises :class:`SkillLLMUnavailable` when no LLM is configured,
    :class:`SkillTruncatedError` when the response was cut at the
    token cap (``finish_reason="length"``), and
    :class:`SkillContractError` when the output fails the contract.
    Nothing is fabricated: an empty or malformed response is a
    structured failure, never a silent pass-through. Grounding
    validation against stored artifacts happens in the service,
    not here.
    """
    if not port.is_available():
        raise SkillLLMUnavailable("No LLM service is configured for direction proposals.")
    response = await port.generate_json(
        template_id=PROPOSAL_TEMPLATE_ID,
        system_prompt=PROPOSAL_SYSTEM_PROMPT,
        user_content=user_content,
        max_tokens=max_tokens,
    )
    if response.payload is None:
        if response.finish_reason == "length":
            raise SkillTruncatedError(PROPOSAL_TEMPLATE_ID, max_tokens=max_tokens)
        raise SkillContractError(
            PROPOSAL_TEMPLATE_ID,
            [
                {
                    "loc": ("root",),
                    "msg": ("no usable JSON response (empty, unparseable, or upstream failure)"),
                }
            ],
        )
    try:
        output = DirectionProposals.model_validate(response.payload)
    except ValidationError as exc:
        raise SkillContractError(PROPOSAL_TEMPLATE_ID, exc.errors())
    return output, response.model


__all__ = [
    "PROPOSAL_MAX_TOKENS",
    "PROPOSAL_SYSTEM_PROMPT",
    "PROPOSAL_TEMPLATE_ID",
    "PROPOSAL_TEMPLATE_VERSION",
    "DirectionProposal",
    "DirectionProposals",
    "ProposalContext",
    "ProposalFamilyRun",
    "ProposalVariable",
    "build_proposal_user_content",
    "propose_directions",
]

"""API request/response models for skill deliberations (Sprint 6, D9).

``SkillDeliberationRecord`` is both the API response shape and the
stored audit fragment on a run's summary (append-only list under
``skill_deliberations``): GET endpoints validate stored fragments back
into this model, so stored and served shapes cannot drift — the Sprint
1-5 fragment discipline, no migration.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from planagent.services.mece.models import DecompositionTree, MeceValidationResult
from planagent.services.skills.orchestration import StageRecord


def _strip_text(value: object) -> object:
    if isinstance(value, str):
        return value.strip()
    return value


class _StripMixin(BaseModel):
    @field_validator("*", mode="before")
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        return _strip_text(value)


class StrategyTeamRequest(_StripMixin):
    """Run the McKinsey strategy-team pipeline over a completed run."""

    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=1, max_length=500)
    decision_question: str = Field(default="", max_length=1000)
    context_lines: list[str] = Field(default_factory=list, max_length=50)
    mode: Literal["standard", "deep"] = "standard"
    output_language: str = Field(default="English", max_length=40)
    include_premortem: bool = True
    failure_date: str = Field(default="one year from now", max_length=120)


class AdvisoryBoardRequest(_StripMixin):
    """Run the 5-persona advisory board over a completed run."""

    model_config = ConfigDict(extra="forbid")

    decision: str = Field(min_length=1, max_length=500)
    options: list[str] = Field(default_factory=list, max_length=20)
    context_lines: list[str] = Field(default_factory=list, max_length=50)
    mode: Literal["quick", "standard"] = "standard"
    output_language: str = Field(default="English", max_length=40)


class MeceProposeRequest(_StripMixin):
    """Propose a decomposition tree (authoring aid; validator disposes)."""

    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=1, max_length=500)
    context_lines: list[str] = Field(default_factory=list, max_length=50)
    suggested_dimensions: list[str] = Field(default_factory=list, max_length=10)
    existing_tree: DecompositionTree | None = None
    output_language: str = Field(default="English", max_length=40)


class SkillDeliberationRecord(BaseModel):
    """One stored deliberation: pipeline result + audit metadata."""

    model_config = ConfigDict(extra="forbid")

    id: str
    run_id: str
    pipeline: Literal["strategy_team", "advisory_board"]
    mode: str
    created_at: str
    result: dict[str, Any]


class SkillDeliberationListRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    deliberations: list[SkillDeliberationRecord] = Field(default_factory=list)


class MeceProposalRead(BaseModel):
    """A proposed tree with its validation verdict and stage provenance."""

    model_config = ConfigDict(extra="forbid")

    proposal: DecompositionTree
    validation: MeceValidationResult
    stage: StageRecord


__all__ = [
    "AdvisoryBoardRequest",
    "MeceProposeRequest",
    "MeceProposalRead",
    "SkillDeliberationListRead",
    "SkillDeliberationRecord",
    "StrategyTeamRequest",
]

"""Snapshot + request/result models for the red-team layer (Phase 4, Track 8).

The :class:`RedTeamFinding` shape is OWNED by
:mod:`planagent.services.completeness.findings` (Phase 4, Track 10) and
re-exported here: both layers emit exactly one shape, with the
``source`` field naming which layer produced the finding, so the two
layers can never produce duplicated or contradictory outputs — a
finding is identified by (kind, target) and the merge in
:mod:`planagent.services.redteam.orchestration` dedupes on it.
(Converged on the Track 10 merge: Track 8's Literal-based copy is
deleted; the enums are str-Enums from the owner module. No test pins
the deleted max_length constraints.)

A red-team finding is a CHALLENGE to the frozen case, not a fact about
the world: it names what is missing or weakly justified, cites the
evidence inside the case snapshot that shows the gap, and proposes a
concrete fix. LLM findings are suggestions needing human review.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from planagent.services.completeness.findings import (
    BoundaryClass,
    FindingKind,
    FindingSeverity,
    FindingSource,
    RedTeamFinding,
)
from planagent.services.mece.models import DecompositionTree


def _strip_text(value: object) -> object:
    if isinstance(value, str):
        return value.strip()
    return value


class _StripMixin(BaseModel):
    @field_validator("*", mode="before")
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        return _strip_text(value)


class RedTeamVariable(_StripMixin):
    """One variable of the frozen case, as the red team sees it.

    Coverage matching (see :mod:`planagent.services.redteam.completeness`)
    scans ``name`` + ``description`` only — never free-form evidence
    text, so a passing mention of a driver inside another variable's
    evidence cannot masquerade as the driver being modelled.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    distribution: str = Field(default="", max_length=500)
    low: float | None = None
    mode: float | None = None
    high: float | None = None
    evidence: list[str] = Field(default_factory=list, max_length=20)
    notes: str = Field(default="", max_length=2000)


class RedTeamFormula(_StripMixin):
    """One transmission formula of the frozen case.

    ``expression`` is the formula text; a driver counts as LINKED when
    its name (or an alias) appears in any formula's target or
    expression. A case with no formulas has no transmission chain at
    all — every growth rate is an exogenous draw.
    """

    model_config = ConfigDict(extra="forbid")

    target: str = Field(min_length=1, max_length=200)
    expression: str = Field(min_length=1, max_length=2000)
    description: str = Field(default="", max_length=1000)


class CaseSnapshot(_StripMixin):
    """A FROZEN case snapshot: the red team's only input.

    MECE tree + variables + formulas + internal situation, as fixed at
    case-build time. The red team never sees simulation results: it
    challenges the case structure before any run exists, which is what
    makes it a pre-run gate rather than a post-hoc commentary.
    """

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=200)
    decision_question: str = Field(min_length=1, max_length=1000)
    decision_time: str = Field(default="", max_length=100)
    domain: str = Field(default="corporate", max_length=100)
    mece_tree: DecompositionTree | None = None
    variables: list[RedTeamVariable] = Field(default_factory=list, max_length=100)
    formulas: list[RedTeamFormula] = Field(default_factory=list, max_length=100)
    internal_situation: str = Field(default="", max_length=20000)
    context_lines: list[str] = Field(default_factory=list, max_length=50)


class RedTeamRequest(_StripMixin):
    """Run the red team over a snapshot (no persistence)."""

    model_config = ConfigDict(extra="forbid")

    snapshot: CaseSnapshot
    mode: Literal["auto", "live", "completeness_only"] = "auto"
    output_language: str = Field(default="Chinese", max_length=40)


class RedTeamRunRequest(_StripMixin):
    """Run the red team over a stored run's frozen configuration."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["auto", "live", "completeness_only"] = "auto"
    output_language: str = Field(default="Chinese", max_length=40)


class RedTeamResult(BaseModel):
    """The merged red-team outcome for one snapshot."""

    model_config = ConfigDict(extra="forbid")

    pipeline: Literal["red_team"] = "red_team"
    case_id: str
    mode: Literal["auto", "live", "completeness_only"]
    llm_available: bool
    llm_source: Literal["red_team_llm", "red_team_fixture", "none"]
    findings: list[RedTeamFinding] = Field(default_factory=list)
    counts_by_severity: dict[str, int] = Field(default_factory=dict)
    counts_by_kind: dict[str, int] = Field(default_factory=dict)
    stages: list[dict[str, Any]] = Field(default_factory=list)
    template_version: str
    contract_version: str
    disclaimer: str


class RedTeamRecord(BaseModel):
    """One stored red-team run: result + audit metadata (fragment discipline)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    run_id: str
    pipeline: Literal["red_team"] = "red_team"
    mode: str
    created_at: str
    result: dict[str, Any]


class RedTeamListRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    red_team_runs: list[RedTeamRecord] = Field(default_factory=list)


__all__ = [
    "BoundaryClass",
    "CaseSnapshot",
    "FindingKind",
    "FindingSeverity",
    "FindingSource",
    "RedTeamFinding",
    "RedTeamFormula",
    "RedTeamListRead",
    "RedTeamRecord",
    "RedTeamRequest",
    "RedTeamResult",
    "RedTeamRunRequest",
    "RedTeamVariable",
]

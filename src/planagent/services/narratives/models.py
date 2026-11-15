"""Models for decision-direction narratives (Sprint 13).

Provenance taxonomy — every content section of the artifact carries
one of exactly three marks:

- ``computed``: derived from stored numbers (ensembles, robustness
  results, gate evaluations, threshold searches, loop triggers,
  calibration fits, MECE trees).
- ``deliberated``: quoted verbatim from a stored skill-deliberation
  output, always citing the deliberation id + pipeline + template.
- ``template``: fixed composer wording, explicitly marked as such.
  Template text never pretends to be analysis: it states what is
  absent (e.g. "no pre-mortem deliberation exists") and names the
  endpoint that would produce it.

The artifact body carries no id, version, or timestamp: those live
on the stored row, so the body — and its content hash — is a pure
function of the inputs. Same inputs compose byte-identical bodies.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NARRATIVE_PROTOCOL_VERSION = "sprint13-v1"

#: Maximum directions per narrative (the MVP prototype's 3-4 shape).
MAX_DIRECTIONS = 4

#: Tornado rows carried per direction (Sprint 6 context cap: top 5).
MAX_DRIVER_ROWS = 5

#: Calibration fits carried in the header context (Sprint 6 cap).
MAX_CALIBRATION_FITS_IN_CONTEXT = 5

ProvenanceKind = Literal["computed", "deliberated", "template"]


class NarrativeError(ValueError):
    """A client-visible narrative failure with a stable error code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


# ---------------------------------------------------------------------------
# Generation request
# ---------------------------------------------------------------------------


class DirectionDefinition(BaseModel):
    """One user-supplied direction definition.

    The codebase has no direction source: ``DecisionOption`` rows carry
    no link to ensembles, scenario branches carry no direction
    semantics, and deliberation option names link to no run or arm.
    Directions therefore come only from explicit definitions in the
    generation request. Each definition names the direction and points
    at the stored artifacts it draws on; the request model enforces
    the shape and the service validates every reference before any
    row is written.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    source_run_id: str = Field(min_length=1, max_length=36)
    arm: Literal["baseline", "strategy"] = "baseline"
    mece_branches: list[str] = Field(default_factory=list, max_length=20)
    deliberation_id: str | None = Field(default=None, max_length=36)

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("mece_branches")
    @classmethod
    def _normalize_branches(cls, branches: list[str]) -> list[str]:
        normalized = [branch.strip() for branch in branches]
        if any(not branch for branch in normalized):
            raise ValueError("mece_branches entries must be non-empty strings")
        seen: list[str] = []
        for branch in normalized:
            if branch not in seen:
                seen.append(branch)
        return seen


class NarrativeGenerateRequest(BaseModel):
    """Generate a decision-direction narrative for a run."""

    model_config = ConfigDict(extra="forbid")

    topic: str | None = Field(default=None, max_length=500)
    directions: list[DirectionDefinition] = Field(min_length=1, max_length=MAX_DIRECTIONS)
    loop_id: str | None = Field(default=None, max_length=36)

    @field_validator("topic", mode="before")
    @classmethod
    def _normalize_topic(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @model_validator(mode="after")
    def _check_unique_names(self) -> NarrativeGenerateRequest:
        names = [direction.name for direction in self.directions]
        if len(set(names)) != len(names):
            raise ValueError("direction names must be unique within one narrative")
        return self


# ---------------------------------------------------------------------------
# Artifact body: per-direction sections
# ---------------------------------------------------------------------------


class DistributionSection(BaseModel):
    """Outcome distribution for one direction (computed)."""

    model_config = ConfigDict(extra="forbid")

    provenance: Literal["computed"] = "computed"
    run_id: str
    ensemble_id: str
    metric: str
    loss_threshold: float
    trials: int
    seed: int
    arm: Literal["baseline", "strategy"]
    n: int
    mean: float
    min: float
    max: float
    p10: float
    p50: float
    p90: float
    stddev: float
    p_loss: float
    expected_shortfall: dict[str, Any] | None = None
    bootstrap_intervals: list[dict[str, Any]] = Field(default_factory=list)
    trial_values_hash: str | None = None


class DriverRow(BaseModel):
    """One tornado row carried as a key driver (computed)."""

    model_config = ConfigDict(extra="forbid")

    variable: str
    low_value: float
    high_value: float
    outcome_low: float
    outcome_high: float
    swing: float


class DriversSection(BaseModel):
    """Key drivers from the stored tornado analysis (computed)."""

    model_config = ConfigDict(extra="forbid")

    provenance: Literal["computed"] = "computed"
    rows: list[DriverRow] = Field(default_factory=list)
    ensemble_id: str | None = None
    note: str | None = None


class TripwireSignal(BaseModel):
    """One tripwire / turn signal, labeled with its source."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "decision_gate",
        "threshold_search",
        "loop_trigger",
        "advisory_contract",
        "wargame_playbook",
    ]
    provenance: ProvenanceKind
    text: str
    source_ids: dict[str, str] = Field(default_factory=dict)
    name: str | None = None
    metric: str | None = None
    operator: str | None = None
    threshold: float | None = None
    observed: float | None = None
    passed: bool | None = None


class FailureModeQuote(BaseModel):
    """One pre-mortem failure mode, quoted from a deliberation."""

    model_config = ConfigDict(extra="forbid")

    mode: str
    cause: str
    early_signal: str
    prevention: str


class PremortemSection(BaseModel):
    """Pre-mortem: deliberated quote, or an explicit template notice."""

    model_config = ConfigDict(extra="forbid")

    provenance: Literal["deliberated", "template"]
    deliberation_id: str | None = None
    template_id: str | None = None
    failure_narrative: str | None = None
    failure_modes: list[FailureModeQuote] = Field(default_factory=list)
    fatal_flags: list[str] = Field(default_factory=list)
    note: str | None = None


class FirstStepSection(BaseModel):
    """48-hour first step: deliberated quote, or an explicit template notice."""

    model_config = ConfigDict(extra="forbid")

    provenance: Literal["deliberated", "template"]
    deliberation_id: str | None = None
    template_id: str | None = None
    next_action: str | None = None
    cheapest_validation_test: str | None = None
    conditions: list[str] = Field(default_factory=list)
    note: str | None = None


class MeceBranchTrace(BaseModel):
    """One MECE branch a direction traces to, with its scope tags."""

    model_config = ConfigDict(extra="forbid")

    name: str
    scope: list[str] = Field(default_factory=list)


class MeceTrace(BaseModel):
    """MECE trace for one direction (computed from the stored tree)."""

    model_config = ConfigDict(extra="forbid")

    provenance: Literal["computed"] = "computed"
    branches: list[MeceBranchTrace] = Field(default_factory=list)
    tree_topic: str


class DirectionNarrative(BaseModel):
    """One composed direction, ranked by P50 descending (ties by name)."""

    model_config = ConfigDict(extra="forbid")

    rank: int
    name: str
    source_run_id: str
    arm: Literal["baseline", "strategy"]
    distribution: DistributionSection
    drivers: DriversSection
    signals: list[TripwireSignal] = Field(default_factory=list)
    signals_note: str | None = None
    premortem: PremortemSection
    first_step: FirstStepSection
    mece_trace: MeceTrace | None = None
    mece_note: str | None = None


# ---------------------------------------------------------------------------
# Artifact body: header context
# ---------------------------------------------------------------------------


class MeceContext(BaseModel):
    """Stored MECE tree summary for the anchor run (computed)."""

    model_config = ConfigDict(extra="forbid")

    provenance: Literal["computed"] = "computed"
    topic: str
    is_mece: bool
    branch_count: int
    scope_tag_count: int
    issue_count: int


class CalibrationContextEntry(BaseModel):
    """One calibration fit visible at generation time (computed)."""

    model_config = ConfigDict(extra="forbid")

    fit_id: str
    kind: str
    loo_rmse: float | None = None
    inputs_hash: str
    calibrated_template_id: str | None = None
    n_observations: int
    created_at: str


class LoopContext(BaseModel):
    """Monitoring loop context when a loop id is supplied (computed)."""

    model_config = ConfigDict(extra="forbid")

    provenance: Literal["computed"] = "computed"
    loop_id: str
    loop_name: str
    registration_id: str | None = None
    trigger_count: int = 0


class NarrativeBody(BaseModel):
    """The deterministic artifact body: pure function of the inputs.

    Carries no id, version, or timestamp — those live on the stored
    row — so ``content_hash`` (SHA-256 of the canonical JSON of this
    body) is stable across regenerations with identical inputs.
    """

    model_config = ConfigDict(extra="forbid")

    protocol: str = NARRATIVE_PROTOCOL_VERSION
    anchor_run_id: str
    domain_id: str
    topic: str
    topic_source: Literal["request", "mece_tree", "run_id"]
    mece: MeceContext | None = None
    calibration_context: list[CalibrationContextEntry] = Field(default_factory=list)
    loop_context: LoopContext | None = None
    directions: list[DirectionNarrative] = Field(min_length=1)
    markdown: str


# ---------------------------------------------------------------------------
# Stored rows + read shapes
# ---------------------------------------------------------------------------


class NarrativePolishRead(BaseModel):
    """One stored LLM polish pass over a narrative (append-only)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    narrative_id: str
    model: str | None = None
    template_id: str
    template_version: str
    polished_markdown: str
    created_at: str


class DecisionNarrativeRead(BaseModel):
    """A stored narrative version with its latest polish, if any."""

    model_config = ConfigDict(extra="forbid")

    id: str
    run_id: str
    version: int
    topic: str
    inputs_hash: str
    content_hash: str
    created_at: str
    body: NarrativeBody
    polish: NarrativePolishRead | None = None


class DecisionNarrativeListRead(BaseModel):
    """Narrative versions for one run, newest first."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    narratives: list[DecisionNarrativeRead] = Field(default_factory=list)


__all__ = [
    "MAX_CALIBRATION_FITS_IN_CONTEXT",
    "MAX_DIRECTIONS",
    "MAX_DRIVER_ROWS",
    "NARRATIVE_PROTOCOL_VERSION",
    "CalibrationContextEntry",
    "DecisionNarrativeListRead",
    "DecisionNarrativeRead",
    "DirectionDefinition",
    "DirectionNarrative",
    "DistributionSection",
    "DriverRow",
    "DriversSection",
    "FailureModeQuote",
    "FirstStepSection",
    "LoopContext",
    "MeceBranchTrace",
    "MeceContext",
    "MeceTrace",
    "NarrativeBody",
    "NarrativeError",
    "NarrativeGenerateRequest",
    "NarrativePolishRead",
    "PremortemSection",
    "ProvenanceKind",
    "TripwireSignal",
]

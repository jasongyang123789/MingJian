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

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from planagent.services.variables.models import MAX_VARIABLES

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


class DirectionError(ValueError):
    """A client-visible direction-derivation/mapping failure.

    Stable error code, same shape as :class:`NarrativeError`; the
    routes map it to 400 with a ``{"code", "message"}`` detail.
    """

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
    """Generate a decision-direction narrative for a run.

    ``directions`` is optional since Sprint 14: when omitted, the
    service resolves direction definitions from the anchor run's
    stored direction mappings (position order, capped at
    ``MAX_DIRECTIONS``). Inline definitions always win over stored
    mappings. An explicitly empty list is still refused, as before.
    """

    model_config = ConfigDict(extra="forbid")

    topic: str | None = Field(default=None, max_length=500)
    directions: list[DirectionDefinition] | None = Field(
        default=None, min_length=1, max_length=MAX_DIRECTIONS
    )
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
        if self.directions is None:
            return self
        names = [direction.name for direction in self.directions]
        if len(set(names)) != len(names):
            raise ValueError("direction names must be unique within one narrative")
        return self


# ---------------------------------------------------------------------------
# Direction mappings (Sprint 14, Part D)
# ---------------------------------------------------------------------------


class DirectionMappingCreate(DirectionDefinition):
    """Author one persisted direction definition for an anchor run.

    Same shape and validation as an inline
    :class:`DirectionDefinition`: the mapping is exactly a stored
    definition, reusable across generations. The service validates
    every reference (source run, ensemble, MECE branches,
    deliberation pin) before any row is written.
    """


class DirectionMappingUpdate(BaseModel):
    """Update a persisted direction mapping.

    Every field is optional: omitted fields are left unchanged. An
    explicitly supplied ``deliberation_id`` of null clears the pin;
    an explicitly supplied empty ``mece_branches`` clears the trace.
    Explicit nulls for ``name``, ``source_run_id``, ``arm``, or
    ``mece_branches`` are refused (422): use omission to leave a
    field unchanged. Any successful update marks the mapping
    ``user_edited``, which protects it from later derivation
    upserts (the no-clobber rule).
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    source_run_id: str | None = Field(default=None, min_length=1, max_length=36)
    arm: Literal["baseline", "strategy"] | None = None
    mece_branches: list[str] | None = Field(default=None, max_length=20)
    deliberation_id: str | None = Field(default=None, max_length=36)

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("mece_branches")
    @classmethod
    def _normalize_branches(cls, branches: list[str] | None) -> list[str] | None:
        if branches is None:
            return None
        normalized = [branch.strip() for branch in branches]
        if any(not branch for branch in normalized):
            raise ValueError("mece_branches entries must be non-empty strings")
        seen: list[str] = []
        for branch in normalized:
            if branch not in seen:
                seen.append(branch)
        return seen

    @model_validator(mode="after")
    def _reject_explicit_nulls(self) -> DirectionMappingUpdate:
        for field_name in ("name", "source_run_id", "arm", "mece_branches"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} must not be null; omit it to leave unchanged")
        return self


class DirectionMappingRead(BaseModel):
    """One stored direction mapping.

    ``origin`` records how the row was written: ``derived`` (Sprint
    14 rules), ``authored`` (a user), ``llm_proposal`` (option C:
    an LLM proposal), or ``override`` (option B: a variable
    override that created a scenario-branch run, with the
    override spec pinned in ``override_record``). ``status`` is
    the review state: ``active`` rows are usable for generation;
    ``proposed`` rows await an explicit human accept/reject;
    ``rejected`` rows are retained for audit and never used. All
    pre-option-C rows are ``active``.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    anchor_run_id: str
    name: str
    source_run_id: str
    arm: Literal["baseline", "strategy"]
    mece_branches: list[str] = Field(default_factory=list)
    deliberation_id: str | None = None
    origin: Literal["derived", "authored", "llm_proposal", "override"]
    rule_id: str | None = None
    rules_version: str | None = None
    rule_record: dict[str, Any] | None = None
    status: Literal["active", "proposed", "rejected"]
    proposal_record: dict[str, Any] | None = None
    override_record: dict[str, Any] | None = None
    user_edited: bool
    position: int
    created_at: str
    updated_at: str


class DirectionMappingListRead(BaseModel):
    """Direction mappings for one anchor run, in position order."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    mappings: list[DirectionMappingRead] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Derivation outcomes (Sprint 14, Part A)
# ---------------------------------------------------------------------------

#: Derivation rule identifiers, in evaluation order.
DERIVATION_RULE_IDS = ("highest_p50", "most_robust", "baseline_control")

#: Mechanical direction names produced by each rule. Renaming is the
#: mapping layer's job (Part D); derivation never invents names.
DERIVATION_RULE_NAMES = {
    "highest_p50": "Highest P50",
    "most_robust": "Most robust",
    "baseline_control": "Baseline",
}


class DerivationRuleOutcome(BaseModel):
    """One rule's outcome in a derivation run.

    Every rule gets an outcome: ``produced`` (a direction was
    selected), ``none`` (no candidate qualified, with the reason),
    ``duplicate`` (the selected candidate was already taken by an
    earlier rule), or ``skipped`` (persistence refused to overwrite
    a user-edited mapping of the same name — the no-clobber rule).
    The deciding statistics are pinned on produced outcomes so the
    selection is auditable without re-running the derivation.
    """

    model_config = ConfigDict(extra="forbid")

    rule_id: Literal["highest_p50", "most_robust", "baseline_control"]
    status: Literal["produced", "none", "duplicate", "skipped"]
    reason: str
    direction_name: str | None = None
    source_run_id: str | None = None
    arm: Literal["baseline", "strategy"] | None = None
    duplicate_of_rule: str | None = None
    p50: float | None = None
    p_loss: float | None = None
    expected_shortfall: float | None = None
    expected_shortfall_alpha: float | None = None


class DerivationRead(BaseModel):
    """A derivation run: rule outcomes plus the mappings it wrote."""

    model_config = ConfigDict(extra="forbid")

    anchor_run_id: str
    rules_version: str
    derivation_hash: str
    family_size: int
    candidates_considered: int
    outcomes: list[DerivationRuleOutcome] = Field(default_factory=list)
    mappings: list[DirectionMappingRead] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# LLM-proposed directions (option C)
# ---------------------------------------------------------------------------


class DirectionProposeRequest(BaseModel):
    """Request one LLM proposal pass for an anchor run.

    ``guidance`` is optional free text from the chair, passed to the
    proposer verbatim (e.g. "favor low-cash-exposure directions").
    It never overrides grounding: proposals are still validated
    against the stored artifacts, whatever the guidance says.
    """

    model_config = ConfigDict(extra="forbid")

    guidance: str | None = Field(default=None, max_length=2000)

    @field_validator("guidance", mode="before")
    @classmethod
    def _normalize_guidance(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class ProposalOutcome(BaseModel):
    """One proposal's outcome in a proposal run.

    ``stored``: the proposal passed grounding validation and was
    written as a ``proposed`` mapping (``mapping_id`` set).
    ``skipped``: a mapping of the same name already exists — the
    proposal never overwrites anything, and the existing row is
    left untouched (the no-clobber rule, extended to proposals).
    Ungrounded proposals never reach this list: they refuse the
    whole request before any write.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    status: Literal["stored", "skipped"]
    reason: str
    mapping_id: str | None = None
    source_run_id: str
    arm: Literal["baseline", "strategy"]
    mece_branches: list[str] = Field(default_factory=list)


class DirectionProposeRead(BaseModel):
    """A proposal run: per-proposal outcomes plus the mappings."""

    model_config = ConfigDict(extra="forbid")

    anchor_run_id: str
    template_id: str
    template_version: str
    model: str | None
    proposal_hash: str
    family_runs_considered: int
    outcomes: list[ProposalOutcome] = Field(default_factory=list)
    mappings: list[DirectionMappingRead] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Variable-override directions (option B, Sprint 14 follow-up)
# ---------------------------------------------------------------------------


def _require_override_value(value: object) -> float:
    """Coerce an override value to a finite float.

    Same discipline as the variable-table models: strings are
    rejected (silently coercing ``"12"`` would hide authoring
    mistakes); booleans, NaN, and infinities are rejected too.
    Raises ``ValueError`` so Pydantic ``before`` validators
    surface it as a ``ValidationError``.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(  # noqa: TRY004 — Pydantic requires ValueError here
            "override values must be finite numbers"
        )
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("override values must be finite numbers")
    return result


class DirectionOverrideSpec(BaseModel):
    """One direction-as-override in an override request.

    ``overrides`` maps bound variable ids to fixed values: the
    child run samples each named variable at exactly that value.
    Keys are stripped; an empty key, a key collision after
    stripping, or a non-finite value refuses the request (422).
    At least one override is required: an empty override set
    would create a run identical to the anchor. ``fork_step``
    names the anchor tick the child run forks from; omitted, the
    scenario-branch midpoint default applies.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    overrides: dict[str, float] = Field(min_length=1, max_length=MAX_VARIABLES)
    arm: Literal["baseline", "strategy"] = "baseline"
    mece_branches: list[str] = Field(default_factory=list, max_length=20)
    fork_step: int | None = Field(default=None, ge=1)

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("overrides", mode="before")
    @classmethod
    def _normalize_overrides(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        normalized: dict[str, float] = {}
        for raw_key, raw_value in value.items():
            key = raw_key.strip() if isinstance(raw_key, str) else raw_key
            if not isinstance(key, str) or not key:
                raise ValueError("override keys must be non-empty strings")
            if key in normalized:
                raise ValueError(f"override key {key!r} is duplicated after stripping")
            normalized[key] = _require_override_value(raw_value)
        return normalized

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


class DirectionOverrideRequest(BaseModel):
    """An override run: 1-4 uniquely named direction specs."""

    model_config = ConfigDict(extra="forbid")

    directions: list[DirectionOverrideSpec] = Field(min_length=1, max_length=MAX_DIRECTIONS)

    @model_validator(mode="after")
    def _check_unique_names(self) -> DirectionOverrideRequest:
        names = [spec.name for spec in self.directions]
        if len(set(names)) != len(names):
            raise ValueError("direction names must be unique within one override request")
        return self


class DirectionOverrideOutcome(BaseModel):
    """One direction's outcome in an override run.

    ``stored``: the child run was created and the direction was
    written as an ``active`` mapping (``mapping_id``,
    ``branch_id``, and ``child_run_id`` set). The child run has
    no ensemble yet: run the monte-carlo endpoint named in the
    reason before generating from it. ``skipped``: a mapping of
    the same name already exists — no branch run was created and
    the existing row is left untouched (the no-clobber rule).
    ``failed``: the branch run could not be created after all
    upfront validation passed; the reason carries the failure,
    and the other directions in the request are unaffected.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    status: Literal["stored", "skipped", "failed"]
    reason: str
    mapping_id: str | None = None
    branch_id: str | None = None
    child_run_id: str | None = None
    fork_step: int | None = None
    child_status: str | None = None
    arm: Literal["baseline", "strategy"]
    mece_branches: list[str] = Field(default_factory=list)


class DirectionOverrideRead(BaseModel):
    """An override run: per-direction outcomes plus the mappings."""

    model_config = ConfigDict(extra="forbid")

    anchor_run_id: str
    override_hash: str
    directions_considered: int
    outcomes: list[DirectionOverrideOutcome] = Field(default_factory=list)
    mappings: list[DirectionMappingRead] = Field(default_factory=list)


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
    """A stored narrative version with its latest polish, if any.

    ``direction_mapping_ids`` names the stored mappings the
    generation resolved its directions from (Sprint 14); empty when
    the request carried inline definitions, or for versions stored
    before Sprint 14.
    """

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
    direction_mapping_ids: list[str] = Field(default_factory=list)


class DecisionNarrativeListRead(BaseModel):
    """Narrative versions for one run, newest first."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    narratives: list[DecisionNarrativeRead] = Field(default_factory=list)


__all__ = [
    "DERIVATION_RULE_IDS",
    "DERIVATION_RULE_NAMES",
    "MAX_CALIBRATION_FITS_IN_CONTEXT",
    "MAX_DIRECTIONS",
    "MAX_DRIVER_ROWS",
    "NARRATIVE_PROTOCOL_VERSION",
    "CalibrationContextEntry",
    "DecisionNarrativeListRead",
    "DecisionNarrativeRead",
    "DerivationRead",
    "DerivationRuleOutcome",
    "DirectionDefinition",
    "DirectionError",
    "DirectionMappingCreate",
    "DirectionMappingListRead",
    "DirectionMappingRead",
    "DirectionMappingUpdate",
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

"""Living-strategy loop models (Sprint 9).

Dependency-free Pydantic models for the monitor → re-simulate loop,
mirroring the MECE/variables/distributions/robustness modules. The loop
is the audit trail for a decision kept alive over time: a baseline run,
recorded observations of what actually happened, pre-registered
triggers evaluated against those observations, explicit re-simulations
with an honestly advancing evidence cutoff, distribution-vs-distribution
comparisons, and recorded review decisions.

Every model here is both an API shape and a stored shape: iteration
records validate their stored JSON back into these models, so stored
and served shapes cannot drift. Statistics are full precision; display
rounding lives in the frontend only.
"""

from __future__ import annotations

import math
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from planagent.services.distributions.models import DistributionSummary
from planagent.services.robustness.models import GateDefinition, GateMetric, GateOutcome
from planagent.services.variables.models import VariableSet

MAX_TRIGGERS_PER_REGISTRATION = 20
MAX_OBSERVATIONS_PER_WINDOW = 10_000


def _require_finite_number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("must be a finite number")
    return result


class TriggerKind(str, Enum):
    """What a loop trigger tests against observed data."""

    THRESHOLD = "threshold"
    GATE = "gate"
    DEVIATION = "deviation"


class ThresholdTrigger(BaseModel):
    """Fire when the latest observed value breaches a threshold."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["threshold"] = "threshold"
    name: str = Field(min_length=1, max_length=120)
    field: str = Field(min_length=1, max_length=120)
    operator: Literal[">", ">=", "<", "<="]
    threshold: float

    @field_validator("name", "field", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("threshold", mode="before")
    @classmethod
    def _validate_threshold(cls, value: object) -> float:
        return _require_finite_number(value)


class GateTrigger(BaseModel):
    """A Sprint 4 gate definition evaluated against observed data.

    The gate statistic (mean, p50, p_loss, expected shortfall, ...) is
    computed over the window's observed values of ``field`` — the same
    pure statistic the gate would test on trial values, applied to
    actuals instead. Paired metrics cannot be evaluated against
    observations (actuals have no baseline/strategy arms) and are
    refused; the arm must be ``baseline`` for the same reason. Gate
    re-evaluation against a new ensemble (where paired metrics do
    apply) happens in the comparison step, not here.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["gate"] = "gate"
    name: str = Field(min_length=1, max_length=120)
    field: str = Field(min_length=1, max_length=120)
    gate: GateDefinition
    loss_threshold: float | None = None

    @field_validator("name", "field", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("loss_threshold", mode="before")
    @classmethod
    def _validate_loss_threshold(cls, value: object) -> float | None:
        if value is None:
            return None
        return _require_finite_number(value)

    @model_validator(mode="after")
    def _check_observable(self) -> GateTrigger:
        if self.gate.metric in (GateMetric.MEAN_DELTA, GateMetric.P_STRATEGY_BETTER):
            raise ValueError(
                f"Metric {self.gate.metric.value!r} is a paired statistic and cannot "
                "be evaluated against observations."
            )
        if self.gate.arm.value != "baseline":
            raise ValueError(
                "Gate triggers evaluate observed data, which has no arms; "
                f"arm must be 'baseline', got {self.gate.arm.value!r}."
            )
        if self.gate.metric is GateMetric.P_LOSS and self.loss_threshold is None:
            raise ValueError("A p_loss gate trigger requires loss_threshold.")
        return self


class DeviationTrigger(BaseModel):
    """Fire on repeated deviation from what the baseline predicted.

    The PwC "repeated deviations should pause" signal: each observation
    in the window is compared against a reference value, and the
    trigger fires only when ``consecutive`` successive observations
    (in observed_at order) each deviate by more than ``tolerance``.
    A single stray reading never fires it. The reference defaults to
    the baseline run's final-state value for ``field``; an explicit
    ``reference_value`` overrides it and is recorded as such.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["deviation"] = "deviation"
    name: str = Field(min_length=1, max_length=120)
    field: str = Field(min_length=1, max_length=120)
    tolerance: float = Field(gt=0.0)
    consecutive: int = Field(default=1, ge=1, le=100)
    reference_value: float | None = None

    @field_validator("name", "field", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("tolerance", "reference_value", mode="before")
    @classmethod
    def _validate_numbers(cls, value: object) -> float | None:
        if value is None:
            return None
        return _require_finite_number(value)


LoopTriggerDefinition = Annotated[
    ThresholdTrigger | GateTrigger | DeviationTrigger,
    Field(discriminator="kind"),
]


class TriggerRegistrationRequest(BaseModel):
    """Register a set of triggers on a loop.

    ``supersedes`` names a previous registration this one replaces; the
    old registration is retained with status ``superseded`` — trigger
    registrations are append-only, never edited or deleted, exactly
    like Sprint 4 gate registrations.
    """

    model_config = ConfigDict(extra="forbid")

    triggers: list[LoopTriggerDefinition] = Field(
        min_length=1, max_length=MAX_TRIGGERS_PER_REGISTRATION
    )
    supersedes: str | None = None


class TriggerRegistration(BaseModel):
    """A registered trigger set, stored immutably on the loop.

    ``observation_count_at_registration`` is the checkable
    pre-registration evidence, mirroring the gate discipline: a
    registration made before any observations existed is genuinely
    pre-registered; one made after observations exist says so in the
    count, and no claim of pre-registration is asserted beyond it.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    loop_id: str
    triggers: list[LoopTriggerDefinition]
    supersedes: str | None = None
    registered_at: str
    observation_count_at_registration: int
    status: Literal["active", "superseded"] = "active"


class LoopObservationCreate(BaseModel):
    """Record one observed actual against a loop.

    Observations are the monitoring seam: there is no existing numeric
    actuals-ingestion path in the codebase (claims are textual), so
    actuals are recorded explicitly, with their observation time and
    an optional link to the evidence claim they came from. The
    observation time — not the recording time — decides which review
    window an observation falls in.
    """

    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=120)
    value: float
    observed_at: datetime
    source_claim_id: str | None = None
    source_note: str | None = Field(default=None, max_length=500)

    @field_validator("field", mode="before")
    @classmethod
    def _strip_field(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("value", mode="before")
    @classmethod
    def _validate_value(cls, value: object) -> float:
        return _require_finite_number(value)

    @field_validator("source_note", mode="before")
    @classmethod
    def _strip_note(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value


class LoopObservationRead(BaseModel):
    """A stored observation. Timestamps are canonical cutoff strings."""

    model_config = ConfigDict(extra="forbid")

    id: str
    loop_id: str
    field: str
    value: float
    observed_at: str
    source_claim_id: str | None = None
    source_note: str | None = None
    recorded_at: str


class TriggerEvaluationOutcome(BaseModel):
    """One trigger's evaluation against one review window.

    ``status`` distinguishes a trigger that fired, a trigger that was
    evaluated and stayed quiet, and a trigger that could not be
    evaluated because the window held no observations for its field.
    Quiet rounds and no-data rounds are recorded, not skipped: they
    are evidence about the monitoring itself.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    kind: TriggerKind
    field: str
    fired: bool
    status: Literal["fired", "quiet", "no_data"]
    observed_value: float | None = None
    threshold: float | None = None
    tolerance: float | None = None
    reference_value: float | None = None
    consecutive_breaches: int | None = None
    observation_ids: list[str] = Field(default_factory=list)
    observed_values: list[float] = Field(default_factory=list)
    note: str


class StrategyLoopCreate(BaseModel):
    """Create a living-strategy loop from a completed run."""

    model_config = ConfigDict(extra="forbid")

    baseline_run_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=200)
    triggers: list[LoopTriggerDefinition] = Field(
        default_factory=list, max_length=MAX_TRIGGERS_PER_REGISTRATION
    )

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class StrategyLoopRead(BaseModel):
    """A loop with its trigger registrations (active and superseded)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    baseline_run_id: str
    domain_id: str
    status: Literal["active"] = "active"
    triggers: list[TriggerRegistration] = Field(default_factory=list)
    created_at: str
    updated_at: str


class StartIterationRequest(BaseModel):
    """Open a review iteration. ``decision_time`` becomes the new
    evidence cutoff for any re-simulation in this iteration, so it
    must advance past the previous cutoff — the service enforces it.
    """

    model_config = ConfigDict(extra="forbid")

    decision_time: datetime


class ResimulateRequest(BaseModel):
    """Explicit changes for a re-simulation, all optional.

    Anything not named is inherited from the baseline run's stored
    configuration (decomposition, template/bindings, seed, tick
    count). Every named change is recorded on the iteration; nothing
    changes silently. A template override names a stored template or
    a built-in preset id — it is resolved by the run-creation gate
    exactly as for a hand-created run, so an unknown id refuses the
    re-simulation before any row is written.
    """

    model_config = ConfigDict(extra="forbid")

    variable_template_id: str | None = None
    variable_set: VariableSet | None = None
    seed: int | None = None
    tick_count: int | None = Field(default=None, ge=1)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("note", mode="before")
    @classmethod
    def _strip_note(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value


class ResimulationRecord(BaseModel):
    """The audit record of one re-simulation.

    Both evidence cutoffs and both input hashes are stored: the input
    hash differs by design (the cutoff is part of the hashed inputs,
    per the Sprint 5 precedent), and the record shows why. Template
    snapshot hashes pin what the baseline carried versus what the
    re-simulation resolved, so template drift between reviews is
    detectable.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str
    previous_cutoff: str | None = None
    new_cutoff: str
    previous_input_hash: str | None = None
    new_input_hash: str | None = None
    template_id: str | None = None
    template_snapshot_hash: str | None = None
    resolved_template_snapshot_hash: str | None = None
    seed: int
    tick_count: int
    changes: dict = Field(default_factory=dict)
    claims_visible: int
    claims_excluded: int
    created_at: str


class ArmDelta(BaseModel):
    """Old-vs-new distribution summary for one ensemble arm."""

    model_config = ConfigDict(extra="forbid")

    arm: Literal["baseline", "strategy"]
    old: DistributionSummary
    new: DistributionSummary
    delta_p10: float
    delta_p50: float
    delta_p90: float
    delta_mean: float
    delta_p_loss: float


class GateReevaluation(BaseModel):
    """The baseline's gates re-evaluated on the new ensemble.

    Computed purely from the new trial values; the new run's own
    audit trail is not mutated. ``pre_registered`` uses the Sprint 4
    formula: the registration predates the evaluated ensemble.
    """

    model_config = ConfigDict(extra="forbid")

    registration_id: str
    ensemble_id: str
    outcomes: list[GateOutcome]
    all_passed: bool
    pre_registered: bool


class ThresholdDriftRow(BaseModel):
    """One threshold search present on both runs, old vs new."""

    model_config = ConfigDict(extra="forbid")

    variable: str
    mode: Literal["p_loss", "arm_flip"]
    old_threshold: float | None = None
    old_reachable: bool
    new_threshold: float | None = None
    new_reachable: bool


class EnsembleComparison(BaseModel):
    """Distribution-vs-distribution comparison between iterations.

    ``seeds_paired`` is true only when both ensembles used the same
    seed and trial count; even then, ``evidence_caveat`` states
    plainly that the evidence sets differ between iterations, so
    paired draws do not make the comparison a pure sampling
    comparison. The baseline's stored results are never recomputed
    or overwritten — everything here reads stored fragments.
    """

    model_config = ConfigDict(extra="forbid")

    baseline_run_id: str
    baseline_ensemble_id: str
    new_run_id: str
    new_ensemble_id: str
    metric: str
    loss_threshold: float
    baseline_arm: ArmDelta
    strategy_arm: ArmDelta
    paired_mean_delta_old: float
    paired_mean_delta_new: float
    paired_mean_delta_change: float
    paired_p_strategy_better_old: float
    paired_p_strategy_better_new: float
    paired_p_strategy_better_change: float
    same_seed: bool
    same_trials: bool
    seeds_paired: bool
    evidence_caveat: str | None = None
    gate_reevaluation: GateReevaluation | None = None
    threshold_drift: list[ThresholdDriftRow] = Field(default_factory=list)
    compared_at: str


class ReviewDecisionRecord(BaseModel):
    """The reviewer's recorded decision for an iteration."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["continue", "pivot", "pause", "stop"]
    rationale: str = Field(min_length=1, max_length=2000)
    decided_at: str


class DecideRequest(BaseModel):
    """Record a review decision. Rationale is required: a decision
    without a reason is not an auditable decision."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["continue", "pivot", "pause", "stop"]
    rationale: str = Field(min_length=1, max_length=2000)

    @field_validator("rationale", mode="before")
    @classmethod
    def _strip_rationale(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class LoopIterationRead(BaseModel):
    """One review iteration: the unit of the living-strategy audit trail."""

    model_config = ConfigDict(extra="forbid")

    id: str
    loop_id: str
    index: int
    state: Literal["open", "evaluated", "resimulated", "compared", "decided"]
    decision_time: str
    previous_cutoff: str | None = None
    window_from: str | None = None
    window_to: str | None = None
    observation_ids: list[str] = Field(default_factory=list)
    trigger_evaluations: list[TriggerEvaluationOutcome] = Field(default_factory=list)
    resimulation: ResimulationRecord | None = None
    comparison: EnsembleComparison | None = None
    decision: ReviewDecisionRecord | None = None
    created_at: str
    updated_at: str


class LoopTimelineRead(BaseModel):
    """A loop with its full history: observations and iterations."""

    model_config = ConfigDict(extra="forbid")

    loop: StrategyLoopRead
    observations: list[LoopObservationRead] = Field(default_factory=list)
    iterations: list[LoopIterationRead] = Field(default_factory=list)

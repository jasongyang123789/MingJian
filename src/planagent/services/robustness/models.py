"""Models for robustness evaluation (Sprint 4, PRD deltas D6/D7).

Dependency-free Pydantic models, mirroring the MECE/variables/distributions
modules. Result models are both the API response shape and the stored audit
fragment on the base run's summary: GET endpoints validate the stored
fragment back into these models, so stored and served shapes cannot drift.

Robustness values are stored at full precision (no rounding): they are
statistics over trial values, not engine state, and gate evaluation must
see the unrounded statistic.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_GATES_PER_REGISTRATION = 20
MAX_BOOTSTRAP_DRAWS = 10_000
MIN_BOOTSTRAP_DRAWS = 100


def _require_finite_number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("must be a finite number")
    return result


class GateOperator(str, Enum):
    """Comparison operators for decision gates (the taylanakgn vocabulary)."""

    GT = ">"
    GTE = ">="
    LT = "<"
    LTE = "<="


class GateMetric(str, Enum):
    """Statistics a decision gate can test.

    Arm metrics (``mean`` … ``expected_shortfall``) are computed on one
    arm's trial values; paired metrics (``mean_delta``,
    ``p_strategy_better``) are computed on the paired baseline-vs-strategy
    deltas and require ``arm="paired"``.
    """

    MEAN = "mean"
    P10 = "p10"
    P50 = "p50"
    P90 = "p90"
    MIN = "min"
    MAX = "max"
    STDDEV = "stddev"
    P_LOSS = "p_loss"
    EXPECTED_SHORTFALL = "expected_shortfall"
    MEAN_DELTA = "mean_delta"
    P_STRATEGY_BETTER = "p_strategy_better"


class GateArm(str, Enum):
    """Which arm a gate tests."""

    BASELINE = "baseline"
    STRATEGY = "strategy"
    PAIRED = "paired"


_PAIRED_METRICS = frozenset({GateMetric.MEAN_DELTA, GateMetric.P_STRATEGY_BETTER})


class GateDefinition(BaseModel):
    """One pre-registered decision gate: a metric, an operator, a threshold.

    ``alpha`` applies only when ``metric`` is ``expected_shortfall`` (the
    tail fraction); it is carried on every definition so the stored shape
    is uniform, and ignored otherwise.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    metric: GateMetric
    operator: GateOperator
    threshold: float
    arm: GateArm = GateArm.BASELINE
    alpha: float = Field(default=0.05, gt=0.0, le=1.0)

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("threshold", mode="before")
    @classmethod
    def _validate_threshold(cls, value: object) -> float:
        return _require_finite_number(value)

    @model_validator(mode="after")
    def _check_metric_arm(self) -> "GateDefinition":
        paired = self.metric in _PAIRED_METRICS
        if paired and self.arm is not GateArm.PAIRED:
            raise ValueError(
                f"Metric {self.metric.value!r} is a paired statistic and requires arm 'paired'."
            )
        if not paired and self.arm is GateArm.PAIRED:
            raise ValueError(
                f"Metric {self.metric.value!r} is an arm statistic and cannot use arm 'paired'."
            )
        return self


class GateRegistrationRequest(BaseModel):
    """Register a set of decision gates on a run.

    ``supersedes`` names a previous registration this one replaces; the old
    registration is retained with status ``superseded`` — gates are
    append-only, never edited or deleted.
    """

    model_config = ConfigDict(extra="forbid")

    gates: list[GateDefinition] = Field(min_length=1, max_length=MAX_GATES_PER_REGISTRATION)
    supersedes: str | None = None


class GateRegistration(BaseModel):
    """A registered gate set, stored immutably in the run's audit trail.

    ``ensemble_existed_at_registration`` plus ``ensemble_id`` are the
    checkable pre-registration evidence (the taylanakgn reference relies
    on commit order; here the audit trail records whether results already
    existed when the gates were declared).
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    run_id: str
    ensemble_id: str | None = None
    gates: list[GateDefinition]
    supersedes: str | None = None
    registered_at: str
    ensemble_existed_at_registration: bool
    status: Literal["active", "superseded"] = "active"


class GateOutcome(BaseModel):
    """One gate's evaluation against a stored ensemble."""

    model_config = ConfigDict(extra="forbid")

    name: str
    metric: GateMetric
    operator: GateOperator
    threshold: float
    arm: GateArm
    alpha: float | None = None
    observed: float
    passed: bool


class GateEvaluation(BaseModel):
    """The evaluation of one registration against one ensemble.

    ``pre_registered`` is true when the gates were declared before the
    evaluated ensemble existed: either no ensemble existed at registration
    time, or the registration targeted a different (earlier) ensemble.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    registration_id: str
    run_id: str
    ensemble_id: str
    evaluated_at: str
    outcomes: list[GateOutcome]
    all_passed: bool
    pre_registered: bool


class GateEvaluationRequest(BaseModel):
    """Evaluate a gate registration against the stored ensemble.

    ``registration_id`` defaults to the latest active registration.
    """

    model_config = ConfigDict(extra="forbid")

    registration_id: str | None = None


class DecisionGatesRead(BaseModel):
    """All gate registrations and evaluations stored on a run."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    registrations: list[GateRegistration] = Field(default_factory=list)
    evaluations: list[GateEvaluation] = Field(default_factory=list)


class ExpectedShortfallDetail(BaseModel):
    """Expected shortfall for one arm (or the paired deltas)."""

    model_config = ConfigDict(extra="forbid")

    value: float
    threshold: float
    tail_count: int
    n: int


class ExpectedShortfallRequest(BaseModel):
    """Expected shortfall over the stored ensemble's trial values."""

    model_config = ConfigDict(extra="forbid")

    alpha: float = Field(default=0.05, gt=0.0, le=1.0)
    tail: Literal["lower", "upper"] = "lower"


class ExpectedShortfallResult(BaseModel):
    """Expected shortfall per arm plus the paired-delta tail."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    ensemble_id: str
    metric: str
    alpha: float
    tail: Literal["lower", "upper"]
    baseline: ExpectedShortfallDetail
    strategy: ExpectedShortfallDetail
    paired: ExpectedShortfallDetail
    trial_values_hash: str
    protocol: str


class TornadoRequest(BaseModel):
    """Tornado sensitivity: swing each variable over its own quantiles."""

    model_config = ConfigDict(extra="forbid")

    low_quantile: float = Field(default=0.10, gt=0.0, lt=1.0)
    high_quantile: float = Field(default=0.90, gt=0.0, lt=1.0)
    seed: int | None = None
    variables: list[str] | None = None

    @model_validator(mode="after")
    def _check_quantiles(self) -> "TornadoRequest":
        if self.low_quantile >= self.high_quantile:
            raise ValueError("low_quantile must be below high_quantile.")
        return self


class TornadoRow(BaseModel):
    """One tornado bar: the outcome swing from one variable's quantile range."""

    model_config = ConfigDict(extra="forbid")

    variable: str
    low_value: float
    high_value: float
    base_value: float
    outcome_low: float
    outcome_high: float
    outcome_base: float
    swing: float


class TornadoResult(BaseModel):
    """Tornado rows ranked by swing descending, plus the probe audit trail."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    ensemble_id: str
    metric: str
    seed: int
    low_quantile: float
    high_quantile: float
    base_run_id: str
    rows: list[TornadoRow]
    probe_run_ids: list[str] = Field(default_factory=list)
    protocol: str


class ThresholdSearchRequest(BaseModel):
    """Find the input value at which a statistic crosses a target.

    ``p_loss`` mode: the statistic is the fraction of probe trials below
    ``loss_threshold``; ``target`` is a probability in (0, 1).
    ``arm_flip`` mode: the statistic is the paired mean delta
    (strategy − baseline); ``target`` must be 0.0, the sign-flip point.
    ``direction`` states the assumed monotonicity (bisection assumes the
    statistic moves monotonically in the variable); bracketing is checked
    and an unreachable target reports ``threshold=None`` honestly.
    """

    model_config = ConfigDict(extra="forbid")

    variable: str = Field(min_length=1, max_length=120)
    mode: Literal["p_loss", "arm_flip"] = "p_loss"
    target: float
    direction: Literal["increasing", "decreasing"] = "increasing"
    bounds: tuple[float, float] | None = None
    trials_per_evaluation: int = Field(default=20, ge=1, le=50)
    max_iterations: int = Field(default=8, ge=1, le=12)
    tolerance: float = Field(default=1e-3, gt=0.0)
    seed: int | None = None
    loss_threshold: float | None = None

    @field_validator("variable", mode="before")
    @classmethod
    def _strip_variable(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("target", "loss_threshold", mode="before")
    @classmethod
    def _validate_numbers(cls, value: object) -> float | None:
        if value is None:
            return None
        return _require_finite_number(value)

    @field_validator("bounds", mode="before")
    @classmethod
    def _validate_bounds(cls, value: object) -> object:
        if value is None:
            return value
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError("bounds must be a [low, high] pair.")
        return (_require_finite_number(value[0]), _require_finite_number(value[1]))

    @model_validator(mode="after")
    def _check_target_and_bounds(self) -> "ThresholdSearchRequest":
        if self.mode == "p_loss" and not 0.0 < self.target < 1.0:
            raise ValueError("p_loss mode requires a target probability in (0, 1).")
        if self.mode == "arm_flip" and self.target != 0.0:
            raise ValueError("arm_flip mode requires target 0.0 (the sign-flip point).")
        if self.bounds is not None and not self.bounds[0] < self.bounds[1]:
            raise ValueError("bounds must satisfy low < high.")
        return self


class ThresholdEvaluation(BaseModel):
    """One probe evaluation inside a threshold search."""

    model_config = ConfigDict(extra="forbid")

    value: float
    statistic: float
    trials: int
    probe_run_ids: list[str] = Field(default_factory=list)


class ThresholdSearchResult(BaseModel):
    """Threshold search outcome, with the full evaluation audit trail."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    ensemble_id: str
    metric: str
    variable: str
    mode: Literal["p_loss", "arm_flip"]
    target: float
    direction: Literal["increasing", "decreasing"]
    bounds: tuple[float, float]
    threshold: float | None = None
    achieved_statistic: float | None = None
    reachable: bool
    iterations: int
    evaluations: list[ThresholdEvaluation] = Field(default_factory=list)
    trials_per_evaluation: int
    tolerance: float
    loss_threshold: float
    seed: int
    protocol: str


class BootstrapRequest(BaseModel):
    """Seeded bootstrap confidence intervals for headline statistics."""

    model_config = ConfigDict(extra="forbid")

    statistics: list[Literal["mean", "median", "p_loss"]] = Field(
        default=["mean", "median", "p_loss"]
    )
    draws: int = Field(default=1000, ge=MIN_BOOTSTRAP_DRAWS, le=MAX_BOOTSTRAP_DRAWS)
    seed: int | None = None
    level: float = Field(default=0.90, gt=0.0, lt=1.0)

    @field_validator("statistics", mode="before")
    @classmethod
    def _dedupe_statistics(cls, value: object) -> object:
        if isinstance(value, list):
            seen: list[str] = []
            for item in value:
                if item not in seen:
                    seen.append(item)
            return seen
        return value


class BootstrapInterval(BaseModel):
    """One bootstrap percentile interval for one statistic on one arm."""

    model_config = ConfigDict(extra="forbid")

    statistic: str
    estimate: float
    low: float
    high: float
    draws: int
    seed: int
    level: float
    method: str = "percentile"


class BootstrapResult(BaseModel):
    """Bootstrap intervals per arm over the stored ensemble's trial values."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    ensemble_id: str
    metric: str
    loss_threshold: float
    baseline: list[BootstrapInterval] = Field(default_factory=list)
    strategy: list[BootstrapInterval] = Field(default_factory=list)
    trial_values_hash: str
    protocol: str


class RobustnessRead(BaseModel):
    """Every robustness analysis stored on a run (absent analyses are null)."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    ensemble_id: str | None = None
    expected_shortfall: ExpectedShortfallResult | None = None
    tornado: TornadoResult | None = None
    threshold_search: ThresholdSearchResult | None = None
    bootstrap: BootstrapResult | None = None

"""Models for the distribution layer (Sprint 3, PRD deltas D4/D5).

Dependency-free Pydantic models, mirroring the MECE/variables modules.
``MonteCarloResult`` is both the API response shape and the stored audit
fragment on the base run's summary: the GET endpoint validates the stored
fragment back into this model, so stored and served shapes cannot drift.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_TRIALS = 200


def _require_finite_number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("must be a finite number")
    return result


class MonteCarloRequest(BaseModel):
    """Request N paired trials over a completed run's variable bindings."""

    model_config = ConfigDict(extra="forbid")

    trials: int = Field(default=50, ge=1, le=MAX_TRIALS)
    seed: int | None = None
    metric: str = Field(min_length=1, max_length=120)
    loss_threshold: float = 0.0
    strategy_levers: dict[str, float] = Field(default_factory=dict)

    @field_validator("metric", mode="before")
    @classmethod
    def _strip_metric(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("loss_threshold", mode="before")
    @classmethod
    def _validate_loss_threshold(cls, value: object) -> float:
        return _require_finite_number(value)

    @field_validator("strategy_levers", mode="before")
    @classmethod
    def _validate_levers(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        return {key: _require_finite_number(item) for key, item in value.items()}


class DistributionSummary(BaseModel):
    """Per-arm distribution summary for the aggregated metric."""

    model_config = ConfigDict(extra="forbid")

    n: int
    mean: float
    min: float
    max: float
    p10: float
    p50: float
    p90: float
    stddev: float
    p_loss: float


class PairedDeltaSummary(BaseModel):
    """Paired baseline-vs-strategy delta summary (trials paired by index)."""

    model_config = ConfigDict(extra="forbid")

    n: int
    mean_delta: float
    p10: float
    p50: float
    p90: float
    p_strategy_better: float


class MonteCarloResult(BaseModel):
    """A completed Monte Carlo ensemble, stored on the base run's summary."""

    model_config = ConfigDict(extra="forbid")

    ensemble_id: str
    base_run_id: str
    trials: int
    seed: int
    metric: str
    loss_threshold: float
    strategy_levers: dict[str, float] = Field(default_factory=dict)
    baseline: DistributionSummary
    strategy: DistributionSummary
    paired: PairedDeltaSummary
    trial_run_ids: dict[str, list[str]] = Field(default_factory=dict)
    protocol: str


class ReplayResult(BaseModel):
    """Outcome of re-executing a run from its stored inputs."""

    model_config = ConfigDict(extra="forbid")

    original_run_id: str
    replay_run_id: str
    match: bool
    first_diverging_tick: int | None = None
    tick_count: int
    original_state_hashes: dict[str, str] = Field(default_factory=dict)
    replay_state_hashes: dict[str, str] = Field(default_factory=dict)
    input_hash_match: bool


class DeterminismRead(BaseModel):
    """Determinism audit data for one run."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    seed: int
    protocol: str
    input_hash: str | None = None
    state_hashes: dict[str, str] = Field(default_factory=dict)
    sampled_values: dict[str, float] = Field(default_factory=dict)
    sampled_applied: list[str] = Field(default_factory=list)

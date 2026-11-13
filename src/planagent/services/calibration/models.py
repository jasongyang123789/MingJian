"""Calibration models (Sprint 5, PRD delta D8).

Dependency-free Pydantic models, mirroring the MECE/variables pattern:
request shapes for the two fit endpoints, the fit record read shape,
and the hindsight-firewall audit read shape. Request validation keeps
bad fits out (positive ridge strength, sane draw counts); the pure
estimator enforces the rest.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .estimator import (
    DEFAULT_BOOTSTRAP_DRAWS,
    DEFAULT_CALIBRATION_SEED,
    DEFAULT_RIDGE_STRENGTH,
)

#: Maximum bootstrap draws per fit request (latency guard for the
#: pure-Python solver; the reference default of 1000 fits inside it).
MAX_BOOTSTRAP_DRAWS = 2000

#: Maximum explicitly listed source runs per fit request.
MAX_SOURCE_RUNS = 500


class PolicyFitRequest(BaseModel):
    """Request a ridge-to-prior fit of a template's policy thresholds.

    ``source_run_ids`` selects the observation runs explicitly; when
    omitted, all eligible completed runs that carried the template are
    used. The fitted thresholds are stored as a NEW template version —
    the source template is never modified.
    """

    model_config = ConfigDict(extra="forbid")

    template_id: str = Field(min_length=1, max_length=200)
    ridge_strength: float = Field(default=DEFAULT_RIDGE_STRENGTH, gt=0)
    seed: int = Field(default=DEFAULT_CALIBRATION_SEED)
    bootstrap_draws: int = Field(default=DEFAULT_BOOTSTRAP_DRAWS, ge=1, le=MAX_BOOTSTRAP_DRAWS)
    level: float = Field(default=0.95, gt=0, lt=1)
    source_run_ids: list[str] | None = Field(default=None, max_length=MAX_SOURCE_RUNS)


class RuleWeightFitRequest(BaseModel):
    """Request a ridge-to-prior fit of the domain's rule weights.

    The target is the final value of ``metric`` across completed runs;
    features are per-rule match counts. Fitted weights are recorded on
    the fit and take effect only through the explicit apply endpoint.
    """

    model_config = ConfigDict(extra="forbid")

    domain_id: str = Field(min_length=1, max_length=64)
    metric: str = Field(min_length=1, max_length=120)
    ridge_strength: float = Field(default=DEFAULT_RIDGE_STRENGTH, gt=0)
    seed: int = Field(default=DEFAULT_CALIBRATION_SEED)
    bootstrap_draws: int = Field(default=DEFAULT_BOOTSTRAP_DRAWS, ge=1, le=MAX_BOOTSTRAP_DRAWS)
    level: float = Field(default=0.95, gt=0, lt=1)
    source_run_ids: list[str] | None = Field(default=None, max_length=MAX_SOURCE_RUNS)


class ThresholdChange(BaseModel):
    """One metric's threshold fit, as recorded on the fit."""

    model_config = ConfigDict(extra="forbid")

    metric: str
    preferred_direction: str
    prior_alert_threshold: float
    fitted_alert_threshold: float
    prior_critical_threshold: float
    fitted_critical_threshold: float
    alert_bootstrap: dict[str, Any] | None = None
    critical_bootstrap: dict[str, Any] | None = None
    n_observations: int
    n_tail: int
    unchanged_reason: str | None = None
    rejected_fit: dict[str, float] | None = None


class RuleWeightChange(BaseModel):
    """One rule's weight fit, as recorded on the fit."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    prior_weight: float
    fitted_weight: float
    bootstrap: dict[str, Any]
    total_matches: float


class CalibrationFitRead(BaseModel):
    """A calibration fit record, as returned by the API.

    ``changes`` holds per-metric threshold changes (policy fits) or
    per-rule weight changes (rule-weight fits). ``inputs_hash`` pins
    the exact input set (source runs, observations, parameters) so a
    later reader can verify what the fit was fit on. ``application``
    records rule-weight apply events; policy fits never write it.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    domain_id: str
    source_template_id: str | None = None
    calibrated_template_id: str | None = None
    metric: str | None = None
    ridge_strength: float
    seed: int
    bootstrap_draws: int
    level: float
    source_run_ids: list[str]
    n_observations: int
    changes: dict[str, Any]
    inputs_hash: str
    loo_rmse: float | None = None
    application: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class FirewallRead(BaseModel):
    """The hindsight-firewall audit view for one run.

    ``included_claim_ids`` / ``excluded_claim_ids`` are a live
    recomputation: the claims the engine's claim fetch selects with
    the cutoff, versus the claims it would select without it. The
    exclusion set is exactly the claims the firewall kept out of
    consideration — claims that match neither fetch (wrong subject or
    scope) appear in neither list. ``stored_evidence_ids`` is the
    execution-time record from the run summary, for completed runs.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str
    decision_time: str | None = None
    cutoff_source: str | None = None
    firewall_active: bool = False
    included_claim_ids: list[str] = Field(default_factory=list)
    excluded_claim_ids: list[str] = Field(default_factory=list)
    stored_evidence_ids: list[str] = Field(default_factory=list)

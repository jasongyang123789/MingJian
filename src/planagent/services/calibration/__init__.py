"""Calibration loop + hindsight firewall (Sprint 5, PRD delta D8).

Only dependency-free modules are exported here (firewall cutoff
mechanics, the ridge-to-prior estimator, request/read models),
mirroring the MECE/variables/distributions/robustness pattern. Service
orchestration (fit runs, template versioning, rule-weight application,
firewall audit) lives in ``services/simulation/calibration.py`` and is
imported from there.
"""

from .estimator import (
    CORRELATION_WARNING_MIN_N,
    CORRELATION_WARNING_THRESHOLD,
    DEFAULT_BOOTSTRAP_DRAWS,
    DEFAULT_CALIBRATION_SEED,
    DEFAULT_RIDGE_STRENGTH,
    MIN_OBSERVATIONS,
    bootstrap_coefficient_intervals,
    calibrate_policy_thresholds,
    calibrate_rule_weights,
    fit_centered_ridge_to_prior,
    fit_ridge_to_prior,
    leave_one_out_rmse,
    pairwise_metric_correlations,
    prior_only_rmse,
    ridge_location_fit,
)
from .firewall import (
    CUTOFF_SOURCE_CREATION_TIME,
    CUTOFF_SOURCE_EXPLICIT,
    FIREWALL_CONFIGURATION_KEY,
    FIREWALL_PROTOCOL_VERSION,
    claim_visible_at,
    firewall_configuration_fragment,
    firewall_cutoff_from_configuration,
    format_cutoff,
    normalize_cutoff,
    parse_cutoff,
)
from .models import (
    MAX_BOOTSTRAP_DRAWS,
    MAX_SOURCE_RUNS,
    CalibrationFitRead,
    FirewallRead,
    PolicyFitRequest,
    RuleWeightChange,
    RuleWeightFitRequest,
    ThresholdChange,
)

__all__ = [
    "CORRELATION_WARNING_MIN_N",
    "CORRELATION_WARNING_THRESHOLD",
    "CUTOFF_SOURCE_CREATION_TIME",
    "CUTOFF_SOURCE_EXPLICIT",
    "DEFAULT_BOOTSTRAP_DRAWS",
    "DEFAULT_CALIBRATION_SEED",
    "DEFAULT_RIDGE_STRENGTH",
    "FIREWALL_CONFIGURATION_KEY",
    "FIREWALL_PROTOCOL_VERSION",
    "MAX_BOOTSTRAP_DRAWS",
    "MAX_SOURCE_RUNS",
    "MIN_OBSERVATIONS",
    "CalibrationFitRead",
    "FirewallRead",
    "PolicyFitRequest",
    "RuleWeightChange",
    "RuleWeightFitRequest",
    "ThresholdChange",
    "bootstrap_coefficient_intervals",
    "calibrate_policy_thresholds",
    "calibrate_rule_weights",
    "claim_visible_at",
    "firewall_configuration_fragment",
    "firewall_cutoff_from_configuration",
    "fit_centered_ridge_to_prior",
    "fit_ridge_to_prior",
    "format_cutoff",
    "leave_one_out_rmse",
    "normalize_cutoff",
    "pairwise_metric_correlations",
    "parse_cutoff",
    "prior_only_rmse",
    "ridge_location_fit",
]

"""Distribution layer (Sprint 3, PRD deltas D4/D5).

Only dependency-free modules are exported here (canonical hashing,
sampling, aggregation, models), mirroring the MECE/variables pattern.
Service orchestration (Monte Carlo runner, replay) lives in
``services/simulation/distributions.py`` and is imported from there.
"""

from .aggregation import paired_delta_stats, percentile, summarize_samples
from .canonical import (
    DETERMINISM_CONFIGURATION_KEY,
    HASH_PROTOCOL_VERSION,
    canonical_json,
    compute_input_hash,
    derive_sub_seed,
    determinism_input_fragment,
    sha256_hash,
    state_hash,
)
from .models import (
    MAX_TRIALS,
    DeterminismRead,
    DistributionSummary,
    MonteCarloRequest,
    MonteCarloResult,
    MonteCarloTrialValues,
    PairedDeltaSummary,
    ReplayResult,
)
from .quantiles import BETA_PERT_QUANTILE_DRAWS, distribution_median, distribution_quantile
from .sampler import (
    MONTE_CARLO_CONFIGURATION_KEY,
    VARIABLES_CONFIGURATION_KEY,
    resolve_run_samples,
    resolve_run_values,
    rng_for_seed,
    sample_variable_set,
)

__all__ = [
    "BETA_PERT_QUANTILE_DRAWS",
    "DETERMINISM_CONFIGURATION_KEY",
    "HASH_PROTOCOL_VERSION",
    "MAX_TRIALS",
    "MONTE_CARLO_CONFIGURATION_KEY",
    "VARIABLES_CONFIGURATION_KEY",
    "DeterminismRead",
    "DistributionSummary",
    "MonteCarloRequest",
    "MonteCarloResult",
    "MonteCarloTrialValues",
    "PairedDeltaSummary",
    "ReplayResult",
    "canonical_json",
    "compute_input_hash",
    "derive_sub_seed",
    "determinism_input_fragment",
    "distribution_median",
    "distribution_quantile",
    "paired_delta_stats",
    "percentile",
    "resolve_run_samples",
    "resolve_run_values",
    "rng_for_seed",
    "sample_variable_set",
    "sha256_hash",
    "state_hash",
    "summarize_samples",
]

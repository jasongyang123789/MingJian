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
    PairedDeltaSummary,
    ReplayResult,
)
from .sampler import (
    MONTE_CARLO_CONFIGURATION_KEY,
    VARIABLES_CONFIGURATION_KEY,
    resolve_run_samples,
    rng_for_seed,
    sample_variable_set,
)

__all__ = [
    "DETERMINISM_CONFIGURATION_KEY",
    "HASH_PROTOCOL_VERSION",
    "MAX_TRIALS",
    "MONTE_CARLO_CONFIGURATION_KEY",
    "VARIABLES_CONFIGURATION_KEY",
    "DeterminismRead",
    "DistributionSummary",
    "MonteCarloRequest",
    "MonteCarloResult",
    "PairedDeltaSummary",
    "ReplayResult",
    "canonical_json",
    "compute_input_hash",
    "derive_sub_seed",
    "determinism_input_fragment",
    "paired_delta_stats",
    "percentile",
    "resolve_run_samples",
    "rng_for_seed",
    "sample_variable_set",
    "sha256_hash",
    "state_hash",
    "summarize_samples",
]

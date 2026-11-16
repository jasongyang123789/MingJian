"""Bottom-layer split structures (Phase 1, automotive track).

Pure deterministic validation of the OEM → nameplate → generation →
trim → product → supplier-share tree, plus the bottom-up aggregation
that turns production volumes into addressable units and capacity. No
LLM calls, no randomness, no I/O.
"""

from __future__ import annotations

from .aggregation import (
    aggregate_capacity,
    aggregate_units,
    generation_mix_at_index,
    market_capacity_by_oem_product,
    own_sales_from_supplier_rows,
    own_sales_with_share,
    prior_fitment_rate,
    simulated_supply_share,
)
from .models import (
    GenerationSplit,
    NameplateSplit,
    OemSplit,
    ProductFitment,
    SplitCheckRecord,
    SplitStructure,
    SplitValidationIssue,
    SplitValidationResult,
    TrimSplit,
)
from .validator import (
    ONE_HOST_PRODUCTS,
    SUM_TOLERANCE,
    SplitValidationError,
    validate_or_raise,
    validate_split_structure,
)

__all__ = [
    "ONE_HOST_PRODUCTS",
    "SUM_TOLERANCE",
    "GenerationSplit",
    "NameplateSplit",
    "OemSplit",
    "ProductFitment",
    "SplitCheckRecord",
    "SplitStructure",
    "SplitValidationError",
    "SplitValidationIssue",
    "SplitValidationResult",
    "TrimSplit",
    "aggregate_capacity",
    "aggregate_units",
    "generation_mix_at_index",
    "market_capacity_by_oem_product",
    "own_sales_from_supplier_rows",
    "own_sales_with_share",
    "prior_fitment_rate",
    "simulated_supply_share",
    "validate_or_raise",
    "validate_split_structure",
]

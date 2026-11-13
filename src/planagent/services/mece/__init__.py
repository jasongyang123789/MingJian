"""MECE decomposition layer (Sprint 1, PRD delta D1).

Pure-code, deterministic validation of issue-tree decompositions over
scope tags, plus the gate that refuses simulation runs whose attached
decomposition fails validation. No LLM calls, no randomness.
"""

from __future__ import annotations

from .models import (
    DecompositionBranch,
    DecompositionTree,
    MeceCheckRecord,
    MeceIssue,
    MeceRunRead,
    MeceValidationResult,
)
from .validator import (
    MAX_TREE_DEPTH,
    MeceValidationError,
    validate_decomposition,
    validate_or_raise,
)

__all__ = [
    "MAX_TREE_DEPTH",
    "DecompositionBranch",
    "DecompositionTree",
    "MeceCheckRecord",
    "MeceIssue",
    "MeceRunRead",
    "MeceValidationError",
    "MeceValidationResult",
    "validate_decomposition",
    "validate_or_raise",
]

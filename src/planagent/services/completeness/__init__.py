"""Deterministic driver-completeness check (Phase 4, Track 10).

The shared finding shape lives in
:mod:`planagent.services.completeness.findings`; the registry in
:mod:`planagent.services.completeness.registry`; the pure check in
:mod:`planagent.services.completeness.check`. This package exports the
public surface.
"""

from __future__ import annotations

from .check import (
    CompletenessCase,
    CompletenessReport,
    CoverageEntry,
    ResidualGap,
    run_completeness_check,
)
from .findings import (
    META_CHECK_PREFIX,
    UNCLASSIFIED_BASIS,
    BoundaryClass,
    CompletenessFinding,
    FindingKind,
    FindingSeverity,
    FindingSource,
    RedTeamFinding,
)
from .registry import (
    AUTOMOTIVE_DRIVER_REGISTRY,
    GENERAL_DRIVER_CHECKLIST,
    REGISTRIES,
    ChecklistItem,
    DriverRegistryEntry,
)

__all__ = [
    "AUTOMOTIVE_DRIVER_REGISTRY",
    "GENERAL_DRIVER_CHECKLIST",
    "META_CHECK_PREFIX",
    "REGISTRIES",
    "UNCLASSIFIED_BASIS",
    "BoundaryClass",
    "ChecklistItem",
    "CompletenessCase",
    "CompletenessFinding",
    "CompletenessReport",
    "CoverageEntry",
    "DriverRegistryEntry",
    "FindingKind",
    "FindingSeverity",
    "FindingSource",
    "RedTeamFinding",
    "ResidualGap",
    "run_completeness_check",
]

"""Driver-completeness endpoints (Phase 4, Track 10).

Two explicit, read-only surfaces over a SUBMITTED case — no run is
created, nothing is stored, no background work (Sprint 9 automation
boundary):

- ``POST /completeness/check``: run the deterministic completeness
  check on the case's assembled variable table (variables, formula /
  driver outputs, rule ids, assumption-data keys) and return the
  ranked findings in the shared Track 8 / Track 10 finding shape.
  Plug-in point for the case-build flow: call it after the variable
  table is assembled and before the run is created.
- ``GET /completeness/drivers``: the driver registry (or the general
  guided checklist, for domains without a registry) a case-build UI
  shows while the builder assembles the variable table.

The check is a pure function of its input: same case in, same
findings out, in the same order. No DB, no LLM, no network.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from planagent.services.completeness import (
    GENERAL_DRIVER_CHECKLIST,
    REGISTRIES,
    UNCLASSIFIED_BASIS,
    BoundaryClass,
    CompletenessCase,
    CompletenessReport,
    run_completeness_check,
)

router = APIRouter()


class DriverRead(BaseModel):
    """One registered driver, as the case-build UI displays it."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str
    weight: float
    severity: str
    drives: list[str]
    model_elements: list[str]
    link_outputs: list[str]
    evidence: list[str]
    suggested_fix: str
    boundary_class: str
    boundary_basis: str


class ChecklistRead(BaseModel):
    """One general-checklist question, as the case-build UI displays it."""

    model_config = ConfigDict(extra="forbid")

    id: str
    question: str
    keywords: list[str]
    drives: list[str]
    suggested_fix: str
    boundary_class: str
    boundary_basis: str


class DriversRead(BaseModel):
    """Registry entries (or the general checklist) for one domain."""

    model_config = ConfigDict(extra="forbid")

    domain_id: str
    registry: str  # domain id, or "general-checklist"
    drivers: list[DriverRead] = Field(default_factory=list)
    checklist: list[ChecklistRead] = Field(default_factory=list)


@router.post("/completeness/check", response_model=CompletenessReport)
async def check_case_completeness(case: CompletenessCase) -> CompletenessReport:
    """Run the deterministic completeness check on a submitted case."""
    return run_completeness_check(case)


@router.get("/completeness/drivers", response_model=DriversRead)
async def list_drivers(domain_id: str) -> DriversRead:
    """List the registered drivers (or general checklist) for a domain."""
    entries = REGISTRIES.get(domain_id.lower())
    if entries is not None:
        return DriversRead(
            domain_id=domain_id,
            registry=domain_id.lower(),
            drivers=[
                DriverRead(
                    id=e.id,
                    name=e.name,
                    description=e.description,
                    weight=e.weight,
                    severity=e.severity,
                    drives=e.drives,
                    model_elements=e.model_elements,
                    link_outputs=e.link_outputs,
                    evidence=e.evidence,
                    suggested_fix=e.suggested_fix,
                    boundary_class=e.boundary_class.value,
                    boundary_basis=e.boundary_basis,
                )
                for e in entries
            ],
        )
    return DriversRead(
        domain_id=domain_id,
        registry="general-checklist",
        checklist=[
            ChecklistRead(
                id=item.id,
                question=item.question,
                keywords=item.keywords,
                drives=item.drives,
                suggested_fix=item.suggested_fix,
                boundary_class=BoundaryClass.UNCLASSIFIED.value,
                boundary_basis=UNCLASSIFIED_BASIS,
            )
            for item in GENERAL_DRIVER_CHECKLIST
        ],
    )

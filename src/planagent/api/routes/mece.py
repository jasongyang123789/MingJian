"""MECE decomposition endpoints (Sprint 1, PRD delta D1).

- ``POST /mece/validate`` validates a submitted decomposition without
  creating anything. It always returns 200: the verdict lives in the
  payload (``is_mece``), and validation is a pure function — no database
  writes, no LLM calls.
- ``GET /runs/{run_id}/mece`` retrieves the decomposition + validation
  result stored with a simulation run at creation time (audit trail).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from planagent.db import get_session
from planagent.domain.models import SimulationRun
from planagent.services.mece import (
    DecompositionTree,
    MeceRunRead,
    MeceValidationResult,
    validate_decomposition,
)

router = APIRouter()


@router.post("/mece/validate", response_model=MeceValidationResult)
async def validate_mece_decomposition(tree: DecompositionTree) -> MeceValidationResult:
    return validate_decomposition(tree)


@router.get("/runs/{run_id}/mece", response_model=MeceRunRead)
async def get_run_mece(
    run_id: str,
    session: AsyncSession = Depends(get_session),
) -> MeceRunRead:
    run = await session.get(SimulationRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Simulation run {run_id} was not found.")
    fragment = (run.configuration or {}).get("mece")
    if not isinstance(fragment, dict):
        raise HTTPException(
            status_code=404,
            detail=f"Simulation run {run_id} has no attached decomposition.",
        )
    return MeceRunRead(
        run_id=run.id,
        decomposition=DecompositionTree.model_validate(fragment["decomposition"]),
        validation=MeceValidationResult.model_validate(fragment["validation"]),
    )

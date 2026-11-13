"""Distribution-layer endpoints (Sprint 3, PRD deltas D4/D5).

- ``POST /runs/{run_id}/monte-carlo`` runs a paired Monte Carlo ensemble
  over a completed run's variable bindings and stores the aggregated
  distributions on the base run's summary (audit trail, not ephemeral).
- ``GET /runs/{run_id}/monte-carlo`` retrieves the stored ensemble result.
- ``POST /runs/{run_id}/replay`` re-executes a run from its stored inputs
  and compares per-tick state hashes, reporting the first diverging tick.
- ``GET /runs/{run_id}/determinism`` returns the input hash, per-tick
  state hashes, and sampled variable values for a run.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from planagent.api.routes._deps import get_simulation_service
from planagent.db import get_session
from planagent.services.distributions.models import (
    DeterminismRead,
    MonteCarloRequest,
    MonteCarloResult,
    ReplayResult,
)
from planagent.services.simulation.distributions import MonteCarloError

router = APIRouter()


@router.post("/runs/{run_id}/monte-carlo", response_model=MonteCarloResult, status_code=201)
async def run_monte_carlo(
    run_id: str,
    payload: MonteCarloRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> MonteCarloResult:
    service = get_simulation_service(request)
    try:
        return await service.run_monte_carlo(session, run_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MonteCarloError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/runs/{run_id}/monte-carlo", response_model=MonteCarloResult)
async def get_monte_carlo(
    run_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> MonteCarloResult:
    service = get_simulation_service(request)
    result = await service.get_monte_carlo(session, run_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Simulation run {run_id} was not found or has no Monte Carlo results.",
        )
    return result


@router.post("/runs/{run_id}/replay", response_model=ReplayResult, status_code=201)
async def replay_run(
    run_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ReplayResult:
    service = get_simulation_service(request)
    try:
        return await service.replay_simulation_run(session, run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MonteCarloError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/runs/{run_id}/determinism", response_model=DeterminismRead)
async def get_run_determinism(
    run_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> DeterminismRead:
    service = get_simulation_service(request)
    result = await service.get_determinism(session, run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Simulation run {run_id} was not found.")
    return result

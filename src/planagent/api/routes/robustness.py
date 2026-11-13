"""Robustness-evaluation endpoints (Sprint 4, PRD deltas D6/D7).

Every analysis runs against a stored Monte Carlo ensemble on the run and
stores its result on the run's summary (audit trail, not ephemeral):

- ``POST /runs/{run_id}/robustness/expected-shortfall`` — tail risk per arm.
- ``POST /runs/{run_id}/robustness/tornado`` — one-variable-at-a-time
  sensitivity, ranked by swing.
- ``POST /runs/{run_id}/robustness/threshold-search`` — bisection search
  for the input value where a statistic crosses a target.
- ``POST /runs/{run_id}/robustness/bootstrap`` — seeded bootstrap
  percentile intervals.
- ``GET /runs/{run_id}/robustness`` — every stored analysis on the run.

Decision gates are append-only registrations evaluated against the
stored ensemble:

- ``POST /runs/{run_id}/decision-gates`` — register a gate set.
- ``GET /runs/{run_id}/decision-gates`` — registrations + evaluations.
- ``POST /runs/{run_id}/decision-gates/evaluate`` — evaluate a
  registration (default: the latest active one).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from planagent.api.routes._deps import get_simulation_service
from planagent.db import get_session
from planagent.services.robustness.models import (
    BootstrapRequest,
    BootstrapResult,
    DecisionGatesRead,
    ExpectedShortfallRequest,
    ExpectedShortfallResult,
    GateEvaluation,
    GateEvaluationRequest,
    GateRegistration,
    GateRegistrationRequest,
    RobustnessRead,
    ThresholdSearchRequest,
    ThresholdSearchResult,
    TornadoRequest,
    TornadoResult,
)
from planagent.services.simulation.robustness import RobustnessError

router = APIRouter()


def _robustness_error(exc: RobustnessError) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"code": exc.code, "message": str(exc)},
    )


@router.post(
    "/runs/{run_id}/robustness/expected-shortfall",
    response_model=ExpectedShortfallResult,
    status_code=201,
)
async def compute_expected_shortfall(
    run_id: str,
    payload: ExpectedShortfallRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ExpectedShortfallResult:
    service = get_simulation_service(request)
    try:
        return await service.compute_expected_shortfall(session, run_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RobustnessError as exc:
        raise _robustness_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/runs/{run_id}/robustness/tornado",
    response_model=TornadoResult,
    status_code=201,
)
async def compute_tornado(
    run_id: str,
    payload: TornadoRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> TornadoResult:
    service = get_simulation_service(request)
    try:
        return await service.compute_tornado(session, run_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RobustnessError as exc:
        raise _robustness_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/runs/{run_id}/robustness/threshold-search",
    response_model=ThresholdSearchResult,
    status_code=201,
)
async def run_threshold_search(
    run_id: str,
    payload: ThresholdSearchRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ThresholdSearchResult:
    service = get_simulation_service(request)
    try:
        return await service.run_threshold_search(session, run_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RobustnessError as exc:
        raise _robustness_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/runs/{run_id}/robustness/bootstrap",
    response_model=BootstrapResult,
    status_code=201,
)
async def compute_bootstrap(
    run_id: str,
    payload: BootstrapRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> BootstrapResult:
    service = get_simulation_service(request)
    try:
        return await service.compute_bootstrap(session, run_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RobustnessError as exc:
        raise _robustness_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/runs/{run_id}/robustness", response_model=RobustnessRead)
async def get_robustness(
    run_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> RobustnessRead:
    service = get_simulation_service(request)
    result = await service.get_robustness(session, run_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Simulation run {run_id} was not found or has no robustness results.",
        )
    return result


@router.post("/runs/{run_id}/decision-gates", response_model=GateRegistration, status_code=201)
async def register_decision_gates(
    run_id: str,
    payload: GateRegistrationRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> GateRegistration:
    service = get_simulation_service(request)
    try:
        return await service.register_decision_gates(session, run_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RobustnessError as exc:
        raise _robustness_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/runs/{run_id}/decision-gates", response_model=DecisionGatesRead)
async def get_decision_gates(
    run_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> DecisionGatesRead:
    service = get_simulation_service(request)
    result = await service.get_decision_gates(session, run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Simulation run {run_id} was not found.")
    return result


@router.post(
    "/runs/{run_id}/decision-gates/evaluate",
    response_model=GateEvaluation,
    status_code=201,
)
async def evaluate_decision_gates(
    run_id: str,
    payload: GateEvaluationRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> GateEvaluation:
    service = get_simulation_service(request)
    try:
        return await service.evaluate_decision_gates(session, run_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RobustnessError as exc:
        raise _robustness_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

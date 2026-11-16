"""Living-strategy loop endpoints (Sprint 9).

- ``POST /loops`` creates a loop from a completed primary run.
- ``POST /loops/{loop_id}/observations`` records an observed actual
  (append-only; the loop's observation seam — claims carry text, not
  numeric actuals, so observations are recorded explicitly).
- ``POST /loops/{loop_id}/triggers`` registers a trigger set
  (append-only with explicit supersede, mirroring Sprint 4 gates).
- ``POST /loops/{loop_id}/iterations`` opens a review iteration whose
  decision_time must advance the evidence cutoff.
- ``POST /loops/{loop_id}/iterations/{id}/evaluate|resimulate|compare``
  advance the iteration state machine; ``POST .../decide`` records
  the review decision (terminal).
- ``GET /loops/{loop_id}/timeline`` reads the full audit trail.
- ``POST /loops/monitoring/evaluate`` runs one monitoring cycle:
  every loop's triggers are evaluated against its recorded
  observations and the outcomes recorded (Sprint 11). The cycle
  only evaluates + records — it creates no runs or iterations and
  changes no loop state (SPRINT9.md §10).
- ``GET /loops/{loop_id}/evaluations`` reads a loop's recorded
  monitoring evaluations, newest first.

All review actions are explicit: there is no scheduler that opens
reviews, re-simulates, or decides. The monitoring worker only
evaluates + records; a recorded trigger firing plus an explicit
review is still what starts a re-simulation. Gate
refusals from re-simulation surface the same codes as hand-created
runs (``mece_validation_failed`` / ``variable_validation_failed`` /
template codes), because the same creation path refused them.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from planagent.api.routes._deps import get_simulation_service
from planagent.db import get_session
from planagent.services.living_loop.models import (
    DecideRequest,
    LoopEvaluationRead,
    LoopIterationRead,
    LoopObservationCreate,
    LoopObservationRead,
    LoopTimelineRead,
    MonitoringCycleResult,
    ResimulateRequest,
    StartIterationRequest,
    StrategyLoopCreate,
    StrategyLoopRead,
    TriggerRegistration,
    TriggerRegistrationRequest,
)
from planagent.services.mece import MeceValidationError
from planagent.services.simulation.living_loop import LoopError
from planagent.services.splits import SplitValidationError
from planagent.services.variables import VariableTemplateError, VariableValidationError

router = APIRouter()


def _loop_error(exc: LoopError) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc)})


def _not_found(exc: LookupError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


@router.post("/loops", response_model=StrategyLoopRead, status_code=201)
async def create_loop(
    request: StrategyLoopCreate,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
) -> StrategyLoopRead:
    service = get_simulation_service(http_request)
    try:
        return await service.create_loop(session, request)
    except LoopError as exc:
        raise _loop_error(exc) from exc
    except LookupError as exc:
        raise _not_found(exc) from exc


@router.get("/loops", response_model=list[StrategyLoopRead])
async def list_loops(
    http_request: Request,
    session: AsyncSession = Depends(get_session),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[StrategyLoopRead]:
    service = get_simulation_service(http_request)
    return await service.list_loops(session, limit=limit, offset=offset)


@router.get("/loops/{loop_id}", response_model=StrategyLoopRead)
async def get_loop(
    loop_id: str,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
) -> StrategyLoopRead:
    service = get_simulation_service(http_request)
    try:
        return await service.get_loop(session, loop_id)
    except LookupError as exc:
        raise _not_found(exc) from exc


@router.get("/loops/{loop_id}/timeline", response_model=LoopTimelineRead)
async def get_loop_timeline(
    loop_id: str,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
) -> LoopTimelineRead:
    service = get_simulation_service(http_request)
    try:
        return await service.get_loop_timeline(session, loop_id)
    except LookupError as exc:
        raise _not_found(exc) from exc


@router.post("/loops/monitoring/evaluate", response_model=MonitoringCycleResult)
async def run_monitoring_cycle(
    http_request: Request,
    session: AsyncSession = Depends(get_session),
) -> MonitoringCycleResult:
    service = get_simulation_service(http_request)
    return await service.run_monitoring_cycle(session)


@router.get("/loops/{loop_id}/evaluations", response_model=list[LoopEvaluationRead])
async def list_loop_evaluations(
    loop_id: str,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[LoopEvaluationRead]:
    service = get_simulation_service(http_request)
    try:
        return await service.list_loop_evaluations(session, loop_id, limit=limit, offset=offset)
    except LookupError as exc:
        raise _not_found(exc) from exc


@router.post(
    "/loops/{loop_id}/observations",
    response_model=LoopObservationRead,
    status_code=201,
)
async def record_loop_observation(
    loop_id: str,
    request: LoopObservationCreate,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
) -> LoopObservationRead:
    service = get_simulation_service(http_request)
    try:
        return await service.record_observation(session, loop_id, request)
    except LoopError as exc:
        raise _loop_error(exc) from exc
    except LookupError as exc:
        raise _not_found(exc) from exc


@router.post(
    "/loops/{loop_id}/triggers",
    response_model=TriggerRegistration,
    status_code=201,
)
async def register_loop_triggers(
    loop_id: str,
    request: TriggerRegistrationRequest,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
) -> TriggerRegistration:
    service = get_simulation_service(http_request)
    try:
        return await service.register_loop_triggers(session, loop_id, request)
    except LoopError as exc:
        raise _loop_error(exc) from exc
    except LookupError as exc:
        raise _not_found(exc) from exc


@router.post(
    "/loops/{loop_id}/iterations",
    response_model=LoopIterationRead,
    status_code=201,
)
async def start_loop_iteration(
    loop_id: str,
    request: StartIterationRequest,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
) -> LoopIterationRead:
    service = get_simulation_service(http_request)
    try:
        return await service.start_iteration(session, loop_id, request)
    except LoopError as exc:
        raise _loop_error(exc) from exc
    except LookupError as exc:
        raise _not_found(exc) from exc


@router.get(
    "/loops/{loop_id}/iterations/{iteration_id}",
    response_model=LoopIterationRead,
)
async def get_loop_iteration(
    loop_id: str,
    iteration_id: str,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
) -> LoopIterationRead:
    service = get_simulation_service(http_request)
    try:
        return await service.get_iteration(session, loop_id, iteration_id)
    except LookupError as exc:
        raise _not_found(exc) from exc


@router.post(
    "/loops/{loop_id}/iterations/{iteration_id}/evaluate",
    response_model=LoopIterationRead,
)
async def evaluate_loop_iteration(
    loop_id: str,
    iteration_id: str,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
) -> LoopIterationRead:
    service = get_simulation_service(http_request)
    try:
        return await service.evaluate_iteration(session, loop_id, iteration_id)
    except LoopError as exc:
        raise _loop_error(exc) from exc
    except LookupError as exc:
        raise _not_found(exc) from exc


@router.post(
    "/loops/{loop_id}/iterations/{iteration_id}/resimulate",
    response_model=LoopIterationRead,
)
async def resimulate_loop_iteration(
    loop_id: str,
    iteration_id: str,
    request: ResimulateRequest,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
) -> LoopIterationRead:
    service = get_simulation_service(http_request)
    try:
        return await service.resimulate_iteration(session, loop_id, iteration_id, request)
    except MeceValidationError as exc:
        # Same dict-detail shape as the hand-created run route: the
        # re-simulation went through the same gate and was refused.
        raise HTTPException(
            status_code=400,
            detail={
                "code": "mece_validation_failed",
                "message": "Decomposition failed MECE validation; re-simulation refused.",
                "validation": exc.result.model_dump(mode="json"),
            },
        ) from exc
    except VariableValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "variable_validation_failed",
                "message": "Variable bindings failed validation; re-simulation refused.",
                "validation": exc.result.model_dump(mode="json"),
            },
        ) from exc
    except VariableTemplateError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except SplitValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "split_validation_failed",
                "message": "Split structure failed validation; re-simulation refused.",
                "validation": exc.result.model_dump(mode="json"),
            },
        ) from exc
    except LoopError as exc:
        raise _loop_error(exc) from exc
    except LookupError as exc:
        raise _not_found(exc) from exc


@router.post(
    "/loops/{loop_id}/iterations/{iteration_id}/compare",
    response_model=LoopIterationRead,
)
async def compare_loop_iteration(
    loop_id: str,
    iteration_id: str,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
) -> LoopIterationRead:
    service = get_simulation_service(http_request)
    try:
        return await service.compare_iteration(session, loop_id, iteration_id)
    except LoopError as exc:
        raise _loop_error(exc) from exc
    except LookupError as exc:
        raise _not_found(exc) from exc


@router.post(
    "/loops/{loop_id}/iterations/{iteration_id}/decide",
    response_model=LoopIterationRead,
)
async def decide_loop_iteration(
    loop_id: str,
    iteration_id: str,
    request: DecideRequest,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
) -> LoopIterationRead:
    service = get_simulation_service(http_request)
    try:
        return await service.decide_iteration(session, loop_id, iteration_id, request)
    except LoopError as exc:
        raise _loop_error(exc) from exc
    except LookupError as exc:
        raise _not_found(exc) from exc

"""Calibration + hindsight-firewall endpoints (Sprint 5, PRD delta D8).

- ``GET /runs/{run_id}/firewall`` audits a run's decision-time cutoff:
  the claims the engine's claim fetch selects with the cutoff versus
  without it, i.e. exactly the claims the firewall kept out.
- ``POST /calibration/policy-fit`` fits a template's policy thresholds
  from stored run outcomes and stores a NEW template version with
  provenance; the source template is never modified.
- ``POST /calibration/rule-weight-fit`` fits a domain's rule weights
  from stored run outcomes; fitted weights take effect only through
  the explicit apply endpoint.
- ``GET /calibration/fits`` / ``GET /calibration/fits/{fit_id}`` read
  stored fits.
- ``POST /calibration/fits/{fit_id}/apply-rule-weights`` applies a
  rule-weight fit to the in-memory rule registry and records the
  application event on the fit.
- ``GET /calibration/current-weights`` / ``GET
  /calibration/weight-applications`` read the persistent
  current-weights record (Sprint 10); ``POST
  /calibration/restore-weights`` explicitly re-applies the latest
  persisted weights to the registry.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from planagent.api.routes._deps import get_simulation_service
from planagent.db import get_session
from planagent.services.calibration.models import (
    CalibrationFitRead,
    FirewallRead,
    PersistedWeightsRead,
    PolicyFitRequest,
    RestoreWeightsRequest,
    RuleWeightFitRequest,
)
from planagent.services.simulation.calibration import CalibrationError

router = APIRouter()


@router.get("/runs/{run_id}/firewall", response_model=FirewallRead)
async def get_run_firewall(
    run_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> FirewallRead:
    service = get_simulation_service(request)
    try:
        return await service.get_firewall_audit(session, run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/calibration/policy-fit", response_model=CalibrationFitRead, status_code=201)
async def fit_policy_thresholds(
    payload: PolicyFitRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> CalibrationFitRead:
    service = get_simulation_service(request)
    try:
        return await service.fit_policy_thresholds(session, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CalibrationError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/calibration/rule-weight-fit", response_model=CalibrationFitRead, status_code=201)
async def fit_rule_weights(
    payload: RuleWeightFitRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> CalibrationFitRead:
    service = get_simulation_service(request)
    try:
        return await service.fit_rule_weights(session, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CalibrationError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/calibration/fits", response_model=list[CalibrationFitRead])
async def list_calibration_fits(
    request: Request,
    session: AsyncSession = Depends(get_session),
    kind: str | None = Query(default=None, max_length=32),
    domain_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[CalibrationFitRead]:
    service = get_simulation_service(request)
    return await service.list_calibration_fits(
        session, kind=kind, domain_id=domain_id, limit=limit, offset=offset
    )


@router.get("/calibration/fits/{fit_id}", response_model=CalibrationFitRead)
async def get_calibration_fit(
    fit_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> CalibrationFitRead:
    service = get_simulation_service(request)
    result = await service.get_calibration_fit(session, fit_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Calibration fit {fit_id} was not found.")
    return result


@router.post(
    "/calibration/fits/{fit_id}/apply-rule-weights",
    response_model=CalibrationFitRead,
    status_code=201,
)
async def apply_rule_weights(
    fit_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> CalibrationFitRead:
    service = get_simulation_service(request)
    try:
        return await service.apply_rule_weights(session, fit_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CalibrationError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/calibration/current-weights", response_model=PersistedWeightsRead)
async def get_current_weights(
    request: Request,
    session: AsyncSession = Depends(get_session),
    domain_id: str = Query(max_length=64),
) -> PersistedWeightsRead:
    service = get_simulation_service(request)
    try:
        return await service.get_current_weights(session, domain_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CalibrationError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc


@router.get("/calibration/weight-applications", response_model=list[PersistedWeightsRead])
async def list_weight_applications(
    request: Request,
    session: AsyncSession = Depends(get_session),
    domain_id: str = Query(max_length=64),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[PersistedWeightsRead]:
    service = get_simulation_service(request)
    try:
        return await service.list_weight_applications(
            session, domain_id, limit=limit, offset=offset
        )
    except CalibrationError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc


@router.post("/calibration/restore-weights", response_model=PersistedWeightsRead)
async def restore_weights(
    payload: RestoreWeightsRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> PersistedWeightsRead:
    service = get_simulation_service(request)
    try:
        return await service.restore_weights(session, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CalibrationError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

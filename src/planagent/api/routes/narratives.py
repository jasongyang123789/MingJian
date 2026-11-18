"""Decision-direction narrative endpoints (Sprint 13) + direction
derivation and mappings (Sprint 14) + LLM-proposed directions
(option C) + variable-override directions (option B).

Generation is deterministic: no LLM call happens on the generate
path. The polish endpoint is the only LLM touchpoint, strictly
separated — it stores its output alongside the artifact and never
mutates it. Derivation is deterministic too: versioned rules over
stored ensembles, explicit trigger only, never creating runs.
Proposing is the second LLM touchpoint: an explicit POST that
stores grounded proposals as ``proposed`` mappings, usable for
generation only after an explicit human accept. Overriding is the
run-creating direction source: an explicit POST that creates one
scenario-branch run per direction with fixed variable overrides
and stores each as an ``active`` ``override`` mapping. Error
mapping follows the Sprint 9/11 pattern: ``NarrativeError``/
``DirectionError`` → 400 with a ``{"code", "message"}`` detail
(polish/proposal availability/contract failures map to 503/502),
``LookupError`` → 404.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from planagent.api.routes._deps import get_narrative_service
from planagent.db import get_session
from planagent.services.narratives.models import (
    DecisionNarrativeListRead,
    DecisionNarrativeRead,
    DerivationRead,
    DirectionError,
    DirectionMappingCreate,
    DirectionMappingListRead,
    DirectionMappingRead,
    DirectionMappingUpdate,
    DirectionOverrideRead,
    DirectionOverrideReforkRead,
    DirectionOverrideReforkRequest,
    DirectionOverrideRequest,
    DirectionProposeRead,
    DirectionProposeRequest,
    NarrativeError,
    NarrativeGenerateRequest,
    NarrativePolishRead,
)

router = APIRouter()

_POLISH_STATUS_CODES = {
    "narrative_polish_unavailable": 503,
    "narrative_polish_contract_failed": 502,
    # The LLM produced content that fails verification against the
    # artifact: same class as a contract failure (bad upstream
    # output), so 502 like narrative_polish_contract_failed.
    "narrative_polish_recheck_failed": 502,
}

_DIRECTION_STATUS_CODES = {
    "direction_propose_unavailable": 503,
    "direction_propose_contract_failed": 502,
    "direction_propose_truncated": 502,
    "direction_override_unavailable": 503,
    "direction_mapping_deleted_concurrently": 409,
}


def _narrative_error(exc: NarrativeError) -> HTTPException:
    status = _POLISH_STATUS_CODES.get(exc.code, 400)
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


def _direction_error(exc: DirectionError) -> HTTPException:
    status = _DIRECTION_STATUS_CODES.get(exc.code, 400)
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


def _not_found(exc: LookupError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


@router.post(
    "/runs/{run_id}/narratives",
    response_model=DecisionNarrativeRead,
    status_code=201,
)
async def generate_narrative(
    run_id: str,
    request: NarrativeGenerateRequest,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
) -> DecisionNarrativeRead:
    service = get_narrative_service(http_request)
    try:
        return await service.generate(session, run_id, request)
    except NarrativeError as exc:
        raise _narrative_error(exc) from exc
    except LookupError as exc:
        raise _not_found(exc) from exc


@router.get(
    "/runs/{run_id}/narratives",
    response_model=DecisionNarrativeListRead,
)
async def list_narratives(
    run_id: str,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
) -> DecisionNarrativeListRead:
    service = get_narrative_service(http_request)
    try:
        return await service.list_narratives(session, run_id)
    except LookupError as exc:
        raise _not_found(exc) from exc


@router.get(
    "/runs/{run_id}/narratives/{narrative_id}",
    response_model=DecisionNarrativeRead,
)
async def get_narrative(
    run_id: str,
    narrative_id: str,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
) -> DecisionNarrativeRead:
    service = get_narrative_service(http_request)
    try:
        return await service.get_narrative(session, run_id, narrative_id)
    except LookupError as exc:
        raise _not_found(exc) from exc


@router.post(
    "/runs/{run_id}/narratives/{narrative_id}/polish",
    response_model=NarrativePolishRead,
    status_code=201,
)
async def polish_narrative(
    run_id: str,
    narrative_id: str,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
) -> NarrativePolishRead:
    service = get_narrative_service(http_request)
    try:
        return await service.polish(session, run_id, narrative_id)
    except NarrativeError as exc:
        raise _narrative_error(exc) from exc
    except LookupError as exc:
        raise _not_found(exc) from exc


# ---------------------------------------------------------------------------
# Direction derivation + mappings (Sprint 14)
# ---------------------------------------------------------------------------


@router.post(
    "/runs/{run_id}/directions/derive",
    response_model=DerivationRead,
)
async def derive_directions(
    run_id: str,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
) -> DerivationRead:
    service = get_narrative_service(http_request)
    try:
        return await service.derive(session, run_id)
    except DirectionError as exc:
        raise _direction_error(exc) from exc
    except LookupError as exc:
        raise _not_found(exc) from exc


@router.get(
    "/runs/{run_id}/directions/mappings",
    response_model=DirectionMappingListRead,
)
async def list_direction_mappings(
    run_id: str,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
) -> DirectionMappingListRead:
    service = get_narrative_service(http_request)
    try:
        return await service.list_mappings(session, run_id)
    except LookupError as exc:
        raise _not_found(exc) from exc


@router.post(
    "/runs/{run_id}/directions/mappings",
    response_model=DirectionMappingRead,
    status_code=201,
)
async def create_direction_mapping(
    run_id: str,
    payload: DirectionMappingCreate,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
) -> DirectionMappingRead:
    service = get_narrative_service(http_request)
    try:
        return await service.create_mapping(session, run_id, payload)
    except DirectionError as exc:
        raise _direction_error(exc) from exc
    except LookupError as exc:
        raise _not_found(exc) from exc


@router.put(
    "/runs/{run_id}/directions/mappings/{mapping_id}",
    response_model=DirectionMappingRead,
)
async def update_direction_mapping(
    run_id: str,
    mapping_id: str,
    payload: DirectionMappingUpdate,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
) -> DirectionMappingRead:
    service = get_narrative_service(http_request)
    try:
        return await service.update_mapping(session, run_id, mapping_id, payload)
    except DirectionError as exc:
        raise _direction_error(exc) from exc
    except LookupError as exc:
        raise _not_found(exc) from exc


@router.delete(
    "/runs/{run_id}/directions/mappings/{mapping_id}",
    status_code=204,
)
async def delete_direction_mapping(
    run_id: str,
    mapping_id: str,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
) -> None:
    service = get_narrative_service(http_request)
    try:
        await service.delete_mapping(session, run_id, mapping_id)
    except LookupError as exc:
        raise _not_found(exc) from exc


# ---------------------------------------------------------------------------
# LLM-proposed directions (option C)
# ---------------------------------------------------------------------------


@router.post(
    "/runs/{run_id}/directions/propose",
    response_model=DirectionProposeRead,
)
async def propose_directions_endpoint(
    run_id: str,
    http_request: Request,
    payload: DirectionProposeRequest | None = None,
    session: AsyncSession = Depends(get_session),
) -> DirectionProposeRead:
    service = get_narrative_service(http_request)
    try:
        return await service.propose(session, run_id, payload or DirectionProposeRequest())
    except DirectionError as exc:
        raise _direction_error(exc) from exc
    except LookupError as exc:
        raise _not_found(exc) from exc


# ---------------------------------------------------------------------------
# Variable-override directions (option B)
# ---------------------------------------------------------------------------


@router.post(
    "/runs/{run_id}/directions/override",
    response_model=DirectionOverrideRead,
    status_code=201,
)
async def override_directions_endpoint(
    run_id: str,
    payload: DirectionOverrideRequest,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
) -> DirectionOverrideRead:
    service = get_narrative_service(http_request)
    try:
        return await service.override(session, run_id, payload)
    except DirectionError as exc:
        raise _direction_error(exc) from exc
    except LookupError as exc:
        raise _not_found(exc) from exc


@router.post(
    "/runs/{run_id}/directions/mappings/{mapping_id}/refork",
    response_model=DirectionOverrideReforkRead,
    status_code=201,
)
async def refork_direction_mapping(
    run_id: str,
    mapping_id: str,
    payload: DirectionOverrideReforkRequest,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
) -> DirectionOverrideReforkRead:
    service = get_narrative_service(http_request)
    try:
        return await service.refork_override_mapping(session, run_id, mapping_id, payload)
    except DirectionError as exc:
        raise _direction_error(exc) from exc
    except LookupError as exc:
        raise _not_found(exc) from exc


@router.post(
    "/runs/{run_id}/directions/mappings/{mapping_id}/accept",
    response_model=DirectionMappingRead,
)
async def accept_direction_mapping(
    run_id: str,
    mapping_id: str,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
) -> DirectionMappingRead:
    service = get_narrative_service(http_request)
    try:
        return await service.accept_mapping(session, run_id, mapping_id)
    except DirectionError as exc:
        raise _direction_error(exc) from exc
    except LookupError as exc:
        raise _not_found(exc) from exc


@router.post(
    "/runs/{run_id}/directions/mappings/{mapping_id}/reject",
    response_model=DirectionMappingRead,
)
async def reject_direction_mapping(
    run_id: str,
    mapping_id: str,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
) -> DirectionMappingRead:
    service = get_narrative_service(http_request)
    try:
        return await service.reject_mapping(session, run_id, mapping_id)
    except DirectionError as exc:
        raise _direction_error(exc) from exc
    except LookupError as exc:
        raise _not_found(exc) from exc

"""Decision-direction narrative endpoints (Sprint 13).

Generation is deterministic: no LLM call happens on the generate
path. The polish endpoint is the only LLM touchpoint, strictly
separated — it stores its output alongside the artifact and never
mutates it. Error mapping follows the Sprint 9/11 pattern:
``NarrativeError`` → 400 with a ``{"code", "message"}`` detail
(polish availability/contract failures map to 503/502),
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
    NarrativeError,
    NarrativeGenerateRequest,
    NarrativePolishRead,
)

router = APIRouter()

_POLISH_STATUS_CODES = {
    "narrative_polish_unavailable": 503,
    "narrative_polish_contract_failed": 502,
}


def _narrative_error(exc: NarrativeError) -> HTTPException:
    status = _POLISH_STATUS_CODES.get(exc.code, 400)
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

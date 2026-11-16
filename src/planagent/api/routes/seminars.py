"""Seminar endpoints (Sprint 16, design §12).

- ``POST /runs/{run_id}/seminars`` freezes the case snapshot and
  creates a seminar (201). Refusals happen before any row is written:
  non-COMPLETED run (400), roster < 2 models (400), chair endpoint
  unconfigured (503, skills semantics).
- ``POST /seminars/{seminar_id}/advance`` runs one wave: every
  unterminated model runs one round (200). Per-model failures are
  isolated and recorded; they never fail the wave.
- ``POST /seminars/{seminar_id}/finalize`` runs final verdicts for
  eligible models (200). A failed verdict writes no row for its model.

``synthesize`` and the GET endpoints are S17 — deliberately absent.
There is no background progression: every wave is an explicit request.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from planagent.api.routes._deps import get_seminar_service
from planagent.db import get_session
from planagent.services.seminar.models import (
    AdvanceRead,
    FinalizeRead,
    SeminarCreateRead,
    SeminarCreateRequest,
)
from planagent.services.seminar.service import (
    SeminarChairUnavailable,
    SeminarServiceError,
)
from planagent.services.skills.contracts import SkillContractError

router = APIRouter()


@router.post(
    "/runs/{run_id}/seminars",
    response_model=SeminarCreateRead,
    status_code=201,
)
async def create_seminar_endpoint(
    run_id: str,
    payload: SeminarCreateRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SeminarCreateRead:
    service = get_seminar_service(request)
    try:
        return await service.create_seminar(session, run_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SeminarServiceError as exc:
        raise HTTPException(
            status_code=400, detail={"code": exc.code, "message": str(exc)}
        ) from exc
    except SeminarChairUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "seminar_chair_unavailable", "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/seminars/{seminar_id}/advance", response_model=AdvanceRead)
async def advance_seminar_endpoint(
    seminar_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdvanceRead:
    service = get_seminar_service(request)
    try:
        return await service.advance_seminar(session, seminar_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SeminarServiceError as exc:
        raise HTTPException(
            status_code=400, detail={"code": exc.code, "message": str(exc)}
        ) from exc
    except SkillContractError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "skill_contract_failed",
                "message": str(exc),
                "template_id": exc.template_id,
                "contract_version": exc.contract_version,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/seminars/{seminar_id}/finalize", response_model=FinalizeRead)
async def finalize_seminar_endpoint(
    seminar_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FinalizeRead:
    service = get_seminar_service(request)
    try:
        return await service.finalize_seminar(session, seminar_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SeminarServiceError as exc:
        raise HTTPException(
            status_code=400, detail={"code": exc.code, "message": str(exc)}
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

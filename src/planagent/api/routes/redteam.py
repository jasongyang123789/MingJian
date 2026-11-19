"""Red-team endpoints (Phase 4, Track 8).

- ``POST /red-team/analyze`` runs the red team over a frozen case
  snapshot in the request body (the case-build gate). No persistence:
  the caller owns the case record and attaches the findings to it.
- ``POST /runs/{run_id}/red-team`` runs it over a stored run's frozen
  configuration and appends the result to the run summary's
  ``red_team`` list (fragment discipline). Unlike skill deliberation,
  no COMPLETED status is required — the red team challenges structure,
  not results.
- ``GET /runs/{run_id}/red-team`` lists stored red-team runs.

Error mapping is honest about the LLM boundary: ``live`` mode with no
configured LLM is 503, malformed LLM output is 502, client errors
stay 400, missing runs are 404. ``auto`` mode never 503s: it degrades
to completeness-only and records ``llm_available: false``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from planagent.api.routes._deps import get_red_team_service
from planagent.db import get_session
from planagent.services.redteam.contracts import RedTeamContractError
from planagent.services.redteam.models import (
    RedTeamListRead,
    RedTeamRecord,
    RedTeamRequest,
    RedTeamResult,
    RedTeamRunRequest,
)
from planagent.services.redteam.service import RedTeamServiceError
from planagent.services.skills.orchestration import SkillLLMUnavailable

router = APIRouter()


def _contract_error(exc: RedTeamContractError) -> HTTPException:
    return HTTPException(
        status_code=502,
        detail={
            "code": "red_team_contract_failed",
            "message": str(exc),
            "template_id": exc.template_id,
            "contract_version": exc.contract_version,
        },
    )


@router.post("/red-team/analyze", response_model=RedTeamResult, status_code=200)
async def analyze_snapshot_endpoint(
    payload: RedTeamRequest,
    request: Request,
) -> RedTeamResult:
    service = get_red_team_service(request)
    try:
        return await service.analyze_snapshot(
            payload.snapshot,
            mode=payload.mode,
            output_language=payload.output_language,
        )
    except SkillLLMUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "red_team_llm_unavailable", "message": str(exc)},
        ) from exc
    except RedTeamContractError as exc:
        raise _contract_error(exc) from exc


@router.post(
    "/runs/{run_id}/red-team",
    response_model=RedTeamRecord,
    status_code=201,
)
async def analyze_run_endpoint(
    run_id: str,
    payload: RedTeamRunRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> RedTeamRecord:
    service = get_red_team_service(request)
    try:
        return await service.analyze_run(
            session,
            run_id,
            mode=payload.mode,
            output_language=payload.output_language,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "run_not_found", "message": str(exc)},
        ) from exc
    except RedTeamServiceError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except SkillLLMUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "red_team_llm_unavailable", "message": str(exc)},
        ) from exc
    except RedTeamContractError as exc:
        raise _contract_error(exc) from exc


@router.get("/runs/{run_id}/red-team", response_model=RedTeamListRead)
async def list_red_team_endpoint(
    run_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> RedTeamListRead:
    service = get_red_team_service(request)
    try:
        return await service.list_red_team_runs(session, run_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "run_not_found", "message": str(exc)},
        ) from exc


__all__ = ["router"]

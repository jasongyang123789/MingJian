"""Skill-deliberation endpoints (Sprint 6, PRD delta D9).

- ``POST /runs/{run_id}/skills/strategy-team`` runs the McKinsey
  strategy-team pipeline over a completed run's stored artifacts.
- ``POST /runs/{run_id}/skills/advisory-board`` runs the 5-persona
  advisory board over a completed run's stored artifacts.
- ``GET /runs/{run_id}/skills/deliberations`` lists stored deliberations.
- ``POST /mece/propose`` proposes a decomposition tree (authoring aid);
  the Sprint 1 validator verdict rides in the payload, following the
  ``/mece/validate`` convention — a failing proposal is a 200 with a
  FAIL verdict, and attaching it to a run is refused by the existing
  creation gate.

Error mapping is honest about the LLM boundary: no configured LLM is
503, malformed LLM output is 502, client errors stay 400.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from planagent.api.routes._deps import get_skill_service
from planagent.db import get_session
from planagent.services.skills.contracts import SkillContractError
from planagent.services.skills.models import (
    AdvisoryBoardRequest,
    MeceProposeRequest,
    MeceProposalRead,
    SkillDeliberationListRead,
    SkillDeliberationRecord,
    StrategyTeamRequest,
)
from planagent.services.skills.orchestration import SkillLLMUnavailable
from planagent.services.skills.service import SkillServiceError

router = APIRouter()


def _contract_error(exc: SkillContractError) -> HTTPException:
    return HTTPException(
        status_code=502,
        detail={
            "code": "skill_contract_failed",
            "message": str(exc),
            "template_id": exc.template_id,
            "contract_version": exc.contract_version,
        },
    )


@router.post(
    "/runs/{run_id}/skills/strategy-team",
    response_model=SkillDeliberationRecord,
    status_code=201,
)
async def run_strategy_team_endpoint(
    run_id: str,
    payload: StrategyTeamRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> SkillDeliberationRecord:
    service = get_skill_service(request)
    try:
        return await service.run_strategy_team(session, run_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SkillServiceError as exc:
        raise HTTPException(
            status_code=400, detail={"code": exc.code, "message": str(exc)}
        ) from exc
    except SkillLLMUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "skill_llm_unavailable", "message": str(exc)},
        ) from exc
    except SkillContractError as exc:
        raise _contract_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/runs/{run_id}/skills/advisory-board",
    response_model=SkillDeliberationRecord,
    status_code=201,
)
async def run_advisory_board_endpoint(
    run_id: str,
    payload: AdvisoryBoardRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> SkillDeliberationRecord:
    service = get_skill_service(request)
    try:
        return await service.run_advisory_board(session, run_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SkillServiceError as exc:
        raise HTTPException(
            status_code=400, detail={"code": exc.code, "message": str(exc)}
        ) from exc
    except SkillLLMUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "skill_llm_unavailable", "message": str(exc)},
        ) from exc
    except SkillContractError as exc:
        raise _contract_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/runs/{run_id}/skills/deliberations", response_model=SkillDeliberationListRead)
async def list_deliberations_endpoint(
    run_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> SkillDeliberationListRead:
    service = get_skill_service(request)
    try:
        return await service.list_deliberations(session, run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/mece/propose", response_model=MeceProposalRead)
async def propose_mece_tree_endpoint(
    payload: MeceProposeRequest,
    request: Request,
) -> MeceProposalRead:
    service = get_skill_service(request)
    try:
        return await service.propose_mece_tree(payload)
    except SkillLLMUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "skill_llm_unavailable", "message": str(exc)},
        ) from exc
    except SkillContractError as exc:
        raise _contract_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

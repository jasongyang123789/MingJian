"""Seminar endpoints (Sprint 16–17, design §12).

- ``POST /runs/{run_id}/seminars`` freezes the case snapshot and
  creates a seminar (201). Refusals happen before any row is written:
  non-COMPLETED run (400), roster < 2 models (400), chair endpoint
  unconfigured (503, skills semantics).
- ``POST /seminars/{seminar_id}/advance`` runs one wave: every
  unterminated model runs one round (200). Per-model failures are
  isolated and recorded; they never fail the wave.
- ``POST /seminars/{seminar_id}/finalize`` runs final verdicts for
  eligible models (200). A failed verdict writes no row for its model.
- ``POST /seminars/{seminar_id}/synthesize`` runs chair clustering +
  synthesis and stores a versioned report (201). Chair-stage failures
  fall back to the deterministic composer; the report records the
  path and the reason. Fewer than 2 finals refuses (400) unless
  ``allow_partial`` is passed. On agent-chair seminars it produces
  and stores a versioned chair brief instead (200) — no model chair
  call, no report row — and the seminar awaits chair input.
- ``POST /seminars/{seminar_id}/chair-synthesis`` accepts an agent
  chair's submission (clustering + synthesis, same contracts, same
  merge-map coverage rule) against a stored brief and writes a
  versioned report (201).
- ``GET /seminars/{seminar_id}/audit`` serves the append-only audit
  log in seq order, filterable by kind and model_id.
- ``POST /seminars/{seminar_id}/audit/purge`` explicitly compacts
  the audit log under the seminar's retention policy floor and
  writes one retention summary event (200). No background job ever
  purges.
- ``GET /seminars/{seminar_id}/audit/retention`` serves the
  retention status (event count, surviving seq range, policy).
- GET endpoints serve stored seminar state: detail, board, rounds,
  finals, report versions, one composed report, and a run's seminars.

There is no background progression: every wave is an explicit request.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from planagent.api.routes._deps import get_seminar_service
from planagent.db import get_session
from planagent.services.seminar.audit import AuditEventRead
from planagent.services.seminar.models import (
    AdvanceRead,
    AuditPurgeRead,
    AuditPurgeRequest,
    AuditRetentionRead,
    BoardRowRead,
    ChairBriefRead,
    ChairSynthesisRequest,
    FinalizeRead,
    FinalRowRead,
    ReportDetailRead,
    RoundRowRead,
    SeminarCreateRead,
    SeminarCreateRequest,
    SeminarDetailRead,
    SeminarReportSummary,
    SeminarSummaryRead,
    SynthesizeRead,
    SynthesizeRequest,
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


@router.post(
    "/seminars/{seminar_id}/synthesize",
    response_model=SynthesizeRead | ChairBriefRead,
    status_code=201,
)
async def synthesize_seminar_endpoint(
    seminar_id: str,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    payload: SynthesizeRequest | None = None,
) -> SynthesizeRead | ChairBriefRead:
    service = get_seminar_service(request)
    try:
        result = await service.synthesize_seminar(
            session, seminar_id, payload or SynthesizeRequest()
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SeminarServiceError as exc:
        raise HTTPException(
            status_code=400, detail={"code": exc.code, "message": str(exc)}
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # A chair brief creates no report: 200, not 201.
    if isinstance(result, ChairBriefRead):
        response.status_code = 200
    return result


@router.post(
    "/seminars/{seminar_id}/chair-synthesis",
    response_model=SynthesizeRead,
    status_code=201,
)
async def submit_chair_synthesis_endpoint(
    seminar_id: str,
    payload: ChairSynthesisRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SynthesizeRead:
    service = get_seminar_service(request)
    try:
        return await service.submit_chair_synthesis(session, seminar_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SeminarServiceError as exc:
        raise HTTPException(
            status_code=400, detail={"code": exc.code, "message": str(exc)}
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/seminars/{seminar_id}/audit", response_model=list[AuditEventRead])
async def get_seminar_audit_endpoint(
    seminar_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    kind: Annotated[str | None, Query()] = None,
    model_id: Annotated[str | None, Query()] = None,
) -> list[AuditEventRead]:
    service = get_seminar_service(request)
    try:
        return await service.list_audit_events(session, seminar_id, kind=kind, model_id=model_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SeminarServiceError as exc:
        raise HTTPException(
            status_code=400, detail={"code": exc.code, "message": str(exc)}
        ) from exc


@router.post(
    "/seminars/{seminar_id}/audit/purge",
    response_model=AuditPurgeRead,
)
async def purge_seminar_audit_endpoint(
    seminar_id: str,
    payload: AuditPurgeRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuditPurgeRead:
    service = get_seminar_service(request)
    try:
        return await service.purge_audit_events(session, seminar_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SeminarServiceError as exc:
        raise HTTPException(
            status_code=400, detail={"code": exc.code, "message": str(exc)}
        ) from exc


@router.get(
    "/seminars/{seminar_id}/audit/retention",
    response_model=AuditRetentionRead,
)
async def get_seminar_audit_retention_endpoint(
    seminar_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuditRetentionRead:
    service = get_seminar_service(request)
    try:
        return await service.get_audit_retention(session, seminar_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/seminars/{seminar_id}", response_model=SeminarDetailRead)
async def get_seminar_endpoint(
    seminar_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SeminarDetailRead:
    service = get_seminar_service(request)
    try:
        return await service.get_seminar_detail(session, seminar_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/seminars/{seminar_id}/board", response_model=list[BoardRowRead])
async def get_seminar_board_endpoint(
    seminar_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[BoardRowRead]:
    service = get_seminar_service(request)
    try:
        return await service.list_board(session, seminar_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/seminars/{seminar_id}/rounds", response_model=list[RoundRowRead])
async def get_seminar_rounds_endpoint(
    seminar_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[RoundRowRead]:
    service = get_seminar_service(request)
    try:
        return await service.list_rounds(session, seminar_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/seminars/{seminar_id}/finals", response_model=list[FinalRowRead])
async def get_seminar_finals_endpoint(
    seminar_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[FinalRowRead]:
    service = get_seminar_service(request)
    try:
        return await service.list_finals(session, seminar_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/seminars/{seminar_id}/reports",
    response_model=list[SeminarReportSummary],
)
async def get_seminar_reports_endpoint(
    seminar_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[SeminarReportSummary]:
    service = get_seminar_service(request)
    try:
        return await service.list_reports(session, seminar_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/seminars/{seminar_id}/reports/{version}",
    response_model=ReportDetailRead,
)
async def get_seminar_report_endpoint(
    seminar_id: str,
    version: int,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReportDetailRead:
    service = get_seminar_service(request)
    try:
        return await service.get_report(session, seminar_id, version)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/runs/{run_id}/seminars",
    response_model=list[SeminarSummaryRead],
)
async def get_run_seminars_endpoint(
    run_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[SeminarSummaryRead]:
    service = get_seminar_service(request)
    try:
        return await service.list_seminars_for_run(session, run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

"""Skill deliberation service (Sprint 6, PRD delta D9).

Wires the grafted skill pipelines into the existing service patterns:
runs deliberations over a completed run's stored artifacts, persists
results as an append-only list on the run summary (fragment discipline,
no migration), and serves MECE authoring proposals without persistence.

The service never touches the numeric core: it reads
``configuration``/``summary`` fragments and calibration-fit rows, and
writes only the ``skill_deliberations`` summary key. A failed
deliberation (LLM unavailable, malformed output) writes nothing.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from planagent.config import Settings
from planagent.domain.enums import SimulationRunStatus
from planagent.domain.models import CalibrationFitRecord, SimulationRun, generate_id, utc_now
from planagent.services.openai_client import OpenAIService
from planagent.services.skills.context import render_run_context
from planagent.services.skills.mece_authoring import propose_decomposition
from planagent.services.skills.models import (
    AdvisoryBoardRequest,
    MeceProposeRequest,
    MeceProposalRead,
    SkillDeliberationListRead,
    SkillDeliberationRecord,
    StrategyTeamRequest,
)
from planagent.services.skills.orchestration import (
    OpenAIServiceSkillPort,
    SkillLLMPort,
    SkillLLMResponse,
    SkillLLMUnavailable,
    run_advisory_board,
    run_strategy_team,
)

SKILL_DELIBERATIONS_SUMMARY_KEY = "skill_deliberations"
_MAX_CALIBRATION_FITS_IN_CONTEXT = 5


class SkillServiceError(ValueError):
    """A client-visible skill-service failure with a stable error code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class _NoLLMPort:
    """Port used when no LLM service is wired: always unavailable."""

    def is_available(self) -> bool:
        return False

    async def generate_json(self, **_kwargs: Any) -> SkillLLMResponse:
        raise SkillLLMUnavailable("No LLM service is configured for skill stages.")


class SkillDeliberationService:
    """Runs grafted skill pipelines and stores their audit trail."""

    def __init__(
        self,
        settings: Settings,
        openai_service: OpenAIService | None = None,
        llm_port: SkillLLMPort | None = None,
    ) -> None:
        self.settings = settings
        if llm_port is not None:
            self._port: SkillLLMPort = llm_port
        elif openai_service is not None:
            self._port = OpenAIServiceSkillPort(openai_service)
        else:
            self._port = _NoLLMPort()  # type: ignore[assignment]

    async def _completed_run(self, session: AsyncSession, run_id: str) -> SimulationRun:
        run = await session.get(SimulationRun, run_id)
        if run is None:
            raise LookupError(f"Simulation run {run_id} was not found.")
        if run.status != SimulationRunStatus.COMPLETED.value:
            raise SkillServiceError(
                "skills_requires_completed_run",
                "Skill deliberation requires a completed run to argue about.",
            )
        return run

    async def _calibration_fits(
        self, session: AsyncSession, domain_id: str
    ) -> list[dict[str, Any]]:
        result = await session.execute(
            select(CalibrationFitRecord)
            .where(CalibrationFitRecord.domain_id == domain_id)
            .order_by(CalibrationFitRecord.created_at.desc())
            .limit(_MAX_CALIBRATION_FITS_IN_CONTEXT)
        )
        fits = []
        for record in result.scalars().all():
            fits.append(
                {
                    "id": record.id,
                    "kind": record.kind,
                    "metric": record.metric,
                    "ridge_strength": record.ridge_strength,
                    "n_observations": record.n_observations,
                    "changes": record.changes or {},
                }
            )
        return fits

    async def _context_for_run(
        self,
        session: AsyncSession,
        run: SimulationRun,
        context_lines: list[str],
    ) -> str:
        fits = await self._calibration_fits(session, run.domain_id)
        context = render_run_context(
            configuration=run.configuration or {},
            summary=run.summary or {},
            calibration_fits=fits,
        )
        if context_lines:
            caller_block = "Caller-supplied context:\n" + "\n".join(
                f"- {line}" for line in context_lines
            )
            context = f"{context}\n\n{caller_block}" if context else caller_block
        return context or "(no engine artifacts stored on this run yet)"

    async def _store_record(
        self,
        session: AsyncSession,
        run: SimulationRun,
        *,
        pipeline: str,
        mode: str,
        result: dict[str, Any],
    ) -> SkillDeliberationRecord:
        record = SkillDeliberationRecord(
            id=generate_id(),
            run_id=run.id,
            pipeline=pipeline,  # type: ignore[arg-type]
            mode=mode,
            created_at=utc_now().isoformat(),
            result=result,
        )
        summary = dict(run.summary or {})
        stored = list(summary.get(SKILL_DELIBERATIONS_SUMMARY_KEY) or [])
        stored.append(record.model_dump(mode="json"))
        run.summary = {**summary, SKILL_DELIBERATIONS_SUMMARY_KEY: stored}
        await session.commit()
        await session.refresh(run)
        return record

    async def run_strategy_team(
        self,
        session: AsyncSession,
        run_id: str,
        request: StrategyTeamRequest,
    ) -> SkillDeliberationRecord:
        run = await self._completed_run(session, run_id)
        context = await self._context_for_run(session, run, request.context_lines)
        result = await run_strategy_team(
            self._port,
            topic=request.topic,
            decision_question=request.decision_question or request.topic,
            context=context,
            mode=request.mode,
            output_language=request.output_language,
            include_premortem=request.include_premortem,
            failure_date=request.failure_date,
        )
        return await self._store_record(
            session,
            run,
            pipeline="strategy_team",
            mode=request.mode,
            result=result.model_dump(mode="json"),
        )

    async def run_advisory_board(
        self,
        session: AsyncSession,
        run_id: str,
        request: AdvisoryBoardRequest,
    ) -> SkillDeliberationRecord:
        run = await self._completed_run(session, run_id)
        context = await self._context_for_run(session, run, request.context_lines)
        result = await run_advisory_board(
            self._port,
            decision=request.decision,
            options=list(request.options),
            context=context,
            mode=request.mode,
            output_language=request.output_language,
        )
        return await self._store_record(
            session,
            run,
            pipeline="advisory_board",
            mode=request.mode,
            result=result.model_dump(mode="json"),
        )

    async def list_deliberations(
        self, session: AsyncSession, run_id: str
    ) -> SkillDeliberationListRead:
        run = await session.get(SimulationRun, run_id)
        if run is None:
            raise LookupError(f"Simulation run {run_id} was not found.")
        stored = (run.summary or {}).get(SKILL_DELIBERATIONS_SUMMARY_KEY) or []
        return SkillDeliberationListRead(
            run_id=run.id,
            deliberations=[
                SkillDeliberationRecord.model_validate(item) for item in stored
            ],
        )

    async def propose_mece_tree(self, request: MeceProposeRequest) -> MeceProposalRead:
        """Propose a decomposition tree. No persistence; validator disposes."""
        result = await propose_decomposition(
            self._port,
            topic=request.topic,
            context_lines=list(request.context_lines),
            suggested_dimensions=list(request.suggested_dimensions) or None,
            existing_tree=request.existing_tree,
            output_language=request.output_language,
        )
        return MeceProposalRead(
            proposal=result.proposal,
            validation=result.validation,
            stage=result.stage,
        )


__all__ = [
    "SKILL_DELIBERATIONS_SUMMARY_KEY",
    "SkillDeliberationService",
    "SkillServiceError",
]

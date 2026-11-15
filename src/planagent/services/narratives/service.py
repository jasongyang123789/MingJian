"""Narrative service: input assembly, validation, persistence, polish.

Reads stored fragments directly with the same Pydantic models the
writing services used (Sprint 6 context-builder precedent) — no
coupling to ``SimulationService``. Every direction reference is
validated before composing or persisting anything: a generation
request with a bad reference refuses before any row is written.

Storage is a new table (migration 0035), not a run-summary key:
narratives are versioned, append-only deliverables that must be
queryable on their own, following the calibration-fits precedent.
Regeneration inserts a new version; nothing is ever overwritten.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from planagent.config import Settings
from planagent.domain.enums import SimulationRunStatus
from planagent.domain.models import (
    CalibrationFitRecord,
    DecisionNarrativePolishRecord,
    DecisionNarrativeRecord,
    SimulationRun,
    StrategyLoopRecord,
)
from planagent.services.distributions.canonical import sha256_hash
from planagent.services.distributions.models import MonteCarloResult
from planagent.services.living_loop.models import TriggerRegistration
from planagent.services.living_loop.monitoring import select_registration
from planagent.services.mece.models import DecompositionTree, MeceValidationResult
from planagent.services.narratives.composer import (
    DirectionInputs,
    LoopContextInput,
    NarrativeInputs,
    compose_narrative,
)
from planagent.services.narratives.models import (
    MAX_CALIBRATION_FITS_IN_CONTEXT,
    CalibrationContextEntry,
    DecisionNarrativeListRead,
    DecisionNarrativeRead,
    DirectionDefinition,
    NarrativeBody,
    NarrativeError,
    NarrativeGenerateRequest,
    NarrativePolishRead,
)
from planagent.services.narratives.polish import (
    POLISH_TEMPLATE_ID,
    POLISH_TEMPLATE_VERSION,
    polish_markdown,
)
from planagent.services.openai_client import OpenAIService
from planagent.services.robustness.models import DecisionGatesRead, RobustnessRead
from planagent.services.simulation.distributions import MONTE_CARLO_SUMMARY_KEY
from planagent.services.simulation.robustness import (
    DECISION_GATES_SUMMARY_KEY,
    ROBUSTNESS_SUMMARY_KEY,
)
from planagent.services.skills.contracts import SkillContractError
from planagent.services.skills.models import SkillDeliberationRecord
from planagent.services.skills.orchestration import (
    OpenAIServiceSkillPort,
    SkillLLMPort,
    SkillLLMResponse,
    SkillLLMUnavailable,
)
from planagent.services.skills.service import SKILL_DELIBERATIONS_SUMMARY_KEY

_MECE_CONFIGURATION_KEY = "mece"


class _NoLLMPort:
    """Port used when no LLM service is wired: always unavailable."""

    def is_available(self) -> bool:
        return False

    async def generate_json(self, **_kwargs: Any) -> SkillLLMResponse:
        raise SkillLLMUnavailable("No LLM service is configured for narrative polish.")


def _corrupt(fragment: str, exc: ValidationError) -> NarrativeError:
    return NarrativeError(
        "narrative_corrupt_fragment",
        f"Stored {fragment} fragment fails its model: {exc}",
    )


class NarrativeService:
    """Generates, lists, reads, and optionally polishes narratives."""

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

    # -- generation ------------------------------------------------------

    async def generate(
        self, session: AsyncSession, run_id: str, request: NarrativeGenerateRequest
    ) -> DecisionNarrativeRead:
        anchor = await session.get(SimulationRun, run_id)
        if anchor is None:
            raise LookupError(f"Simulation run {run_id} was not found.")
        if anchor.status != SimulationRunStatus.COMPLETED.value:
            raise NarrativeError(
                "narrative_requires_completed_run",
                "Narrative generation requires a completed anchor run.",
            )
        tree, validation = self._read_mece(anchor)
        anchor_deliberations = self._read_deliberations(anchor)
        direction_inputs = [
            await self._assemble_direction(session, definition, anchor_deliberations)
            for definition in request.directions
        ]
        loop_context = await self._read_loop(session, request.loop_id, anchor.id)
        calibration_context = await self._read_calibration(session, anchor.domain_id)
        composed = compose_narrative(
            NarrativeInputs(
                anchor_run_id=anchor.id,
                domain_id=anchor.domain_id,
                request_topic=request.topic,
                mece_tree=tree,
                mece_validation=validation,
                directions=direction_inputs,
                calibration_context=calibration_context,
                loop_context=loop_context,
            )
        )
        body_dump = composed.body.model_dump(mode="json")
        max_version = (
            await session.execute(
                select(func.coalesce(func.max(DecisionNarrativeRecord.version), 0)).where(
                    DecisionNarrativeRecord.run_id == anchor.id
                )
            )
        ).scalar_one()
        record = DecisionNarrativeRecord(
            run_id=anchor.id,
            version=int(max_version) + 1,
            topic=composed.body.topic,
            inputs_hash=sha256_hash(composed.input_pins),
            content_hash=sha256_hash(body_dump),
            artifact=body_dump,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return self._to_read(record, polish=None)

    async def _assemble_direction(
        self,
        session: AsyncSession,
        definition: DirectionDefinition,
        anchor_deliberations: list[SkillDeliberationRecord],
    ) -> DirectionInputs:
        source = await session.get(SimulationRun, definition.source_run_id)
        if source is None:
            raise NarrativeError(
                "narrative_unknown_source_run",
                f"Direction {definition.name!r} names unknown source run "
                f"{definition.source_run_id!r}.",
            )
        if source.status != SimulationRunStatus.COMPLETED.value:
            raise NarrativeError(
                "narrative_source_run_not_completed",
                f"Direction {definition.name!r} draws on run "
                f"{definition.source_run_id!r}, which is not completed.",
            )
        summary = source.summary or {}
        ensemble_fragment = summary.get(MONTE_CARLO_SUMMARY_KEY)
        if ensemble_fragment is None:
            raise NarrativeError(
                "narrative_requires_ensemble",
                f"Direction {definition.name!r} draws on run "
                f"{definition.source_run_id!r}, which has no stored ensemble. "
                f"Run POST /runs/{definition.source_run_id}/monte-carlo first.",
            )
        try:
            ensemble = MonteCarloResult.model_validate(ensemble_fragment)
        except ValidationError as exc:
            raise _corrupt("monte_carlo", exc) from exc
        robustness: RobustnessRead | None = None
        robustness_fragment = summary.get(ROBUSTNESS_SUMMARY_KEY)
        if robustness_fragment is not None:
            try:
                robustness = RobustnessRead.model_validate(robustness_fragment)
            except ValidationError as exc:
                raise _corrupt("robustness", exc) from exc
        gates: DecisionGatesRead | None = None
        gates_fragment = summary.get(DECISION_GATES_SUMMARY_KEY)
        if gates_fragment is not None:
            try:
                gates = DecisionGatesRead.model_validate(gates_fragment)
            except ValidationError as exc:
                raise _corrupt("decision_gates", exc) from exc
        return DirectionInputs(
            definition=definition,
            ensemble=ensemble,
            tornado=robustness.tornado if robustness else None,
            threshold_search=robustness.threshold_search if robustness else None,
            expected_shortfall=robustness.expected_shortfall if robustness else None,
            bootstrap=robustness.bootstrap if robustness else None,
            gates=gates,
            deliberations=self._read_deliberations(source),
            anchor_deliberations=anchor_deliberations,
        )

    def _read_mece(
        self, run: SimulationRun
    ) -> tuple[DecompositionTree | None, MeceValidationResult | None]:
        fragment = (run.configuration or {}).get(_MECE_CONFIGURATION_KEY)
        if fragment is None:
            return None, None
        try:
            tree = DecompositionTree.model_validate(fragment["decomposition"])
            validation = MeceValidationResult.model_validate(fragment["validation"])
        except (ValidationError, KeyError, TypeError) as exc:
            raise NarrativeError(
                "narrative_corrupt_fragment",
                f"Stored mece fragment fails its model: {exc}",
            ) from exc
        return tree, validation

    def _read_deliberations(self, run: SimulationRun) -> list[SkillDeliberationRecord]:
        stored = (run.summary or {}).get(SKILL_DELIBERATIONS_SUMMARY_KEY) or []
        try:
            return [SkillDeliberationRecord.model_validate(item) for item in stored]
        except ValidationError as exc:
            raise _corrupt("skill_deliberations", exc) from exc

    async def _read_loop(
        self, session: AsyncSession, loop_id: str | None, anchor_run_id: str
    ) -> LoopContextInput | None:
        if loop_id is None:
            return None
        row = await session.get(StrategyLoopRecord, loop_id)
        if row is None:
            raise NarrativeError(
                "narrative_loop_not_found",
                f"Loop {loop_id!r} was not found.",
            )
        if row.baseline_run_id != anchor_run_id:
            raise NarrativeError(
                "narrative_loop_baseline_mismatch",
                f"Loop {loop_id!r} baselines run {row.baseline_run_id!r}, "
                f"not the anchor run {anchor_run_id!r}.",
            )
        try:
            registrations = [
                TriggerRegistration.model_validate(item) for item in (row.triggers or [])
            ]
        except ValidationError as exc:
            raise _corrupt("loop triggers", exc) from exc
        registration = select_registration(registrations)
        return LoopContextInput(
            loop_id=row.id,
            loop_name=row.name,
            registration_id=registration.id if registration else None,
            triggers=list(registration.triggers) if registration else [],
        )

    async def _read_calibration(
        self, session: AsyncSession, domain_id: str
    ) -> list[CalibrationContextEntry]:
        result = await session.execute(
            select(CalibrationFitRecord)
            .where(CalibrationFitRecord.domain_id == domain_id)
            .order_by(CalibrationFitRecord.created_at.desc(), CalibrationFitRecord.id.desc())
            .limit(MAX_CALIBRATION_FITS_IN_CONTEXT)
        )
        return [
            CalibrationContextEntry(
                fit_id=row.id,
                kind=row.kind,
                loo_rmse=row.loo_rmse,
                inputs_hash=row.inputs_hash,
                calibrated_template_id=row.calibrated_template_id,
                n_observations=row.n_observations,
                created_at=row.created_at.isoformat(),
            )
            for row in result.scalars().all()
        ]

    # -- reads -----------------------------------------------------------

    async def list_narratives(
        self, session: AsyncSession, run_id: str
    ) -> DecisionNarrativeListRead:
        run = await session.get(SimulationRun, run_id)
        if run is None:
            raise LookupError(f"Simulation run {run_id} was not found.")
        result = await session.execute(
            select(DecisionNarrativeRecord)
            .where(DecisionNarrativeRecord.run_id == run_id)
            .order_by(DecisionNarrativeRecord.version.desc())
        )
        rows = list(result.scalars().all())
        polishes = await self._latest_polishes(session, [row.id for row in rows])
        return DecisionNarrativeListRead(
            run_id=run_id,
            narratives=[self._to_read(row, polishes.get(row.id)) for row in rows],
        )

    async def get_narrative(
        self, session: AsyncSession, run_id: str, narrative_id: str
    ) -> DecisionNarrativeRead:
        record = await self._narrative_for_run(session, run_id, narrative_id)
        polishes = await self._latest_polishes(session, [record.id])
        return self._to_read(record, polishes.get(record.id))

    async def _narrative_for_run(
        self, session: AsyncSession, run_id: str, narrative_id: str
    ) -> DecisionNarrativeRecord:
        record = await session.get(DecisionNarrativeRecord, narrative_id)
        if record is None or record.run_id != run_id:
            raise LookupError(f"Narrative {narrative_id} was not found for run {run_id}.")
        return record

    async def _latest_polishes(
        self, session: AsyncSession, narrative_ids: list[str]
    ) -> dict[str, NarrativePolishRead]:
        if not narrative_ids:
            return {}
        result = await session.execute(
            select(DecisionNarrativePolishRecord)
            .where(DecisionNarrativePolishRecord.narrative_id.in_(narrative_ids))
            .order_by(
                DecisionNarrativePolishRecord.created_at.desc(),
                DecisionNarrativePolishRecord.id.desc(),
            )
        )
        latest: dict[str, NarrativePolishRead] = {}
        for row in result.scalars().all():
            latest.setdefault(row.narrative_id, self._polish_to_read(row))
        return latest

    def _to_read(
        self, record: DecisionNarrativeRecord, polish: NarrativePolishRead | None
    ) -> DecisionNarrativeRead:
        try:
            body = NarrativeBody.model_validate(record.artifact)
        except ValidationError as exc:
            raise _corrupt("decision_narratives.artifact", exc) from exc
        return DecisionNarrativeRead(
            id=record.id,
            run_id=record.run_id,
            version=record.version,
            topic=record.topic,
            inputs_hash=record.inputs_hash,
            content_hash=record.content_hash,
            created_at=record.created_at.isoformat(),
            body=body,
            polish=polish,
        )

    @staticmethod
    def _polish_to_read(row: DecisionNarrativePolishRecord) -> NarrativePolishRead:
        return NarrativePolishRead(
            id=row.id,
            narrative_id=row.narrative_id,
            model=row.model,
            template_id=row.template_id,
            template_version=row.template_version,
            polished_markdown=row.polished_markdown,
            created_at=row.created_at.isoformat(),
        )

    # -- polish ----------------------------------------------------------

    async def polish(
        self, session: AsyncSession, run_id: str, narrative_id: str
    ) -> NarrativePolishRead:
        """Run one LLM polish pass; the artifact row is never touched.

        Raises :class:`NarrativeError` with code
        ``narrative_polish_unavailable`` (route maps to 503) when no
        LLM is configured, and ``narrative_polish_contract_failed``
        (route maps to 502) when the output fails its contract. Both
        write nothing.
        """
        record = await self._narrative_for_run(session, run_id, narrative_id)
        body = self._to_read(record, polish=None).body
        try:
            output, model = await polish_markdown(self._port, body.markdown)
        except SkillLLMUnavailable as exc:
            raise NarrativeError("narrative_polish_unavailable", str(exc)) from exc
        except SkillContractError as exc:
            raise NarrativeError("narrative_polish_contract_failed", str(exc)) from exc
        row = DecisionNarrativePolishRecord(
            narrative_id=record.id,
            model=model,
            template_id=POLISH_TEMPLATE_ID,
            template_version=POLISH_TEMPLATE_VERSION,
            polished_markdown=output.polished_markdown,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return self._polish_to_read(row)


__all__ = ["NarrativeService"]

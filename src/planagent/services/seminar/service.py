"""Seminar service (Sprint 16).

Wires the seminar mechanism into the existing service patterns:
creates seminars over completed runs (frozen case snapshot, roster +
chair config stored, chair availability checked BEFORE any row is
written), runs explicit advance waves (bounded-concurrency asyncio,
per-model failure isolation, sequential deterministic persistence),
and runs explicit finalization (verdicts for eligible models).

No scheduler, no worker, no background progression of any kind: every
wave and every finalization is an explicit request (the Sprint 9
automation boundary). The service never touches the numeric core: it
reads stored engine products at freeze time and writes only seminar
tables.

Port injection: the service takes a ``port_factory`` mapping a
:class:`ModelPortConfig` to a :class:`SkillLLMPort`. Production uses
:func:`default_port_factory` (parameterized ports from settings +
environment); tests inject fake ports. The chair port is built and
availability-checked at creation; roster ports are built per wave
(roster unavailability surfaces per model at advance time, isolated
per design §10.1 — it is NOT a creation-time refusal).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from planagent.config import Settings
from planagent.domain.enums import SimulationRunStatus
from planagent.domain.models import (
    SeminarBoardRecord,
    SeminarFinalRecord,
    SeminarRecord,
    SeminarRoundRecord,
    SimulationRun,
    generate_id,
    utc_now,
)
from planagent.services.seminar.engine import (
    RoundOutcome,
    classify_error,
    derive_model_status,
    run_round,
    run_verdict,
)
from planagent.services.seminar.models import (
    AdvanceModelRead,
    AdvanceRead,
    FinalizeModelRead,
    FinalizeRead,
    ModelPortConfig,
    ModelStatus,
    RosterEntry,
    SeminarConfig,
    SeminarCreateRead,
    SeminarCreateRequest,
    SeminarStatus,
    validate_seminar_transition,
)
from planagent.services.seminar.port import default_port_factory
from planagent.services.seminar.snapshot import (
    fetch_calibration_fits,
    freeze_case_snapshot,
    latest_narrative_directions,
)
from planagent.services.skills.orchestration import SkillLLMPort

PortFactory = Callable[[ModelPortConfig], SkillLLMPort]

_TERMINAL_STATUSES = frozenset(
    {
        SeminarStatus.SYNTHESIZING.value,
        SeminarStatus.REPORTED.value,
        SeminarStatus.PARTIAL.value,
    }
)


class SeminarServiceError(ValueError):
    """A client-visible seminar-service failure with a stable error code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class SeminarChairUnavailable(RuntimeError):
    """The chair endpoint is not configured; nothing was written."""


class SeminarService:
    """Runs multi-model seminars over frozen case snapshots."""

    def __init__(
        self,
        settings: Settings,
        port_factory: PortFactory | None = None,
    ) -> None:
        self.settings = settings
        self._port_factory = port_factory or default_port_factory(settings)

    # -- loading helpers -------------------------------------------------

    async def _get_seminar(self, session: AsyncSession, seminar_id: str) -> SeminarRecord:
        seminar = await session.get(SeminarRecord, seminar_id)
        if seminar is None:
            raise LookupError(f"Seminar {seminar_id} was not found.")
        return seminar

    async def _round_rows(
        self, session: AsyncSession, seminar_id: str
    ) -> list[SeminarRoundRecord]:
        result = await session.execute(
            select(SeminarRoundRecord)
            .where(SeminarRoundRecord.seminar_id == seminar_id)
            .order_by(SeminarRoundRecord.model_id, SeminarRoundRecord.round_no)
        )
        return list(result.scalars().all())

    async def _board_rows(
        self, session: AsyncSession, seminar_id: str
    ) -> list[SeminarBoardRecord]:
        result = await session.execute(
            select(SeminarBoardRecord)
            .where(SeminarBoardRecord.seminar_id == seminar_id)
            .order_by(SeminarBoardRecord.seq)
        )
        return list(result.scalars().all())

    async def _final_rows(
        self, session: AsyncSession, seminar_id: str
    ) -> list[SeminarFinalRecord]:
        result = await session.execute(
            select(SeminarFinalRecord).where(
                SeminarFinalRecord.seminar_id == seminar_id
            )
        )
        return list(result.scalars().all())

    def _model_statuses(
        self,
        *,
        roster: list[RosterEntry],
        config: SeminarConfig,
        round_rows: list[SeminarRoundRecord],
        board_rows: list[SeminarBoardRecord],
        final_model_ids: frozenset[str],
    ) -> dict[str, ModelStatus]:
        digests: dict[str, dict[int, dict[str, Any]]] = {}
        for board_row in board_rows:
            digests.setdefault(board_row.model_id, {})[board_row.round_no] = (
                board_row.digest or {}
            )
        rounds_by_model: dict[str, list[dict[str, Any]]] = {}
        for row in round_rows:
            rounds_by_model.setdefault(row.model_id, []).append(
                {
                    "round_no": row.round_no,
                    "status": row.status,
                    "reflection": row.reflection,
                }
            )
        statuses: dict[str, ModelStatus] = {}
        for entry in roster:
            max_rounds = entry.max_rounds or config.max_rounds
            statuses[entry.model_id] = derive_model_status(
                round_rows=rounds_by_model.get(entry.model_id, []),
                digests_by_round=digests.get(entry.model_id, {}),
                has_final=entry.model_id in final_model_ids,
                max_rounds=max_rounds,
                quiet_rounds=config.quiet_rounds,
            )
        return statuses

    # -- creation --------------------------------------------------------

    async def create_seminar(
        self,
        session: AsyncSession,
        run_id: str,
        request: SeminarCreateRequest,
    ) -> SeminarCreateRead:
        run = await session.get(SimulationRun, run_id)
        if run is None:
            raise LookupError(f"Simulation run {run_id} was not found.")
        if run.status != SimulationRunStatus.COMPLETED.value:
            raise SeminarServiceError(
                "seminar_requires_completed_run",
                "A seminar requires a completed run to argue about.",
            )
        if len(request.roster) < 2:
            raise SeminarServiceError(
                "seminar_roster_too_small",
                "A seminar requires at least 2 models on the roster.",
            )
        model_ids = [entry.model_id for entry in request.roster]
        if len(set(model_ids)) != len(model_ids):
            raise SeminarServiceError(
                "seminar_duplicate_model_id",
                "Roster model_ids must be unique within a seminar.",
            )
        # Chair liveness (config-level, no network): the chair port must
        # resolve to a configured endpoint, checked BEFORE any row is
        # written — the skills 503 discipline. Full chair-call liveness
        # is an S17 concern (the chair port machinery lands with
        # synthesis); creation validates shape + configuration only.
        chair_port = self._port_factory(request.chair_model)
        if not chair_port.is_available():
            raise SeminarChairUnavailable(
                "The chair model endpoint is not configured; "
                "the seminar cannot be synthesized later."
            )
        chair_participates = request.chair_model.model_id in model_ids
        config = request.to_config(chair_participates=chair_participates)
        fits = await fetch_calibration_fits(session, run.domain_id)
        narrative_directions = await latest_narrative_directions(session, run.id)
        snapshot, snapshot_hash = freeze_case_snapshot(
            run=run,
            topic=request.topic,
            options=list(request.options),
            context_lines=list(request.context_lines),
            calibration_fits=fits,
            narrative_directions=narrative_directions,
        )
        record = SeminarRecord(
            id=generate_id(),
            run_id=run.id,
            topic=request.topic,
            case_snapshot=snapshot,
            case_snapshot_hash=snapshot_hash,
            roster=[entry.model_dump(mode="json") for entry in request.roster],
            config=config.model_dump(mode="json"),
            chair_model=request.chair_model.model_dump(mode="json"),
            status=SeminarStatus.OPEN.value,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return SeminarCreateRead(
            seminar_id=record.id,
            run_id=record.run_id,
            status=record.status,
            case_snapshot_hash=record.case_snapshot_hash,
            topic=record.topic,
            roster=[RosterEntry.model_validate(item) for item in record.roster],
            config=SeminarConfig.model_validate(record.config),
            chair_model=ModelPortConfig.model_validate(record.chair_model),
        )

    # -- advance ---------------------------------------------------------

    async def advance_seminar(
        self, session: AsyncSession, seminar_id: str
    ) -> AdvanceRead:
        seminar = await self._get_seminar(session, seminar_id)
        if seminar.status in _TERMINAL_STATUSES:
            raise SeminarServiceError(
                "seminar_terminated",
                f"Seminar {seminar_id} is {seminar.status} and cannot advance.",
            )
        roster = [RosterEntry.model_validate(item) for item in seminar.roster]
        config = SeminarConfig.model_validate(seminar.config)
        round_rows = await self._round_rows(session, seminar_id)
        board_rows = await self._board_rows(session, seminar_id)
        final_rows = await self._final_rows(session, seminar_id)
        final_model_ids = frozenset(row.model_id for row in final_rows)
        statuses = self._model_statuses(
            roster=roster,
            config=config,
            round_rows=round_rows,
            board_rows=board_rows,
            final_model_ids=final_model_ids,
        )
        active = [entry for entry in roster if statuses[entry.model_id] == "active"]
        wave_no = max((row.round_no for row in round_rows), default=0)
        if not active:
            return AdvanceRead(
                seminar_id=seminar.id,
                wave_no=wave_no,
                per_model=[],
                status=seminar.status,
            )

        # The wave-start board snapshot: every model in the wave reads
        # the same snapshot; same-wave publications are invisible until
        # the next wave (async semantics, design §4.2).
        board_snapshot: list[dict[str, Any]] = [
            {
                "seq": row.seq,
                "model_id": row.model_id,
                "round_no": row.round_no,
                "digest": row.digest or {},
            }
            for row in board_rows
        ]
        snapshot_seq = max((row["seq"] for row in board_snapshot), default=0)
        rounds_by_model: dict[str, list[dict[str, Any]]] = {}
        digests_by_model: dict[str, dict[int, dict[str, Any]]] = {}
        for row in round_rows:
            rounds_by_model.setdefault(row.model_id, []).append(
                {
                    "round_no": row.round_no,
                    "status": row.status,
                    "reflection": row.reflection,
                }
            )
        for item in board_snapshot:
            digests_by_model.setdefault(item["model_id"], {})[item["round_no"]] = (
                item["digest"]
            )

        semaphore = asyncio.Semaphore(config.max_concurrency)

        async def _run_one(entry: RosterEntry) -> RoundOutcome:
            prior = rounds_by_model.get(entry.model_id, [])
            round_no = max((item["round_no"] for item in prior), default=0) + 1
            port = self._port_factory(entry)
            async with semaphore:
                return await run_round(
                    port,
                    model_id=entry.model_id,
                    round_no=round_no,
                    board_snapshot_seq=snapshot_seq,
                    board_rows=board_snapshot,
                    prior_rounds=prior,
                    digests_by_round=digests_by_model.get(entry.model_id, {}),
                    snapshot=seminar.case_snapshot or {},
                    pipeline=config.pipeline,
                    mode=config.mode,
                    decision_question=config.decision_question,
                    options=list(config.options),
                    output_language=config.output_language,
                    include_premortem=config.include_premortem,
                    failure_date=config.failure_date,
                    snapshot_policy=config.snapshot_policy,
                )

        # gather() without return_exceptions: run_round captures stage
        # failures itself, so a raise here is a genuine defect, not a
        # model failure — it must surface, not be recorded as a round.
        outcomes = await asyncio.gather(*(_run_one(entry) for entry in active))

        # Sequential persistence in roster order: board seq assignment
        # is deterministic (wave order x roster order), and a single
        # commit keeps the wave atomic.
        next_seq = snapshot_seq
        per_model: list[AdvanceModelRead] = []
        for outcome in outcomes:
            session.add(
                SeminarRoundRecord(
                    id=generate_id(),
                    seminar_id=seminar.id,
                    model_id=outcome.model_id,
                    round_no=outcome.round_no,
                    board_snapshot_seq=outcome.board_snapshot_seq,
                    stages=[stage.model_dump(mode="json") for stage in outcome.stages],
                    reflection=(
                        outcome.reflection.model_dump(mode="json")
                        if outcome.reflection is not None
                        else None
                    ),
                    reflection_stage=(
                        outcome.reflection_stage.model_dump(mode="json")
                        if outcome.reflection_stage is not None
                        else None
                    ),
                    status=outcome.status,
                    error=(
                        outcome.error.model_dump(mode="json")
                        if outcome.error is not None
                        else None
                    ),
                    created_at=utc_now(),
                )
            )
            if outcome.digest is not None:
                next_seq += 1
                session.add(
                    SeminarBoardRecord(
                        id=generate_id(),
                        seminar_id=seminar.id,
                        seq=next_seq,
                        model_id=outcome.model_id,
                        round_no=outcome.round_no,
                        digest=outcome.digest.model_dump(mode="json"),
                        created_at=utc_now(),
                    )
                )
            per_model.append(
                AdvanceModelRead(
                    model_id=outcome.model_id,
                    round_no=outcome.round_no,
                    status=outcome.status,
                    board_snapshot_seq=outcome.board_snapshot_seq,
                )
            )
        await session.commit()

        # Recompute statuses from the newly stored rows and advance the
        # seminar state machine: running until every model terminates,
        # then collecting.
        round_rows = await self._round_rows(session, seminar_id)
        board_rows = await self._board_rows(session, seminar_id)
        statuses = self._model_statuses(
            roster=roster,
            config=config,
            round_rows=round_rows,
            board_rows=board_rows,
            final_model_ids=final_model_ids,
        )
        target = (
            SeminarStatus.COLLECTING.value
            if all(status != "active" for status in statuses.values())
            else SeminarStatus.RUNNING.value
        )
        validate_seminar_transition(seminar.status, target)
        seminar.status = target
        seminar.updated_at = utc_now()
        await session.commit()
        wave_no = max((row.round_no for row in round_rows), default=0)
        return AdvanceRead(
            seminar_id=seminar.id,
            wave_no=wave_no,
            per_model=per_model,
            status=seminar.status,
        )

    # -- finalize --------------------------------------------------------

    async def finalize_seminar(
        self, session: AsyncSession, seminar_id: str
    ) -> FinalizeRead:
        seminar = await self._get_seminar(session, seminar_id)
        if seminar.status in _TERMINAL_STATUSES:
            raise SeminarServiceError(
                "seminar_terminated",
                f"Seminar {seminar_id} is {seminar.status} and cannot finalize.",
            )
        roster = [RosterEntry.model_validate(item) for item in seminar.roster]
        config = SeminarConfig.model_validate(seminar.config)
        round_rows = await self._round_rows(session, seminar_id)
        board_rows = await self._board_rows(session, seminar_id)
        final_rows = await self._final_rows(session, seminar_id)
        final_model_ids = frozenset(row.model_id for row in final_rows)
        board_snapshot: list[dict[str, Any]] = [
            {
                "seq": row.seq,
                "model_id": row.model_id,
                "round_no": row.round_no,
                "digest": row.digest or {},
            }
            for row in board_rows
        ]
        snapshot_seq = max((row["seq"] for row in board_snapshot), default=0)
        rounds_by_model: dict[str, list[dict[str, Any]]] = {}
        digests_by_model: dict[str, dict[int, dict[str, Any]]] = {}
        for row in round_rows:
            rounds_by_model.setdefault(row.model_id, []).append(
                {
                    "round_no": row.round_no,
                    "status": row.status,
                    "reflection": row.reflection,
                }
            )
        for item in board_snapshot:
            digests_by_model.setdefault(item["model_id"], {})[item["round_no"]] = (
                item["digest"]
            )

        semaphore = asyncio.Semaphore(config.max_concurrency)

        async def _verdict_for(
            entry: RosterEntry,
        ) -> tuple[RosterEntry, str, dict[str, Any] | None, Any]:
            if entry.model_id in final_model_ids:
                return entry, "already_final", None, None
            prior = rounds_by_model.get(entry.model_id, [])
            usable = [
                item
                for item in prior
                if item["status"] in ("completed", "completed_reflection_missing")
            ]
            if not usable:
                return entry, "skipped_no_usable_round", None, None
            port = self._port_factory(entry)
            try:
                async with semaphore:
                    verdict, stage = await run_verdict(
                        port,
                        model_id=entry.model_id,
                        board_snapshot_seq=snapshot_seq,
                        board_rows=board_snapshot,
                        prior_rounds=prior,
                        digests_by_round=digests_by_model.get(entry.model_id, {}),
                        snapshot=seminar.case_snapshot or {},
                        output_language=config.output_language,
                        snapshot_policy=config.snapshot_policy,
                    )
            except Exception as exc:  # noqa: BLE001 — verdict failure: zero rows
                return (
                    entry,
                    "failed",
                    {
                        "kind": classify_error(exc),
                        "stage": "final_verdict",
                        "message": str(exc)[:500],
                    },
                    None,
                )
            return entry, "final", None, (verdict, stage)

        results = await asyncio.gather(
            *(_verdict_for(entry) for entry in roster)
        )
        finals: list[FinalizeModelRead] = []
        for entry, status, error, payload in results:
            if status == "final" and payload is not None:
                verdict, stage = payload
                session.add(
                    SeminarFinalRecord(
                        id=generate_id(),
                        seminar_id=seminar.id,
                        model_id=entry.model_id,
                        verdict=verdict.model_dump(mode="json"),
                        stage=stage.model_dump(mode="json"),
                        board_snapshot_seq=snapshot_seq,
                        status="final",
                        created_at=utc_now(),
                    )
                )
            finals.append(
                FinalizeModelRead(
                    model_id=entry.model_id, status=status, error=error
                )
            )
        await session.commit()
        return FinalizeRead(
            seminar_id=seminar.id, finals=finals, status=seminar.status
        )


__all__ = [
    "PortFactory",
    "SeminarChairUnavailable",
    "SeminarService",
    "SeminarServiceError",
]

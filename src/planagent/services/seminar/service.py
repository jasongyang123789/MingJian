"""Seminar service (Sprint 16–18).

Wires the seminar mechanism into the existing service patterns:
creates seminars over completed runs (frozen case snapshot, roster +
chair config stored, chair availability checked BEFORE any row is
written), runs explicit advance waves (bounded-concurrency asyncio,
per-model failure isolation, sequential deterministic persistence),
runs explicit finalization (verdicts for eligible models), and runs
explicit chair synthesis (clustering + synthesis + deterministic
composer fallback, versioned reports).

No scheduler, no worker, no background progression of any kind: every
wave, finalization, and synthesis is an explicit request (the Sprint
9 automation boundary). The service never touches the numeric core:
it reads stored engine products at freeze time and writes only
seminar tables.

Port injection: the service takes a ``port_factory`` mapping a
:class:`ModelPortConfig` to a :class:`SkillLLMPort`. Production uses
:func:`default_port_factory` (parameterized ports from settings +
environment); tests inject fake ports. The chair port is built and
availability-checked at creation; roster ports are built per wave
(roster unavailability surfaces per model at advance time, isolated
per design §10.1 — it is NOT a creation-time refusal). At synthesize
time the chair port is rebuilt: chair unavailability or chair-stage
failure does NOT refuse the request — the deterministic composer
produces a fallback report and the report records the path and the
reason (design §7.4/§10.1).

Sprint 18 hardening: every port is wrapped in
:class:`~planagent.services.seminar.instrumentation.InstrumentedPort`
(timeout-only retries, per-seminar budgets, audit observation);
synthesizes to one seminar serialize on a per-seminar lock instead
of refusing; agent-chair seminars (``chair_mode="agent"``) produce a
stored chair brief on synthesize and accept a validated chair
submission; every operation writes to the append-only audit log.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any, NoReturn

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from planagent.config import Settings
from planagent.domain.enums import SimulationRunStatus
from planagent.domain.models import (
    SeminarAuditEventRecord,
    SeminarBoardRecord,
    SeminarChairBriefRecord,
    SeminarFinalRecord,
    SeminarRecord,
    SeminarReportRecord,
    SeminarRoundRecord,
    SimulationRun,
    generate_id,
    utc_now,
)
from planagent.services.distributions.canonical import sha256_hash
from planagent.services.seminar.audit import (
    AuditEventKind,
    AuditEventRead,
    AuditRecorder,
    BudgetRead,
    compute_diagnosis,
    ledger_totals,
    rollup_usage_by_model,
)
from planagent.services.seminar.chair import build_chair_brief, run_cluster, run_synthesize
from planagent.services.seminar.clustering import (
    collect_claim_items,
    deterministic_clusters,
    deterministic_prepass,
    expand_clusters,
)
from planagent.services.seminar.composer import compose_report
from planagent.services.seminar.contracts import (
    ClaimClusters,
    SeminarSynthesis,
    parse_seminar_stage_output,
)
from planagent.services.seminar.engine import (
    RoundOutcome,
    classify_error,
    derive_model_status,
    run_round,
    run_verdict,
)
from planagent.services.seminar.instrumentation import BudgetTracker, InstrumentedPort
from planagent.services.seminar.metrics import compute_metrics
from planagent.services.seminar.models import (
    AGENT_CHAIR_MODEL_ID,
    AdvanceModelRead,
    AdvanceRead,
    BoardRowRead,
    ChairBriefRead,
    ChairSynthesisRequest,
    FinalizeModelRead,
    FinalizeRead,
    FinalRowRead,
    ModelPortConfig,
    ModelStatus,
    ReportDetailRead,
    RosterEntry,
    RoundRowRead,
    SeminarConfig,
    SeminarCreateRead,
    SeminarCreateRequest,
    SeminarDetailRead,
    SeminarModelProgress,
    SeminarReportSummary,
    SeminarStatus,
    SeminarSummaryRead,
    SynthesizeRead,
    SynthesizeRequest,
    validate_seminar_transition,
)
from planagent.services.seminar.port import default_port_factory
from planagent.services.seminar.snapshot import (
    fetch_calibration_fits,
    freeze_case_snapshot,
    latest_narrative_directions,
)
from planagent.services.skills.contracts import SkillContractError
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


def compute_report_hash(
    *,
    seminar_id: str,
    chair_model_id: str,
    partial: bool,
    prepass: dict[str, Any],
    cluster_production: str,
    computed_metrics: dict[str, Any],
    verdicts: list[dict[str, Any]],
    synthesis_production_path: str,
) -> str:
    """Hash the report's deterministic content (design §9 audit 4).

    Covers ONLY deterministic inputs: the pre-pass, the computed
    metrics, the verbatim verdicts, and the system facts (partial
    flag, chair, production paths). LLM outputs (cluster wordings,
    synthesis narrative) are excluded, so the same stored inputs
    always hash identically; the version is excluded so a
    re-synthesis from unchanged inputs hashes identically too.
    """
    return sha256_hash(
        {
            "seminar_id": seminar_id,
            "chair_model_id": chair_model_id,
            "partial": partial,
            "prepass": prepass,
            "cluster_production": cluster_production,
            "computed_metrics": computed_metrics,
            "verdicts": [entry["verdict"] for entry in verdicts],
            "synthesis_production_path": synthesis_production_path,
        }
    )


class SeminarService:
    """Runs multi-model seminars over frozen case snapshots."""

    def __init__(
        self,
        settings: Settings,
        port_factory: PortFactory | None = None,
    ) -> None:
        self.settings = settings
        self._port_factory = port_factory or default_port_factory(settings)
        # Per-seminar synthesize locks (Sprint 18): concurrent
        # synthesize/submission requests to one seminar serialize
        # instead of refusing. The service instance is cached on app
        # state (one per process), so this registry serializes across
        # requests. Locks are never removed: one per seminar id, and
        # seminar ids are never reused.
        self._synthesize_locks: dict[str, asyncio.Lock] = {}

    def _synthesize_lock(self, seminar_id: str) -> asyncio.Lock:
        lock = self._synthesize_locks.get(seminar_id)
        if lock is None:
            lock = asyncio.Lock()
            self._synthesize_locks[seminar_id] = lock
        return lock

    # -- loading helpers -------------------------------------------------

    async def _get_seminar(self, session: AsyncSession, seminar_id: str) -> SeminarRecord:
        seminar = await session.get(SeminarRecord, seminar_id)
        if seminar is None:
            raise LookupError(f"Seminar {seminar_id} was not found.")
        return seminar

    async def _round_rows(self, session: AsyncSession, seminar_id: str) -> list[SeminarRoundRecord]:
        result = await session.execute(
            select(SeminarRoundRecord)
            .where(SeminarRoundRecord.seminar_id == seminar_id)
            .order_by(SeminarRoundRecord.model_id, SeminarRoundRecord.round_no)
        )
        return list(result.scalars().all())

    async def _board_rows(self, session: AsyncSession, seminar_id: str) -> list[SeminarBoardRecord]:
        result = await session.execute(
            select(SeminarBoardRecord)
            .where(SeminarBoardRecord.seminar_id == seminar_id)
            .order_by(SeminarBoardRecord.seq)
        )
        return list(result.scalars().all())

    async def _final_rows(self, session: AsyncSession, seminar_id: str) -> list[SeminarFinalRecord]:
        result = await session.execute(
            select(SeminarFinalRecord).where(SeminarFinalRecord.seminar_id == seminar_id)
        )
        return list(result.scalars().all())

    async def _report_rows(
        self, session: AsyncSession, seminar_id: str
    ) -> list[SeminarReportRecord]:
        result = await session.execute(
            select(SeminarReportRecord)
            .where(SeminarReportRecord.seminar_id == seminar_id)
            .order_by(SeminarReportRecord.version)
        )
        return list(result.scalars().all())

    async def _audit_rows(
        self, session: AsyncSession, seminar_id: str
    ) -> list[SeminarAuditEventRecord]:
        result = await session.execute(
            select(SeminarAuditEventRecord)
            .where(SeminarAuditEventRecord.seminar_id == seminar_id)
            .order_by(SeminarAuditEventRecord.seq)
        )
        return list(result.scalars().all())

    async def _audit_event_dicts(
        self, session: AsyncSession, seminar_id: str
    ) -> list[dict[str, Any]]:
        rows = await self._audit_rows(session, seminar_id)
        return [
            {
                "kind": row.kind,
                "model_id": row.model_id,
                "stage": row.stage,
                "detail": row.detail or {},
                "round_no": row.round_no,
                "stage_call_id": row.stage_call_id,
            }
            for row in rows
        ]

    async def _brief_rows(
        self, session: AsyncSession, seminar_id: str
    ) -> list[SeminarChairBriefRecord]:
        result = await session.execute(
            select(SeminarChairBriefRecord)
            .where(SeminarChairBriefRecord.seminar_id == seminar_id)
            .order_by(SeminarChairBriefRecord.version)
        )
        return list(result.scalars().all())

    def _instrumented_port(
        self,
        config: ModelPortConfig,
        *,
        model_id: str,
        round_no: int | None,
        recorder: AuditRecorder,
        tracker: BudgetTracker,
        seminar_config: SeminarConfig,
    ) -> InstrumentedPort:
        return InstrumentedPort(
            self._port_factory(config),
            model_id=model_id,
            round_no=round_no,
            recorder=recorder,
            tracker=tracker,
            max_retries=seminar_config.max_retries,
            backoff_seconds=seminar_config.retry_backoff_seconds,
        )

    async def _seed_tracker(
        self, session: AsyncSession, seminar_id: str, config: SeminarConfig
    ) -> BudgetTracker:
        """Seed a budget tracker from the persisted audit ledger."""
        calls_used, tokens_used = ledger_totals(await self._audit_event_dicts(session, seminar_id))
        return BudgetTracker(
            max_stage_calls=config.max_stage_calls,
            max_tokens=config.max_tokens,
            stage_calls_used=calls_used,
            tokens_used=tokens_used,
        )

    async def _record_refusal(
        self,
        session: AsyncSession,
        *,
        seminar_id: str,
        code: str,
        message: str,
        recorder: AuditRecorder | None = None,
    ) -> None:
        """Write a refusal audit event (its own commit).

        Refusals change no seminar state; the audit event is the only
        row written, so a refused request stays visible in the log
        without creating phantom state. Any pending recorder events
        (e.g. a queue wait) flush in the same commit.
        """
        own_recorder = recorder or AuditRecorder()
        own_recorder.record(
            AuditEventKind.REFUSAL,
            detail={"code": code, "message": message},
        )
        await own_recorder.flush(session, seminar_id=seminar_id)
        await session.commit()

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
            digests.setdefault(board_row.model_id, {})[board_row.round_no] = board_row.digest or {}
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
        # Chair liveness (config-level, no network): in model mode the
        # chair port must resolve to a configured endpoint, checked
        # BEFORE any row is written — the skills 503 discipline. In
        # agent mode (Sprint 18) no model chair is ever called, so no
        # liveness check applies and the chair never participates as
        # a roster model; the stored chair_model config is kept for
        # shape stability but unused.
        if request.chair_mode == "agent":
            chair_participates = False
        else:
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

    async def advance_seminar(self, session: AsyncSession, seminar_id: str) -> AdvanceRead:
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
            digests_by_model.setdefault(item["model_id"], {})[item["round_no"]] = item["digest"]

        semaphore = asyncio.Semaphore(config.max_concurrency)
        recorder = AuditRecorder()
        tracker = await self._seed_tracker(session, seminar_id, config)

        async def _run_one(entry: RosterEntry) -> RoundOutcome:
            prior = rounds_by_model.get(entry.model_id, [])
            round_no = max((item["round_no"] for item in prior), default=0) + 1
            port = self._instrumented_port(
                entry,
                model_id=entry.model_id,
                round_no=round_no,
                recorder=recorder,
                tracker=tracker,
                seminar_config=config,
            )
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
                        outcome.error.model_dump(mode="json") if outcome.error is not None else None
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
        # The wave's audit events commit with the wave's rows: one
        # transaction, so the log and the state can never diverge.
        await recorder.flush(session, seminar_id=seminar.id)
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
        recorder.record(
            AuditEventKind.STATUS_TRANSITION,
            detail={"from": seminar.status, "to": target, "trigger": "advance"},
        )
        seminar.status = target
        seminar.updated_at = utc_now()
        await recorder.flush(session, seminar_id=seminar.id)
        await session.commit()
        wave_no = max((row.round_no for row in round_rows), default=0)
        return AdvanceRead(
            seminar_id=seminar.id,
            wave_no=wave_no,
            per_model=per_model,
            status=seminar.status,
        )

    # -- finalize --------------------------------------------------------

    async def finalize_seminar(self, session: AsyncSession, seminar_id: str) -> FinalizeRead:
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
            digests_by_model.setdefault(item["model_id"], {})[item["round_no"]] = item["digest"]

        semaphore = asyncio.Semaphore(config.max_concurrency)
        recorder = AuditRecorder()
        tracker = await self._seed_tracker(session, seminar_id, config)

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
            port = self._instrumented_port(
                entry,
                model_id=entry.model_id,
                round_no=None,
                recorder=recorder,
                tracker=tracker,
                seminar_config=config,
            )
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

        results = await asyncio.gather(*(_verdict_for(entry) for entry in roster))
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
            finals.append(FinalizeModelRead(model_id=entry.model_id, status=status, error=error))
        await recorder.flush(session, seminar_id=seminar.id)
        await session.commit()
        return FinalizeRead(seminar_id=seminar.id, finals=finals, status=seminar.status)

    # -- synthesize ------------------------------------------------------

    def _absent_models(
        self,
        *,
        roster: list[RosterEntry],
        final_model_ids: frozenset[str],
        statuses: dict[str, ModelStatus],
        round_rows: list[SeminarRoundRecord],
    ) -> list[dict[str, Any]]:
        absent: list[dict[str, Any]] = []
        for entry in roster:
            if entry.model_id in final_model_ids:
                continue
            rows = [row for row in round_rows if row.model_id == entry.model_id]
            latest = max(rows, key=lambda row: row.round_no) if rows else None
            error = (latest.error or {}) if latest is not None else {}
            if error:
                reason = (
                    f"failed at stage {error.get('stage')} "
                    f"({error.get('kind')}): {error.get('message')}"
                )
            else:
                reason = (
                    f"no final verdict stored (model status: "
                    f"{statuses[entry.model_id]}; finalize produced no verdict)"
                )
            absent.append(
                {
                    "model_id": entry.model_id,
                    "status": statuses[entry.model_id],
                    "reason": reason,
                }
            )
        return absent

    async def synthesize_seminar(
        self,
        session: AsyncSession,
        seminar_id: str,
        request: SynthesizeRequest,
    ) -> SynthesizeRead | ChairBriefRead:
        """Synthesize a report — or, in agent-chair mode, a chair brief.

        Concurrent requests to one seminar SERIALIZE on the
        per-seminar lock (Sprint 18): a second request waits for the
        first, then proceeds on fresh state as a new version. The
        lock is acquired before any state is read, so the waiter
        always sees the outcome of the earlier request.
        """
        lock = self._synthesize_lock(seminar_id)
        contended = lock.locked()
        waited_since = time.monotonic()
        await lock.acquire()
        try:
            wait_ms = (time.monotonic() - waited_since) * 1000.0
            return await self._synthesize_under_lock(
                session,
                seminar_id,
                request,
                queue_wait_ms=wait_ms if contended else None,
            )
        finally:
            lock.release()

    async def _refuse(
        self,
        session: AsyncSession,
        *,
        seminar_id: str,
        code: str,
        message: str,
        recorder: AuditRecorder,
    ) -> NoReturn:
        """Record a refusal audit event, then raise the refusal."""
        await self._record_refusal(
            session, seminar_id=seminar_id, code=code, message=message, recorder=recorder
        )
        raise SeminarServiceError(code, message)

    async def _synthesize_under_lock(
        self,
        session: AsyncSession,
        seminar_id: str,
        request: SynthesizeRequest,
        *,
        queue_wait_ms: float | None,
    ) -> SynthesizeRead | ChairBriefRead:
        seminar = await self._get_seminar(session, seminar_id)
        recorder = AuditRecorder()
        if queue_wait_ms is not None:
            recorder.record(
                AuditEventKind.QUEUE_WAIT,
                detail={"wait_ms": queue_wait_ms, "trigger": "synthesize"},
            )
        if seminar.status == SeminarStatus.SYNTHESIZING.value:
            # Stuck, not in flight: this request holds the lock, so no
            # other synthesize is running. A previous attempt crashed
            # without rolling back; the audit log names the step.
            await self._refuse(
                session,
                seminar_id=seminar.id,
                code="seminar_synthesize_stuck",
                message=(
                    f"Seminar {seminar_id} is stuck in synthesizing: a previous "
                    "synthesize attempt did not complete. Inspect the audit log "
                    "(GET /seminars/{id}/audit) to locate the failed step."
                ),
                recorder=recorder,
            )
        if seminar.status == SeminarStatus.OPEN.value:
            await self._refuse(
                session,
                seminar_id=seminar.id,
                code="seminar_not_ready",
                message=(
                    f"Seminar {seminar_id} has never advanced; "
                    "advance and finalize before synthesizing."
                ),
                recorder=recorder,
            )
        roster = [RosterEntry.model_validate(item) for item in seminar.roster]
        config = SeminarConfig.model_validate(seminar.config)
        chair_model = ModelPortConfig.model_validate(seminar.chair_model)
        round_rows = await self._round_rows(session, seminar_id)
        board_rows = await self._board_rows(session, seminar_id)
        final_rows = await self._final_rows(session, seminar_id)
        finals_by_model = {row.model_id: row for row in final_rows}
        verdicts: list[dict[str, Any]] = [
            {
                "model_id": entry.model_id,
                "verdict": finals_by_model[entry.model_id].verdict,
                "stage": finals_by_model[entry.model_id].stage,
                "board_snapshot_seq": finals_by_model[entry.model_id].board_snapshot_seq,
            }
            for entry in roster
            if entry.model_id in finals_by_model
        ]
        # Minimum-threshold refusals happen BEFORE any write (design
        # §10.4): zero finals always refuse; one final refuses unless
        # the caller explicitly allows a partial report. The refusal
        # itself is the only row written (an audit event).
        if not verdicts:
            await self._refuse(
                session,
                seminar_id=seminar.id,
                code="seminar_no_finals",
                message=(
                    "Synthesis requires at least one final verdict; "
                    "this seminar has none. Finalize first."
                ),
                recorder=recorder,
            )
        if len(verdicts) < 2 and not request.allow_partial:
            await self._refuse(
                session,
                seminar_id=seminar.id,
                code="seminar_insufficient_finals",
                message=(
                    "Synthesis requires at least 2 final verdicts; "
                    "this seminar has 1. Pass allow_partial=true to "
                    "synthesize a partial report from a single verdict."
                ),
                recorder=recorder,
            )
        inputs = self._synthesis_inputs(
            roster=roster,
            config=config,
            round_rows=round_rows,
            board_rows=board_rows,
            verdicts=verdicts,
        )

        # Agent-chair mode: produce + store a chair brief and await
        # chair input. No model chair call, no status change, no
        # report row. The deterministic-fallback flag bypasses the
        # brief and writes a deterministic report instead.
        if config.chair_mode == "agent" and not request.deterministic_fallback:
            return await self._produce_chair_brief(
                session,
                seminar=seminar,
                roster=roster,
                config=config,
                inputs=inputs,
                recorder=recorder,
            )

        prior_status = seminar.status
        validate_seminar_transition(prior_status, SeminarStatus.SYNTHESIZING.value)
        recorder.record(
            AuditEventKind.STATUS_TRANSITION,
            detail={
                "from": prior_status,
                "to": SeminarStatus.SYNTHESIZING.value,
                "trigger": "synthesize",
            },
        )
        seminar.status = SeminarStatus.SYNTHESIZING.value
        seminar.updated_at = utc_now()
        await recorder.flush(session, seminar_id=seminar.id)
        await session.commit()
        try:
            return await self._run_synthesis(
                session,
                seminar=seminar,
                roster=roster,
                config=config,
                chair_model=chair_model,
                inputs=inputs,
                recorder=recorder,
                deterministic_only=request.deterministic_fallback,
            )
        except Exception as exc:
            # Failure rollback: no report row, status restored, and
            # the failure itself recorded — the audit events from the
            # failed attempt flush with the restore commit, so the
            # log shows exactly which step failed.
            await session.rollback()
            recorder.record(
                AuditEventKind.SYNTHESIS_FAILED,
                detail={"error_kind": classify_error(exc), "message": str(exc)[:500]},
            )
            recorder.record(
                AuditEventKind.STATUS_TRANSITION,
                detail={
                    "from": SeminarStatus.SYNTHESIZING.value,
                    "to": prior_status,
                    "trigger": "rollback",
                },
            )
            seminar.status = prior_status
            seminar.updated_at = utc_now()
            await recorder.flush(session, seminar_id=seminar.id)
            await session.commit()
            raise

    def _synthesis_inputs(
        self,
        *,
        roster: list[RosterEntry],
        config: SeminarConfig,
        round_rows: list[SeminarRoundRecord],
        board_rows: list[SeminarBoardRecord],
        verdicts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """The shared deterministic synthesis inputs (pre-pass, statuses,
        absent models, round dicts) for the brief, model, fallback,
        and submission paths."""
        round_no_by_model: dict[str, int] = {}
        for row in round_rows:
            round_no_by_model[row.model_id] = max(
                round_no_by_model.get(row.model_id, 0), row.round_no
            )
        items, excluded_placeholders = collect_claim_items(
            verdicts, round_no_by_model=round_no_by_model
        )
        prepass = deterministic_prepass(
            items, near_duplicate_threshold=config.near_duplicate_threshold
        )
        prepass["excluded_dissent_placeholders"] = excluded_placeholders
        final_model_ids = frozenset(entry["model_id"] for entry in verdicts)
        statuses = self._model_statuses(
            roster=roster,
            config=config,
            round_rows=round_rows,
            board_rows=board_rows,
            final_model_ids=final_model_ids,
        )
        absent = self._absent_models(
            roster=roster,
            final_model_ids=final_model_ids,
            statuses=statuses,
            round_rows=round_rows,
        )
        round_dicts = [
            {
                "model_id": row.model_id,
                "round_no": row.round_no,
                "status": row.status,
                "board_snapshot_seq": row.board_snapshot_seq,
                "stages": row.stages or [],
            }
            for row in round_rows
        ]
        return {
            "verdicts": verdicts,
            "items": items,
            "prepass": prepass,
            "statuses": statuses,
            "absent": absent,
            "round_dicts": round_dicts,
        }

    async def _produce_chair_brief(
        self,
        session: AsyncSession,
        *,
        seminar: SeminarRecord,
        roster: list[RosterEntry],
        config: SeminarConfig,
        inputs: dict[str, Any],
        recorder: AuditRecorder,
    ) -> ChairBriefRead:
        """Produce + store one versioned chair brief (agent-chair mode)."""
        clusters = deterministic_clusters(inputs["prepass"])
        computed_metrics = compute_metrics(
            verdicts=inputs["verdicts"],
            clusters=clusters,
            roster_ids=[entry.model_id for entry in roster],
            round_rows=inputs["round_dicts"],
            statuses={model_id: str(status) for model_id, status in inputs["statuses"].items()},
            absent_models=inputs["absent"],
        )
        existing = await self._brief_rows(session, seminar.id)
        version = max((row.version for row in existing), default=0) + 1
        brief = build_chair_brief(
            seminar_id=seminar.id,
            topic=seminar.topic,
            status=seminar.status,
            brief_version=version,
            prepass=inputs["prepass"],
            deterministic_clusters=clusters,
            computed_metrics=computed_metrics,
            verdicts=inputs["verdicts"],
            absent_models=inputs["absent"],
            chair_participates=config.chair_participates,
            chair_model_id=AGENT_CHAIR_MODEL_ID,
            chair_mode="agent",
        )
        session.add(
            SeminarChairBriefRecord(
                id=generate_id(),
                seminar_id=seminar.id,
                version=version,
                brief=brief,
                brief_hash=str(brief["brief_hash"]),
                created_at=utc_now(),
            )
        )
        recorder.record(
            AuditEventKind.CHAIR_BRIEF_PRODUCED,
            detail={"brief_version": version, "brief_hash": brief["brief_hash"]},
        )
        await recorder.flush(session, seminar_id=seminar.id)
        await session.commit()
        return ChairBriefRead.model_validate(brief)

    async def _run_synthesis(
        self,
        session: AsyncSession,
        *,
        seminar: SeminarRecord,
        roster: list[RosterEntry],
        config: SeminarConfig,
        chair_model: ModelPortConfig,
        inputs: dict[str, Any],
        recorder: AuditRecorder,
        deterministic_only: bool,
    ) -> SynthesizeRead:
        """Run the chair stages (or the deterministic path) and write
        the versioned report. The caller owns the synthesizing status
        and the rollback; this method either writes the report or
        raises before any report row exists."""
        verdicts: list[dict[str, Any]] = inputs["verdicts"]
        prepass: dict[str, Any] = inputs["prepass"]
        failures: list[str] = []
        cluster_stage_json: dict[str, Any] | None = None

        # One tracker + one instrumented chair port for BOTH chair
        # stages: the cluster and synthesize calls share one budget
        # position within this synthesis.
        tracker = await self._seed_tracker(session, seminar.id, config)
        chair_port = self._instrumented_port(
            chair_model,
            model_id=chair_model.model_id,
            round_no=None,
            recorder=recorder,
            tracker=tracker,
            seminar_config=config,
        )

        if deterministic_only:
            clusters = deterministic_clusters(prepass)
            failures.append("deterministic fallback requested by the caller")
        else:
            # Stage 1: clustering. Any failure (unavailable port,
            # empty response, contract violation, incomplete merge
            # map, budget exhaustion) falls back to deterministic
            # pre-pass clusters — recorded, never hidden.
            try:
                parsed_clusters, cluster_stage = await run_cluster(
                    chair_port,
                    topic=seminar.topic,
                    prepass=prepass,
                    output_language=config.output_language,
                )
            except Exception as exc:  # noqa: BLE001 — chair failure -> fallback
                clusters = deterministic_clusters(prepass)
                kind = classify_error(exc)
                failures.append(f"cluster stage failed ({kind}): {str(exc)[:300]}")
                recorder.record(
                    AuditEventKind.FALLBACK,
                    model_id=chair_model.model_id,
                    stage="seminar.cluster",
                    detail={"error_kind": kind, "reason": str(exc)[:300]},
                )
            else:
                try:
                    clusters = expand_clusters(parsed_clusters, prepass=prepass)
                except ValueError as exc:
                    clusters = deterministic_clusters(prepass)
                    failures.append(f"cluster stage failed (contract): {str(exc)[:300]}")
                    recorder.record(
                        AuditEventKind.FALLBACK,
                        model_id=chair_model.model_id,
                        stage="seminar.cluster",
                        detail={"error_kind": "contract", "reason": str(exc)[:300]},
                    )
                else:
                    cluster_stage_json = cluster_stage.model_dump(mode="json")
        clusters["stage"] = cluster_stage_json

        computed_metrics = compute_metrics(
            verdicts=verdicts,
            clusters=clusters,
            roster_ids=[entry.model_id for entry in roster],
            round_rows=inputs["round_dicts"],
            statuses={model_id: str(status) for model_id, status in inputs["statuses"].items()},
            absent_models=inputs["absent"],
        )

        # Stage 2: synthesis. Runs over whatever clusters exist (LLM
        # or deterministic); failure leaves synthesis null and the
        # composer marks the narrative sections as not generated.
        # Skipped entirely on the deterministic path.
        synthesis_payload: dict[str, Any] | None = None
        synthesis_stage_json: dict[str, Any] | None = None
        if not deterministic_only:
            try:
                parsed_synthesis, synthesis_stage = await run_synthesize(
                    chair_port,
                    topic=seminar.topic,
                    clusters=clusters,
                    verdicts=verdicts,
                    computed_metrics=computed_metrics,
                    chair_participates=config.chair_participates,
                    chair_model_id=chair_model.model_id,
                    output_language=config.output_language,
                )
                synthesis_payload = parsed_synthesis.model_dump(mode="json")
                synthesis_stage_json = synthesis_stage.model_dump(mode="json")
            except Exception as exc:  # noqa: BLE001 — chair failure -> fallback
                kind = classify_error(exc)
                failures.append(f"synthesize stage failed ({kind}): {str(exc)[:300]}")
                recorder.record(
                    AuditEventKind.FALLBACK,
                    model_id=chair_model.model_id,
                    stage="seminar.synthesize",
                    detail={"error_kind": kind, "reason": str(exc)[:300]},
                )
        synthesis_path = "chair" if synthesis_payload is not None else "deterministic_fallback"
        fallback_reason = "; ".join(failures) if failures else None
        chair_model_id = (
            AGENT_CHAIR_MODEL_ID if config.chair_mode == "agent" else chair_model.model_id
        )
        return await self._write_report(
            session,
            seminar=seminar,
            roster=roster,
            config=config,
            verdicts=verdicts,
            clusters=clusters,
            synthesis_payload=synthesis_payload,
            synthesis_stage_json=synthesis_stage_json,
            computed_metrics=computed_metrics,
            production_path=synthesis_path,
            fallback_reason=fallback_reason,
            chair_model_id=chair_model_id,
            recorder=recorder,
            extra_envelope={"chair_mode": config.chair_mode},
        )

    async def _write_report(
        self,
        session: AsyncSession,
        *,
        seminar: SeminarRecord,
        roster: list[RosterEntry],
        config: SeminarConfig,
        verdicts: list[dict[str, Any]],
        clusters: dict[str, Any],
        synthesis_payload: dict[str, Any] | None,
        synthesis_stage_json: dict[str, Any] | None,
        computed_metrics: dict[str, Any],
        production_path: str,
        fallback_reason: str | None,
        chair_model_id: str,
        recorder: AuditRecorder,
        extra_envelope: dict[str, Any],
    ) -> SynthesizeRead:
        """Store one versioned report row + move the status, with audit.

        Shared by the model-chair, deterministic-fallback, and
        agent-chair-submission paths: versioning, hashing, status
        transition, and audit events are identical; only the
        production inputs differ.
        """
        partial = len(verdicts) < len(roster)
        report_hash = compute_report_hash(
            seminar_id=seminar.id,
            chair_model_id=chair_model_id,
            partial=partial,
            prepass=clusters["prepass"],
            cluster_production=str(clusters.get("production")),
            computed_metrics=computed_metrics,
            verdicts=verdicts,
            synthesis_production_path=production_path,
        )
        existing = await self._report_rows(session, seminar.id)
        version = max((row.version for row in existing), default=0) + 1
        synthesis_envelope: dict[str, Any] = {
            "synthesis": synthesis_payload,
            "stage": synthesis_stage_json,
            "production_path": production_path,
            "fallback_reason": fallback_reason,
            "chair_participates": config.chair_participates,
            **extra_envelope,
        }
        record = SeminarReportRecord(
            id=generate_id(),
            seminar_id=seminar.id,
            version=version,
            clusters=clusters,
            synthesis=synthesis_envelope,
            computed_metrics=computed_metrics,
            report_hash=report_hash,
            chair_model_id=chair_model_id,
            partial=partial,
            created_at=utc_now(),
        )
        session.add(record)
        target = SeminarStatus.PARTIAL.value if partial else SeminarStatus.REPORTED.value
        validate_seminar_transition(seminar.status, target)
        recorder.record(
            AuditEventKind.REPORT_WRITTEN,
            detail={
                "version": version,
                "production_path": production_path,
                "cluster_production": str(clusters.get("production")),
                "partial": partial,
                "report_hash": report_hash,
            },
        )
        recorder.record(
            AuditEventKind.STATUS_TRANSITION,
            detail={
                "from": seminar.status,
                "to": target,
                "trigger": "synthesize",
            },
        )
        seminar.status = target
        seminar.updated_at = utc_now()
        await recorder.flush(session, seminar_id=seminar.id)
        await session.commit()
        await session.refresh(record)
        agreement_level = (
            str(synthesis_payload["agreement_level"]) if synthesis_payload is not None else None
        )
        return SynthesizeRead(
            report_id=record.id,
            seminar_id=seminar.id,
            version=record.version,
            partial=record.partial,
            agreement_level=agreement_level,
            production_path=production_path,
            cluster_production=str(clusters.get("production")),
            fallback_reason=fallback_reason,
            report_hash=record.report_hash,
            chair_model_id=record.chair_model_id,
            status=seminar.status,
        )

    # -- chair synthesis submission (agent-chair mode) -------------------

    async def submit_chair_synthesis(
        self,
        session: AsyncSession,
        seminar_id: str,
        request: ChairSynthesisRequest,
    ) -> SynthesizeRead:
        """Accept an agent chair's submission and write the report.

        Serialized on the same per-seminar lock as synthesize: a
        submission waits for an in-flight synthesize and vice versa.
        """
        lock = self._synthesize_lock(seminar_id)
        contended = lock.locked()
        waited_since = time.monotonic()
        await lock.acquire()
        try:
            wait_ms = (time.monotonic() - waited_since) * 1000.0
            return await self._submit_under_lock(
                session,
                seminar_id,
                request,
                queue_wait_ms=wait_ms if contended else None,
            )
        finally:
            lock.release()

    async def _submit_under_lock(
        self,
        session: AsyncSession,
        seminar_id: str,
        request: ChairSynthesisRequest,
        *,
        queue_wait_ms: float | None,
    ) -> SynthesizeRead:
        seminar = await self._get_seminar(session, seminar_id)
        recorder = AuditRecorder()
        if queue_wait_ms is not None:
            recorder.record(
                AuditEventKind.QUEUE_WAIT,
                detail={"wait_ms": queue_wait_ms, "trigger": "chair_synthesis"},
            )
        roster = [RosterEntry.model_validate(item) for item in seminar.roster]
        config = SeminarConfig.model_validate(seminar.config)
        if config.chair_mode != "agent":
            await self._refuse(
                session,
                seminar_id=seminar.id,
                code="seminar_chair_mode_mismatch",
                message=(
                    "Chair synthesis submissions are only accepted on "
                    f"agent-chair seminars; this seminar uses chair_mode "
                    f"{config.chair_mode!r}. Use POST /synthesize instead."
                ),
                recorder=recorder,
            )
        if seminar.status == SeminarStatus.SYNTHESIZING.value:
            await self._refuse(
                session,
                seminar_id=seminar.id,
                code="seminar_synthesize_stuck",
                message=(
                    f"Seminar {seminar_id} is stuck in synthesizing: a previous "
                    "synthesize attempt did not complete. Inspect the audit log "
                    "(GET /seminars/{id}/audit) to locate the failed step."
                ),
                recorder=recorder,
            )
        if seminar.status == SeminarStatus.OPEN.value:
            await self._refuse(
                session,
                seminar_id=seminar.id,
                code="seminar_not_ready",
                message=(
                    f"Seminar {seminar_id} has never advanced; "
                    "advance and finalize before synthesizing."
                ),
                recorder=recorder,
            )
        brief_rows = await self._brief_rows(session, seminar_id)
        brief_row: SeminarChairBriefRecord | None = None
        if request.brief_version is not None:
            brief_row = next(
                (row for row in brief_rows if row.version == request.brief_version), None
            )
            if brief_row is None:
                await self._refuse(
                    session,
                    seminar_id=seminar.id,
                    code="seminar_unknown_brief_version",
                    message=(
                        f"Seminar {seminar_id} has no chair brief version "
                        f"{request.brief_version}; produce one via POST /synthesize."
                    ),
                    recorder=recorder,
                )
        else:
            brief_row = brief_rows[-1] if brief_rows else None
            if brief_row is None:
                await self._refuse(
                    session,
                    seminar_id=seminar.id,
                    code="seminar_no_chair_brief",
                    message=(
                        f"Seminar {seminar_id} has no stored chair brief; "
                        "produce one via POST /synthesize before submitting."
                    ),
                    recorder=recorder,
                )
        brief = brief_row.brief or {}
        prepass: dict[str, Any] = brief["prepass"]

        # Both payloads are validated against the SAME contracts the
        # model chair's outputs are validated against, and the
        # clustering goes through the SAME merge-map coverage
        # enforcement — before any write, so an invalid submission
        # writes zero report rows.
        try:
            parsed_clusters = parse_seminar_stage_output("seminar.cluster", request.clusters)
            parsed_synthesis = parse_seminar_stage_output("seminar.synthesize", request.synthesis)
        except SkillContractError as exc:
            await self._refuse(
                session,
                seminar_id=seminar.id,
                code="chair_submission_contract_failed",
                message=f"Chair submission failed contract validation: {exc}",
                recorder=recorder,
            )
        if not isinstance(parsed_clusters, ClaimClusters) or not isinstance(
            parsed_synthesis, SeminarSynthesis
        ):
            raise SeminarServiceError(
                "chair_submission_contract_failed",
                "Chair submission failed contract validation: unexpected payload shape.",
            )
        try:
            clusters = expand_clusters(
                parsed_clusters, prepass=prepass, production="agent_chair"
            )
        except ValueError as exc:
            await self._refuse(
                session,
                seminar_id=seminar.id,
                code="chair_submission_coverage_failed",
                message=f"Chair submission clustering failed merge-map coverage: {exc}",
                recorder=recorder,
            )
        clusters["stage"] = None  # no model stage call produced these clusters

        # Metrics recompute from the brief's PINNED verdicts + the
        # submitted clusters + fresh round rows (rounds may have run
        # after the brief; the verdict set stays pinned and the
        # brief version/hash in the report header discloses it).
        round_rows = await self._round_rows(session, seminar_id)
        board_rows = await self._board_rows(session, seminar_id)
        brief_verdicts: list[dict[str, Any]] = list(brief["verdicts"])
        inputs = self._synthesis_inputs(
            roster=roster,
            config=config,
            round_rows=round_rows,
            board_rows=board_rows,
            verdicts=brief_verdicts,
        )
        computed_metrics = compute_metrics(
            verdicts=brief_verdicts,
            clusters=clusters,
            roster_ids=[entry.model_id for entry in roster],
            round_rows=inputs["round_dicts"],
            statuses={model_id: str(status) for model_id, status in inputs["statuses"].items()},
            absent_models=inputs["absent"],
        )

        prior_status = seminar.status
        validate_seminar_transition(prior_status, SeminarStatus.SYNTHESIZING.value)
        recorder.record(
            AuditEventKind.STATUS_TRANSITION,
            detail={
                "from": prior_status,
                "to": SeminarStatus.SYNTHESIZING.value,
                "trigger": "chair_synthesis",
            },
        )
        seminar.status = SeminarStatus.SYNTHESIZING.value
        seminar.updated_at = utc_now()
        await recorder.flush(session, seminar_id=seminar.id)
        await session.commit()
        try:
            recorder.record(
                AuditEventKind.SYNTHESIS_SUBMITTED,
                model_id=AGENT_CHAIR_MODEL_ID,
                detail={
                    "brief_version": brief_row.version,
                    "brief_hash": brief_row.brief_hash,
                    "production_path": "agent_chair",
                },
            )
            return await self._write_report(
                session,
                seminar=seminar,
                roster=roster,
                config=config,
                verdicts=brief_verdicts,
                clusters=clusters,
                synthesis_payload=parsed_synthesis.model_dump(mode="json"),
                synthesis_stage_json=None,
                computed_metrics=computed_metrics,
                production_path="agent_chair",
                fallback_reason=None,
                chair_model_id=AGENT_CHAIR_MODEL_ID,
                recorder=recorder,
                extra_envelope={
                    "chair_mode": "agent",
                    "brief_version": brief_row.version,
                    "brief_hash": brief_row.brief_hash,
                    "submitted_by": AGENT_CHAIR_MODEL_ID,
                },
            )
        except Exception as exc:
            await session.rollback()
            recorder.record(
                AuditEventKind.SYNTHESIS_FAILED,
                detail={"error_kind": classify_error(exc), "message": str(exc)[:500]},
            )
            recorder.record(
                AuditEventKind.STATUS_TRANSITION,
                detail={
                    "from": SeminarStatus.SYNTHESIZING.value,
                    "to": prior_status,
                    "trigger": "rollback",
                },
            )
            seminar.status = prior_status
            seminar.updated_at = utc_now()
            await recorder.flush(session, seminar_id=seminar.id)
            await session.commit()
            raise

    # -- reads -------------------------------------------------------------

    async def get_seminar_detail(self, session: AsyncSession, seminar_id: str) -> SeminarDetailRead:
        seminar = await self._get_seminar(session, seminar_id)
        roster = [RosterEntry.model_validate(item) for item in seminar.roster]
        config = SeminarConfig.model_validate(seminar.config)
        round_rows = await self._round_rows(session, seminar_id)
        board_rows = await self._board_rows(session, seminar_id)
        final_rows = await self._final_rows(session, seminar_id)
        report_rows = await self._report_rows(session, seminar_id)
        final_model_ids = frozenset(row.model_id for row in final_rows)
        statuses = self._model_statuses(
            roster=roster,
            config=config,
            round_rows=round_rows,
            board_rows=board_rows,
            final_model_ids=final_model_ids,
        )
        latest_seq: dict[str, int] = {}
        for row in board_rows:
            latest_seq[row.model_id] = max(latest_seq.get(row.model_id, 0), row.seq)
        per_model = [
            SeminarModelProgress(
                model_id=entry.model_id,
                status=str(statuses[entry.model_id]),
                rounds=sum(1 for row in round_rows if row.model_id == entry.model_id),
                has_final=entry.model_id in final_model_ids,
                latest_board_seq=latest_seq.get(entry.model_id),
            )
            for entry in roster
        ]
        event_dicts = await self._audit_event_dicts(session, seminar_id)
        calls_used, tokens_used = ledger_totals(event_dicts)
        return SeminarDetailRead(
            seminar_id=seminar.id,
            run_id=seminar.run_id,
            topic=seminar.topic,
            status=seminar.status,
            case_snapshot_hash=seminar.case_snapshot_hash,
            roster=roster,
            config=config,
            chair_model=ModelPortConfig.model_validate(seminar.chair_model),
            per_model=per_model,
            board_publications=len(board_rows),
            board_latest_seq=max((row.seq for row in board_rows), default=0),
            finals_count=len(final_rows),
            reports=[
                SeminarReportSummary(
                    version=row.version,
                    partial=row.partial,
                    production_path=str((row.synthesis or {}).get("production_path", "unknown")),
                    cluster_production=str((row.clusters or {}).get("production", "unknown")),
                    report_hash=row.report_hash,
                    chair_model_id=row.chair_model_id,
                )
                for row in report_rows
            ],
            budgets=BudgetRead(
                max_stage_calls=config.max_stage_calls,
                stage_calls_used=calls_used,
                stage_calls_remaining=max(0, config.max_stage_calls - calls_used),
                max_tokens=config.max_tokens,
                tokens_used=tokens_used,
                tokens_remaining=max(0, config.max_tokens - tokens_used),
            ).model_dump(mode="json"),
            diagnosis=compute_diagnosis(event_dicts).model_dump(mode="json"),
        )

    async def list_audit_events(
        self,
        session: AsyncSession,
        seminar_id: str,
        *,
        kind: str | None = None,
        model_id: str | None = None,
    ) -> list[AuditEventRead]:
        """The seminar's audit log in seq order, filterable by kind and
        model. An unknown kind refuses (a typo'd filter returning an
        empty log would silently mislead a diagnosis)."""
        await self._get_seminar(session, seminar_id)
        if kind is not None and kind not in AuditEventKind.ALL:
            raise SeminarServiceError(
                "seminar_audit_unknown_kind",
                f"Unknown audit event kind {kind!r}; known kinds: "
                f"{', '.join(sorted(AuditEventKind.ALL))}.",
            )
        rows = await self._audit_rows(session, seminar_id)
        return [
            AuditEventRead(
                id=row.id,
                seminar_id=row.seminar_id,
                seq=row.seq,
                model_id=row.model_id,
                stage=row.stage,
                kind=row.kind,
                detail=row.detail or {},
                round_no=row.round_no,
                stage_call_id=row.stage_call_id,
                created_at=row.created_at.isoformat(),
            )
            for row in rows
            if (kind is None or row.kind == kind)
            and (model_id is None or row.model_id == model_id)
        ]

    async def list_board(self, session: AsyncSession, seminar_id: str) -> list[BoardRowRead]:
        await self._get_seminar(session, seminar_id)
        rows = await self._board_rows(session, seminar_id)
        return [
            BoardRowRead(
                id=row.id,
                seminar_id=row.seminar_id,
                seq=row.seq,
                model_id=row.model_id,
                round_no=row.round_no,
                digest=row.digest or {},
            )
            for row in rows
        ]

    async def list_rounds(self, session: AsyncSession, seminar_id: str) -> list[RoundRowRead]:
        await self._get_seminar(session, seminar_id)
        rows = await self._round_rows(session, seminar_id)
        return [
            RoundRowRead(
                id=row.id,
                seminar_id=row.seminar_id,
                model_id=row.model_id,
                round_no=row.round_no,
                board_snapshot_seq=row.board_snapshot_seq,
                stages=row.stages or [],
                reflection=row.reflection,
                reflection_stage=row.reflection_stage,
                status=row.status,
                error=row.error,
            )
            for row in rows
        ]

    async def list_finals(self, session: AsyncSession, seminar_id: str) -> list[FinalRowRead]:
        await self._get_seminar(session, seminar_id)
        rows = await self._final_rows(session, seminar_id)
        return [
            FinalRowRead(
                id=row.id,
                seminar_id=row.seminar_id,
                model_id=row.model_id,
                verdict=row.verdict or {},
                stage=row.stage or {},
                board_snapshot_seq=row.board_snapshot_seq,
                status=row.status,
            )
            for row in rows
        ]

    async def list_reports(
        self, session: AsyncSession, seminar_id: str
    ) -> list[SeminarReportSummary]:
        await self._get_seminar(session, seminar_id)
        rows = await self._report_rows(session, seminar_id)
        return [
            SeminarReportSummary(
                version=row.version,
                partial=row.partial,
                production_path=str((row.synthesis or {}).get("production_path", "unknown")),
                cluster_production=str((row.clusters or {}).get("production", "unknown")),
                report_hash=row.report_hash,
                chair_model_id=row.chair_model_id,
            )
            for row in rows
        ]

    async def get_report(
        self, session: AsyncSession, seminar_id: str, version: int
    ) -> ReportDetailRead:
        seminar = await self._get_seminar(session, seminar_id)
        rows = await self._report_rows(session, seminar_id)
        record = next((row for row in rows if row.version == version), None)
        if record is None:
            raise LookupError(f"Seminar {seminar_id} has no report version {version}.")
        roster = [RosterEntry.model_validate(item) for item in seminar.roster]
        config = SeminarConfig.model_validate(seminar.config)
        round_rows = await self._round_rows(session, seminar_id)
        board_rows = await self._board_rows(session, seminar_id)
        final_rows = await self._final_rows(session, seminar_id)
        finals_by_model = {row.model_id: row for row in final_rows}
        verdicts = [
            {
                "model_id": entry.model_id,
                "verdict": finals_by_model[entry.model_id].verdict,
                "stage": finals_by_model[entry.model_id].stage,
                "board_snapshot_seq": finals_by_model[entry.model_id].board_snapshot_seq,
            }
            for entry in roster
            if entry.model_id in finals_by_model
        ]
        document = compose_report(
            seminar_id=seminar.id,
            run_id=seminar.run_id,
            topic=seminar.topic,
            version=record.version,
            partial=record.partial,
            chair_model_id=record.chair_model_id,
            chair_participates=config.chair_participates,
            case_snapshot_hash=seminar.case_snapshot_hash,
            roster=[entry.model_dump(mode="json") for entry in roster],
            chair_config=seminar.chair_model or {},
            clusters=record.clusters or {},
            synthesis_envelope=record.synthesis or {},
            computed_metrics=record.computed_metrics or {},
            verdicts=verdicts,
            round_rows=[
                {
                    "model_id": row.model_id,
                    "round_no": row.round_no,
                    "status": row.status,
                    "board_snapshot_seq": row.board_snapshot_seq,
                    "stages": row.stages or [],
                }
                for row in round_rows
            ],
            board_rows=[
                {"seq": row.seq, "model_id": row.model_id, "round_no": row.round_no}
                for row in board_rows
            ],
            report_hash=record.report_hash,
            usage_rollup=self._usage_rollup_for_report(
                await self._audit_event_dicts(session, seminar_id)
            ),
        )
        return ReportDetailRead(
            report_id=record.id,
            seminar_id=seminar.id,
            version=record.version,
            partial=record.partial,
            chair_model_id=record.chair_model_id,
            report_hash=record.report_hash,
            document=document,
        )

    @staticmethod
    def _usage_rollup_for_report(events: list[dict[str, Any]]) -> dict[str, Any]:
        """Token rollup for the report audit appendix, from the ledger."""
        calls_used, tokens_used = ledger_totals(events)
        return {
            "per_model": rollup_usage_by_model(events),
            "total_tokens": tokens_used,
            "stage_call_attempts": calls_used,
            "note": (
                "Token usage as reported by the ports; calls that reported "
                "no usage contribute zero. Counts cover the whole seminar, "
                "not only this report version."
            ),
        }

    async def list_seminars_for_run(
        self, session: AsyncSession, run_id: str
    ) -> list[SeminarSummaryRead]:
        run = await session.get(SimulationRun, run_id)
        if run is None:
            raise LookupError(f"Simulation run {run_id} was not found.")
        result = await session.execute(
            select(SeminarRecord)
            .where(SeminarRecord.run_id == run_id)
            .order_by(SeminarRecord.created_at)
        )
        seminars = list(result.scalars().all())
        summaries: list[SeminarSummaryRead] = []
        for seminar in seminars:
            finals = await self._final_rows(session, seminar.id)
            reports = await self._report_rows(session, seminar.id)
            summaries.append(
                SeminarSummaryRead(
                    seminar_id=seminar.id,
                    run_id=seminar.run_id,
                    topic=seminar.topic,
                    status=seminar.status,
                    roster_size=len(seminar.roster or []),
                    finals_count=len(finals),
                    report_versions=len(reports),
                )
            )
        return summaries


__all__ = [
    "PortFactory",
    "SeminarChairUnavailable",
    "SeminarService",
    "SeminarServiceError",
    "compute_report_hash",
]

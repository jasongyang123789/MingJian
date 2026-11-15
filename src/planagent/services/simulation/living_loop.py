"""Living-strategy loop service mixin (Sprint 9).

Wires the loop's state machine into ``SimulationService`` so
re-simulation goes through the existing run-creation path (MECE gate,
variable gate, firewall fragment — all engage exactly as for
hand-created runs) and comparison reads the stored Sprint 3/4
fragments. Nothing here touches the numeric core: the mixin reads
stored values, creates runs through ``create_simulation_run``, and
records audit rows.

State machine per iteration, strictly forward::

    open -> evaluated -> resimulated -> compared -> decided
              \\_________________________^
    (a quiet round may be decided directly from ``evaluated``)

``decided`` is terminal. Only one non-decided iteration may exist
per loop. Every transition refusal names the current state and the
missing prerequisite; nothing is silently skipped or auto-advanced.
There is no scheduler and no worker hook: evaluation,
re-simulation, comparison, and decisions are explicit actions.

The Sprint 11 monitoring worker is the one exception to "no worker
hook", and it is deliberately narrow: ``run_monitoring_cycle``
evaluates each loop's triggers against its recorded observations
and records the outcome in ``loop_evaluations`` — and does nothing
else. It never creates runs or iterations, never transitions
iteration state, and never mutates loop rows. A recorded trigger
firing plus an explicit review is still what starts a
re-simulation (SPRINT9.md §10).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from planagent.domain.api import SimulationRunCreate
from planagent.domain.enums import ExecutionMode, SimulationRunStatus
from planagent.domain.models import (
    Claim,
    CompanyProfile,
    ForceProfile,
    LoopEvaluationRecord,
    LoopIterationRecord,
    LoopObservationRecord,
    SimulationRun,
    StrategyLoopRecord,
    generate_id,
    utc_now,
)
from planagent.services.calibration import (
    firewall_cutoff_from_configuration,
    format_cutoff,
    normalize_cutoff,
)
from planagent.services.distributions import sha256_hash
from planagent.services.living_loop.comparison import (
    compare_ensembles as _compare_ensembles,
)
from planagent.services.living_loop.comparison import (
    reevaluate_gates as _reevaluate_gates,
)
from planagent.services.living_loop.comparison import (
    threshold_drift as _threshold_drift,
)
from planagent.services.living_loop.models import (
    DecideRequest,
    EnsembleComparison,
    LoopEvaluationRead,
    LoopIterationRead,
    LoopObservationCreate,
    LoopObservationRead,
    LoopTimelineRead,
    MonitoringCycleLoopResult,
    MonitoringCycleResult,
    ResimulateRequest,
    ResimulationRecord,
    ReviewDecisionRecord,
    StartIterationRequest,
    StrategyLoopCreate,
    StrategyLoopRead,
    TriggerEvaluationOutcome,
    TriggerRegistration,
    TriggerRegistrationRequest,
)
from planagent.services.living_loop.monitoring import (
    EvaluationSummary,
    evaluation_fingerprint,
    select_registration,
    summarize_outcomes,
)
from planagent.services.living_loop.triggers import evaluate_triggers, select_window
from planagent.services.mece.models import DecompositionTree
from planagent.services.variables.models import VariableSet
from planagent.simulation.domain_packs import registry
from planagent.workers.base import public_worker_error

_logger = logging.getLogger(__name__)

#: Configuration fragments that mark a run as a derived artifact
#: rather than a primary run (same rule as the Sprint 5 calibration
#: eligibility check: MC trials, robustness probes, and replays are
#: excluded as loop baselines because they double-count evidence).
_EXCLUDED_CONFIGURATION_KEYS = ("monte_carlo", "robustness_probe")


class LoopError(ValueError):
    """Refusal with a stable machine-readable code (route maps to 400)."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _is_derived_run(run: SimulationRun) -> bool:
    configuration = run.configuration or {}
    if any(key in configuration for key in _EXCLUDED_CONFIGURATION_KEYS):
        return True
    summary = run.summary or {}
    return bool(summary.get("replay_of"))


def _state_fields(domain_id: str) -> set[str]:
    pack = registry.get(domain_id)
    return {field.name for field in pack.state_fields}


def _stored_template_snapshot(configuration: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(configuration, dict):
        return None
    fragment = configuration.get("variables")
    if not isinstance(fragment, dict):
        return None
    template = fragment.get("template")
    return template if isinstance(template, dict) else None


def _input_hash(configuration: dict[str, Any] | None) -> str | None:
    if not isinstance(configuration, dict):
        return None
    fragment = configuration.get("determinism")
    if not isinstance(fragment, dict):
        return None
    value = fragment.get("input_hash")
    return value if isinstance(value, str) else None


def _read_loop(row: StrategyLoopRecord) -> StrategyLoopRead:
    return StrategyLoopRead(
        id=row.id,
        name=row.name,
        baseline_run_id=row.baseline_run_id,
        domain_id=row.domain_id,
        status="active",
        triggers=[TriggerRegistration.model_validate(item) for item in (row.triggers or [])],
        created_at=format_cutoff(row.created_at),
        updated_at=format_cutoff(row.updated_at),
    )


def _read_observation(row: LoopObservationRecord) -> LoopObservationRead:
    return LoopObservationRead(
        id=row.id,
        loop_id=row.loop_id,
        field=row.field,
        value=row.value,
        observed_at=format_cutoff(row.observed_at),
        source_claim_id=row.source_claim_id,
        source_note=row.source_note,
        recorded_at=format_cutoff(row.created_at),
    )


def _read_iteration(row: LoopIterationRecord) -> LoopIterationRead:
    window = row.window or {}
    return LoopIterationRead(
        id=row.id,
        loop_id=row.loop_id,
        index=row.index,
        state=row.state,  # type: ignore[arg-type]
        decision_time=format_cutoff(row.decision_time),
        previous_cutoff=(
            format_cutoff(row.previous_cutoff) if row.previous_cutoff is not None else None
        ),
        window_from=window.get("from"),
        window_to=window.get("to"),
        observation_ids=list(window.get("observation_ids", [])),
        trigger_evaluations=list(row.trigger_evaluations or []),
        resimulation=(
            ResimulationRecord.model_validate(row.resimulation)
            if row.resimulation is not None
            else None
        ),
        comparison=(
            EnsembleComparison.model_validate(row.comparison)
            if row.comparison is not None
            else None
        ),
        decision=(
            ReviewDecisionRecord.model_validate(row.decision) if row.decision is not None else None
        ),
        created_at=format_cutoff(row.created_at),
        updated_at=format_cutoff(row.updated_at),
    )


def _read_evaluation(row: LoopEvaluationRecord) -> LoopEvaluationRead:
    return LoopEvaluationRead(
        id=row.id,
        loop_id=row.loop_id,
        cycle_id=row.cycle_id,
        evaluated_at=format_cutoff(row.evaluated_at),
        observation_fingerprint=row.observation_fingerprint,
        registration_id=row.registration_id,
        observation_ids=list(row.observation_ids or []),
        outcomes=[TriggerEvaluationOutcome.model_validate(item) for item in (row.outcomes or [])],
        summary=row.summary,  # type: ignore[arg-type]
        error_code=row.error_code,
        error_message=row.error_message,
        created_at=format_cutoff(row.created_at),
    )


class SimulationLivingLoopMixin:
    """Loop orchestration over the existing simulation machinery."""

    # ------------------------------------------------------------------ loops

    async def create_loop(
        self, session: AsyncSession, request: StrategyLoopCreate
    ) -> StrategyLoopRead:
        """Create a loop from a completed primary run."""

        baseline = await session.get(SimulationRun, request.baseline_run_id)
        if baseline is None:
            raise LookupError(f"Simulation run {request.baseline_run_id} was not found.")
        if baseline.status != SimulationRunStatus.COMPLETED.value:
            raise LoopError(
                "loop_requires_completed_run",
                "A living-strategy loop requires a completed baseline run.",
            )
        if _is_derived_run(baseline):
            raise LoopError(
                "loop_derived_run_excluded",
                "Monte Carlo trials, robustness probes, and replays cannot be "
                "loop baselines; they are derived artifacts, not decisions.",
            )
        fields = _state_fields(baseline.domain_id)
        for trigger in request.triggers:
            if trigger.field not in fields:
                raise LoopError(
                    "loop_unknown_field",
                    f"Trigger {trigger.name!r} names field {trigger.field!r}, which is "
                    f"not a state field of domain {baseline.domain_id!r}.",
                )
        row = StrategyLoopRecord(
            id=generate_id(),
            name=request.name,
            baseline_run_id=baseline.id,
            domain_id=baseline.domain_id,
            status="active",
            triggers=[],
        )
        session.add(row)
        await session.flush()
        if request.triggers:
            registration = TriggerRegistration(
                id=generate_id(),
                loop_id=row.id,
                triggers=list(request.triggers),
                registered_at=format_cutoff(utc_now()),
                observation_count_at_registration=0,
                status="active",
            )
            row.triggers = [registration.model_dump(mode="json")]
        await session.commit()
        await session.refresh(row)
        return _read_loop(row)

    async def get_loop(self, session: AsyncSession, loop_id: str) -> StrategyLoopRead:
        row = await self._require_loop(session, loop_id)
        return _read_loop(row)

    async def list_loops(
        self, session: AsyncSession, *, limit: int = 20, offset: int = 0
    ) -> list[StrategyLoopRead]:
        rows = list(
            (
                await session.scalars(
                    select(StrategyLoopRecord)
                    .order_by(StrategyLoopRecord.created_at.desc())
                    .limit(min(limit, 100))
                    .offset(max(offset, 0))
                )
            ).all()
        )
        return [_read_loop(row) for row in rows]

    async def get_loop_timeline(self, session: AsyncSession, loop_id: str) -> LoopTimelineRead:
        row = await self._require_loop(session, loop_id)
        observations = list(
            (
                await session.scalars(
                    select(LoopObservationRecord)
                    .where(LoopObservationRecord.loop_id == loop_id)
                    .order_by(
                        LoopObservationRecord.observed_at.asc(), LoopObservationRecord.id.asc()
                    )
                )
            ).all()
        )
        iterations = list(
            (
                await session.scalars(
                    select(LoopIterationRecord)
                    .where(LoopIterationRecord.loop_id == loop_id)
                    .order_by(LoopIterationRecord.index.asc())
                )
            ).all()
        )
        return LoopTimelineRead(
            loop=_read_loop(row),
            observations=[_read_observation(item) for item in observations],
            iterations=[_read_iteration(item) for item in iterations],
        )

    # ------------------------------------------------------------ observations

    async def record_observation(
        self, session: AsyncSession, loop_id: str, request: LoopObservationCreate
    ) -> LoopObservationRead:
        """Record one observed actual. Append-only; never edited."""

        row = await self._require_loop(session, loop_id)
        if request.field not in _state_fields(row.domain_id):
            raise LoopError(
                "loop_unknown_field",
                f"Field {request.field!r} is not a state field of domain {row.domain_id!r}.",
            )
        if request.source_claim_id is not None:
            claim = await session.get(Claim, request.source_claim_id)
            if claim is None:
                raise LoopError(
                    "loop_unknown_claim",
                    f"Source claim {request.source_claim_id!r} does not exist.",
                )
        record = LoopObservationRecord(
            id=generate_id(),
            loop_id=row.id,
            field=request.field,
            value=request.value,
            observed_at=normalize_cutoff(request.observed_at),
            source_claim_id=request.source_claim_id,
            source_note=request.source_note,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return _read_observation(record)

    # --------------------------------------------------------------- triggers

    async def register_loop_triggers(
        self, session: AsyncSession, loop_id: str, request: TriggerRegistrationRequest
    ) -> TriggerRegistration:
        """Register a trigger set. Append-only; supersede is explicit."""

        row = await self._require_loop(session, loop_id)
        registrations = list(row.triggers or [])
        if request.supersedes is not None and all(
            item.get("id") != request.supersedes for item in registrations
        ):
            raise LoopError(
                "loop_unknown_registration",
                f"Trigger registration {request.supersedes!r} does not exist on loop {loop_id}.",
            )
        fields = _state_fields(row.domain_id)
        for trigger in request.triggers:
            if trigger.field not in fields:
                raise LoopError(
                    "loop_unknown_field",
                    f"Trigger {trigger.name!r} names field {trigger.field!r}, which is "
                    f"not a state field of domain {row.domain_id!r}.",
                )
        observation_count = int(
            (
                await session.scalar(
                    select(func.count())
                    .select_from(LoopObservationRecord)
                    .where(LoopObservationRecord.loop_id == loop_id)
                )
            )
            or 0
        )
        registration = TriggerRegistration(
            id=generate_id(),
            loop_id=row.id,
            triggers=list(request.triggers),
            supersedes=request.supersedes,
            registered_at=format_cutoff(utc_now()),
            observation_count_at_registration=observation_count,
            status="active",
        )
        if request.supersedes is not None:
            for item in registrations:
                if item.get("id") == request.supersedes:
                    item["status"] = "superseded"
        registrations.append(registration.model_dump(mode="json"))
        row.triggers = registrations
        row.updated_at = utc_now()
        await session.commit()
        await session.refresh(row)
        return registration

    # -------------------------------------------------------------- iterations

    async def start_iteration(
        self, session: AsyncSession, loop_id: str, request: StartIterationRequest
    ) -> LoopIterationRead:
        """Open a review iteration. The decision time must advance the
        evidence cutoff past the previous review — never backwards."""

        row = await self._require_loop(session, loop_id)
        open_iterations = list(
            (
                await session.scalars(
                    select(LoopIterationRecord)
                    .where(
                        LoopIterationRecord.loop_id == loop_id,
                        LoopIterationRecord.state != "decided",
                    )
                    .order_by(LoopIterationRecord.index.asc())
                )
            ).all()
        )
        if open_iterations:
            raise LoopError(
                "loop_iteration_in_progress",
                f"Loop {loop_id} already has an open iteration "
                f"(index {open_iterations[0].index}, state "
                f"{open_iterations[0].state!r}). Record its decision before "
                "starting a new review.",
            )
        decision_time = normalize_cutoff(request.decision_time)
        previous = await self._latest_iteration(session, loop_id)
        if previous is not None:
            previous_cutoff: datetime | None = normalize_cutoff(previous.decision_time)
            index = previous.index + 1
        else:
            baseline = await session.get(SimulationRun, row.baseline_run_id)
            if baseline is None:  # pragma: no cover - FK guards this
                raise LookupError(f"Simulation run {row.baseline_run_id} was not found.")
            previous_cutoff, _source = firewall_cutoff_from_configuration(baseline.configuration)
            index = 0
        if previous_cutoff is not None and decision_time <= previous_cutoff:
            raise LoopError(
                "loop_cutoff_must_advance",
                "The review decision_time must advance past the previous "
                f"evidence cutoff ({format_cutoff(previous_cutoff)}); got "
                f"{format_cutoff(decision_time)}. A re-simulation must see "
                "at least the evidence the previous review saw.",
            )
        record = LoopIterationRecord(
            id=generate_id(),
            loop_id=row.id,
            index=index,
            state="open",
            decision_time=decision_time,
            previous_cutoff=previous_cutoff,
            window={},
            trigger_evaluations=[],
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return _read_iteration(record)

    async def get_iteration(
        self, session: AsyncSession, loop_id: str, iteration_id: str
    ) -> LoopIterationRead:
        record = await self._require_iteration(session, loop_id, iteration_id)
        return _read_iteration(record)

    async def evaluate_iteration(
        self, session: AsyncSession, loop_id: str, iteration_id: str
    ) -> LoopIterationRead:
        """Evaluate the active triggers against the review window."""

        row = await self._require_loop(session, loop_id)
        record = await self._require_iteration(session, loop_id, iteration_id)
        self._require_state(record, ("open",), "evaluate triggers")
        registrations = [TriggerRegistration.model_validate(item) for item in (row.triggers or [])]
        if not registrations:
            raise LoopError(
                "loop_no_triggers",
                f"Loop {loop_id} has no registered triggers. Register triggers "
                "before evaluating a review.",
            )
        active = [item for item in registrations if item.status == "active"]
        registration = active[-1] if active else registrations[-1]
        decision_time = normalize_cutoff(record.decision_time)
        previous_cutoff = (
            normalize_cutoff(record.previous_cutoff) if record.previous_cutoff is not None else None
        )
        observations = list(
            (
                await session.scalars(
                    select(LoopObservationRecord).where(LoopObservationRecord.loop_id == loop_id)
                )
            ).all()
        )
        reads = [_read_observation(item) for item in observations]
        window = select_window(reads, after=previous_cutoff, up_to=decision_time)
        baseline = await session.get(SimulationRun, row.baseline_run_id)
        if baseline is None:  # pragma: no cover - FK guards this
            raise LookupError(f"Simulation run {row.baseline_run_id} was not found.")
        final_state = (baseline.summary or {}).get("final_state")
        baseline_final = (
            {key: float(value) for key, value in final_state.items()}
            if isinstance(final_state, dict)
            else {}
        )
        try:
            outcomes = evaluate_triggers(
                registration.triggers, window, baseline_final_state=baseline_final
            )
        except ValueError as exc:
            raise LoopError("loop_trigger_evaluation_failed", str(exc)) from exc
        record.window = {
            "from": format_cutoff(previous_cutoff) if previous_cutoff is not None else None,
            "to": format_cutoff(decision_time),
            "observation_ids": [item.id for item in window],
        }
        record.trigger_evaluations = [outcome.model_dump(mode="json") for outcome in outcomes]
        record.state = "evaluated"
        record.updated_at = utc_now()
        await session.commit()
        await session.refresh(record)
        return _read_iteration(record)

    async def resimulate_iteration(
        self, session: AsyncSession, loop_id: str, iteration_id: str, request: ResimulateRequest
    ) -> LoopIterationRead:
        """Create a re-simulation run through the existing creation path.

        The gates engage exactly as for a hand-created run: a refused
        re-simulation writes zero rows and leaves the iteration
        untouched (the creation call happens before any iteration
        mutation). The new run's decision_time is the review time, so
        its evidence cutoff advances honestly past the baseline's.
        """

        row = await self._require_loop(session, loop_id)
        record = await self._require_iteration(session, loop_id, iteration_id)
        self._require_state(record, ("evaluated",), "re-simulate")
        baseline = await session.get(SimulationRun, row.baseline_run_id)
        if baseline is None:  # pragma: no cover - FK guards this
            raise LookupError(f"Simulation run {row.baseline_run_id} was not found.")
        decision_time = normalize_cutoff(record.decision_time)
        payload, changes = await self._build_resimulation_payload(
            session, baseline, decision_time, request
        )
        # Gate discipline: creation refuses before any row is written,
        # and this method mutates nothing until creation succeeds.
        new_run = await self.create_simulation_run(session, payload)
        audit = await self.get_firewall_audit(session, new_run.id)
        baseline_template = _stored_template_snapshot(baseline.configuration)
        resolved_template = _stored_template_snapshot(new_run.configuration)
        resimulation = ResimulationRecord(
            run_id=new_run.id,
            previous_cutoff=(
                format_cutoff(record.previous_cutoff)
                if record.previous_cutoff is not None
                else None
            ),
            new_cutoff=format_cutoff(decision_time),
            previous_input_hash=_input_hash(baseline.configuration),
            new_input_hash=_input_hash(new_run.configuration),
            template_id=(baseline.configuration or {}).get("variables", {}).get("template_id")
            if isinstance((baseline.configuration or {}).get("variables"), dict)
            else None,
            template_snapshot_hash=(
                sha256_hash(baseline_template) if baseline_template is not None else None
            ),
            resolved_template_snapshot_hash=(
                sha256_hash(resolved_template) if resolved_template is not None else None
            ),
            seed=new_run.seed,
            tick_count=new_run.tick_count,
            changes=changes,
            claims_visible=len(audit.included_claim_ids),
            claims_excluded=len(audit.excluded_claim_ids),
            created_at=format_cutoff(utc_now()),
        )
        # An explicit template override names the new template, not the
        # baseline's: record what the run actually resolved.
        if request.variable_template_id is not None:
            resimulation.template_id = request.variable_template_id
        record.resimulation = resimulation.model_dump(mode="json")
        record.state = "resimulated"
        record.updated_at = utc_now()
        await session.commit()
        await session.refresh(record)
        return _read_iteration(record)

    async def compare_iteration(
        self, session: AsyncSession, loop_id: str, iteration_id: str
    ) -> LoopIterationRead:
        """Compare the baseline and re-simulation ensembles, stored vs stored."""

        row = await self._require_loop(session, loop_id)
        record = await self._require_iteration(session, loop_id, iteration_id)
        self._require_state(record, ("resimulated",), "compare ensembles")
        resimulation = ResimulationRecord.model_validate(record.resimulation)
        baseline_ensemble = await self.get_monte_carlo(session, row.baseline_run_id)
        if baseline_ensemble is None:
            raise LoopError(
                "loop_requires_baseline_ensemble",
                f"Baseline run {row.baseline_run_id} has no stored Monte Carlo "
                "ensemble. Run POST /runs/{id}/monte-carlo on the baseline "
                "run before comparing.",
            )
        new_ensemble = await self.get_monte_carlo(session, resimulation.run_id)
        if new_ensemble is None:
            raise LoopError(
                "loop_requires_resimulation_ensemble",
                f"Re-simulation run {resimulation.run_id} has no stored Monte "
                "Carlo ensemble. Run POST /runs/{id}/monte-carlo on the "
                "re-simulation run before comparing.",
            )
        baseline_values, strategy_values = await self._trial_values_for_ensemble(
            session, new_ensemble
        )
        gate_reevaluation = await self._reevaluate_baseline_gates(
            session, row.baseline_run_id, new_ensemble, baseline_values, strategy_values
        )
        old_robustness = await self.get_robustness(session, row.baseline_run_id)
        new_robustness = await self.get_robustness(session, resimulation.run_id)
        drift_rows = _threshold_drift(
            old_robustness.threshold_search if old_robustness is not None else None,
            new_robustness.threshold_search if new_robustness is not None else None,
        )
        previous_cutoff = (
            normalize_cutoff(record.previous_cutoff) if record.previous_cutoff is not None else None
        )
        try:
            comparison = _compare_ensembles(
                baseline_ensemble,
                new_ensemble,
                compared_at=format_cutoff(utc_now()),
                cutoffs_differ=previous_cutoff != normalize_cutoff(record.decision_time),
                gate_reevaluation=gate_reevaluation,
                drift_rows=drift_rows,
            )
        except ValueError as exc:
            raise LoopError("loop_comparison_failed", str(exc)) from exc
        record.comparison = comparison.model_dump(mode="json")
        record.state = "compared"
        record.updated_at = utc_now()
        await session.commit()
        await session.refresh(record)
        return _read_iteration(record)

    async def decide_iteration(
        self, session: AsyncSession, loop_id: str, iteration_id: str, request: DecideRequest
    ) -> LoopIterationRead:
        """Record the review decision. Terminal: decided iterations are
        immutable, and the next review is a new iteration."""

        record = await self._require_iteration(session, loop_id, iteration_id)
        if record.state == "open":
            raise LoopError(
                "loop_invalid_state",
                "Cannot record a decision while the iteration is 'open'. "
                "Evaluate the triggers first.",
            )
        if record.state == "resimulated":
            raise LoopError(
                "loop_invalid_state",
                "Cannot record a decision while the iteration is 'resimulated'. "
                "Compare the ensembles first so the decision rests on the "
                "comparison.",
            )
        if record.state == "decided":
            raise LoopError(
                "loop_invalid_state",
                "Iteration is already decided (terminal). Start a new "
                "iteration for the next review.",
            )
        record.decision = ReviewDecisionRecord(
            decision=request.decision,
            rationale=request.rationale,
            decided_at=format_cutoff(utc_now()),
        ).model_dump(mode="json")
        record.state = "decided"
        record.updated_at = utc_now()
        await session.commit()
        await session.refresh(record)
        return _read_iteration(record)

    # -------------------------------------------------------------- monitoring

    async def run_monitoring_cycle(
        self,
        session: AsyncSession,
        *,
        cycle_id: str | None = None,
        evaluated_at: datetime | None = None,
    ) -> MonitoringCycleResult:
        """Evaluate every loop's triggers and record the outcomes.

        AUTOMATION BOUNDARY (SPRINT9.md §10): evaluate + record
        only. This method's only writes are INSERTs into
        ``loop_evaluations``. It never creates simulation runs or
        loop iterations, never transitions iteration state, and
        never mutates loop or observation rows — a recorded
        trigger firing plus an explicit review is still what
        starts a re-simulation, and this cycle starts none.

        Each loop is evaluated against ALL its recorded
        observations (the cumulative monitor view; see
        ``services.living_loop.monitoring``). A loop whose latest
        evaluation already carries the current fingerprint is
        skipped without a write. One loop's failure never aborts
        the cycle: known evaluation failures are recorded as
        error rows, and unexpected exceptions are logged, reported
        as public errors, and skipped.
        """

        cycle = cycle_id or generate_id()
        now = normalize_cutoff(evaluated_at) if evaluated_at is not None else utc_now()
        loops = list(
            (
                await session.scalars(
                    select(StrategyLoopRecord).order_by(
                        StrategyLoopRecord.created_at.asc(), StrategyLoopRecord.id.asc()
                    )
                )
            ).all()
        )
        results: list[MonitoringCycleLoopResult] = []
        errors: list[str] = []
        for loop in loops:
            try:
                results.append(
                    await self._evaluate_loop_for_monitoring(session, loop, cycle, now)
                )
            except Exception:
                _logger.exception("Monitoring evaluation failed: loop_id=%s", loop.id)
                errors.append(public_worker_error("loop", loop.id))
        await session.commit()
        return MonitoringCycleResult(
            cycle_id=cycle,
            evaluated_at=format_cutoff(now),
            loops_evaluated=sum(1 for item in results if item.result == "evaluated"),
            loops_skipped=sum(1 for item in results if item.result == "skipped_unchanged"),
            loops_fired=sum(1 for item in results if item.summary == "fired"),
            loops_errored=sum(1 for item in results if item.summary == "error"),
            loops=results,
            errors=errors,
        )

    async def list_loop_evaluations(
        self, session: AsyncSession, loop_id: str, *, limit: int = 20, offset: int = 0
    ) -> list[LoopEvaluationRead]:
        """Evaluation history for one loop, newest first."""

        await self._require_loop(session, loop_id)
        rows = list(
            (
                await session.scalars(
                    select(LoopEvaluationRecord)
                    .where(LoopEvaluationRecord.loop_id == loop_id)
                    .order_by(
                        LoopEvaluationRecord.created_at.desc(), LoopEvaluationRecord.id.desc()
                    )
                    .limit(min(limit, 100))
                    .offset(max(offset, 0))
                )
            ).all()
        )
        return [_read_evaluation(row) for row in rows]

    async def _evaluate_loop_for_monitoring(
        self,
        session: AsyncSession,
        loop: StrategyLoopRecord,
        cycle_id: str,
        evaluated_at: datetime,
    ) -> MonitoringCycleLoopResult:
        observations = list(
            (
                await session.scalars(
                    select(LoopObservationRecord)
                    .where(LoopObservationRecord.loop_id == loop.id)
                    .order_by(
                        LoopObservationRecord.observed_at.asc(), LoopObservationRecord.id.asc()
                    )
                )
            ).all()
        )
        reads = [_read_observation(item) for item in observations]
        observation_ids = [item.id for item in reads]

        # Registration selection; stored JSON that no longer
        # validates becomes a recorded error, not a crash — the
        # fingerprint still covers the raw stored JSON so the
        # error row dedups like any other.
        registration_error: tuple[str, str] | None = None
        try:
            registrations = [
                TriggerRegistration.model_validate(item) for item in (loop.triggers or [])
            ]
        except ValidationError as exc:
            registration = None
            registration_error = (
                "loop_corrupt_registration",
                f"Loop {loop.id} carries trigger registrations that fail "
                f"validation: {exc}.",
            )
            triggers_payload: Any = loop.triggers or []
        else:
            registration = select_registration(registrations)
            triggers_payload = (
                registration.model_dump(mode="json")["triggers"]
                if registration is not None
                else None
            )
        fingerprint = evaluation_fingerprint(
            observation_ids,
            registration.id if registration is not None else None,
            triggers_payload,
        )
        latest = (
            await session.scalars(
                select(LoopEvaluationRecord)
                .where(LoopEvaluationRecord.loop_id == loop.id)
                .order_by(
                    LoopEvaluationRecord.created_at.desc(), LoopEvaluationRecord.id.desc()
                )
                .limit(1)
            )
        ).first()
        if latest is not None and latest.observation_fingerprint == fingerprint:
            existing = _read_evaluation(latest)
            return MonitoringCycleLoopResult(
                loop_id=loop.id,
                result="skipped_unchanged",
                evaluation_id=existing.id,
                summary=existing.summary,
            )

        error_code: str | None = None
        error_message: str | None = None
        outcomes: list[TriggerEvaluationOutcome] = []
        if registration_error is not None:
            error_code, error_message = registration_error
            summary: EvaluationSummary = "error"
        elif registration is None:
            summary = "no_data"
        else:
            baseline = await session.get(SimulationRun, loop.baseline_run_id)
            if baseline is None:
                error_code = "loop_baseline_missing"
                error_message = (
                    f"Baseline run {loop.baseline_run_id} was not found "
                    f"for loop {loop.id}."
                )
                summary = "error"
            else:
                final_state = (baseline.summary or {}).get("final_state")
                baseline_final = (
                    {key: float(value) for key, value in final_state.items()}
                    if isinstance(final_state, dict)
                    else {}
                )
                try:
                    outcomes = evaluate_triggers(
                        registration.triggers, reads, baseline_final_state=baseline_final
                    )
                except ValueError as exc:
                    error_code = "loop_trigger_evaluation_failed"
                    error_message = str(exc)
                    summary = "error"
                else:
                    summary = summarize_outcomes(outcomes, has_triggers=True)

        row = LoopEvaluationRecord(
            id=generate_id(),
            loop_id=loop.id,
            cycle_id=cycle_id,
            evaluated_at=evaluated_at,
            observation_fingerprint=fingerprint,
            registration_id=registration.id if registration is not None else None,
            observation_ids=observation_ids,
            outcomes=[outcome.model_dump(mode="json") for outcome in outcomes],
            summary=summary,
            error_code=error_code,
            error_message=error_message,
        )
        session.add(row)
        await session.flush()
        return MonitoringCycleLoopResult(
            loop_id=loop.id,
            result="evaluated",
            evaluation_id=row.id,
            summary=summary,
        )

    # ---------------------------------------------------------------- helpers

    async def _require_loop(self, session: AsyncSession, loop_id: str) -> StrategyLoopRecord:
        row = await session.get(StrategyLoopRecord, loop_id)
        if row is None:
            raise LookupError(f"Strategy loop {loop_id} was not found.")
        return row

    async def _require_iteration(
        self, session: AsyncSession, loop_id: str, iteration_id: str
    ) -> LoopIterationRecord:
        record = await session.get(LoopIterationRecord, iteration_id)
        if record is None or record.loop_id != loop_id:
            raise LookupError(f"Loop iteration {iteration_id} was not found on loop {loop_id}.")
        return record

    async def _latest_iteration(
        self, session: AsyncSession, loop_id: str
    ) -> LoopIterationRecord | None:
        return (
            await session.scalars(
                select(LoopIterationRecord)
                .where(LoopIterationRecord.loop_id == loop_id)
                .order_by(LoopIterationRecord.index.desc())
                .limit(1)
            )
        ).first()

    @staticmethod
    def _require_state(record: LoopIterationRecord, allowed: tuple[str, ...], action: str) -> None:
        if record.state not in allowed:
            raise LoopError(
                "loop_invalid_state",
                f"Cannot {action} while the iteration is {record.state!r}; "
                f"required state: {' or '.join(repr(state) for state in allowed)}.",
            )

    async def _reevaluate_baseline_gates(
        self,
        session: AsyncSession,
        baseline_run_id: str,
        new_ensemble: Any,
        baseline_values: list[float],
        strategy_values: list[float],
    ) -> Any | None:
        gates = await self.get_decision_gates(session, baseline_run_id)
        if gates is None or not gates.registrations:
            return None
        active = [item for item in gates.registrations if item.status == "active"]
        registration = active[-1] if active else gates.registrations[-1]
        return _reevaluate_gates(registration, new_ensemble, baseline_values, strategy_values)

    async def _build_resimulation_payload(
        self,
        session: AsyncSession,
        baseline: SimulationRun,
        decision_time: datetime,
        request: ResimulateRequest,
    ) -> tuple[SimulationRunCreate, dict[str, Any]]:
        """Rebuild the baseline's creation payload with explicit changes.

        Decomposition and bindings come from the baseline's stored
        configuration fragments, so the re-simulation inherits exactly
        what the baseline ran with — unless the review explicitly
        names a change, which is recorded in ``changes``. A malformed
        stored fragment fails loudly: silently dropping a
        decomposition or bindings would change what the run means.
        """

        configuration = baseline.configuration or {}
        changes: dict[str, Any] = {}
        if request.note is not None:
            changes["note"] = request.note

        decomposition = None
        mece_fragment = configuration.get("mece")
        if mece_fragment is not None:
            if not isinstance(mece_fragment, dict) or "decomposition" not in mece_fragment:
                raise LoopError(
                    "loop_corrupt_baseline_fragment",
                    "Baseline run carries a malformed MECE fragment; refusing "
                    "to re-simulate rather than silently drop it.",
                )
            decomposition = DecompositionTree.model_validate(mece_fragment["decomposition"])

        variables_fragment = configuration.get("variables")
        template_id: str | None = None
        variable_set: VariableSet | None = None
        if variables_fragment is not None:
            if not isinstance(variables_fragment, dict):
                raise LoopError(
                    "loop_corrupt_baseline_fragment",
                    "Baseline run carries a malformed variables fragment; "
                    "refusing to re-simulate rather than silently drop it.",
                )
            template_id = variables_fragment.get("template_id")
            bindings = variables_fragment.get("bindings")
            if isinstance(bindings, dict):
                variable_set = VariableSet.model_validate(bindings)

        if request.variable_template_id is not None:
            changes["variable_template_id"] = {
                "from": template_id,
                "to": request.variable_template_id,
            }
            template_id = request.variable_template_id
        if request.variable_set is not None:
            changes["variable_set"] = "override supplied"
            variable_set = request.variable_set

        seed = baseline.seed
        if request.seed is not None and request.seed != baseline.seed:
            changes["seed"] = {"from": baseline.seed, "to": request.seed}
            seed = request.seed
        tick_count = baseline.tick_count
        if request.tick_count is not None and request.tick_count != baseline.tick_count:
            changes["tick_count"] = {"from": baseline.tick_count, "to": request.tick_count}
            tick_count = request.tick_count

        initial_state = configuration.get("initial_state") or {}
        if not isinstance(initial_state, dict):
            raise LoopError(
                "loop_corrupt_baseline_fragment",
                "Baseline run carries a malformed initial_state; refusing to re-simulate.",
            )

        payload_kwargs: dict[str, Any] = {
            "domain_id": baseline.domain_id,
            "actor_template": baseline.actor_template,
            "execution_mode": ExecutionMode.INLINE,
            "tick_count": tick_count,
            "seed": seed,
            "tenant_id": baseline.tenant_id,
            "preset_id": baseline.preset_id,
            "initial_state": {key: float(value) for key, value in initial_state.items()},
            "decomposition": decomposition,
            "variable_template_id": template_id,
            "variable_set": variable_set,
            "decision_time": decision_time,
        }
        if baseline.domain_id == "corporate":
            company = (
                await session.get(CompanyProfile, baseline.company_id)
                if baseline.company_id
                else None
            )
            if company is None:
                raise LoopError(
                    "loop_missing_subject",
                    "Baseline run's company profile is missing; refusing to "
                    "re-simulate without its subject.",
                )
            payload_kwargs["company_id"] = company.id
            payload_kwargs["company_name"] = company.name
            payload_kwargs["market"] = configuration.get("market", "ai")
        elif baseline.domain_id == "military":
            force = (
                await session.get(ForceProfile, baseline.force_id) if baseline.force_id else None
            )
            if force is None:
                raise LoopError(
                    "loop_missing_subject",
                    "Baseline run's force profile is missing; refusing to "
                    "re-simulate without its subject.",
                )
            payload_kwargs["force_id"] = force.id
            payload_kwargs["force_name"] = force.name
            payload_kwargs["theater"] = configuration.get("theater") or force.theater
            payload_kwargs["military_use_mode"] = baseline.military_use_mode or "full_domain"
        else:  # pragma: no cover - creation restricts domains
            raise LoopError(
                "loop_unsupported_domain",
                f"Domain {baseline.domain_id!r} cannot be re-simulated.",
            )
        return SimulationRunCreate(**payload_kwargs), changes

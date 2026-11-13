"""Monte Carlo ensembles and hash-verified replay (Sprint 3, PRD deltas D4/D5).

This mixin holds the service orchestration; the pure mechanics (canonical
hashing, sampling, aggregation) live in :mod:`planagent.services.distributions`.

Monte Carlo: N paired trials (baseline vs strategy) over a completed run's
variable bindings. Each trial is a real ``SimulationRun`` row executed by
the same ``_execute_run`` as any other run, so trials are inspectable
through the existing endpoints. Trial seeds derive from the requested seed
via :func:`derive_sub_seed` — the arm is deliberately NOT part of the
derivation, so a baseline trial and its strategy pair share one RNG stream
and identical draws for non-levered variables (the SimplifySimulation
paired pattern). Strategy levers replace drawn values after the draw is
consumed. Trial runs skip report generation: they are ensemble members,
not standalone decision artifacts.

Replay: re-execute a run from its stored inputs (same configuration, seed,
subject, tick count) as a fresh run row, then compare per-tick state
hashes. A divergence reports the first diverging tick. Replay is exact
when the execution inputs are unchanged: the evidence base, the rule
registry (including calibration weights), and the LLM configuration. The
LLM-assisted decision level is inherently non-reproducible; in
no-LLM-key environments every tick is rule/fallback and replay matches.
"""

from __future__ import annotations

from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from planagent.domain.enums import ExecutionMode, SimulationRunStatus
from planagent.domain.models import (
    SimulationRun,
    StateSnapshotRecord,
    generate_id,
)
from planagent.services.distributions import (
    HASH_PROTOCOL_VERSION,
    compute_input_hash,
    derive_sub_seed,
    determinism_input_fragment,
    paired_delta_stats,
    state_hash,
    summarize_samples,
)
from planagent.services.distributions.models import (
    DeterminismRead,
    DistributionSummary,
    MonteCarloRequest,
    MonteCarloResult,
    MonteCarloTrialValues,
    PairedDeltaSummary,
    ReplayResult,
)
from planagent.services.variables.models import VariableSet
from planagent.simulation.domain_packs import registry

MONTE_CARLO_SUMMARY_KEY = "monte_carlo"
DETERMINISM_SUMMARY_KEY = "determinism"


class MonteCarloError(ValueError):
    """Refusal with a stable machine-readable code (route maps to 400)."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _stored_bindings(run: SimulationRun) -> VariableSet | None:
    fragment = (run.configuration or {}).get("variables")
    if not isinstance(fragment, dict):
        return None
    bindings = fragment.get("bindings")
    if not isinstance(bindings, dict):
        return None
    variable_set = VariableSet.model_validate(bindings)
    return variable_set if variable_set.variables else None


def compare_snapshot_hashes(
    original_hashes: dict[str, str],
    replay_hashes: dict[str, str],
) -> tuple[bool, int | None]:
    """Compare per-tick state hashes; report the first diverging tick.

    Ticks are compared in numeric order; a tick present on one side only
    counts as diverging at that tick. Returns ``(match,
    first_diverging_tick)`` with the tick None when the trajectories
    match exactly.
    """

    all_ticks = sorted({*original_hashes, *replay_hashes}, key=int)
    for tick_key in all_ticks:
        if original_hashes.get(tick_key) != replay_hashes.get(tick_key):
            return False, int(tick_key)
    return True, None


class SimulationDistributionsMixin:
    async def run_monte_carlo(
        self,
        session: AsyncSession,
        run_id: str,
        request: MonteCarloRequest,
    ) -> MonteCarloResult:
        """Run a paired Monte Carlo ensemble over a completed run's bindings."""

        base_run = await session.get(SimulationRun, run_id)
        if base_run is None:
            raise LookupError(f"Simulation run {run_id} was not found.")
        if base_run.status != SimulationRunStatus.COMPLETED.value:
            raise MonteCarloError(
                "monte_carlo_requires_completed_run",
                "Monte Carlo requires a completed baseline run.",
            )
        bindings = _stored_bindings(base_run)
        if bindings is None:
            raise MonteCarloError(
                "monte_carlo_requires_bindings",
                "Monte Carlo requires variable bindings on the baseline run.",
            )
        pack = registry.get(base_run.domain_id)
        state_fields = {field.name for field in pack.state_fields}
        if request.metric not in state_fields:
            raise MonteCarloError(
                "monte_carlo_unknown_metric",
                f"Metric {request.metric!r} is not a state field of domain {base_run.domain_id!r}.",
            )
        variable_ids = {variable.id for variable in bindings.variables}
        unknown_levers = sorted(set(request.strategy_levers) - variable_ids)
        if unknown_levers:
            raise MonteCarloError(
                "monte_carlo_unknown_lever",
                f"Strategy levers name unknown variables: {', '.join(unknown_levers)}.",
            )

        seed = request.seed if request.seed is not None else base_run.seed
        ensemble_id = generate_id()
        baseline_values: list[float] = []
        strategy_values: list[float] = []
        trial_run_ids: dict[str, list[str]] = {"baseline": [], "strategy": []}

        for trial_index in range(request.trials):
            trial_seed = derive_sub_seed(seed, "monte-carlo", str(trial_index))
            for arm, levers in (
                ("baseline", {}),
                ("strategy", dict(request.strategy_levers)),
            ):
                trial_run = await self._create_monte_carlo_trial(
                    session,
                    base_run,
                    ensemble_id=ensemble_id,
                    trial_index=trial_index,
                    arm=arm,
                    trial_seed=trial_seed,
                    levers=levers,
                )
                final_state = trial_run.summary.get("final_state", {})
                value = float(final_state.get(request.metric, 0.0))
                if arm == "baseline":
                    baseline_values.append(value)
                else:
                    strategy_values.append(value)
                trial_run_ids[arm].append(trial_run.id)

        result = MonteCarloResult(
            ensemble_id=ensemble_id,
            base_run_id=base_run.id,
            trials=request.trials,
            seed=seed,
            metric=request.metric,
            loss_threshold=request.loss_threshold,
            strategy_levers=dict(request.strategy_levers),
            baseline=DistributionSummary(
                **summarize_samples(baseline_values, request.loss_threshold)
            ),
            strategy=DistributionSummary(
                **summarize_samples(strategy_values, request.loss_threshold)
            ),
            paired=PairedDeltaSummary(**paired_delta_stats(baseline_values, strategy_values)),
            trial_run_ids=trial_run_ids,
            protocol=HASH_PROTOCOL_VERSION,
        )
        base_run.summary = {
            **base_run.summary,
            MONTE_CARLO_SUMMARY_KEY: result.model_dump(mode="json"),
        }
        await session.commit()
        await session.refresh(base_run)
        return result

    async def _create_monte_carlo_trial(
        self,
        session: AsyncSession,
        base_run: SimulationRun,
        *,
        ensemble_id: str,
        trial_index: int,
        arm: str,
        trial_seed: int,
        levers: dict[str, float],
    ) -> SimulationRun:
        configuration = deepcopy(base_run.configuration)
        configuration["monte_carlo"] = {
            "ensemble_id": ensemble_id,
            "base_run_id": base_run.id,
            "trial_index": trial_index,
            "arm": arm,
            "trial_seed": trial_seed,
            "levers": levers,
        }
        configuration["determinism"] = determinism_input_fragment(
            domain_id=base_run.domain_id,
            actor_template=base_run.actor_template,
            tick_count=base_run.tick_count,
            seed=trial_seed,
            company_id=base_run.company_id,
            force_id=base_run.force_id,
            tenant_id=base_run.tenant_id,
            preset_id=base_run.preset_id,
            configuration=configuration,
        )
        run = SimulationRun(
            company_id=base_run.company_id,
            force_id=base_run.force_id,
            tenant_id=base_run.tenant_id,
            preset_id=base_run.preset_id,
            domain_id=base_run.domain_id,
            actor_template=base_run.actor_template,
            military_use_mode=base_run.military_use_mode,
            parent_run_id=None,
            execution_mode=ExecutionMode.INLINE.value,
            status=SimulationRunStatus.PENDING.value,
            tick_count=base_run.tick_count,
            seed=trial_seed,
            configuration=configuration,
            summary={},
        )
        session.add(run)
        await session.flush()
        if base_run.domain_id == "military":
            await self._clone_geo_assets_for_scenario(session, base_run.id, run)
        # Trial runs execute the same tick loop as any run, but skip
        # report generation: they are ensemble members, not decision
        # artifacts.
        await self._execute_run(session, run)
        return run

    async def get_monte_carlo(
        self,
        session: AsyncSession,
        run_id: str,
    ) -> MonteCarloResult | None:
        run = await session.get(SimulationRun, run_id)
        if run is None:
            return None
        fragment = (run.summary or {}).get(MONTE_CARLO_SUMMARY_KEY)
        if not isinstance(fragment, dict):
            return None
        return MonteCarloResult.model_validate(fragment)

    async def get_monte_carlo_trial_values(
        self,
        session: AsyncSession,
        run_id: str,
    ) -> MonteCarloTrialValues | None:
        """Per-trial values behind a stored ensemble, for charting (Sprint 8).

        Returns None when the run is missing or has no stored ensemble
        (the route maps that to 404, like :meth:`get_monte_carlo`). The
        values are re-read from the trial run rows via the robustness
        mixin's helpers — the same re-read and the same hash the
        robustness analyses use — so the hash on this response equals
        the ``trial_values_hash`` pinned on every robustness result for
        the ensemble. Nothing is re-executed. A missing trial row raises
        the robustness mixin's missing-values error, mapped by the route
        to 400 with its stable code.
        """

        ensemble = await self.get_monte_carlo(session, run_id)
        if ensemble is None:
            return None
        baseline, strategy = await self._trial_values_for_ensemble(session, ensemble)
        return MonteCarloTrialValues(
            ensemble_id=ensemble.ensemble_id,
            base_run_id=ensemble.base_run_id,
            metric=ensemble.metric,
            loss_threshold=ensemble.loss_threshold,
            baseline=baseline,
            strategy=strategy,
            trial_values_hash=self._trial_values_hash(ensemble, baseline, strategy),
            protocol=HASH_PROTOCOL_VERSION,
        )

    async def replay_simulation_run(
        self,
        session: AsyncSession,
        run_id: str,
    ) -> ReplayResult:
        """Re-execute a run from its stored inputs and compare state hashes."""

        original = await session.get(SimulationRun, run_id)
        if original is None:
            raise LookupError(f"Simulation run {run_id} was not found.")
        if original.status != SimulationRunStatus.COMPLETED.value:
            raise MonteCarloError(
                "replay_requires_completed_run",
                "Replay requires a completed run.",
            )
        original_hashes = await self._snapshot_hashes(session, original.id)
        if not original_hashes:
            raise MonteCarloError(
                "replay_no_snapshots",
                f"Run {run_id} has no stored state snapshots to replay against.",
            )

        configuration = deepcopy(original.configuration)
        configuration["determinism"] = determinism_input_fragment(
            domain_id=original.domain_id,
            actor_template=original.actor_template,
            tick_count=original.tick_count,
            seed=original.seed,
            company_id=original.company_id,
            force_id=original.force_id,
            tenant_id=original.tenant_id,
            preset_id=original.preset_id,
            configuration=configuration,
        )
        replay_run = SimulationRun(
            company_id=original.company_id,
            force_id=original.force_id,
            tenant_id=original.tenant_id,
            preset_id=original.preset_id,
            domain_id=original.domain_id,
            actor_template=original.actor_template,
            military_use_mode=original.military_use_mode,
            parent_run_id=None,
            execution_mode=ExecutionMode.INLINE.value,
            status=SimulationRunStatus.PENDING.value,
            tick_count=original.tick_count,
            seed=original.seed,
            configuration=configuration,
            summary={"replay_of": original.id},
        )
        session.add(replay_run)
        await session.flush()
        if original.domain_id == "military":
            await self._clone_geo_assets_for_scenario(session, original.id, replay_run)
        await self._execute_run(session, replay_run)

        replay_hashes = await self._snapshot_hashes(session, replay_run.id)
        match, first_diverging_tick = compare_snapshot_hashes(original_hashes, replay_hashes)

        original_input_hash = compute_input_hash(
            domain_id=original.domain_id,
            actor_template=original.actor_template,
            tick_count=original.tick_count,
            seed=original.seed,
            company_id=original.company_id,
            force_id=original.force_id,
            tenant_id=original.tenant_id,
            preset_id=original.preset_id,
            configuration=original.configuration,
        )
        replay_input_hash = (replay_run.configuration.get("determinism") or {}).get("input_hash")
        result = ReplayResult(
            original_run_id=original.id,
            replay_run_id=replay_run.id,
            match=match,
            first_diverging_tick=first_diverging_tick,
            tick_count=len(original_hashes),
            original_state_hashes=original_hashes,
            replay_state_hashes=replay_hashes,
            input_hash_match=original_input_hash == replay_input_hash,
        )
        replay_run.summary = {
            **replay_run.summary,
            "replay_verification": result.model_dump(mode="json"),
        }
        await session.commit()
        await session.refresh(replay_run)
        return result

    async def _snapshot_hashes(
        self,
        session: AsyncSession,
        run_id: str,
    ) -> dict[str, str]:
        snapshots = list(
            (
                await session.scalars(
                    select(StateSnapshotRecord)
                    .where(StateSnapshotRecord.run_id == run_id)
                    .order_by(StateSnapshotRecord.tick.asc())
                )
            ).all()
        )
        return {str(item.tick): state_hash(item.state) for item in snapshots}

    async def get_determinism(
        self,
        session: AsyncSession,
        run_id: str,
    ) -> DeterminismRead | None:
        """Determinism audit data, preferring stored fragments.

        Stored fragments are the audit trail; when a run predates Sprint 3
        (no stored fragment), the same values are recomputed live from the
        stored configuration and snapshots, so the endpoint works for
        every run.
        """

        run = await session.get(SimulationRun, run_id)
        if run is None:
            return None
        stored = (run.configuration or {}).get("determinism")
        input_hash = stored.get("input_hash") if isinstance(stored, dict) else None
        if input_hash is None:
            input_hash = compute_input_hash(
                domain_id=run.domain_id,
                actor_template=run.actor_template,
                tick_count=run.tick_count,
                seed=run.seed,
                company_id=run.company_id,
                force_id=run.force_id,
                tenant_id=run.tenant_id,
                preset_id=run.preset_id,
                configuration=run.configuration,
            )
        summary_fragment = (run.summary or {}).get(DETERMINISM_SUMMARY_KEY)
        state_hashes: dict[str, str] = {}
        sampled_values: dict[str, float] = {}
        sampled_applied: list[str] = []
        derived_values: dict[str, float] = {}
        derived_applied: list[str] = []
        if isinstance(summary_fragment, dict):
            state_hashes = dict(summary_fragment.get("state_hashes") or {})
            sampled_values = dict(summary_fragment.get("sampled_values") or {})
            sampled_applied = list(summary_fragment.get("sampled_applied") or [])
            derived_values = dict(summary_fragment.get("derived_values") or {})
            derived_applied = list(summary_fragment.get("derived_applied") or [])
        if not state_hashes:
            state_hashes = await self._snapshot_hashes(session, run.id)
        return DeterminismRead(
            run_id=run.id,
            seed=run.seed,
            protocol=HASH_PROTOCOL_VERSION,
            input_hash=input_hash,
            state_hashes=state_hashes,
            sampled_values=sampled_values,
            sampled_applied=sampled_applied,
            derived_values=derived_values,
            derived_applied=derived_applied,
        )

"""Robustness evaluation orchestration (Sprint 4, PRD deltas D6/D7).

This mixin holds the service orchestration; the pure mechanics (expected
shortfall, bootstrap, bisection, gate metrics) live in
:mod:`planagent.services.robustness`. Every analysis requires a stored Monte
Carlo ensemble on the run: robustness is an analysis OF an ensemble, and the
ensemble's metric, loss threshold, and strategy levers define the analysis
context. Trial values are re-read from the stored trial run rows (reached
via the ensemble's trial run ids) — never re-derived by re-execution — and
each result carries a SHA-256 hash of the exact trial values used, so an
analysis is pinned to its inputs.

Tornado and threshold search execute new probe runs: real ``SimulationRun``
rows through the same ``_execute_run`` as any other run (marked with a
``robustness_probe`` configuration fragment, report generation skipped), so
probe outcomes are inspectable through the existing endpoints and covered
by the replay machinery. Probe runs use fixed bindings (point values for
the tornado, one frozen variable for threshold search) with seeds derived
from the analysis seed, so a probe set is reproducible.
"""

from __future__ import annotations

import statistics
from copy import deepcopy
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from planagent.domain.enums import ExecutionMode, SimulationRunStatus
from planagent.domain.models import SimulationRun, generate_id, utc_now
from planagent.services.distributions import (
    HASH_PROTOCOL_VERSION,
    derive_sub_seed,
    determinism_input_fragment,
    distribution_median,
    distribution_quantile,
    sha256_hash,
)
from planagent.services.distributions.models import MonteCarloResult
from planagent.services.robustness.methods import (
    apply_gate_operator,
    bisect_threshold_search,
    bootstrap_intervals,
    expected_shortfall,
    gate_observed_value,
    tornado_swing,
)
from planagent.services.robustness.models import (
    BootstrapInterval,
    BootstrapRequest,
    BootstrapResult,
    DecisionGatesRead,
    ExpectedShortfallDetail,
    ExpectedShortfallRequest,
    ExpectedShortfallResult,
    GateEvaluation,
    GateEvaluationRequest,
    GateMetric,
    GateOutcome,
    GateRegistration,
    GateRegistrationRequest,
    RobustnessRead,
    ThresholdEvaluation,
    ThresholdSearchRequest,
    ThresholdSearchResult,
    TornadoRequest,
    TornadoResult,
    TornadoRow,
)
from planagent.services.variables.models import (
    DistributionType,
    VariableDefinition,
    VariableDistribution,
    VariableSet,
)
from planagent.services.variables.validator import validate_variable_set

ROBUSTNESS_SUMMARY_KEY = "robustness"
DECISION_GATES_SUMMARY_KEY = "decision_gates"
ROBUSTNESS_PROBE_CONFIGURATION_KEY = "robustness_probe"


class RobustnessError(ValueError):
    """Refusal with a stable machine-readable code (route maps to 400)."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _run_bindings(run: SimulationRun) -> VariableSet | None:
    """The stored variable bindings of a run, if it carries any."""

    fragment = (run.configuration or {}).get("variables")
    if not isinstance(fragment, dict):
        return None
    bindings = fragment.get("bindings")
    if not isinstance(bindings, dict):
        return None
    variable_set = VariableSet.model_validate(bindings)
    return variable_set if variable_set.variables else None


def _fixed_variable(variable: VariableDefinition, value: float) -> VariableDefinition:
    """The same variable pinned to a constant (for probe bindings)."""

    return VariableDefinition(
        id=variable.id,
        unit=variable.unit,
        distribution=VariableDistribution(type=DistributionType.FIXED, value=value),
        evidence_ref=variable.evidence_ref,
        description=variable.description,
        scope_tags=list(variable.scope_tags),
    )


def _distribution_support(variable: VariableDefinition) -> tuple[float, float]:
    """The searchable range of a variable's distribution.

    Triangular/beta_pert use their bounds; normal uses mean ± 3 std (99.7%
    of the mass). Fixed and bernoulli variables have no continuum to
    search and are refused by the caller.
    """

    distribution = variable.distribution
    if distribution.type in (DistributionType.TRIANGULAR, DistributionType.BETA_PERT):
        if distribution.min is None or distribution.max is None:
            raise RobustnessError(
                "robustness_threshold_missing_bounds",
                f"Variable {variable.id!r} is missing distribution bounds.",
            )
        return float(distribution.min), float(distribution.max)
    if distribution.type is DistributionType.NORMAL:
        if distribution.mean is None or distribution.std is None:
            raise RobustnessError(
                "robustness_threshold_missing_bounds",
                f"Variable {variable.id!r} is missing distribution parameters.",
            )
        return float(distribution.mean - 3 * distribution.std), float(
            distribution.mean + 3 * distribution.std
        )
    if distribution.type is DistributionType.FIXED:
        raise RobustnessError(
            "robustness_threshold_fixed_variable",
            f"Variable {variable.id!r} is fixed; there is no range to search.",
        )
    raise RobustnessError(
        "robustness_threshold_discrete_variable",
        f"Variable {variable.id!r} is bernoulli; bisection needs a continuum.",
    )


class SimulationRobustnessMixin:
    async def _stored_ensemble(
        self, session: AsyncSession, run_id: str
    ) -> tuple[SimulationRun, MonteCarloResult]:
        run = await session.get(SimulationRun, run_id)
        if run is None:
            raise LookupError(f"Simulation run {run_id} was not found.")
        ensemble = await self.get_monte_carlo(session, run_id)
        if ensemble is None:
            raise RobustnessError(
                "robustness_requires_ensemble",
                f"Run {run_id} has no stored Monte Carlo ensemble to analyze.",
            )
        return run, ensemble

    async def _trial_values(
        self,
        session: AsyncSession,
        ensemble: MonteCarloResult,
        arm: str,
    ) -> list[float]:
        """Trial metric values for one arm, re-read from the trial rows."""

        values: list[float] = []
        for trial_id in ensemble.trial_run_ids.get(arm, []):
            trial = await session.get(SimulationRun, trial_id)
            if trial is None:
                raise RobustnessError(
                    "robustness_trial_values_missing",
                    f"Trial run {trial_id} of ensemble {ensemble.ensemble_id} is missing.",
                )
            final_state = (trial.summary or {}).get("final_state")
            if not isinstance(final_state, dict) or ensemble.metric not in final_state:
                raise RobustnessError(
                    "robustness_trial_values_missing",
                    f"Trial run {trial_id} has no final {ensemble.metric!r} value.",
                )
            values.append(float(final_state[ensemble.metric]))
        if not values:
            raise RobustnessError(
                "robustness_trial_values_missing",
                f"Ensemble {ensemble.ensemble_id} has no {arm} trial values.",
            )
        return values

    async def _trial_values_for_ensemble(
        self, session: AsyncSession, ensemble: MonteCarloResult
    ) -> tuple[list[float], list[float]]:
        baseline = await self._trial_values(session, ensemble, "baseline")
        strategy = await self._trial_values(session, ensemble, "strategy")
        return baseline, strategy

    @staticmethod
    def _trial_values_hash(
        ensemble: MonteCarloResult,
        baseline_values: list[float],
        strategy_values: list[float],
    ) -> str:
        return sha256_hash(
            {
                "ensemble_id": ensemble.ensemble_id,
                "metric": ensemble.metric,
                "baseline": baseline_values,
                "strategy": strategy_values,
            }
        )

    async def _store_robustness_result(
        self,
        session: AsyncSession,
        run: SimulationRun,
        key: str,
        result: Any,
    ) -> None:
        fragment = dict((run.summary or {}).get(ROBUSTNESS_SUMMARY_KEY) or {})
        fragment[key] = result.model_dump(mode="json")
        run.summary = {**run.summary, ROBUSTNESS_SUMMARY_KEY: fragment}
        await session.commit()
        await session.refresh(run)

    async def _create_analysis_run(
        self,
        session: AsyncSession,
        base_run: SimulationRun,
        *,
        seed: int,
        probe: dict[str, Any],
        bindings: VariableSet | None = None,
        levers: dict[str, float] | None = None,
    ) -> SimulationRun:
        """Execute one probe run: a real run row through ``_execute_run``.

        ``bindings`` replaces the stored bindings (tornado point values,
        threshold frozen variables); ``levers`` ride the Monte Carlo
        fragment (strategy arm of arm-flip probes). Report generation is
        skipped: probes are analysis members, not decision artifacts.
        """

        configuration = deepcopy(base_run.configuration)
        if bindings is not None:
            variables_fragment = dict(configuration.get("variables") or {})
            variables_fragment["bindings"] = bindings.model_dump(mode="json")
            variables_fragment["validation"] = validate_variable_set(bindings).model_dump(
                mode="json"
            )
            configuration["variables"] = variables_fragment
        if levers:
            monte_carlo = dict(configuration.get("monte_carlo") or {})
            monte_carlo["levers"] = dict(levers)
            configuration["monte_carlo"] = monte_carlo
        configuration[ROBUSTNESS_PROBE_CONFIGURATION_KEY] = probe
        configuration["determinism"] = determinism_input_fragment(
            domain_id=base_run.domain_id,
            actor_template=base_run.actor_template,
            tick_count=base_run.tick_count,
            seed=seed,
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
            seed=seed,
            configuration=configuration,
            summary={},
        )
        session.add(run)
        await session.flush()
        if base_run.domain_id == "military":
            await self._clone_geo_assets_for_scenario(session, base_run.id, run)
        await self._execute_run(session, run)
        return run

    @staticmethod
    def _probe_metric_value(probe_run: SimulationRun, metric: str) -> float:
        final_state = (probe_run.summary or {}).get("final_state", {})
        return float(final_state.get(metric, 0.0))

    async def compute_expected_shortfall(
        self,
        session: AsyncSession,
        run_id: str,
        request: ExpectedShortfallRequest,
    ) -> ExpectedShortfallResult:
        """Expected shortfall per arm plus the paired-delta tail."""

        run, ensemble = await self._stored_ensemble(session, run_id)
        baseline_values, strategy_values = await self._trial_values_for_ensemble(session, ensemble)
        deltas = [s - b for b, s in zip(baseline_values, strategy_values)]
        result = ExpectedShortfallResult(
            run_id=run.id,
            ensemble_id=ensemble.ensemble_id,
            metric=ensemble.metric,
            alpha=request.alpha,
            tail=request.tail,
            baseline=ExpectedShortfallDetail(
                **expected_shortfall(baseline_values, request.alpha, request.tail)
            ),
            strategy=ExpectedShortfallDetail(
                **expected_shortfall(strategy_values, request.alpha, request.tail)
            ),
            paired=ExpectedShortfallDetail(
                **expected_shortfall(deltas, request.alpha, request.tail)
            ),
            trial_values_hash=self._trial_values_hash(ensemble, baseline_values, strategy_values),
            protocol=HASH_PROTOCOL_VERSION,
        )
        await self._store_robustness_result(session, run, "expected_shortfall", result)
        return result

    async def compute_bootstrap(
        self,
        session: AsyncSession,
        run_id: str,
        request: BootstrapRequest,
    ) -> BootstrapResult:
        """Seeded bootstrap percentile intervals per arm."""

        run, ensemble = await self._stored_ensemble(session, run_id)
        baseline_values, strategy_values = await self._trial_values_for_ensemble(session, ensemble)
        seed = request.seed if request.seed is not None else ensemble.seed
        baseline_seed = derive_sub_seed(seed, "bootstrap", "baseline")
        strategy_seed = derive_sub_seed(seed, "bootstrap", "strategy")
        result = BootstrapResult(
            run_id=run.id,
            ensemble_id=ensemble.ensemble_id,
            metric=ensemble.metric,
            loss_threshold=ensemble.loss_threshold,
            baseline=[
                BootstrapInterval(**interval)
                for interval in bootstrap_intervals(
                    baseline_values,
                    list(request.statistics),
                    draws=request.draws,
                    seed=baseline_seed,
                    level=request.level,
                    loss_threshold=ensemble.loss_threshold,
                )
            ],
            strategy=[
                BootstrapInterval(**interval)
                for interval in bootstrap_intervals(
                    strategy_values,
                    list(request.statistics),
                    draws=request.draws,
                    seed=strategy_seed,
                    level=request.level,
                    loss_threshold=ensemble.loss_threshold,
                )
            ],
            trial_values_hash=self._trial_values_hash(ensemble, baseline_values, strategy_values),
            protocol=HASH_PROTOCOL_VERSION,
        )
        await self._store_robustness_result(session, run, "bootstrap", result)
        return result

    async def compute_tornado(
        self,
        session: AsyncSession,
        run_id: str,
        request: TornadoRequest,
    ) -> TornadoResult:
        """Tornado sensitivity: one variable at a time over its quantiles.

        Every other variable is held at its median; the swung variable
        takes its low/high quantile values. Each point evaluation is a
        real probe run, so formulas and the tick loop apply exactly as in
        a normal run.
        """

        run, ensemble = await self._stored_ensemble(session, run_id)
        bindings = _run_bindings(run)
        if bindings is None:
            raise RobustnessError(
                "robustness_requires_bindings",
                f"Run {run_id} has no variable bindings to swing.",
            )
        by_id = {variable.id: variable for variable in bindings.variables}
        swing_ids = request.variables or [variable.id for variable in bindings.variables]
        unknown = sorted(set(swing_ids) - set(by_id))
        if unknown:
            raise RobustnessError(
                "robustness_unknown_variable",
                f"Tornado names unknown variables: {', '.join(unknown)}.",
            )
        seed = request.seed if request.seed is not None else ensemble.seed
        quantile_seed = derive_sub_seed(seed, "tornado-quantiles")
        base_values = {
            variable.id: distribution_median(variable.distribution, seed=quantile_seed)
            for variable in bindings.variables
        }

        def fixed_bindings(overrides: dict[str, float]) -> VariableSet:
            return VariableSet(
                name=bindings.name,
                variables=[
                    _fixed_variable(variable, overrides.get(variable.id, base_values[variable.id]))
                    for variable in bindings.variables
                ],
                formulas=list(bindings.formulas),
                internal=dict(bindings.internal),
            )

        analysis_id = generate_id()
        base_probe = await self._create_analysis_run(
            session,
            run,
            seed=seed,
            probe={"analysis": "tornado", "analysis_id": analysis_id, "role": "base"},
            bindings=fixed_bindings({}),
        )
        outcome_base = self._probe_metric_value(base_probe, ensemble.metric)
        probe_run_ids = [base_probe.id]
        rows: list[TornadoRow] = []
        for variable_id in swing_ids:
            variable = by_id[variable_id]
            low_value = distribution_quantile(
                variable.distribution, request.low_quantile, seed=quantile_seed
            )
            high_value = distribution_quantile(
                variable.distribution, request.high_quantile, seed=quantile_seed
            )
            low_probe = await self._create_analysis_run(
                session,
                run,
                seed=seed,
                probe={
                    "analysis": "tornado",
                    "analysis_id": analysis_id,
                    "role": "low",
                    "variable": variable_id,
                },
                bindings=fixed_bindings({variable_id: low_value}),
            )
            high_probe = await self._create_analysis_run(
                session,
                run,
                seed=seed,
                probe={
                    "analysis": "tornado",
                    "analysis_id": analysis_id,
                    "role": "high",
                    "variable": variable_id,
                },
                bindings=fixed_bindings({variable_id: high_value}),
            )
            probe_run_ids.extend([low_probe.id, high_probe.id])
            outcome_low = self._probe_metric_value(low_probe, ensemble.metric)
            outcome_high = self._probe_metric_value(high_probe, ensemble.metric)
            rows.append(
                TornadoRow(
                    variable=variable_id,
                    low_value=low_value,
                    high_value=high_value,
                    base_value=base_values[variable_id],
                    outcome_low=outcome_low,
                    outcome_high=outcome_high,
                    outcome_base=outcome_base,
                    swing=tornado_swing(outcome_low, outcome_high),
                )
            )
        # Stable sort: ties keep the binding order, so the ranking is
        # deterministic.
        rows.sort(key=lambda row: row.swing, reverse=True)
        result = TornadoResult(
            run_id=run.id,
            ensemble_id=ensemble.ensemble_id,
            metric=ensemble.metric,
            seed=seed,
            low_quantile=request.low_quantile,
            high_quantile=request.high_quantile,
            base_run_id=base_probe.id,
            rows=rows,
            probe_run_ids=probe_run_ids,
            protocol=HASH_PROTOCOL_VERSION,
        )
        await self._store_robustness_result(session, run, "tornado", result)
        return result

    async def run_threshold_search(
        self,
        session: AsyncSession,
        run_id: str,
        request: ThresholdSearchRequest,
    ) -> ThresholdSearchResult:
        """Bisection search for the input value where a statistic flips."""

        run, ensemble = await self._stored_ensemble(session, run_id)
        bindings = _run_bindings(run)
        if bindings is None:
            raise RobustnessError(
                "robustness_requires_bindings",
                f"Run {run_id} has no variable bindings to search over.",
            )
        by_id = {variable.id: variable for variable in bindings.variables}
        variable = by_id.get(request.variable)
        if variable is None:
            raise RobustnessError(
                "robustness_unknown_variable",
                f"Variable {request.variable!r} is not bound on run {run_id}.",
            )
        bounds = request.bounds or _distribution_support(variable)
        loss_threshold = (
            request.loss_threshold
            if request.loss_threshold is not None
            else ensemble.loss_threshold
        )
        seed = request.seed if request.seed is not None else ensemble.seed
        search_id = generate_id()

        def frozen_bindings(value: float) -> VariableSet:
            variables = [
                _fixed_variable(item, value) if item.id == variable.id else item
                for item in bindings.variables
            ]
            return VariableSet(
                name=bindings.name,
                variables=variables,
                formulas=list(bindings.formulas),
                internal=dict(bindings.internal),
            )

        async def evaluate_at(value: float) -> tuple[float, list[str]]:
            """One probe evaluation: frozen-variable trials at ``value``.

            Every evaluation reuses the same per-trial seeds, so
            differences between evaluations are the frozen variable, not
            sampling noise (the reference's same-seed rule).
            """

            probe_ids: list[str] = []
            baseline_values: list[float] = []
            strategy_values: list[float] = []
            frozen = frozen_bindings(value)
            strategy_levers = {
                key: item for key, item in ensemble.strategy_levers.items() if key != variable.id
            }
            for trial_index in range(request.trials_per_evaluation):
                trial_seed = derive_sub_seed(seed, "threshold-search", str(trial_index))
                baseline_probe = await self._create_analysis_run(
                    session,
                    run,
                    seed=trial_seed,
                    probe={
                        "analysis": "threshold-search",
                        "analysis_id": search_id,
                        "variable": variable.id,
                        "value": value,
                        "arm": "baseline",
                        "trial_index": trial_index,
                    },
                    bindings=frozen,
                )
                probe_ids.append(baseline_probe.id)
                baseline_values.append(self._probe_metric_value(baseline_probe, ensemble.metric))
                if request.mode == "arm_flip":
                    strategy_probe = await self._create_analysis_run(
                        session,
                        run,
                        seed=trial_seed,
                        probe={
                            "analysis": "threshold-search",
                            "analysis_id": search_id,
                            "variable": variable.id,
                            "value": value,
                            "arm": "strategy",
                            "trial_index": trial_index,
                        },
                        bindings=frozen,
                        levers=strategy_levers,
                    )
                    probe_ids.append(strategy_probe.id)
                    strategy_values.append(
                        self._probe_metric_value(strategy_probe, ensemble.metric)
                    )
            if request.mode == "arm_flip":
                statistic = float(
                    statistics.fmean([s - b for b, s in zip(baseline_values, strategy_values)])
                )
            else:
                statistic = sum(1 for item in baseline_values if item < loss_threshold) / len(
                    baseline_values
                )
            return statistic, probe_ids

        evaluations: list[ThresholdEvaluation] = []
        search = bisect_threshold_search(
            target=request.target,
            bounds=bounds,
            direction=request.direction,
            tolerance=request.tolerance,
            max_iterations=request.max_iterations,
        )
        probe_value = next(search)
        while True:
            statistic, probe_ids = await evaluate_at(probe_value)
            evaluations.append(
                ThresholdEvaluation(
                    value=probe_value,
                    statistic=statistic,
                    trials=request.trials_per_evaluation,
                    probe_run_ids=probe_ids,
                )
            )
            try:
                probe_value = search.send(statistic)
            except StopIteration as done:
                outcome = done.value
                break
        result = ThresholdSearchResult(
            run_id=run.id,
            ensemble_id=ensemble.ensemble_id,
            metric=ensemble.metric,
            variable=variable.id,
            mode=request.mode,
            target=request.target,
            direction=request.direction,
            bounds=bounds,
            threshold=outcome["threshold"],
            achieved_statistic=outcome["achieved_statistic"],
            reachable=outcome["reachable"],
            iterations=outcome["iterations"],
            evaluations=evaluations,
            trials_per_evaluation=request.trials_per_evaluation,
            tolerance=request.tolerance,
            loss_threshold=loss_threshold,
            seed=seed,
            protocol=HASH_PROTOCOL_VERSION,
        )
        await self._store_robustness_result(session, run, "threshold_search", result)
        return result

    async def get_robustness(
        self,
        session: AsyncSession,
        run_id: str,
    ) -> RobustnessRead | None:
        run = await session.get(SimulationRun, run_id)
        if run is None:
            return None
        fragment = (run.summary or {}).get(ROBUSTNESS_SUMMARY_KEY)
        if not isinstance(fragment, dict):
            return None
        ensemble = await self.get_monte_carlo(session, run_id)
        return RobustnessRead(
            run_id=run.id,
            ensemble_id=ensemble.ensemble_id if ensemble is not None else None,
            expected_shortfall=ExpectedShortfallResult.model_validate(
                fragment["expected_shortfall"]
            )
            if isinstance(fragment.get("expected_shortfall"), dict)
            else None,
            tornado=TornadoResult.model_validate(fragment["tornado"])
            if isinstance(fragment.get("tornado"), dict)
            else None,
            threshold_search=ThresholdSearchResult.model_validate(fragment["threshold_search"])
            if isinstance(fragment.get("threshold_search"), dict)
            else None,
            bootstrap=BootstrapResult.model_validate(fragment["bootstrap"])
            if isinstance(fragment.get("bootstrap"), dict)
            else None,
        )

    async def register_decision_gates(
        self,
        session: AsyncSession,
        run_id: str,
        request: GateRegistrationRequest,
    ) -> GateRegistration:
        """Register a gate set on a run. Registrations are append-only."""

        run = await session.get(SimulationRun, run_id)
        if run is None:
            raise LookupError(f"Simulation run {run_id} was not found.")
        fragment = deepcopy((run.summary or {}).get(DECISION_GATES_SUMMARY_KEY) or {})
        registrations = fragment.get("registrations", [])
        if request.supersedes is not None and all(
            item.get("id") != request.supersedes for item in registrations
        ):
            raise RobustnessError(
                "robustness_unknown_registration",
                f"Gate registration {request.supersedes!r} does not exist on run {run_id}.",
            )
        ensemble = await self.get_monte_carlo(session, run_id)
        registration = GateRegistration(
            id=generate_id(),
            run_id=run.id,
            ensemble_id=ensemble.ensemble_id if ensemble is not None else None,
            gates=list(request.gates),
            supersedes=request.supersedes,
            registered_at=utc_now().isoformat(),
            ensemble_existed_at_registration=ensemble is not None,
            status="active",
        )
        if request.supersedes is not None:
            for item in registrations:
                if item.get("id") == request.supersedes:
                    item["status"] = "superseded"
        registrations.append(registration.model_dump(mode="json"))
        fragment["registrations"] = registrations
        fragment.setdefault("evaluations", [])
        run.summary = {**run.summary, DECISION_GATES_SUMMARY_KEY: fragment}
        await session.commit()
        await session.refresh(run)
        return registration

    async def evaluate_decision_gates(
        self,
        session: AsyncSession,
        run_id: str,
        request: GateEvaluationRequest,
    ) -> GateEvaluation:
        """Evaluate a gate registration against the stored ensemble."""

        run, ensemble = await self._stored_ensemble(session, run_id)
        fragment = (run.summary or {}).get(DECISION_GATES_SUMMARY_KEY)
        registrations = fragment.get("registrations", []) if isinstance(fragment, dict) else []
        if not registrations:
            raise RobustnessError(
                "robustness_no_gate_registrations",
                f"Run {run_id} has no registered decision gates.",
            )
        if request.registration_id is not None:
            matches = [item for item in registrations if item.get("id") == request.registration_id]
            if not matches:
                raise RobustnessError(
                    "robustness_unknown_registration",
                    f"Gate registration {request.registration_id!r} does not exist "
                    f"on run {run_id}.",
                )
            stored = matches[0]
        else:
            active = [item for item in registrations if item.get("status") == "active"]
            stored = active[-1] if active else registrations[-1]
        registration = GateRegistration.model_validate(stored)
        baseline_values, strategy_values = await self._trial_values_for_ensemble(session, ensemble)
        outcomes: list[GateOutcome] = []
        for gate in registration.gates:
            observed = gate_observed_value(
                gate, baseline_values, strategy_values, ensemble.loss_threshold
            )
            outcomes.append(
                GateOutcome(
                    name=gate.name,
                    metric=gate.metric,
                    operator=gate.operator,
                    threshold=gate.threshold,
                    arm=gate.arm,
                    alpha=gate.alpha if gate.metric is GateMetric.EXPECTED_SHORTFALL else None,
                    observed=observed,
                    passed=apply_gate_operator(gate.operator, observed, gate.threshold),
                )
            )
        evaluation = GateEvaluation(
            id=generate_id(),
            registration_id=registration.id,
            run_id=run.id,
            ensemble_id=ensemble.ensemble_id,
            evaluated_at=utc_now().isoformat(),
            outcomes=outcomes,
            all_passed=all(outcome.passed for outcome in outcomes),
            pre_registered=(
                registration.ensemble_id != ensemble.ensemble_id
                or not registration.ensemble_existed_at_registration
            ),
        )
        stored_fragment = deepcopy(fragment) if isinstance(fragment, dict) else {}
        evaluations = stored_fragment.get("evaluations", [])
        evaluations.append(evaluation.model_dump(mode="json"))
        stored_fragment["evaluations"] = evaluations
        run.summary = {**run.summary, DECISION_GATES_SUMMARY_KEY: stored_fragment}
        await session.commit()
        await session.refresh(run)
        return evaluation

    async def get_decision_gates(
        self,
        session: AsyncSession,
        run_id: str,
    ) -> DecisionGatesRead | None:
        run = await session.get(SimulationRun, run_id)
        if run is None:
            return None
        fragment = (run.summary or {}).get(DECISION_GATES_SUMMARY_KEY)
        if not isinstance(fragment, dict):
            return DecisionGatesRead(run_id=run.id)
        return DecisionGatesRead(
            run_id=run.id,
            registrations=[
                GateRegistration.model_validate(item) for item in fragment.get("registrations", [])
            ],
            evaluations=[
                GateEvaluation.model_validate(item) for item in fragment.get("evaluations", [])
            ],
        )

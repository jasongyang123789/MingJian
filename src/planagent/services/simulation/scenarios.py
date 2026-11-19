from __future__ import annotations

from typing import Any

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from planagent.domain.api import ScenarioRunCreate
from planagent.domain.enums import ExecutionMode, SimulationRunStatus
from planagent.domain.models import (
    CompanyProfile,
    DecisionOption,
    DecisionRecordRecord,
    ExternalShockRecord,
    ForceProfile,
    GeneratedReport,
    GeoAssetRecord,
    Hypothesis,
    PredictionCalibrationContext,
    PredictionSeries,
    PredictionVersion,
    ScenarioBranchRecord,
    SimulationRun,
    StateSnapshotRecord,
    generate_id,
)
from planagent.services.distributions import determinism_input_fragment
from planagent.services.mece import find_branch_by_path
from planagent.services.mece.models import DecompositionTree
from planagent.services.simulation_branching import (
    build_branch_trajectory,
    build_scenario_compare_summary,
    score_branch_delta,
    summarize_branch_trajectory,
)
from planagent.services.variables.formulas import validate_formulas
from planagent.services.variables.models import (
    VariableSet,
    VariableTemplate,
    VariableValidationResult,
)
from planagent.services.variables.presets import (
    resolve_policies,
    variables_configuration_fragment,
)
from planagent.services.variables.store import get_variable_template
from planagent.services.variables.validator import (
    VariableTemplateError,
    VariableValidationError,
    merge_variable_sets,
    validate_scope_bindings,
    validate_variable_set,
)


class SimulationScenariosMixin:
    def _build_scenario_template(
        self,
        parent_run: SimulationRun,
        payload: ScenarioRunCreate,
        fork_step: int | None = None,
    ) -> dict[str, Any]:
        resolved_fork_step = fork_step or payload.fork_step or max(1, parent_run.tick_count // 2)
        return {
            "parent_run_id": parent_run.id,
            "domain_id": parent_run.domain_id,
            "actor_template": parent_run.actor_template,
            "fork_step": resolved_fork_step,
            "tick_count": payload.tick_count or max(1, parent_run.tick_count - resolved_fork_step),
            "assumptions": list(payload.assumptions),
            "decision_deltas": list(payload.decision_deltas),
            "state_overrides": dict(payload.state_overrides),
            "probability_band": payload.probability_band,
        }

    def _generate_scenarios(
        self,
        parent_run: SimulationRun,
        payloads: list[ScenarioRunCreate],
    ) -> list[dict[str, Any]]:
        return [self._build_scenario_template(parent_run, payload) for payload in payloads]

    async def _resolve_scenario_variable_bindings(
        self,
        session: AsyncSession,
        parent_run: SimulationRun,
        payload: ScenarioRunCreate,
    ) -> dict[str, Any]:
        """Branch-level variable bindings (Sprint 3).

        Returns the ``variables`` fragment for the child run, or {} when
        the payload carries no binding fields (the child then inherits
        the parent's fragment through the configuration copy, as before).

        Merge semantics: a branch template replaces the parent's template
        snapshot and supplies the base variable set; otherwise the
        parent's stored bindings are the base. An inline set merges over
        the base (inline wins per variable id). The effective set is
        validated with the same gate as run creation, and scope tags are
        cross-checked against the named decomposition branch's scope when
        ``decomposition_branch`` is given (else the parent decomposition's
        root scope, when the parent carries one). Failures raise before
        any row is written, mirroring the run-creation gates.
        """
        if (
            payload.variable_template_id is None
            and payload.variable_set is None
            and payload.decomposition_branch is None
        ):
            return {}

        parent_fragment = (parent_run.configuration or {}).get("variables")
        parent_fragment = parent_fragment if isinstance(parent_fragment, dict) else {}
        parent_template = parent_fragment.get("template")
        parent_bindings = parent_fragment.get("bindings")

        template: VariableTemplate | None = None
        if payload.variable_template_id is not None:
            template = await get_variable_template(session, payload.variable_template_id)
            if template is None:
                raise VariableTemplateError(
                    "variable_template_not_found",
                    f"Variable template {payload.variable_template_id!r} was not found.",
                )
            if template.domain_id != parent_run.domain_id:
                raise VariableTemplateError(
                    "variable_template_domain_mismatch",
                    f"Variable template {template.id!r} belongs to domain "
                    f"{template.domain_id!r}, not {parent_run.domain_id!r}.",
                )
        elif isinstance(parent_template, dict):
            template = VariableTemplate.model_validate(parent_template)

        base_set: VariableSet | None = None
        if payload.variable_template_id is not None and template is not None:
            base_set = VariableSet(
                name=template.name,
                variables=template.variables,
                formulas=template.formulas,
                internal=template.internal,
            )
        elif isinstance(parent_bindings, dict):
            base_set = VariableSet.model_validate(parent_bindings)

        if base_set is not None and payload.variable_set is not None:
            effective = merge_variable_sets(base_set, payload.variable_set)
        elif base_set is not None:
            effective = base_set
        elif payload.variable_set is not None:
            effective = payload.variable_set
        else:
            effective = None

        if effective is None:
            # Only a decomposition branch was named, with no bindings to
            # re-check: nothing to override, inherit unchanged.
            return {}
        if not effective.variables and payload.variable_set is None:
            # A template with no variables: snapshot the template (its
            # state defaults and policies still apply) without bindings
            # or a validation result, as in the run-creation gate —
            # unless the effective set carries formulas, which need
            # stored bindings to evaluate at runtime.
            if not effective.formulas:
                fragment = variables_configuration_fragment(template, None, None)
                fragment["variables"]["branch_override"] = True
                return fragment
            formula_issues, formula_checks = validate_formulas([], effective.formulas)
            if formula_issues:
                raise VariableValidationError(
                    VariableValidationResult(
                        is_valid=False,
                        variable_count=0,
                        checks=formula_checks,
                        issues=formula_issues,
                    )
                )
            fragment = variables_configuration_fragment(
                template,
                effective,
                VariableValidationResult(
                    is_valid=True, variable_count=0, checks=formula_checks, issues=[]
                ),
            )
            fragment["variables"]["branch_override"] = True
            return fragment

        result = validate_variable_set(effective)
        issues = list(result.issues)
        allowed_scope = self._branch_scope_for_bindings(parent_run, payload.decomposition_branch)
        if allowed_scope is not None:
            issues.extend(validate_scope_bindings(allowed_scope, effective))
        if issues:
            raise VariableValidationError(
                VariableValidationResult(
                    is_valid=False,
                    variable_count=result.variable_count,
                    checks=result.checks,
                    issues=issues,
                )
            )
        fragment = variables_configuration_fragment(template, effective, result)
        fragment["variables"]["branch_override"] = True
        if payload.decomposition_branch is not None:
            fragment["variables"]["decomposition_branch"] = payload.decomposition_branch
        return fragment

    def _branch_scope_for_bindings(
        self,
        parent_run: SimulationRun,
        decomposition_branch: str | None,
    ) -> list[str] | None:
        """Scope tags the branch's variables must stay inside.

        With a named branch: that branch's scope (the parent must carry a
        decomposition and the path must resolve). Without one: the parent
        decomposition's root scope, or None when the parent carries no
        decomposition (no scope check).
        """
        mece_fragment = (parent_run.configuration or {}).get("mece")
        if not isinstance(mece_fragment, dict) or not isinstance(
            mece_fragment.get("decomposition"), dict
        ):
            if decomposition_branch is not None:
                raise ValueError(
                    "decomposition_branch requires the parent run to carry a decomposition."
                )
            return None
        tree = DecompositionTree.model_validate(mece_fragment["decomposition"])
        if decomposition_branch is None:
            return list(tree.root.scope)
        branch = find_branch_by_path(tree, decomposition_branch)
        if branch is None:
            raise ValueError(
                f"Decomposition branch {decomposition_branch!r} was not found in the "
                "parent run's decomposition tree."
            )
        return list(branch.scope)

    async def create_scenario_run(
        self,
        session: AsyncSession,
        parent_run_id: str,
        payload: ScenarioRunCreate,
    ) -> ScenarioBranchRecord:
        parent_run = await session.get(SimulationRun, parent_run_id)
        if parent_run is None:
            raise LookupError(f"Simulation run {parent_run_id} was not found.")
        if parent_run.status != SimulationRunStatus.COMPLETED.value:
            raise ValueError("Scenario branching requires a completed baseline run.")
        if parent_run.domain_id == "military":
            if parent_run.force_id is None:
                raise ValueError(
                    "Military scenario branching requires a force-backed baseline run."
                )
        elif parent_run.domain_id in ("corporate", "automotive"):
            if parent_run.company_id is None:
                raise ValueError(
                    f"{parent_run.domain_id.capitalize()} scenario branching requires a company-backed baseline run."
                )
        else:
            raise ValueError(
                f"Scenario branching is not implemented for domain {parent_run.domain_id}."
            )

        # Branch-level variable bindings (Sprint 3): resolved before any
        # row is written, so an invalid override refuses the branch.
        variables_fragment = await self._resolve_scenario_variable_bindings(
            session, parent_run, payload
        )

        fork_step = payload.fork_step or max(1, parent_run.tick_count // 2)
        source_snapshot = (
            await session.scalars(
                select(StateSnapshotRecord)
                .where(
                    and_(
                        StateSnapshotRecord.run_id == parent_run.id,
                        StateSnapshotRecord.tick == fork_step,
                    )
                )
                .limit(1)
            )
        ).first()
        if source_snapshot is None:
            raise LookupError(
                f"No state snapshot found at fork step {fork_step} for run {parent_run.id}."
            )

        scenario_id = generate_id()
        execution_mode = (
            parent_run.execution_mode
            if parent_run.execution_mode in {ExecutionMode.INLINE.value, ExecutionMode.QUEUED.value}
            else ExecutionMode.INLINE.value
        )
        remaining_ticks = max(1, parent_run.tick_count - fork_step)
        child_tick_count = payload.tick_count or remaining_ticks
        child_configuration = {
            **parent_run.configuration,
            "initial_state": {
                **source_snapshot.state,
                **{key: float(value) for key, value in payload.state_overrides.items()},
            },
            "scenario": {
                "id": scenario_id,
                "fork_step": fork_step,
                "assumptions": payload.assumptions,
                "decision_deltas": payload.decision_deltas,
                "state_overrides": payload.state_overrides,
                "probability_band": payload.probability_band,
                # Arm resampling (fix/arm-resample): when true, the
                # executor lets this run's own seeded sampled values
                # win over the inherited fork-snapshot initial state
                # for the state fields they cover (see _execute_run).
                # Stored here so Monte Carlo trials and replays of
                # the child inherit it with the configuration copy.
                "resample_variables": payload.resample_variables,
            },
            "military_use_mode": parent_run.military_use_mode,
        }
        if variables_fragment:
            # Branch override replaces the inherited variables fragment.
            child_configuration["variables"] = variables_fragment["variables"]
        # Sprint 3: hash the child run's inputs at creation. The parent's
        # stored determinism fragment is excluded from the hashed payload,
        # so the child hash covers the child's own inputs.
        child_configuration["determinism"] = determinism_input_fragment(
            domain_id=parent_run.domain_id,
            actor_template=parent_run.actor_template,
            tick_count=child_tick_count,
            seed=parent_run.seed,
            company_id=parent_run.company_id,
            force_id=parent_run.force_id,
            tenant_id=parent_run.tenant_id,
            preset_id=parent_run.preset_id,
            configuration=child_configuration,
        )
        run = SimulationRun(
            company_id=parent_run.company_id,
            force_id=parent_run.force_id,
            tenant_id=parent_run.tenant_id,
            preset_id=parent_run.preset_id,
            domain_id=parent_run.domain_id,
            actor_template=parent_run.actor_template,
            military_use_mode=parent_run.military_use_mode,
            parent_run_id=parent_run.id,
            execution_mode=execution_mode,
            status=SimulationRunStatus.PENDING.value,
            tick_count=child_tick_count,
            seed=parent_run.seed,
            configuration=child_configuration,
            summary={"scenario_id": scenario_id},
        )
        session.add(run)
        await session.flush()
        if parent_run.domain_id == "military":
            await self._clone_geo_assets_for_scenario(session, parent_run.id, run)

        branch = ScenarioBranchRecord(
            id=scenario_id,
            run_id=run.id,
            parent_run_id=parent_run.id,
            fork_step=fork_step,
            assumptions=payload.assumptions,
            decision_deltas=payload.decision_deltas,
            kpi_trajectory=[],
            probability_band=payload.probability_band,
            notable_events=[],
            evidence_summary=self._build_evidence_summary(parent_run),
        )
        session.add(branch)
        await session.flush()
        parent_run.summary = {
            **parent_run.summary,
            "scenario_branch_ids": sorted(
                {*(parent_run.summary.get("scenario_branch_ids", [])), branch.id}
            ),
        }

        if execution_mode == ExecutionMode.INLINE.value:
            await self._execute_run(session, run)
            await self._refresh_scenario_branch(session, branch, parent_run, run)
            await self._generate_report(session, run)

        await session.commit()
        try:
            await session.refresh(branch)
        except Exception:
            # The commit above already persisted the branch: a refresh
            # failure must not strand it as an unreported orphan.
            # Best-effort cleanup, then the original failure surfaces.
            try:
                await self.delete_scenario_branch(session, scenario_id)
            except Exception:  # noqa: BLE001, S110 — cleanup must not mask the refresh error
                pass
            raise
        return branch

    async def delete_scenario_branch(self, session: AsyncSession, scenario_id: str) -> bool:
        """Delete one scenario branch and its child run, restoring pre-branch state.

        Removes ONLY the named branch: its child run and every row
        branch execution created for that child, in foreign-key
        order (no ``ON DELETE`` cascades exist anywhere, so the
        order is what keeps this valid on Postgres). The parent
        run itself is untouched apart from dropping the branch id
        from its ``scenario_branch_ids`` summary list. Returns
        ``True`` when a branch was deleted, ``False`` when no such
        branch exists (already deleted: idempotent). The deletion
        commits, so it survives the caller's rollback.

        Scope is exactly what :meth:`create_scenario_run` writes
        for a fresh branch: snapshots, decision records, external
        shocks, the generated report, geo-asset clones (military),
        decision options, hypotheses, prediction series/versions,
        and the calibration context. Rows other flows may attach
        later (evidence links, replay packages) are NOT deleted:
        if one blocks the deletion, the failure surfaces and the
        branch survives for explicit human cleanup. Event-archive
        rows and bus emissions are append-only audit side effects
        and are deliberately left in place.
        """
        branch = await session.get(ScenarioBranchRecord, scenario_id)
        if branch is None:
            return False
        child_id = branch.run_id
        parent_id = branch.parent_run_id

        series_ids = list(
            (
                await session.scalars(
                    select(PredictionSeries.id).where(
                        PredictionSeries.source_run_id == child_id
                    )
                )
            ).all()
        )
        if series_ids:
            # Versions hang off their series; hypotheses point at
            # versions, so versions go before both.
            await session.execute(
                delete(PredictionVersion).where(PredictionVersion.series_id.in_(series_ids))
            )
            await session.execute(
                delete(PredictionSeries).where(PredictionSeries.id.in_(series_ids))
            )
        await session.execute(delete(Hypothesis).where(Hypothesis.run_id == child_id))
        await session.execute(delete(DecisionOption).where(DecisionOption.run_id == child_id))
        await session.execute(
            delete(PredictionCalibrationContext).where(
                PredictionCalibrationContext.run_id == child_id
            )
        )
        await session.execute(delete(GeneratedReport).where(GeneratedReport.run_id == child_id))
        await session.execute(
            delete(StateSnapshotRecord).where(StateSnapshotRecord.run_id == child_id)
        )
        await session.execute(
            delete(DecisionRecordRecord).where(DecisionRecordRecord.run_id == child_id)
        )
        await session.execute(
            delete(ExternalShockRecord).where(ExternalShockRecord.run_id == child_id)
        )
        await session.execute(delete(GeoAssetRecord).where(GeoAssetRecord.run_id == child_id))
        await session.execute(
            delete(ScenarioBranchRecord).where(ScenarioBranchRecord.id == scenario_id)
        )
        await session.execute(delete(SimulationRun).where(SimulationRun.id == child_id))

        parent = await session.get(SimulationRun, parent_id)
        if parent is not None:
            branch_ids = parent.summary.get("scenario_branch_ids", [])
            if scenario_id in branch_ids:
                parent.summary = {
                    **parent.summary,
                    "scenario_branch_ids": [
                        kept for kept in branch_ids if kept != scenario_id
                    ],
                }
        await session.commit()
        return True

    async def get_scenario_branch(
        self,
        session: AsyncSession,
        scenario_id: str,
    ) -> ScenarioBranchRecord | None:
        return await session.get(ScenarioBranchRecord, scenario_id)

    async def build_scenario_compare(
        self,
        session: AsyncSession,
        run_id: str,
    ) -> dict[str, Any]:
        run = await session.get(SimulationRun, run_id)
        if run is None:
            raise LookupError(f"Simulation run {run_id} was not found.")

        baseline_run = run
        if run.parent_run_id is not None:
            parent_run = await session.get(SimulationRun, run.parent_run_id)
            if parent_run is not None:
                baseline_run = parent_run

        branch_records = list(
            (
                await session.scalars(
                    select(ScenarioBranchRecord)
                    .where(ScenarioBranchRecord.parent_run_id == baseline_run.id)
                    .order_by(ScenarioBranchRecord.created_at.asc())
                )
            ).all()
        )
        baseline_state_record = await self._load_latest_state(session, baseline_run.id)
        baseline_final_state = (
            {key: float(value) for key, value in baseline_state_record.state.items()}
            if baseline_state_record is not None
            else {}
        )
        baseline_report = await self._latest_run_report(session, baseline_run.id)
        metric_names = sorted(
            {
                metric["metric"]
                for branch in branch_records
                for metric in branch.kpi_trajectory
                if "metric" in metric
            }
            | set(baseline_final_state.keys())
        )
        subject_name = await self._scenario_subject_name(session, baseline_run)
        branches: list[dict[str, Any]] = []
        best_branch_id: str | None = None
        best_branch_score = 0.0
        for branch in branch_records:
            branch_run = await session.get(SimulationRun, branch.run_id)
            branch_report = await self.latest_scenario_report(session, branch.id)
            branch_final_state = (
                {
                    key: float(value)
                    for key, value in (
                        branch_run.summary.get("final_state", {}) if branch_run is not None else {}
                    ).items()
                }
                if branch_run is not None
                else {}
            )
            # Sprint 2: compare against the baseline run's effective
            # policies (template-overlaid when the baseline carries one).
            # Child runs inherit the parent's variables fragment via the
            # configuration copy in create_scenario_run.
            effective_policies = resolve_policies(
                baseline_run.domain_id, baseline_run.configuration
            )
            branch_score = score_branch_delta(
                baseline_run.domain_id,
                baseline_final_state,
                branch_final_state,
                effective_policies,
            )
            key_deltas = summarize_branch_trajectory(
                baseline_run.domain_id,
                branch.kpi_trajectory,
                effective_policies,
            )
            recommendation_summary = self._report_recommendations(branch_report)
            if branch_score > best_branch_score:
                best_branch_score = branch_score
                best_branch_id = branch.id
            branches.append(
                {
                    "branch_id": branch.id,
                    "run_id": branch.run_id,
                    "fork_step": branch.fork_step,
                    "probability_band": branch.probability_band,
                    "assumptions": branch.assumptions,
                    "decision_deltas": branch.decision_deltas,
                    "notable_events": branch.notable_events,
                    "kpi_trajectory": branch.kpi_trajectory,
                    "matched_rules": branch_run.summary.get("matched_rules", [])
                    if branch_run is not None
                    else [],
                    "report_id": branch_report.id if branch_report is not None else None,
                    "final_state": branch_final_state,
                    "branch_score": round(branch_score, 4),
                    "key_deltas": key_deltas,
                    "recommendation_summary": recommendation_summary,
                    "debate_suggestion": {
                        "run_id": branch.run_id,
                        "topic": f"Should {subject_name} adopt scenario branch {branch.id} over the baseline plan?",
                        "trigger_type": "branch_evaluation",
                        "target_type": "branch",
                        "target_id": branch.id,
                        "context_lines": [
                            *(
                                key_deltas[:2]
                                or ["Compare this branch against the baseline outcome."]
                            ),
                            *recommendation_summary[:1],
                        ],
                    },
                }
            )
        summary = build_scenario_compare_summary(
            baseline_run.domain_id,
            branches,
            best_branch_id,
            best_branch_score,
        )
        return {
            "baseline_run_id": baseline_run.id,
            "domain_id": baseline_run.domain_id,
            "branch_count": len(branches),
            "metric_names": metric_names,
            "baseline_final_state": baseline_final_state,
            "baseline_report_id": baseline_report.id if baseline_report is not None else None,
            "baseline_recommendations": self._report_recommendations(baseline_report),
            "recommended_branch_id": best_branch_id if best_branch_score > 0.08 else None,
            "summary": summary,
            "branches": branches,
        }

    async def _scenario_subject_name(
        self,
        session: AsyncSession,
        run: SimulationRun,
    ) -> str:
        if run.company_id is not None:
            company = await session.get(CompanyProfile, run.company_id)
            if company is not None:
                return company.name
        if run.force_id is not None:
            force = await session.get(ForceProfile, run.force_id)
            if force is not None:
                return force.name
        return self._subject_id(run)

    async def _refresh_scenario_branch(
        self,
        session: AsyncSession,
        branch: ScenarioBranchRecord,
        parent_run: SimulationRun,
        branch_run: SimulationRun,
    ) -> None:
        parent_final = await self._load_latest_state(session, parent_run.id)
        branch_final = await self._load_latest_state(session, branch_run.id)
        if branch_final is None:
            return

        branch.kpi_trajectory = build_branch_trajectory(
            branch_run.domain_id,
            parent_final.state if parent_final is not None else {},
            branch_final.state,
        )
        shocks = await self.list_external_shocks(session, branch_run.id)
        branch.notable_events = [shock.summary for shock in shocks[:3]] or [
            f"Scenario matched {rule_id}"
            for rule_id in branch_run.summary.get("matched_rules", [])[:3]
        ]
        if not branch.decision_deltas:
            branch.decision_deltas = await self._derive_decision_deltas(
                session,
                parent_run.id,
                branch_run.id,
                branch.fork_step,
            )
        branch.evidence_summary = self._build_evidence_summary(branch_run)

    async def _load_latest_state(
        self,
        session: AsyncSession,
        run_id: str,
    ) -> StateSnapshotRecord | None:
        return (
            await session.scalars(
                select(StateSnapshotRecord)
                .where(StateSnapshotRecord.run_id == run_id)
                .order_by(StateSnapshotRecord.tick.desc())
                .limit(1)
            )
        ).first()

    async def _derive_decision_deltas(
        self,
        session: AsyncSession,
        parent_run_id: str,
        branch_run_id: str,
        fork_step: int,
    ) -> list[str]:
        parent_records = list(
            (
                await session.scalars(
                    select(DecisionRecordRecord)
                    .where(
                        and_(
                            DecisionRecordRecord.run_id == parent_run_id,
                            DecisionRecordRecord.tick > fork_step,
                        )
                    )
                    .order_by(DecisionRecordRecord.tick.asc())
                )
            ).all()
        )
        branch_records = list(
            (
                await session.scalars(
                    select(DecisionRecordRecord)
                    .where(DecisionRecordRecord.run_id == branch_run_id)
                    .order_by(DecisionRecordRecord.tick.asc())
                )
            ).all()
        )
        deltas: list[str] = []
        for index, branch_record in enumerate(branch_records):
            parent_action = parent_records[index].action_id if index < len(parent_records) else None
            if branch_record.action_id != parent_action:
                baseline_action = parent_action or "no baseline action"
                deltas.append(
                    f"Tick {branch_record.tick}: scenario chose {branch_record.action_id} instead of {baseline_action}."
                )
        return deltas or ["Scenario followed the baseline action sequence after the fork point."]

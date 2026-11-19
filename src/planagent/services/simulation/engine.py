from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import logging
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from planagent.domain.api import SimulationRunCreate
from planagent.domain.enums import ClaimStatus, EventTopic, ExecutionMode, SimulationRunStatus
from planagent.domain.models import (
    Claim,
    DecisionRecordRecord,
    EventArchive,
    ExternalShockRecord,
    GeneratedReport,
    ScenarioBranchRecord,
    SimulationRun,
    StateSnapshotRecord,
    utc_now,
)
from planagent.services.calibration import (
    CUTOFF_SOURCE_CREATION_TIME,
    CUTOFF_SOURCE_EXPLICIT,
    firewall_configuration_fragment,
    firewall_cutoff_from_configuration,
    format_cutoff,
)
from planagent.services.distributions import (
    determinism_input_fragment,
    resolve_run_values,
    state_hash,
    tick_driver_formulas,
)
from planagent.services.mece import MeceValidationResult, validate_or_raise
from planagent.services.splits.models import SplitValidationIssue, SplitValidationResult
from planagent.services.splits.validator import (
    SplitValidationError,
    validate_oem_shares,
    validate_or_raise as validate_split_or_raise,
)
from planagent.services.startup import normalize_tenant_id, startup_preset_config
from planagent.services.variables.formulas import evaluate_tick_drivers, validate_formulas
from planagent.services.variables.models import VariableSet, VariableValidationResult
from planagent.services.variables.opportunities import (
    BreakoutPrompt,
    KeyOpportunityPrompt,
    detect_creation_prompts,
)
from planagent.services.variables.presets import (
    CONFIGURATION_KEY,
    resolve_policies,
    resolve_state_defaults,
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
from planagent.simulation.domain_packs import registry
from .impact import _DECISION_EVIDENCE_WINDOW

_SIMULATION_PUBLIC_ERROR = "Simulation execution failed"
_logger = logging.getLogger(__name__)


def _mece_configuration_fragment(
    payload: SimulationRunCreate,
    mece_result: MeceValidationResult | None,
) -> dict[str, Any]:
    """Audit-trail fragment for a validated decomposition.

    Stored inside ``SimulationRun.configuration`` (existing JSON column),
    so no schema migration is needed. Returns {} when no decomposition
    was attached.
    """
    if mece_result is None or payload.decomposition is None:
        return {}
    return {
        "mece": {
            "decomposition": payload.decomposition.model_dump(mode="json"),
            "validation": mece_result.model_dump(mode="json"),
        }
    }


def _split_configuration_fragment(
    payload: SimulationRunCreate,
    split_result: SplitValidationResult | None,
) -> dict[str, Any]:
    """Audit-trail fragment for a validated split structure.

    Stored inside ``SimulationRun.configuration`` (existing JSON column),
    so no schema migration is needed. Returns {} when no split structure
    was attached. Mirrors :func:`_mece_configuration_fragment`.
    """
    if split_result is None or payload.split_structure is None:
        return {}
    fragment: dict[str, Any] = {
        "structure": payload.split_structure.model_dump(mode="json"),
        "validation": split_result.model_dump(mode="json"),
    }
    if payload.oem_production_shares is not None:
        # Stored OEM mix (S-layer real splits): the shares are run
        # inputs, so they live in the fragment beside the structure and
        # enter the Sprint 3 input hash with it.
        fragment["oem_production_shares"] = payload.oem_production_shares.model_dump(
            mode="json"
        )
    return {"split_structure": fragment}


def _firewall_configuration_fragment(payload: SimulationRunCreate) -> dict[str, Any]:
    """Hindsight-firewall fragment for a run under creation (Sprint 5).

    An explicit ``decision_time`` is recorded as supplied; otherwise the
    cutoff defaults to the run's creation time — evidence available
    when the decision was made. The fragment is part of the run
    configuration, so the Sprint 3 input hash covers it and replays
    reproduce the same evidence set.
    """
    if payload.decision_time is not None:
        return firewall_configuration_fragment(payload.decision_time, CUTOFF_SOURCE_EXPLICIT)
    return firewall_configuration_fragment(utc_now(), CUTOFF_SOURCE_CREATION_TIME)


def _creation_prompts(
    variables_fragment: dict[str, Any],
    tick_count: int,
) -> tuple[list[KeyOpportunityPrompt], list[BreakoutPrompt]]:
    """Creation-time prompts from the effective variable bindings.

    Reconstructs the effective VariableSet from the bindings fragment
    (template + inline already merged by ``_resolve_variable_bindings``)
    and runs the decision-time checks: discounted-growth prompts + T1.
    Returns ([], []) when no variable set is attached. A prompt
    computation must never fail run creation — the prompts are advisory
    and the bindings were validated moments earlier — so an unexpected
    failure logs a warning and returns empty lists.
    """

    try:
        fragment = variables_fragment.get(CONFIGURATION_KEY)
        bindings = fragment.get("bindings") if isinstance(fragment, dict) else None
        if not isinstance(bindings, dict):
            return [], []
        effective = VariableSet.model_validate(bindings)
        return detect_creation_prompts(effective.variables, tick_count)
    except Exception:  # noqa: BLE001 - advisory prompts must not block runs
        _logger.warning("creation-prompt detection failed; continuing without prompts")
        return [], []


class SimulationEngineMixin:
    async def run_simulation(self, session: AsyncSession, run: SimulationRun) -> None:
        await self._execute_run(session, run)

    async def _execute_scenario(self, session: AsyncSession, run: SimulationRun) -> None:
        await self._execute_run(session, run)

    async def _resolve_variable_bindings(
        self,
        session: AsyncSession,
        payload: SimulationRunCreate,
    ) -> dict[str, Any]:
        """Variable gate (Sprint 2, PRD deltas D2/D3).

        Resolves the attached template (if any), merges the template's
        variable set with an inline set (inline wins per variable id),
        validates the effective set, and cross-checks variable scope tags
        against the decomposition scope when both are attached. Raises
        :class:`VariableTemplateError` or :class:`VariableValidationError`
        before any row is written, mirroring the MECE gate. Returns the
        ``variables`` configuration fragment, or {} when nothing is attached.
        """
        template = None
        if payload.variable_template_id is not None:
            template = await get_variable_template(session, payload.variable_template_id)
            if template is None:
                raise VariableTemplateError(
                    "variable_template_not_found",
                    f"Variable template {payload.variable_template_id!r} was not found.",
                )
            if template.domain_id != payload.domain_id:
                raise VariableTemplateError(
                    "variable_template_domain_mismatch",
                    f"Variable template {template.id!r} belongs to domain "
                    f"{template.domain_id!r}, not {payload.domain_id!r}.",
                )
        base_set: VariableSet | None = None
        if template is not None:
            base_set = VariableSet(
                name=template.name,
                variables=template.variables,
                formulas=template.formulas,
                internal=template.internal,
                assumption_data=template.assumption_data,
            )
        inline_set = payload.variable_set
        if base_set is not None and inline_set is not None:
            effective = merge_variable_sets(base_set, inline_set)
        elif base_set is not None:
            effective = base_set
        elif inline_set is not None:
            effective = inline_set
        else:
            return {}
        if not effective.variables and inline_set is None:
            # A template with no variables and no inline set: snapshot the
            # template (its state defaults and policies still apply) without
            # bindings or a validation result — unless the template carries
            # formulas, which need stored bindings to evaluate at runtime.
            # The empty-set rule does not apply to template-only sets, so
            # only the formulas are validated here.
            if not effective.formulas:
                return variables_configuration_fragment(template, None, None)
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
            return variables_configuration_fragment(
                template,
                effective,
                VariableValidationResult(
                    is_valid=True, variable_count=0, checks=formula_checks, issues=[]
                ),
            )
        result = validate_variable_set(effective)
        issues = list(result.issues)
        if payload.decomposition is not None:
            issues.extend(validate_scope_bindings(payload.decomposition.root.scope, effective))
        if issues:
            raise VariableValidationError(
                VariableValidationResult(
                    is_valid=False,
                    variable_count=result.variable_count,
                    checks=result.checks,
                    issues=issues,
                )
            )
        return variables_configuration_fragment(template, effective, result)

    async def create_simulation_run(
        self,
        session: AsyncSession,
        payload: SimulationRunCreate,
    ) -> SimulationRun:
        # MECE gate (Sprint 1, PRD delta D1): an attached decomposition
        # that fails validation refuses run creation entirely — no run
        # row is written, no ticks execute, no bypass exists.
        mece_result: MeceValidationResult | None = None
        if payload.decomposition is not None:
            mece_result = validate_or_raise(payload.decomposition)
        # Variable gate (Sprint 2, PRD deltas D2/D3): resolves the attached
        # template and bindings; invalid bindings refuse run creation.
        variables_fragment = await self._resolve_variable_bindings(session, payload)
        # Split gate (Phase 1, automotive track): an attached split
        # structure that fails validation refuses run creation entirely —
        # no run row is written, mirroring the MECE/variables gates.
        # Split structures are automotive-only.
        split_result: SplitValidationResult | None = None
        if payload.split_structure is not None:
            if payload.domain_id != "automotive":
                raise SplitValidationError(
                    SplitValidationResult(
                        is_valid=False,
                        issues=[
                            SplitValidationIssue(
                                kind="split_structure_requires_automotive_domain",
                                message=(
                                    "Split structures are only supported for automotive "
                                    f"runs; domain is {payload.domain_id!r}."
                                ),
                            )
                        ],
                    )
                )
            split_result = validate_split_or_raise(payload.split_structure)
        # Stored OEM-shares gate (S-layer real splits): shares without a
        # structure are meaningless, and shares that do not cover exactly
        # the structure's OEMs (or do not sum to 1) refuse run creation
        # entirely — no run row is written, mirroring the split gate.
        if payload.oem_production_shares is not None:
            if payload.split_structure is None:
                raise SplitValidationError(
                    SplitValidationResult(
                        is_valid=False,
                        issues=[
                            SplitValidationIssue(
                                kind="oem_shares_require_split_structure",
                                message=(
                                    "OEM production shares require an attached "
                                    "split structure; the shares cover the "
                                    "structure's OEMs."
                                ),
                            )
                        ],
                    )
                )
            share_issues = validate_oem_shares(
                payload.split_structure, payload.oem_production_shares
            )
            if share_issues:
                raise SplitValidationError(
                    SplitValidationResult(is_valid=False, issues=share_issues)
                )
        execution_mode = payload.execution_mode or (
            ExecutionMode.INLINE
            if self.settings.inline_simulation_default
            else ExecutionMode.QUEUED
        )
        if payload.domain_id == "corporate":
            run = await self._create_corporate_run(
                session, payload, execution_mode, mece_result, variables_fragment
            )
        elif payload.domain_id == "military":
            run = await self._create_military_run(
                session, payload, execution_mode, mece_result, variables_fragment
            )
        elif payload.domain_id == "automotive":
            run = await self._create_automotive_run(
                session,
                payload,
                execution_mode,
                mece_result,
                variables_fragment,
                split_result,
            )
        else:
            raise ValueError(f"Domain {payload.domain_id} is not implemented yet.")

        if execution_mode == ExecutionMode.INLINE:
            await self._execute_run(session, run)
            await self._generate_report(session, run)

        await session.commit()
        await session.refresh(run)
        # Phase 4, Track 9 — report-time opportunity / breakout prompts.
        # Pure functions over the effective variable set: they change no
        # numbers and never touch the simulation. Attached transiently
        # (not a column, not in the input hash); the creation route copies
        # them onto the response. Set AFTER refresh() so the refresh
        # cannot drop the transient attributes.
        key_opportunities, breakout_prompts = _creation_prompts(
            variables_fragment, run.tick_count
        )
        run.key_opportunities = key_opportunities
        run.breakout_prompts = breakout_prompts
        return run

    async def process_queued_runs(
        self,
        session: AsyncSession,
        limit: int = 10,
        worker_id: str | None = None,
    ) -> int:
        runs = await self._claim_simulation_runs(
            session,
            limit=limit,
            worker_id=worker_id or "simulation-worker",
        )
        processed = 0
        for run in runs:
            try:
                await self._execute_run(session, run)
                branch = (
                    await session.scalars(
                        select(ScenarioBranchRecord).where(ScenarioBranchRecord.run_id == run.id)
                    )
                ).first()
                if branch is not None and run.parent_run_id is not None:
                    parent_run = await session.get(SimulationRun, run.parent_run_id)
                    if parent_run is not None:
                        await self._refresh_scenario_branch(session, branch, parent_run, run)
                run.last_error = None
                processed += 1
            except Exception:
                _logger.exception("Queued simulation failed: run_id=%s", run.id)
                run.last_error = _SIMULATION_PUBLIC_ERROR
                run.status = (
                    SimulationRunStatus.FAILED.value
                    if run.processing_attempts >= self.settings.worker_max_attempts
                    else SimulationRunStatus.PENDING.value
                )
            finally:
                run.lease_owner = None
                run.lease_expires_at = None
                run.updated_at = utc_now()
        await session.commit()
        return processed

    async def _create_corporate_run(
        self,
        session: AsyncSession,
        payload: SimulationRunCreate,
        execution_mode: ExecutionMode,
        mece_result: MeceValidationResult | None = None,
        variables_fragment: dict[str, Any] | None = None,
    ) -> SimulationRun:
        company = await self._upsert_company(session, payload)
        tick_count = payload.tick_count or self.settings.default_corporate_ticks
        configuration = {
            "initial_state": payload.initial_state,
            "market": payload.market,
            **startup_preset_config(payload.tenant_id, payload.preset_id),
            **_mece_configuration_fragment(payload, mece_result),
            **(variables_fragment or {}),
            **_firewall_configuration_fragment(payload),
        }
        # Sprint 3: hash the run inputs at creation (determinism audit trail).
        configuration["determinism"] = determinism_input_fragment(
            domain_id="corporate",
            actor_template=payload.actor_template,
            tick_count=tick_count,
            seed=payload.seed,
            company_id=company.id,
            force_id=None,
            tenant_id=normalize_tenant_id(payload.tenant_id),
            preset_id=payload.preset_id,
            configuration=configuration,
        )
        run = SimulationRun(
            company_id=company.id,
            force_id=None,
            tenant_id=normalize_tenant_id(payload.tenant_id),
            preset_id=payload.preset_id,
            domain_id="corporate",
            actor_template=payload.actor_template,
            military_use_mode=None,
            execution_mode=execution_mode.value,
            status=SimulationRunStatus.PENDING.value,
            tick_count=tick_count,
            seed=payload.seed,
            configuration=configuration,
            summary={},
        )
        session.add(run)
        await session.flush()
        return run

    async def _create_military_run(
        self,
        session: AsyncSession,
        payload: SimulationRunCreate,
        execution_mode: ExecutionMode,
        mece_result: MeceValidationResult | None = None,
        variables_fragment: dict[str, Any] | None = None,
    ) -> SimulationRun:
        force = await self._upsert_force(session, payload)
        military_use_mode = payload.military_use_mode or "full_domain"
        tick_count = payload.tick_count or self.settings.default_military_ticks
        configuration = {
            "initial_state": payload.initial_state,
            "theater": payload.theater or force.theater,
            "military_use_mode": military_use_mode,
            "simulation_only": True,
            **startup_preset_config(payload.tenant_id, payload.preset_id),
            **_mece_configuration_fragment(payload, mece_result),
            **(variables_fragment or {}),
            **_firewall_configuration_fragment(payload),
        }
        # Sprint 3: hash the run inputs at creation (determinism audit trail).
        configuration["determinism"] = determinism_input_fragment(
            domain_id="military",
            actor_template=payload.actor_template,
            tick_count=tick_count,
            seed=payload.seed,
            company_id=None,
            force_id=force.id,
            tenant_id=normalize_tenant_id(payload.tenant_id),
            preset_id=payload.preset_id,
            configuration=configuration,
        )
        run = SimulationRun(
            company_id=None,
            force_id=force.id,
            tenant_id=normalize_tenant_id(payload.tenant_id),
            preset_id=payload.preset_id,
            domain_id="military",
            actor_template=payload.actor_template,
            military_use_mode=military_use_mode,
            execution_mode=execution_mode.value,
            status=SimulationRunStatus.PENDING.value,
            tick_count=tick_count,
            seed=payload.seed,
            configuration=configuration,
            summary={},
        )
        session.add(run)
        await session.flush()
        if military_use_mode == "full_domain":
            session.add(
                EventArchive(
                    topic="military.full_domain.audit",
                    payload={
                        "run_id": run.id,
                        "force_id": force.id,
                        "tenant_id": run.tenant_id,
                        "simulation_only": True,
                        "military_use_mode": military_use_mode,
                    },
                )
            )
        await self._ensure_geo_assets_for_run(session, run, force)
        return run

    async def _create_automotive_run(
        self,
        session: AsyncSession,
        payload: SimulationRunCreate,
        execution_mode: ExecutionMode,
        mece_result: MeceValidationResult | None = None,
        variables_fragment: dict[str, Any] | None = None,
        split_result: SplitValidationResult | None = None,
    ) -> SimulationRun:
        # Automotive runs reuse the company subject (the OEM or Tier-1
        # supplier under simulation), mirroring _create_corporate_run,
        # plus the validated split-structure fragment. Tick = 1 month.
        company = await self._upsert_company(session, payload)
        tick_count = payload.tick_count or self.settings.default_automotive_ticks
        configuration = {
            "initial_state": payload.initial_state,
            "market": payload.market,
            **startup_preset_config(payload.tenant_id, payload.preset_id),
            **_mece_configuration_fragment(payload, mece_result),
            **(variables_fragment or {}),
            **_split_configuration_fragment(payload, split_result),
            **_firewall_configuration_fragment(payload),
        }
        # Sprint 3: hash the run inputs at creation (determinism audit trail).
        configuration["determinism"] = determinism_input_fragment(
            domain_id="automotive",
            actor_template=payload.actor_template,
            tick_count=tick_count,
            seed=payload.seed,
            company_id=company.id,
            force_id=None,
            tenant_id=normalize_tenant_id(payload.tenant_id),
            preset_id=payload.preset_id,
            configuration=configuration,
        )
        run = SimulationRun(
            company_id=company.id,
            force_id=None,
            tenant_id=normalize_tenant_id(payload.tenant_id),
            preset_id=payload.preset_id,
            domain_id="automotive",
            actor_template=payload.actor_template,
            military_use_mode=None,
            execution_mode=execution_mode.value,
            status=SimulationRunStatus.PENDING.value,
            tick_count=tick_count,
            seed=payload.seed,
            configuration=configuration,
            summary={},
        )
        session.add(run)
        await session.flush()
        return run

    async def _execute_run(self, session: AsyncSession, run: SimulationRun) -> None:
        run.status = SimulationRunStatus.PROCESSING.value
        run.updated_at = utc_now()

        pack = registry.get(run.domain_id)
        # Sprint 2: a run carrying a variable template starts from the
        # template's state defaults and scores against its policies.
        template_defaults = resolve_state_defaults(run.domain_id, run.configuration)
        initial_state = self._resolve_initial_state(
            pack, run.actor_template, state_defaults=template_defaults
        )
        # Sprint 3: sample the run's bound variables once, from the run
        # seed. Sprint 4: evaluate the formula graph over the sampled
        # values (post-lever). Sampled and derived values whose id matches
        # a state field override that field's initial value; the explicit
        # initial_state overlay below keeps precedence over both — except
        # on an arm-resampling branch child (see below), where the sampled
        # values win back precedence for the fields they cover. Runs
        # without bindings sample nothing and behave exactly as before.
        sampled_values, derived_values, applied_values = resolve_run_values(
            run.configuration, run.seed, set(initial_state)
        )
        initial_state.update(applied_values)
        initial_state.update(
            {key: float(value) for key, value in run.configuration.get("initial_state", {}).items()}
        )
        # Arm resampling (fix/arm-resample): a scenario-branch child
        # created with resample_variables re-draws its non-pinned
        # variables from their own distributions, deterministically
        # from the run seed, and the re-drawn values take precedence
        # over the inherited fork-snapshot initial state — for exactly
        # the state fields the sampled/derived values cover. Without
        # this, the overlay above discards every re-draw (the fork
        # snapshot is identical for all Monte Carlo trials of the
        # child) and the arm ensemble collapses to a degenerate point
        # estimate whenever every remaining driver variable is pinned
        # FIXED. Pinned overrides are unaffected: a FIXED variable
        # samples at exactly its pinned value, so it still lands here
        # verbatim. Every other forked state field keeps the snapshot
        # value. Default off (no ``scenario`` fragment, or the flag
        # absent/false): existing runs behave exactly as before. The
        # flag travels with the configuration copy, so Monte Carlo
        # trials and replays of a resampling child resample too.
        scenario_fragment = run.configuration.get("scenario")
        if isinstance(scenario_fragment, dict) and scenario_fragment.get("resample_variables"):
            initial_state.update(applied_values)
        # Phase 1: the per-tick variable scope. Sampled + initial derived
        # values are fixed for the run; tick drivers evaluate against
        # this scope overlaid with the current state, and variable-scaled
        # rule effects read it at selection time. Runs without bindings
        # get an empty scope and behave exactly as before.
        variable_scope = {**sampled_values, **derived_values}
        driver_formulas = tick_driver_formulas(run.configuration)
        state_field_names = {field.name for field in pack.state_fields}
        effective_policies = resolve_policies(run.domain_id, run.configuration)
        # Sprint 5: hindsight firewall — resolve the decision-time cutoff
        # from the run's stored configuration and filter claim reads to
        # evidence ingested at or before it. Runs without a fragment
        # (pre-Sprint-5 rows, direct construction) keep the legacy
        # unfiltered reads; a malformed fragment fails loudly rather
        # than silently leaking hindsight.
        firewall_cutoff, firewall_source = firewall_cutoff_from_configuration(run.configuration)
        claims = await self._fetch_relevant_claims(session, run, cutoff=firewall_cutoff)
        rules = self.rule_registry.get_rules(run.domain_id)
        matched_rules: list[str] = []
        shock_count = 0
        current_state = deepcopy(initial_state)
        actor_id = f"{self._subject_id(run)}:{run.actor_template}"
        recent_claims: list[Claim] = []
        action_history: list[str] = []
        enemy_history: list[str] = []
        recent_decision_records: list[DecisionRecordRecord] = []
        military_tick_summaries: list[dict[str, Any]] = []
        geo_assets = (
            await self.list_geo_assets(session, run.id) if run.domain_id == "military" else []
        )
        calibration_ctx = await self._build_calibration_context(session, run.domain_id, run.id)

        session.add(
            StateSnapshotRecord(
                run_id=run.id, tick=0, actor_id=actor_id, state=deepcopy(current_state)
            )
        )
        # Sprint 3: per-tick state hashes for replay verification.
        state_hashes: dict[str, str] = {"0": state_hash(current_state)}

        for tick in range(1, run.tick_count + 1):
            active_claim = claims[(tick - 1) % len(claims)] if claims else None
            if active_claim is not None:
                shock_count += await self._record_external_shock(session, run, tick, active_claim)
                self._apply_external_shock(run.domain_id, current_state, active_claim.statement)
                recent_claims.append(active_claim)
                recent_claims = recent_claims[-_DECISION_EVIDENCE_WINDOW:]
            selected = await self._select_action(
                run.domain_id,
                current_state,
                active_claim,
                rules,
                recent_claims=recent_claims,
                action_history=action_history,
                recent_decisions=recent_decision_records,
                calibration_context_text=calibration_ctx["context_text"],
                session=session,
                policies=effective_policies,
                scale_scope=variable_scope,
            )
            matched_rules.extend(selected.rule_ids)
            actual_effect = selected.actual_effect
            why_selected = selected.why_selected
            if run.domain_id == "military":
                military_resolution = self._military.resolve_military_action_outcome(
                    current_state,
                    selected,
                    active_claim,
                    enemy_history,
                )
                actual_effect = military_resolution.actual_effect
                why_selected = (
                    f"{selected.why_selected} Enemy response {military_resolution.enemy_action_id} "
                    f"produced fire balance {military_resolution.fire_balance:+.2f}; objective control moved "
                    f"{military_resolution.objective_delta:+.3f} and the supply network moved "
                    f"{military_resolution.supply_delta:+.3f}."
                )
                enemy_history.append(military_resolution.enemy_action_id)
            self._apply_effects(current_state, actual_effect)
            if run.domain_id == "military":
                operational_picture = self._military.build_military_operational_picture(
                    run,
                    geo_assets,
                    current_state,
                    enemy_action_id=military_resolution.enemy_action_id,
                    enemy_reason=military_resolution.enemy_reason,
                )
                military_tick_summaries.append(
                    {
                        "tick": tick,
                        "enemy_action_id": military_resolution.enemy_action_id,
                        "enemy_reason": military_resolution.enemy_reason,
                        "fire_balance": military_resolution.fire_balance,
                        "objective_delta": military_resolution.objective_delta,
                        "supply_delta": military_resolution.supply_delta,
                        "recovery_delta": military_resolution.recovery_delta,
                        "enemy_posture": operational_picture["enemy_posture"],
                        "objective_snapshot": {
                            "critical_objective_id": operational_picture["objective_network"].get(
                                "critical_objective_id"
                            ),
                            "critical_route_id": operational_picture["objective_network"].get(
                                "critical_route_id"
                            ),
                            "contested_asset_ids": operational_picture["objective_network"].get(
                                "contested_asset_ids", []
                            ),
                        },
                    }
                )
            if driver_formulas:
                # Phase 1: per-tick variable drivers, applied AFTER the
                # action effects and BEFORE the decision record and
                # snapshot, so the snapshot (and its hash) captures the
                # driven state. Drivers evaluate over the run's sampled +
                # initial derived values, the current (post-rule) state,
                # and the tick index, in stored list order; outputs whose
                # id names a pack state field overwrite that field.
                # Self-referential drivers transform the post-rule state,
                # so rule effects compose instead of being overwritten.
                # Deterministic: same seed + same bindings + same tick
                # index reproduce the same values, so Sprint 3 replay
                # still matches tick by tick. A driver failure fails the
                # run loudly (never silently skipped).
                driver_updates = evaluate_tick_drivers(
                    driver_formulas, variable_scope, current_state, tick
                )
                for key, value in driver_updates.items():
                    if key in state_field_names:
                        current_state[key] = value
            action_history.append(selected.action_id)
            decision_record = DecisionRecordRecord(
                run_id=run.id,
                tick=tick,
                sequence=1,
                actor_id=actor_id,
                action_id=selected.action_id,
                why_selected=why_selected,
                evidence_ids=selected.evidence_ids,
                policy_rule_ids=selected.rule_ids,
                expected_effect=selected.expected_effect,
                actual_effect=actual_effect,
                decision_method=selected.decision_method,
            )
            session.add(decision_record)
            recent_decision_records.append(decision_record)
            session.add(
                StateSnapshotRecord(
                    run_id=run.id,
                    tick=tick,
                    actor_id=actor_id,
                    state=deepcopy(current_state),
                )
            )
            state_hashes[str(tick)] = state_hash(current_state)

        run.status = SimulationRunStatus.COMPLETED.value
        run.completed_at = utc_now()
        run.updated_at = utc_now()
        final_operational_picture = (
            self._military.build_military_operational_picture(
                run,
                geo_assets,
                current_state,
                enemy_action_id=military_tick_summaries[-1]["enemy_action_id"]
                if military_tick_summaries
                else None,
                enemy_reason=military_tick_summaries[-1]["enemy_reason"]
                if military_tick_summaries
                else None,
            )
            if run.domain_id == "military"
            else {}
        )
        accepted_claims = [claim for claim in claims if claim.status == ClaimStatus.ACCEPTED.value]
        provisional_claims = [
            claim for claim in claims if claim.status == ClaimStatus.PENDING_REVIEW.value
        ]
        accepted_evidence_ids = sorted({claim.evidence_item_id for claim in accepted_claims})
        provisional_evidence_ids = sorted({claim.evidence_item_id for claim in provisional_claims})
        evidence_audit = {
            "accepted_claim_count": len(accepted_claims),
            "accepted_evidence_count": len(accepted_evidence_ids),
            "provisional_claim_count": len(provisional_claims),
            "provisional_claim_ids": sorted(claim.id for claim in provisional_claims),
            "provisional_evidence_count": len(provisional_evidence_ids),
            "provisional_evidence_ids": provisional_evidence_ids,
            "provisional_confidence_floor": self.settings.review_auto_process_confidence,
            "provisional_evidence_disclaimer": (
                "Provisional evidence met the simulation safety floor but is not accepted "
                "or fully reviewed evidence."
            ),
        }
        run.summary = {
            **run.summary,
            "ticks_completed": run.tick_count,
            "evidence_count": len(claims),
            "shock_count": shock_count,
            "evidence_ids": sorted({claim.evidence_item_id for claim in claims}),
            "evidence_statements": [claim.statement for claim in claims[:5]],
            "evidence_audit": evidence_audit,
            "matched_rules": sorted(set(matched_rules)),
            "final_state": deepcopy(current_state),
            # Sprint 3: determinism audit trail — the input hash recorded
            # at creation, the per-tick state hashes, and the sampled
            # variable values (with the subset applied to the state).
            # Sprint 4: derived formula values, recorded alongside.
            # Sprint 5: the hindsight-firewall cutoff in effect.
            "determinism": {
                "input_hash": (run.configuration.get("determinism") or {}).get("input_hash"),
                "state_hashes": state_hashes,
                "sampled_values": sampled_values,
                "sampled_applied": [key for key in applied_values if key in sampled_values],
                "derived_values": derived_values,
                "derived_applied": [key for key in applied_values if key in derived_values],
                "decision_time": (
                    format_cutoff(firewall_cutoff) if firewall_cutoff is not None else None
                ),
                "cutoff_source": firewall_source,
                "firewall_active": firewall_cutoff is not None,
            },
            "military_tick_summaries": military_tick_summaries
            if run.domain_id == "military"
            else [],
            "objective_network": (
                final_operational_picture.get("objective_network", {})
                if run.domain_id == "military"
                else {}
            ),
            "enemy_posture": (
                final_operational_picture.get("enemy_posture", {})
                if run.domain_id == "military"
                else {}
            ),
            "enemy_order_of_battle": (
                final_operational_picture.get("enemy_order_of_battle", [])
                if run.domain_id == "military"
                else []
            ),
        }

        event_topic = (
            EventTopic.SCENARIO_COMPLETED.value
            if run.parent_run_id is not None
            else EventTopic.SIMULATION_COMPLETED.value
        )
        event_payload = {
            "run_id": run.id,
            "company_id": run.company_id,
            "force_id": run.force_id,
            "scenario_id": run.summary.get("scenario_id"),
        }
        session.add(EventArchive(topic=event_topic, payload=event_payload))
        await self.event_bus.publish(event_topic, event_payload)

        await self._generate_decision_options(session, run, current_state)
        from planagent.services.prediction import PredictionService

        prediction_service = PredictionService(self.settings, self.event_bus)
        versions = await prediction_service.create_initial_versions_for_run(session, run_id=run.id)
        await self._apply_calibrated_confidence(session, versions, calibration_ctx)

    async def _build_calibration_context(
        self,
        session: AsyncSession,
        domain_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        """Build the calibration context injected into simulation prompts."""
        from planagent.domain.models import (
            PredictionCalibrationContext,
            PredictionSeries,
            PredictionVersion,
            RuleAccuracy,
        )

        rule_accuracies = list(
            (
                await session.scalars(
                    select(RuleAccuracy)
                    .where(RuleAccuracy.domain_id == domain_id, RuleAccuracy.total_predictions >= 3)
                    .order_by(RuleAccuracy.accuracy_score.desc())
                )
            ).all()
        )

        run = await session.get(SimulationRun, run_id)
        subject_id = self._subject_id(run) if run is not None else None
        historical_query = (
            select(PredictionVersion)
            .join(PredictionSeries, PredictionSeries.id == PredictionVersion.series_id)
            .where(PredictionSeries.domain_id == domain_id)
        )
        if subject_id:
            historical_query = historical_query.where(PredictionSeries.subject_id == subject_id)
        historical_versions = list(
            (
                await session.scalars(
                    historical_query.where(
                        or_(PredictionVersion.run_id.is_(None), PredictionVersion.run_id != run_id)
                    )
                    .order_by(PredictionVersion.created_at.desc())
                    .limit(5)
                )
            ).all()
        )

        context_parts: list[str] = []
        if rule_accuracies:
            context_parts.append("## 历史规则准确率（基于过往验证）")
            for ra in rule_accuracies[:10]:
                context_parts.append(
                    f"- 规则 {ra.rule_id}: 准确率 {ra.accuracy_score:.1%} "
                    f"(验证{ra.total_predictions}次, 对{ra.confirmed}次, "
                    f"错{ra.refuted}次, 部分对{ra.partial}次)"
                )
            context_parts.append(
                "准确率高的规则应给予更高权重，准确率低的规则应谨慎使用或标记不确定性。"
            )

        if historical_versions:
            context_parts.append("\n## 同主题历史预测（供参考）")
            for hv in historical_versions:
                status_label = (
                    "[SUPERSEDED]"
                    if hv.status == "SUPERSEDED"
                    else "[ACTIVE]"
                    if hv.status == "ACTIVE"
                    else "[UNKNOWN]"
                )
                context_parts.append(
                    f"- {status_label} v{hv.version_number}: {hv.prediction_text[:200]} "
                    f"(概率:{hv.probability:.0%}, 置信度:{hv.confidence:.0%}, 触发:{hv.trigger_type})"
                )
            context_parts.append(
                "请参考历史预测的验证结果，避免重复已知错误，强化已验证的正确判断。"
            )

        rule_weights = {
            ra.rule_id: float(ra.weight_multiplier if ra.weight_multiplier is not None else 1.0)
            for ra in rule_accuracies
        }
        cal_ctx = PredictionCalibrationContext(
            run_id=run_id,
            historical_versions_injected=len(historical_versions),
            rule_weights_applied={
                ra.rule_id: rule_weights[ra.rule_id] for ra in rule_accuracies[:20]
            },
            confidence_adjustment=0.0,
        )
        session.add(cal_ctx)
        await session.flush()

        return {
            "context_text": "\n".join(context_parts),
            "rule_weights": rule_weights,
            "historical_count": len(historical_versions),
            "context_record_id": cal_ctx.id,
        }

    async def _apply_calibrated_confidence(
        self,
        session: AsyncSession,
        versions: list[Any],
        calibration_ctx: dict[str, Any],
    ) -> None:
        rule_weights = calibration_ctx.get("rule_weights") or {}
        if not versions or not rule_weights:
            return

        avg_weight = sum(float(weight) for weight in rule_weights.values()) / len(rule_weights)
        adjusted_versions = []
        for version in versions:
            original_confidence = float(version.confidence)
            adjusted_confidence = min(1.0, original_confidence * avg_weight)
            version.confidence = adjusted_confidence
            version.version_metadata = {
                **(version.version_metadata or {}),
                "calibration_avg_rule_weight": round(avg_weight, 4),
                "calibration_original_confidence": round(original_confidence, 4),
                "calibration_adjusted_confidence": round(adjusted_confidence, 4),
            }
            adjusted_versions.append(version)

        from planagent.domain.models import PredictionCalibrationContext

        context_record_id = calibration_ctx.get("context_record_id")
        if context_record_id:
            context_record = await session.get(PredictionCalibrationContext, context_record_id)
            if context_record is not None:
                context_record.prediction_version_id = adjusted_versions[0].id
                context_record.confidence_adjustment = round(avg_weight - 1.0, 4)

    async def _generate_decision_options(
        self,
        session: AsyncSession,
        run: SimulationRun,
        final_state: dict[str, float],
    ) -> None:
        from planagent.domain.models import DecisionOption, Hypothesis

        pack = registry.get(run.domain_id)
        # Sprint 2: risk text uses the run's effective (template-overlaid)
        # policies, matching the action-selection scoring for the same run.
        effective_policies = resolve_policies(run.domain_id, run.configuration)
        decisions = list(
            (
                await session.scalars(
                    select(DecisionRecordRecord)
                    .where(DecisionRecordRecord.run_id == run.id)
                    .order_by(DecisionRecordRecord.tick.asc())
                )
            ).all()
        )
        if not decisions:
            return

        unique_actions: dict[str, DecisionRecordRecord] = {}
        for d in decisions:
            if d.action_id not in unique_actions:
                unique_actions[d.action_id] = d
        top_actions = list(unique_actions.values())[:3]

        existing_count = int(
            await session.scalar(
                select(func.count())
                .select_from(DecisionOption)
                .where(DecisionOption.run_id == run.id)
            )
        )
        if existing_count > 0:
            return

        for ranking, decision in enumerate(top_actions, start=1):
            action_spec = None
            for a in pack.action_library:
                if a.action_id == decision.action_id:
                    action_spec = a
                    break
            title = action_spec.description if action_spec else decision.action_id
            description = (
                decision.why_selected
                or f"Action {decision.action_id} selected at tick {decision.tick}."
            )
            expected_effects = dict(decision.expected_effect) if decision.expected_effect else {}
            risks: list[str] = []
            for metric, value in expected_effects.items():
                policy = effective_policies.get(metric)
                if policy is not None:
                    if policy.preferred_direction == "increase" and value < -0.02:
                        risks.append(f"{metric} may decrease ({value:+.3f}).")
                    elif policy.preferred_direction == "decrease" and value > 0.02:
                        risks.append(f"{metric} may increase ({value:+.3f}).")
            confidence = round(
                min(0.95, max(0.3, 0.5 + len(decision.policy_rule_ids or []) * 0.1)), 2
            )
            conditions: list[str] = []
            if run.domain_id == "military" and final_state.get("escalation_index", 0) > 0.6:
                conditions.append("Escalation risk should be monitored if this option is pursued.")

            option = DecisionOption(
                run_id=run.id,
                tenant_id=run.tenant_id,
                preset_id=run.preset_id,
                title=title[:255],
                description=description[:2000],
                expected_effects=expected_effects,
                risks=risks,
                evidence_ids=decision.evidence_ids or [],
                confidence=confidence,
                conditions=conditions,
                ranking=ranking,
            )
            session.add(option)
            await session.flush()

            horizon = "1_week" if run.domain_id == "military" else "3_months"
            prediction = f"If '{decision.action_id}' continues, {', '.join(f'{k} will move toward {v:+.2f}' for k, v in list(expected_effects.items())[:3])}."
            hypothesis = Hypothesis(
                run_id=run.id,
                decision_option_id=option.id,
                tenant_id=run.tenant_id,
                preset_id=run.preset_id,
                prediction=prediction[:2000],
                time_horizon=horizon,
            )
            session.add(hypothesis)

    async def _record_external_shock(
        self,
        session: AsyncSession,
        run: SimulationRun,
        tick: int,
        claim: Claim,
    ) -> int:
        shocks = self._derive_shocks(run.domain_id, claim.statement, claim.evidence_item_id)
        for shock in shocks:
            session.add(
                ExternalShockRecord(
                    run_id=run.id,
                    tick=tick,
                    domain=run.domain_id,
                    shock_type=shock["shock_type"],
                    summary=shock["summary"],
                    evidence_ids=[claim.evidence_item_id],
                    payload=shock["payload"],
                )
            )
        return len(shocks)

    async def _fetch_relevant_claims(
        self,
        session: AsyncSession,
        run: SimulationRun,
        cutoff: datetime | None = None,
    ) -> list[Claim]:
        """Fetch the claims visible to a run.

        ``cutoff`` is the Sprint 5 hindsight-firewall decision time:
        when given, every query below is restricted to claims ingested
        at or before it (the predicate lives in ``scoped``, which all
        four queries pass through, so no query can bypass the
        firewall). ``None`` keeps the legacy unfiltered reads for runs
        without a firewall fragment.
        """
        tenant_id = normalize_tenant_id(run.tenant_id or run.configuration.get("tenant_id"))
        preset_id = run.preset_id or run.configuration.get("preset_id")
        scope_predicates = []
        if tenant_id is not None:
            scope_predicates.append(Claim.tenant_id == tenant_id)
        if preset_id is not None:
            scope_predicates.append(or_(Claim.preset_id == preset_id, Claim.preset_id.is_(None)))

        terms = await self._subject_terms(session, run)
        subject_predicates = []
        if terms:
            for term in terms:
                lowered = term.lower()
                subject_predicates.extend(
                    [
                        Claim.statement.ilike(f"%{lowered}%"),
                        Claim.subject.ilike(f"%{lowered}%"),
                        Claim.object_text.ilike(f"%{lowered}%"),
                    ]
                )

        def scoped(query: Any) -> Any:
            if scope_predicates:
                query = query.where(*scope_predicates)
            if cutoff is not None:
                # Hindsight firewall (Sprint 5): every claim query passes
                # through here, so the cutoff cannot be bypassed by any
                # of the fallback fetches below.
                query = query.where(Claim.created_at <= cutoff)
            return query

        def subject_scoped(query: Any) -> Any:
            return query.where(or_(*subject_predicates)) if subject_predicates else query

        accepted_query = subject_scoped(
            scoped(select(Claim).where(Claim.status == ClaimStatus.ACCEPTED.value))
        )
        claims = list(
            (await session.scalars(accepted_query.order_by(Claim.created_at.asc()))).all()
        )
        minimum_claims = max(4, run.tick_count)
        if len(claims) >= minimum_claims:
            return claims

        selected_by_id = {claim.id: claim for claim in claims}

        recent_query = scoped(select(Claim).where(Claim.status == ClaimStatus.ACCEPTED.value))
        if claims:
            recent_query = recent_query.where(Claim.created_at >= claims[0].created_at)
        recent_claims = list(
            (await session.scalars(recent_query.order_by(Claim.created_at.asc()).limit(25))).all()
        )
        for claim in recent_claims:
            selected_by_id.setdefault(claim.id, claim)
            if len(selected_by_id) >= minimum_claims:
                break

        if len(selected_by_id) >= minimum_claims:
            return list(selected_by_id.values())

        provisional_filter = and_(
            Claim.status == ClaimStatus.PENDING_REVIEW.value,
            Claim.confidence >= self.settings.review_auto_process_confidence,
        )
        provisional_query = subject_scoped(scoped(select(Claim).where(provisional_filter)))
        provisional_claims = list(
            (
                await session.scalars(
                    provisional_query.order_by(Claim.confidence.desc(), Claim.created_at.asc())
                )
            ).all()
        )
        for claim in provisional_claims:
            selected_by_id.setdefault(claim.id, claim)
            if len(selected_by_id) >= minimum_claims:
                break

        if len(selected_by_id) >= minimum_claims:
            return list(selected_by_id.values())

        recent_provisional_query = scoped(select(Claim).where(provisional_filter))
        if selected_by_id:
            first_selected = next(iter(selected_by_id.values()))
            recent_provisional_query = recent_provisional_query.where(
                Claim.created_at >= first_selected.created_at
            )
        recent_provisional_claims = list(
            (
                await session.scalars(
                    recent_provisional_query.order_by(
                        Claim.confidence.desc(), Claim.created_at.asc()
                    ).limit(25)
                )
            ).all()
        )
        for claim in recent_provisional_claims:
            selected_by_id.setdefault(claim.id, claim)
            if len(selected_by_id) >= minimum_claims:
                break
        return list(selected_by_id.values())

    async def _claim_simulation_runs(
        self,
        session: AsyncSession,
        limit: int,
        worker_id: str,
    ) -> list[SimulationRun]:
        now = utc_now()
        lease_expires_at = now + timedelta(seconds=self.settings.worker_lease_seconds)
        candidate_ids = list(
            (
                await session.scalars(
                    select(SimulationRun.id)
                    .where(
                        or_(
                            SimulationRun.status == SimulationRunStatus.PENDING.value,
                            and_(
                                SimulationRun.status == SimulationRunStatus.PROCESSING.value,
                                or_(
                                    SimulationRun.lease_expires_at.is_(None),
                                    SimulationRun.lease_expires_at < now,
                                ),
                            ),
                        )
                    )
                    .order_by(SimulationRun.created_at.asc())
                    .limit(limit * 3)
                )
            ).all()
        )
        claimed: list[SimulationRun] = []
        for run_id in candidate_ids:
            result = await session.execute(
                update(SimulationRun)
                .where(
                    SimulationRun.id == run_id,
                    or_(
                        SimulationRun.status == SimulationRunStatus.PENDING.value,
                        and_(
                            SimulationRun.status == SimulationRunStatus.PROCESSING.value,
                            or_(
                                SimulationRun.lease_expires_at.is_(None),
                                SimulationRun.lease_expires_at < now,
                            ),
                        ),
                    ),
                )
                .values(
                    status=SimulationRunStatus.PROCESSING.value,
                    lease_owner=worker_id,
                    lease_expires_at=lease_expires_at,
                    processing_attempts=SimulationRun.processing_attempts + 1,
                    updated_at=now,
                )
            )
            if result.rowcount:
                run = await session.get(SimulationRun, run_id)
                if run is not None:
                    claimed.append(run)
            if len(claimed) >= limit:
                break
        return claimed

    async def _claim_report_runs(
        self,
        session: AsyncSession,
        limit: int,
        worker_id: str,
    ) -> list[SimulationRun]:
        now = utc_now()
        lease_expires_at = now + timedelta(seconds=self.settings.worker_lease_seconds)
        candidate_ids = list(
            (
                await session.scalars(
                    select(SimulationRun.id)
                    .outerjoin(GeneratedReport, GeneratedReport.run_id == SimulationRun.id)
                    .where(
                        SimulationRun.status == SimulationRunStatus.COMPLETED.value,
                        GeneratedReport.id.is_(None),
                        or_(
                            SimulationRun.lease_expires_at.is_(None),
                            SimulationRun.lease_expires_at < now,
                        ),
                    )
                    .order_by(SimulationRun.completed_at.asc(), SimulationRun.created_at.asc())
                    .limit(limit * 3)
                )
            ).all()
        )
        claimed: list[SimulationRun] = []
        for run_id in candidate_ids:
            result = await session.execute(
                update(SimulationRun)
                .where(
                    SimulationRun.id == run_id,
                    SimulationRun.status == SimulationRunStatus.COMPLETED.value,
                    or_(
                        SimulationRun.lease_expires_at.is_(None),
                        SimulationRun.lease_expires_at < now,
                    ),
                )
                .values(
                    lease_owner=worker_id,
                    lease_expires_at=lease_expires_at,
                    processing_attempts=SimulationRun.processing_attempts + 1,
                    updated_at=now,
                )
            )
            if result.rowcount:
                run = await session.get(SimulationRun, run_id)
                if run is not None:
                    claimed.append(run)
            if len(claimed) >= limit:
                break
        return claimed

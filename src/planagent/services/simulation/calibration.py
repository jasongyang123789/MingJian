"""Calibration loop + hindsight-firewall audit (Sprint 5, PRD delta D8).

This mixin holds the service orchestration; the pure mechanics (cutoff
normalization, the ridge-to-prior estimator) live in
:mod:`planagent.services.calibration`.

Hindsight firewall (per the saisrikolanu structural split): the
decision side never sees post-decision evidence. The cutoff lives in
the run configuration, so the Sprint 3 input hash covers it and
replays reproduce the same evidence set. The audit endpoint recomputes
the claim fetch with and without the cutoff and reports the diff —
the exact set of claims the firewall kept out. The calibration
worker's verification path is deliberately NOT firewalled: it is the
evaluator side of the split, and verification legitimately uses
post-decision evidence.

Ridge-to-prior calibration (per the jasonrkeen pattern): policy
thresholds and rule weights are fit from stored run outcomes,
shrinking toward the template/registry priors. A policy fit stores a
NEW template version with provenance and never touches the prior row.
A rule-weight fit records fitted weights on the fit row; they take
effect only through the explicit apply step, which sets the in-memory
registry weights and appends an application event to the fit record.
Fitted weights are an association signal, not a causal estimate.

Sprint 10 hardening: rule-weight fits center by default (derived
intercept, no prior semantics); fitted weights are durably recorded
per application with explicit restore; scenario children can be
excluded or family-weighted; both fit kinds carry a fit-quality gate
against the prior-only baseline; policy fits record per-metric
correlation diagnostics. The calibration worker is untouched: its
periodic blend starts from whatever weights are current, including
restored ones, exactly as Sprint 5 documented.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from planagent.domain.enums import SimulationRunStatus
from planagent.domain.models import (
    CalibrationFitRecord,
    CalibrationWeightApplicationRecord,
    DecisionRecordRecord,
    SimulationRun,
    VariableTemplateRecord,
    generate_id,
    utc_now,
)
from planagent.services.calibration import (
    calibrate_policy_thresholds,
    calibrate_rule_weights,
    firewall_cutoff_from_configuration,
    format_cutoff,
    pairwise_metric_correlations,
)
from planagent.services.calibration.models import (
    CalibrationFitRead,
    FirewallRead,
    PersistedWeightsRead,
    PolicyFitRequest,
    RestoreWeightsRequest,
    RuleWeightChange,
    RuleWeightFitRequest,
    ScenarioChildrenMode,
    ThresholdChange,
)
from planagent.services.distributions import sha256_hash
from planagent.services.variables.models import (
    MetricPolicySpec,
    VariableTemplateCreate,
)
from planagent.services.variables.presets import (
    builtin_template,
    is_builtin_template_id,
    known_domain_ids,
)
from planagent.services.variables.store import create_variable_template, get_variable_template
from planagent.simulation.domain_packs import registry

#: Configuration fragments that mark a run as a derived artifact rather
#: than an independent observation. MC trials and robustness probes are
#: re-executions of another run's inputs; including them would
#: double-count the same evidence. Replays are marked on the summary.
_EXCLUDED_CONFIGURATION_KEYS = ("monte_carlo", "robustness_probe")


class CalibrationError(ValueError):
    """Refusal with a stable machine-readable code (route maps to 400)."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _is_derived_run(run: SimulationRun) -> bool:
    """True for MC trials, robustness probes, and replays."""

    configuration = run.configuration or {}
    if any(key in configuration for key in _EXCLUDED_CONFIGURATION_KEYS):
        return True
    summary = run.summary or {}
    return bool(summary.get("replay_of"))


def _run_template_id(run: SimulationRun) -> str | None:
    """The template id a run carried, or None when it carried none."""

    fragment = (run.configuration or {}).get("variables")
    if not isinstance(fragment, dict):
        return None
    template_id = fragment.get("template_id")
    return template_id if isinstance(template_id, str) else None


def _carried_template(run: SimulationRun, template_id: str, *, builtin: bool) -> bool:
    """Whether a run's execution used the given template's policies.

    Stored templates: the run must carry the template id. Built-ins:
    a run with no variables fragment, a fragment naming the builtin
    id, or a bindings-only fragment (``template_id`` None) all execute
    against the pack defaults the builtin synthesizes.
    """

    carried = _run_template_id(run)
    if builtin:
        return carried is None or carried == template_id
    return carried == template_id


def _final_state_value(run: SimulationRun, metric: str) -> float | None:
    """A run's final value for a metric, or None when unusable."""

    summary = run.summary or {}
    final_state = summary.get("final_state")
    if not isinstance(final_state, dict):
        return None
    value = final_state.get(metric)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _fit_record_to_read(record: CalibrationFitRecord) -> CalibrationFitRead:
    return CalibrationFitRead(
        id=record.id,
        kind=record.kind,
        domain_id=record.domain_id,
        source_template_id=record.source_template_id,
        calibrated_template_id=record.calibrated_template_id,
        metric=record.metric,
        ridge_strength=record.ridge_strength,
        seed=record.seed,
        bootstrap_draws=record.bootstrap_draws,
        level=record.level,
        source_run_ids=list(record.source_run_ids or []),
        n_observations=record.n_observations,
        changes=dict(record.changes or {}),
        inputs_hash=record.inputs_hash,
        loo_rmse=record.loo_rmse,
        application=dict(record.application or {}),
        created_at=record.created_at.isoformat(),
    )


def _application_record_to_read(
    record: CalibrationWeightApplicationRecord,
) -> PersistedWeightsRead:
    return PersistedWeightsRead(
        id=record.id,
        domain_id=record.domain_id,
        fit_id=record.fit_id,
        weights={str(key): float(value) for key, value in dict(record.weights or {}).items()},
        previous_weights={
            str(key): float(value) for key, value in dict(record.previous_weights or {}).items()
        },
        supersedes_id=record.supersedes_id,
        applied_at=record.applied_at.isoformat(),
    )


async def _family_root_id(session: AsyncSession, run: SimulationRun, cache: dict[str, str]) -> str:
    """The root ancestor of a run's scenario family.

    Scenario children carry ``parent_run_id`` (only they do: MC
    trials, probes, and replays set it to None explicitly), and a
    child can itself be branched, so the family root is found by
    walking the chain. A dangling parent or a cycle stops the walk
    and treats the current run as its own root rather than failing
    the fit. Results are cached per fit: the walk is over the
    identity map for runs already loaded.
    """

    if run.id in cache:
        return cache[run.id]
    seen = {run.id}
    current = run
    while current.parent_run_id is not None:
        parent = await session.get(SimulationRun, current.parent_run_id)
        if parent is None or parent.id in seen:
            break
        seen.add(parent.id)
        current = parent
    for run_id in seen:
        cache[run_id] = current.id
    return current.id


async def _scenario_selection(
    session: AsyncSession,
    runs: list[SimulationRun],
    mode: ScenarioChildrenMode,
) -> tuple[list[SimulationRun], list[str], dict[str, float]]:
    """Apply the scenario-children mode to an observation set.

    Returns (kept runs in input order, excluded run ids, per-run
    weights keyed by run id). ``include`` keeps everything at weight
    1; ``exclude`` drops runs with a ``parent_run_id``; ``family``
    weights each root-ancestor family to total weight 1
    (1/family-size per member, families counted within this
    observation set). Weights are exact fractions of family sizes;
    the estimator consumes them as row weights.
    """

    if mode == "include":
        return runs, [], {run.id: 1.0 for run in runs}
    if mode == "exclude":
        kept = [run for run in runs if run.parent_run_id is None]
        excluded = [run.id for run in runs if run.parent_run_id is not None]
        return kept, excluded, {run.id: 1.0 for run in kept}
    cache: dict[str, str] = {}
    families: dict[str, list[SimulationRun]] = {}
    for run in runs:
        families.setdefault(await _family_root_id(session, run, cache), []).append(run)
    weights = {run.id: 1.0 / len(members) for members in families.values() for run in members}
    return runs, [], weights


class SimulationCalibrationMixin:
    """Calibration fits and firewall audit for :class:`SimulationService`."""

    async def _eligible_runs(
        self,
        session: AsyncSession,
        domain_id: str,
        source_run_ids: list[str] | None,
    ) -> list[SimulationRun]:
        """Completed primary runs for a domain, in deterministic order.

        Explicit ids are validated uniformly (existence, completed,
        domain match, not a derived artifact); an unknown or ineligible
        id refuses the fit rather than being silently skipped. Without
        explicit ids, all eligible runs for the domain are used.
        Ordered by (created_at, id) so the fit inputs are deterministic.
        """

        if source_run_ids is not None:
            runs: list[SimulationRun] = []
            for run_id in source_run_ids:
                run = await session.get(SimulationRun, run_id)
                if run is None:
                    raise LookupError(f"Simulation run {run_id} was not found.")
                if run.domain_id != domain_id:
                    raise CalibrationError(
                        "domain_mismatch",
                        f"Run {run_id} belongs to domain {run.domain_id!r}, not {domain_id!r}.",
                    )
                if run.status != SimulationRunStatus.COMPLETED.value:
                    raise CalibrationError(
                        "run_not_completed",
                        f"Run {run_id} has status {run.status!r}; "
                        "only completed runs can feed a calibration fit.",
                    )
                if _is_derived_run(run):
                    raise CalibrationError(
                        "derived_run_excluded",
                        f"Run {run_id} is a Monte Carlo trial, robustness "
                        "probe, or replay and cannot feed a calibration fit.",
                    )
                runs.append(run)
            runs.sort(key=lambda run: (run.created_at, run.id))
            return runs
        result = await session.execute(
            select(SimulationRun)
            .where(SimulationRun.domain_id == domain_id)
            .where(SimulationRun.status == SimulationRunStatus.COMPLETED.value)
            .order_by(SimulationRun.created_at, SimulationRun.id)
        )
        return [run for run in result.scalars().all() if not _is_derived_run(run)]

    async def get_firewall_audit(self, session: AsyncSession, run_id: str) -> FirewallRead:
        """Recompute a run's claim fetch with and without its cutoff."""

        run = await session.get(SimulationRun, run_id)
        if run is None:
            raise LookupError(f"Simulation run {run_id} was not found.")
        cutoff, source = firewall_cutoff_from_configuration(run.configuration)
        included = [
            claim.id for claim in await self._fetch_relevant_claims(session, run, cutoff=cutoff)
        ]
        if cutoff is None:
            excluded: list[str] = []
        else:
            unfiltered = [
                claim.id for claim in await self._fetch_relevant_claims(session, run, cutoff=None)
            ]
            included_set = set(included)
            excluded = [claim_id for claim_id in unfiltered if claim_id not in included_set]
        summary = run.summary or {}
        stored_evidence = summary.get("evidence_ids")
        return FirewallRead(
            run_id=run.id,
            decision_time=format_cutoff(cutoff) if cutoff is not None else None,
            cutoff_source=source,
            firewall_active=cutoff is not None,
            included_claim_ids=included,
            excluded_claim_ids=excluded,
            stored_evidence_ids=list(stored_evidence) if isinstance(stored_evidence, list) else [],
        )

    async def fit_policy_thresholds(
        self, session: AsyncSession, request: PolicyFitRequest
    ) -> CalibrationFitRead:
        """Fit a template's policy thresholds from stored run outcomes.

        The fitted thresholds are stored as a NEW template version; the
        source template row is never modified. Runs that carried the
        template (or, for builtins, runs that executed against the pack
        defaults) supply per-metric final-state observations.
        """

        template_id = request.template_id
        builtin = is_builtin_template_id(template_id)
        source_record: VariableTemplateRecord | None = None
        if builtin:
            domain_id = template_id[len("builtin:") :]
            try:
                template = builtin_template(domain_id)
            except ValueError as exc:
                raise LookupError(f"Variable template {template_id} was not found.") from exc
        else:
            source_record = await session.get(VariableTemplateRecord, template_id)
            if source_record is None:
                raise LookupError(f"Variable template {template_id} was not found.")
            stored = await get_variable_template(session, template_id)
            if stored is None:
                raise LookupError(f"Variable template {template_id} was not found.")
            template = stored
            domain_id = template.domain_id
        if not template.policies:
            raise CalibrationError(
                "no_policies",
                f"Template {template_id} defines no metric policies to calibrate.",
            )

        runs = [
            run
            for run in await self._eligible_runs(session, domain_id, request.source_run_ids)
            if _carried_template(run, template_id, builtin=builtin)
        ]
        contributing: list[tuple[SimulationRun, dict[str, float]]] = []
        for run in runs:
            values = {}
            for metric in template.policies:
                value = _final_state_value(run, metric)
                if value is not None:
                    values[metric] = value
            if values:
                contributing.append((run, values))
        if not contributing:
            raise CalibrationError(
                "insufficient_observations",
                "No eligible run carried this template with usable final-state "
                "values for its policy metrics.",
            )
        kept_runs, excluded_ids, weights = await _scenario_selection(
            session, [run for run, _ in contributing], request.scenario_children
        )
        kept_ids = {run.id for run in kept_runs}
        kept_values = [(run, values) for run, values in contributing if run.id in kept_ids]
        if not kept_values:
            raise CalibrationError(
                "insufficient_observations",
                "No eligible run remains after scenario-children handling "
                f"(mode {request.scenario_children!r} excluded "
                f"{len(excluded_ids)} run(s)).",
            )
        observations: dict[str, list[float]] = {}
        observation_weights: dict[str, list[float]] = {}
        aligned: dict[str, dict[str, float]] = {}
        for run, values in kept_values:
            for metric, value in values.items():
                observations.setdefault(metric, []).append(value)
                observation_weights.setdefault(metric, []).append(weights[run.id])
                aligned.setdefault(metric, {})[run.id] = value
        contributing_ids = [run.id for run, _ in kept_values]

        priors = {
            metric: {
                "preferred_direction": spec.preferred_direction,
                "alert_threshold": spec.alert_threshold,
                "critical_threshold": spec.critical_threshold,
            }
            for metric, spec in template.policies.items()
        }
        fitted = calibrate_policy_thresholds(
            priors,
            observations,
            ridge_strength=request.ridge_strength,
            seed=request.seed,
            bootstrap_draws=request.bootstrap_draws,
            level=request.level,
            observation_weights=observation_weights,
            quality_gate=request.quality_gate,
        )
        fitted_policies = fitted["policies"]
        changes = {
            metric: ThresholdChange(
                metric=metric,
                preferred_direction=change["preferred_direction"],
                prior_alert_threshold=change["prior_alert_threshold"],
                fitted_alert_threshold=change["fitted_alert_threshold"],
                prior_critical_threshold=change["prior_critical_threshold"],
                fitted_critical_threshold=change["fitted_critical_threshold"],
                alert_bootstrap=change["alert_bootstrap"],
                critical_bootstrap=change["critical_bootstrap"],
                n_observations=change["n_observations"],
                n_tail=change["n_tail"],
                unchanged_reason=change["unchanged_reason"],
                rejected_fit=change.get("rejected_fit"),
                fitted_loo_rmse=change["fitted_loo_rmse"],
                prior_only_rmse=change["prior_only_rmse"],
                quality_gate_passed=change["quality_gate_passed"],
            ).model_dump(mode="json")
            for metric, change in fitted["changes"].items()
        }
        correlations = pairwise_metric_correlations(aligned)
        # The gate suppresses version creation only when it is the
        # reason nothing changed: enabled, every evaluated metric
        # failed, and no metric changed. Insufficient-observation
        # metrics keep Sprint 5 behavior (a version is still created).
        gate_verdicts = [
            change["quality_gate_passed"]
            for change in fitted["changes"].values()
            if change["quality_gate_passed"] is not None
        ]
        any_changed = any(
            change["unchanged_reason"] is None for change in fitted["changes"].values()
        )
        gate_suppresses_version = bool(
            request.quality_gate and gate_verdicts and not any(gate_verdicts) and not any_changed
        )
        version_created_reason = (
            "quality_gate: all evaluated metrics failed the fit-quality gate; "
            "no thresholds changed, so no calibrated template version was created."
            if gate_suppresses_version
            else None
        )
        inputs_hash = sha256_hash(
            {
                "kind": "policy_thresholds",
                "domain_id": domain_id,
                "source_template_id": template_id,
                "source_run_ids": contributing_ids,
                "observations": observations,
                "priors": priors,
                "ridge_strength": request.ridge_strength,
                "seed": request.seed,
                "bootstrap_draws": request.bootstrap_draws,
                "level": request.level,
                "scenario_children": request.scenario_children,
                "observation_weights": {run_id: weights[run_id] for run_id in contributing_ids},
                "excluded_run_ids": excluded_ids,
                "quality_gate": request.quality_gate,
            }
        )

        # New template version: same state fields, variables, formulas,
        # and internal entries; fitted policies; provenance in the
        # description. The source row is never touched. When the gate
        # leaves zero metrics changed, no version is created: a
        # "(calibrated)" template identical to its source would
        # mislead, and the cockpit already treats a null
        # calibrated_template_id as "no new version".
        calibrated_template_id: str | None = None
        if not gate_suppresses_version:
            calibrated_policies = {
                metric: MetricPolicySpec(
                    preferred_direction=spec["preferred_direction"],
                    alert_threshold=spec["alert_threshold"],
                    critical_threshold=spec["critical_threshold"],
                )
                for metric, spec in fitted_policies.items()
            }
            calibrated_name = f"{template.name} (calibrated)"[:200]
            calibrated = await create_variable_template(
                session,
                VariableTemplateCreate(
                    name=calibrated_name,
                    domain_id=domain_id,
                    description=(
                        f"Calibrated from template {template_id} by ridge-to-prior "
                        f"fit (ridge_strength={request.ridge_strength}, "
                        f"seed={request.seed}) over {len(contributing_ids)} run(s). "
                        f"Source description: {template.description}"
                    )[:2000],
                    state_fields=list(template.state_fields),
                    policies=calibrated_policies,
                    variables=list(template.variables),
                    formulas=list(template.formulas),
                    internal=dict(template.internal),
                ),
                tenant_id=source_record.tenant_id if source_record is not None else None,
                preset_id=source_record.preset_id if source_record is not None else None,
            )
            calibrated_template_id = calibrated.id
        record = CalibrationFitRecord(
            id=generate_id(),
            kind="policy_thresholds",
            domain_id=domain_id,
            source_template_id=template_id,
            calibrated_template_id=calibrated_template_id,
            metric=None,
            ridge_strength=request.ridge_strength,
            seed=request.seed,
            bootstrap_draws=request.bootstrap_draws,
            level=request.level,
            source_run_ids=contributing_ids,
            n_observations=len(contributing_ids),
            changes={
                "metrics": changes,
                "version_created": not gate_suppresses_version,
                "version_created_reason": version_created_reason,
                "correlations": correlations,
                "scenario_children": {
                    "mode": request.scenario_children,
                    "excluded_run_ids": excluded_ids,
                    "observation_weights": {run_id: weights[run_id] for run_id in contributing_ids},
                },
            },
            inputs_hash=inputs_hash,
            loo_rmse=None,
            application={},
        )
        session.add(record)
        await session.commit()
        return _fit_record_to_read(record)

    async def fit_rule_weights(
        self, session: AsyncSession, request: RuleWeightFitRequest
    ) -> CalibrationFitRead:
        """Fit a domain's rule weights from stored run outcomes.

        Features are per-rule match counts from decision records;
        the target is the final value of ``request.metric``. Fitted
        weights are recorded on the fit row and take effect only
        through the explicit apply endpoint.
        """

        domain_id = request.domain_id
        if domain_id not in known_domain_ids():
            raise CalibrationError("unknown_domain", f"Unknown domain_id: {domain_id}")
        try:
            pack = registry.get(domain_id)
        except (KeyError, ModuleNotFoundError) as exc:
            raise CalibrationError("unknown_domain", f"Unknown domain_id: {domain_id}") from exc
        state_field_names = {field.name for field in pack.state_fields}
        if request.metric not in state_field_names:
            raise CalibrationError(
                "unknown_metric",
                f"Metric {request.metric!r} is not a state field of domain "
                f"{domain_id!r} (known: {sorted(state_field_names)}).",
            )

        runs = await self._eligible_runs(session, domain_id, request.source_run_ids)
        observed: list[tuple[SimulationRun, float]] = []
        for run in runs:
            value = _final_state_value(run, request.metric)
            if value is not None:
                observed.append((run, value))
        if len(observed) < 2:
            raise CalibrationError(
                "insufficient_observations",
                "Rule-weight calibration needs at least 2 completed runs "
                f"with a final {request.metric!r} value; found {len(observed)}.",
            )
        kept_runs, excluded_ids, weights = await _scenario_selection(
            session, [run for run, _ in observed], request.scenario_children
        )
        kept_ids = {run.id for run in kept_runs}
        observed = [(run, value) for run, value in observed if run.id in kept_ids]
        if len(observed) < 2:
            raise CalibrationError(
                "insufficient_observations",
                "Rule-weight calibration needs at least 2 completed runs "
                f"with a final {request.metric!r} value after scenario-children "
                f"handling (mode {request.scenario_children!r} excluded "
                f"{len(excluded_ids)} run(s)); found {len(observed)}.",
            )
        run_ids = [run.id for run, _ in observed]
        sample_weights = [weights[run_id] for run_id in run_ids]
        result = await session.execute(
            select(DecisionRecordRecord)
            .where(DecisionRecordRecord.run_id.in_(run_ids))
            .order_by(
                DecisionRecordRecord.run_id,
                DecisionRecordRecord.tick,
                DecisionRecordRecord.sequence,
            )
        )
        counts: dict[str, Counter[str]] = {run_id: Counter() for run_id in run_ids}
        for decision in result.scalars().all():
            matched = decision.policy_rule_ids or []
            counts[decision.run_id].update(rule_id for rule_id in matched if rule_id)

        registry_rules = self.rule_registry.get_rules(domain_id)
        rule_ids = [rule.rule_id for rule in registry_rules]
        seen = set(rule_ids)
        for counter in counts.values():
            for rule_id in sorted(counter):
                if rule_id not in seen:
                    seen.add(rule_id)
                    rule_ids.append(rule_id)
        current_weights = self.rule_registry.calibration_weights
        priors = {rule_id: float(current_weights.get(rule_id, 1.0)) for rule_id in rule_ids}
        design = [[float(counts[run_id][rule_id]) for rule_id in rule_ids] for run_id in run_ids]
        targets = [value for _, value in observed]
        # The general fit needs >= 2 observations (the reference's
        # floor); the per-metric location fits in the policy path keep
        # the stricter 3-observation default.
        fitted = calibrate_rule_weights(
            rule_ids,
            design,
            targets,
            [priors[rule_id] for rule_id in rule_ids],
            ridge_strength=request.ridge_strength,
            seed=request.seed,
            bootstrap_draws=request.bootstrap_draws,
            level=request.level,
            min_observations=2,
            center_target=request.center_target,
            sample_weights=sample_weights,
        )
        loo_rmse = fitted["loo_rmse"]
        prior_only_rmse = fitted["prior_only_rmse"]
        gate_evaluated = bool(request.quality_gate and loo_rmse is not None)
        gate_passed = (loo_rmse <= prior_only_rmse) if gate_evaluated else None
        if gate_passed is False:
            # Whole-fit gate, house discipline: refuse before any row
            # is written, with both numbers in the message.
            raise CalibrationError(
                "fit_quality_gate_failed",
                "Rule-weight fit refused by the fit-quality gate: fitted "
                f"LOO RMSE {loo_rmse:.4f} is worse than the prior-only "
                f"baseline RMSE {prior_only_rmse:.4f} on the same "
                f"{len(observed)} observation(s). No fit was recorded; "
                "re-run with quality_gate=false to record the fit anyway.",
            )
        gate_record: dict[str, Any] = {
            "enabled": request.quality_gate,
            "evaluated": gate_evaluated,
            "passed": gate_passed,
            "fitted_loo_rmse": loo_rmse,
            "prior_only_rmse": prior_only_rmse,
            "reason": (
                None
                if gate_evaluated
                else (
                    "quality_gate_disabled"
                    if not request.quality_gate
                    else "loo_undefined_below_3_observations"
                )
            ),
        }
        changes = {
            rule_id: RuleWeightChange(
                rule_id=rule_id,
                prior_weight=change["prior_weight"],
                fitted_weight=change["fitted_weight"],
                bootstrap=change["bootstrap"],
                total_matches=change["total_matches"],
            ).model_dump(mode="json")
            for rule_id, change in fitted["changes"].items()
        }
        fit_record = CalibrationFitRecord(
            id=generate_id(),
            kind="rule_weights",
            domain_id=domain_id,
            source_template_id=None,
            calibrated_template_id=None,
            metric=request.metric,
            ridge_strength=request.ridge_strength,
            seed=request.seed,
            bootstrap_draws=request.bootstrap_draws,
            level=request.level,
            source_run_ids=run_ids,
            n_observations=len(observed),
            changes={
                "rules": changes,
                "association_note": (
                    "Fitted weights are an association signal between rule "
                    "match counts and the target metric, not a causal "
                    "estimate of rule effects."
                ),
                "centering": fitted["centering"],
                "intercept": fitted["intercept"],
                "quality_gate": gate_record,
                "scenario_children": {
                    "mode": request.scenario_children,
                    "excluded_run_ids": excluded_ids,
                    "observation_weights": {run_id: weights[run_id] for run_id in run_ids},
                },
            },
            inputs_hash=sha256_hash(
                {
                    "kind": "rule_weights",
                    "domain_id": domain_id,
                    "metric": request.metric,
                    "source_run_ids": run_ids,
                    "design": design,
                    "targets": targets,
                    "priors": priors,
                    "ridge_strength": request.ridge_strength,
                    "seed": request.seed,
                    "bootstrap_draws": request.bootstrap_draws,
                    "level": request.level,
                    "center_target": request.center_target,
                    "scenario_children": request.scenario_children,
                    "observation_weights": {run_id: weights[run_id] for run_id in run_ids},
                    "excluded_run_ids": excluded_ids,
                    "quality_gate": request.quality_gate,
                }
            ),
            loo_rmse=loo_rmse,
            application={},
        )
        session.add(fit_record)
        await session.commit()
        return _fit_record_to_read(fit_record)

    async def apply_rule_weights(self, session: AsyncSession, fit_id: str) -> CalibrationFitRead:
        """Apply a stored rule-weight fit to the in-memory registry.

        The fit row is the durable record of the fit: the application
        event (previous weights, applied weights, timestamp) is
        appended to it. Sprint 10 adds the persistent current-weights
        record: the same application is written as a
        ``CalibrationWeightApplicationRecord`` in the same transaction,
        chained to the previous application for the domain. Registry
        weights are still in-memory only — ``reload()`` resets them,
        and the calibration worker's periodic blend starts from the
        applied values — but the durable record now survives a
        restart and can be explicitly restored.
        """

        record = await session.get(CalibrationFitRecord, fit_id)
        if record is None:
            raise LookupError(f"Calibration fit {fit_id} was not found.")
        if record.kind != "rule_weights":
            raise CalibrationError(
                "wrong_fit_kind",
                f"Fit {fit_id} is a {record.kind!r} fit; only rule-weight "
                "fits can be applied to the rule registry.",
            )
        rules = (record.changes or {}).get("rules") or {}
        fitted = {rule_id: float(change["fitted_weight"]) for rule_id, change in rules.items()}
        current = self.rule_registry.calibration_weights
        previous = {rule_id: float(current.get(rule_id, 1.0)) for rule_id in fitted}
        applied = self.rule_registry.apply_fitted_weights(fitted)
        previous_application = await self._latest_weight_application(session, record.domain_id)
        session.add(
            CalibrationWeightApplicationRecord(
                id=generate_id(),
                domain_id=record.domain_id,
                fit_id=record.id,
                weights=dict(applied),
                previous_weights=dict(previous),
                supersedes_id=previous_application.id if previous_application is not None else None,
                applied_at=utc_now(),
            )
        )
        application = dict(record.application or {})
        events = list(application.get("events") or [])
        events.append(
            {
                "applied_at": utc_now().isoformat(),
                "previous_weights": previous,
                "applied_weights": applied,
            }
        )
        application["events"] = events
        record.application = application
        await session.commit()
        return _fit_record_to_read(record)

    async def _latest_weight_application(
        self, session: AsyncSession, domain_id: str
    ) -> CalibrationWeightApplicationRecord | None:
        result = await session.execute(
            select(CalibrationWeightApplicationRecord)
            .where(CalibrationWeightApplicationRecord.domain_id == domain_id)
            .order_by(
                CalibrationWeightApplicationRecord.applied_at.desc(),
                CalibrationWeightApplicationRecord.id.desc(),
            )
            .limit(1)
        )
        return result.scalars().first()

    async def get_current_weights(
        self, session: AsyncSession, domain_id: str
    ) -> PersistedWeightsRead:
        """The latest persisted rule weights for a domain, if any."""

        if domain_id not in known_domain_ids():
            raise CalibrationError("unknown_domain", f"Unknown domain_id: {domain_id}")
        record = await self._latest_weight_application(session, domain_id)
        if record is None:
            raise LookupError(f"No persisted rule weights found for domain {domain_id!r}.")
        return _application_record_to_read(record)

    async def list_weight_applications(
        self,
        session: AsyncSession,
        domain_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PersistedWeightsRead]:
        """The append-only application history for a domain, newest first."""

        if domain_id not in known_domain_ids():
            raise CalibrationError("unknown_domain", f"Unknown domain_id: {domain_id}")
        result = await session.execute(
            select(CalibrationWeightApplicationRecord)
            .where(CalibrationWeightApplicationRecord.domain_id == domain_id)
            .order_by(
                CalibrationWeightApplicationRecord.applied_at.desc(),
                CalibrationWeightApplicationRecord.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return [_application_record_to_read(record) for record in result.scalars().all()]

    async def restore_weights(
        self, session: AsyncSession, request: RestoreWeightsRequest
    ) -> PersistedWeightsRead:
        """Explicitly re-apply the latest persisted weights to the registry.

        Restore is always explicit: nothing restores weights on
        startup or ``reload()``, so a restart never silently changes
        registry behavior. Restore writes no row — the application
        record it re-asserts is already the durable trace — it only
        changes in-memory registry state, and returns the record that
        was re-applied so the caller can verify exactly what took
        effect. The calibration worker's next blend starts from the
        restored values, as it does after any apply.
        """

        if request.domain_id not in known_domain_ids():
            raise CalibrationError("unknown_domain", f"Unknown domain_id: {request.domain_id}")
        record = await self._latest_weight_application(session, request.domain_id)
        if record is None:
            raise LookupError(f"No persisted rule weights found for domain {request.domain_id!r}.")
        weights = {str(key): float(value) for key, value in dict(record.weights or {}).items()}
        self.rule_registry.apply_fitted_weights(weights)
        return _application_record_to_read(record)

    async def get_calibration_fit(
        self, session: AsyncSession, fit_id: str
    ) -> CalibrationFitRead | None:
        record = await session.get(CalibrationFitRecord, fit_id)
        return _fit_record_to_read(record) if record is not None else None

    async def list_calibration_fits(
        self,
        session: AsyncSession,
        kind: str | None = None,
        domain_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CalibrationFitRead]:
        query = select(CalibrationFitRecord)
        if kind is not None:
            query = query.where(CalibrationFitRecord.kind == kind)
        if domain_id is not None:
            query = query.where(CalibrationFitRecord.domain_id == domain_id)
        query = (
            query.order_by(CalibrationFitRecord.created_at.desc(), CalibrationFitRecord.id.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(query)
        return [_fit_record_to_read(record) for record in result.scalars().all()]

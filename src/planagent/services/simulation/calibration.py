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
"""

from __future__ import annotations

import math
from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from planagent.domain.enums import SimulationRunStatus
from planagent.domain.models import (
    CalibrationFitRecord,
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
)
from planagent.services.calibration.models import (
    CalibrationFitRead,
    FirewallRead,
    PolicyFitRequest,
    RuleWeightChange,
    RuleWeightFitRequest,
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
        observations: dict[str, list[float]] = {}
        contributing: list[str] = []
        for run in runs:
            contributed = False
            for metric in template.policies:
                value = _final_state_value(run, metric)
                if value is not None:
                    observations.setdefault(metric, []).append(value)
                    contributed = True
            if contributed:
                contributing.append(run.id)
        if not contributing:
            raise CalibrationError(
                "insufficient_observations",
                "No eligible run carried this template with usable final-state "
                "values for its policy metrics.",
            )

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
            ).model_dump(mode="json")
            for metric, change in fitted["changes"].items()
        }
        inputs_hash = sha256_hash(
            {
                "kind": "policy_thresholds",
                "domain_id": domain_id,
                "source_template_id": template_id,
                "source_run_ids": contributing,
                "observations": observations,
                "priors": priors,
                "ridge_strength": request.ridge_strength,
                "seed": request.seed,
                "bootstrap_draws": request.bootstrap_draws,
                "level": request.level,
            }
        )

        # New template version: same state fields, variables, formulas,
        # and internal entries; fitted policies; provenance in the
        # description. The source row is never touched.
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
                    f"seed={request.seed}) over {len(contributing)} run(s). "
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
        record = CalibrationFitRecord(
            id=generate_id(),
            kind="policy_thresholds",
            domain_id=domain_id,
            source_template_id=template_id,
            calibrated_template_id=calibrated.id,
            metric=None,
            ridge_strength=request.ridge_strength,
            seed=request.seed,
            bootstrap_draws=request.bootstrap_draws,
            level=request.level,
            source_run_ids=contributing,
            n_observations=len(contributing),
            changes={"metrics": changes},
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
        run_ids = [run.id for run, _ in observed]
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
        )
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
                }
            ),
            loo_rmse=fitted["loo_rmse"],
            application={},
        )
        session.add(fit_record)
        await session.commit()
        return _fit_record_to_read(fit_record)

    async def apply_rule_weights(self, session: AsyncSession, fit_id: str) -> CalibrationFitRead:
        """Apply a stored rule-weight fit to the in-memory registry.

        The fit row is the durable record: the application event
        (previous weights, applied weights, timestamp) is appended to
        it. Registry weights are in-memory only — ``reload()`` resets
        them, and the calibration worker's periodic blend starts from
        the applied values.
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

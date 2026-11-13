"""Pure ensemble comparison for the living-strategy loop (Sprint 9).

Compares two stored ensembles — the baseline run's and a
re-simulation's — distribution against distribution. Everything here
reads stored fragments; nothing is recomputed from trial rows except
the gate re-evaluation, which reads the new trial values through the
same re-read discipline as Sprint 4 (the caller supplies the values;
this module never touches I/O). The baseline's stored results are
never recomputed or overwritten.

The honest caveat is structural: the two ensembles ran under
different evidence cutoffs, so even with identical seeds and trial
counts the comparison is not a pure sampling comparison — the
evidence sets differ, and the record says so.
"""

from __future__ import annotations

from planagent.services.distributions.models import MonteCarloResult
from planagent.services.robustness.methods import apply_gate_operator, gate_observed_value
from planagent.services.robustness.models import (
    GateEvaluation,
    GateMetric,
    GateOutcome,
    GateRegistration,
    ThresholdSearchResult,
)

from .models import (
    ArmDelta,
    EnsembleComparison,
    GateReevaluation,
    ThresholdDriftRow,
)

EVIDENCE_CAVEAT = (
    "The two ensembles ran under different evidence cutoffs: the "
    "re-simulation saw claims ingested after the baseline decision "
    "time. Identical seeds pair the sampling draws, but they do not "
    "make this a pure sampling comparison — outcome differences may "
    "come from the evidence, not the draws."
)


def _arm_delta(arm: str, old: MonteCarloResult, new: MonteCarloResult) -> ArmDelta:
    old_summary = old.baseline if arm == "baseline" else old.strategy
    new_summary = new.baseline if arm == "baseline" else new.strategy
    return ArmDelta(
        arm=arm,  # type: ignore[arg-type]
        old=old_summary,
        new=new_summary,
        delta_p10=new_summary.p10 - old_summary.p10,
        delta_p50=new_summary.p50 - old_summary.p50,
        delta_p90=new_summary.p90 - old_summary.p90,
        delta_mean=new_summary.mean - old_summary.mean,
        delta_p_loss=new_summary.p_loss - old_summary.p_loss,
    )


def reevaluate_gates(
    registration: GateRegistration,
    new_ensemble: MonteCarloResult,
    baseline_values: list[float],
    strategy_values: list[float],
) -> GateReevaluation:
    """Evaluate a baseline gate registration on a new ensemble.

    Pure: the caller supplies the new trial values. The new run's
    audit trail is not mutated — the outcomes live on the loop
    iteration record. ``pre_registered`` uses the Sprint 4 formula.
    """

    outcomes: list[GateOutcome] = []
    for gate in registration.gates:
        observed = gate_observed_value(
            gate, baseline_values, strategy_values, new_ensemble.loss_threshold
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
    return GateReevaluation(
        registration_id=registration.id,
        ensemble_id=new_ensemble.ensemble_id,
        outcomes=outcomes,
        all_passed=all(outcome.passed for outcome in outcomes),
        pre_registered=(
            registration.ensemble_id != new_ensemble.ensemble_id
            or not registration.ensemble_existed_at_registration
        ),
    )


def threshold_drift(
    old_search: ThresholdSearchResult | None,
    new_search: ThresholdSearchResult | None,
) -> list[ThresholdDriftRow]:
    """Match stored threshold searches by (variable, mode), old vs new.

    Each run stores at most one threshold-search result per fragment
    key (per-analysis-key overwrite, Sprint 4), so the match is at
    most one row — and only when both sides searched the same
    variable in the same mode. Anything else is honestly absent, not
    interpolated.
    """

    if old_search is None or new_search is None:
        return []
    if old_search.variable != new_search.variable or old_search.mode != new_search.mode:
        return []
    return [
        ThresholdDriftRow(
            variable=old_search.variable,
            mode=old_search.mode,
            old_threshold=old_search.threshold,
            old_reachable=old_search.reachable,
            new_threshold=new_search.threshold,
            new_reachable=new_search.reachable,
        )
    ]


def compare_ensembles(
    old: MonteCarloResult,
    new: MonteCarloResult,
    *,
    compared_at: str,
    cutoffs_differ: bool,
    gate_reevaluation: GateReevaluation | None = None,
    drift_rows: list[ThresholdDriftRow] | None = None,
) -> EnsembleComparison:
    """Build the distribution-vs-distribution comparison record.

    Raises ``ValueError`` when the ensembles measure different
    metrics or loss thresholds: comparing a cash distribution
    against a pipeline distribution would produce numbers that look
    meaningful and are not.
    """

    if old.metric != new.metric:
        raise ValueError(
            f"Cannot compare ensembles with different metrics: {old.metric!r} vs {new.metric!r}."
        )
    if old.loss_threshold != new.loss_threshold:
        raise ValueError(
            f"Cannot compare ensembles with different loss thresholds: "
            f"{old.loss_threshold!r} vs {new.loss_threshold!r}."
        )
    same_seed = old.seed == new.seed
    same_trials = old.trials == new.trials
    return EnsembleComparison(
        baseline_run_id=old.base_run_id,
        baseline_ensemble_id=old.ensemble_id,
        new_run_id=new.base_run_id,
        new_ensemble_id=new.ensemble_id,
        metric=old.metric,
        loss_threshold=old.loss_threshold,
        baseline_arm=_arm_delta("baseline", old, new),
        strategy_arm=_arm_delta("strategy", old, new),
        paired_mean_delta_old=old.paired.mean_delta,
        paired_mean_delta_new=new.paired.mean_delta,
        paired_mean_delta_change=new.paired.mean_delta - old.paired.mean_delta,
        paired_p_strategy_better_old=old.paired.p_strategy_better,
        paired_p_strategy_better_new=new.paired.p_strategy_better,
        paired_p_strategy_better_change=(
            new.paired.p_strategy_better - old.paired.p_strategy_better
        ),
        same_seed=same_seed,
        same_trials=same_trials,
        seeds_paired=same_seed and same_trials,
        evidence_caveat=EVIDENCE_CAVEAT if cutoffs_differ else None,
        gate_reevaluation=gate_reevaluation,
        threshold_drift=drift_rows or [],
        compared_at=compared_at,
    )


def gate_evaluation_to_reevaluation(evaluation: GateEvaluation) -> GateReevaluation:
    """Adapt a stored Sprint 4 evaluation to the comparison shape.

    Kept for callers that already hold an evaluation record; the
    comparison path normally uses :func:`reevaluate_gates` directly
    so the new run's audit trail stays untouched.
    """

    return GateReevaluation(
        registration_id=evaluation.registration_id,
        ensemble_id=evaluation.ensemble_id,
        outcomes=list(evaluation.outcomes),
        all_passed=evaluation.all_passed,
        pre_registered=evaluation.pre_registered,
    )

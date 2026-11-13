"""Unit tests for living-loop ensemble comparison (Sprint 9, pure).

Covers arm deltas, the metric/loss-threshold mismatch refusals, the
seeds-paired flag and evidence caveat, gate re-evaluation against new
trial values (pure, no run mutation), and threshold-drift matching.
"""

from __future__ import annotations

import pytest

from planagent.services.distributions.models import (
    DistributionSummary,
    MonteCarloResult,
    PairedDeltaSummary,
)
from planagent.services.living_loop.comparison import (
    compare_ensembles,
    reevaluate_gates,
    threshold_drift,
)
from planagent.services.robustness.models import (
    GateDefinition,
    GateRegistration,
    ThresholdSearchResult,
)


def _summary(mean: float, p10: float, p50: float, p90: float, p_loss: float) -> DistributionSummary:
    return DistributionSummary(
        n=10,
        mean=mean,
        min=p10 - 5.0,
        max=p90 + 5.0,
        p10=p10,
        p50=p50,
        p90=p90,
        stddev=10.0,
        p_loss=p_loss,
    )


def _paired(mean_delta: float, p_better: float) -> PairedDeltaSummary:
    return PairedDeltaSummary(
        n=10, mean_delta=mean_delta, p10=0.0, p50=mean_delta, p90=0.0, p_strategy_better=p_better
    )


def _ensemble(
    ensemble_id: str,
    base_run_id: str,
    seed: int,
    trials: int,
    *,
    metric: str = "cash",
    loss_threshold: float = 90.0,
    baseline_mean: float = 100.0,
    strategy_mean: float = 140.0,
) -> MonteCarloResult:
    return MonteCarloResult(
        ensemble_id=ensemble_id,
        base_run_id=base_run_id,
        trials=trials,
        seed=seed,
        metric=metric,
        loss_threshold=loss_threshold,
        strategy_levers={"cash": 140.0},
        baseline=_summary(baseline_mean, 80.0, 100.0, 120.0, 0.3),
        strategy=_summary(strategy_mean, 140.0, 140.0, 140.0, 0.0),
        paired=_paired(strategy_mean - baseline_mean, 1.0),
        trial_run_ids={"baseline": [], "strategy": []},
        protocol="sprint3-v1",
    )


def test_arm_deltas_are_new_minus_old() -> None:
    old = _ensemble("ens-old", "run-old", 42, 10, baseline_mean=100.0)
    new = _ensemble("ens-new", "run-new", 42, 10, baseline_mean=90.0, strategy_mean=130.0)
    comparison = compare_ensembles(
        old, new, compared_at="2026-04-01T00:00:00.000000Z", cutoffs_differ=False
    )
    assert comparison.baseline_arm.delta_mean == pytest.approx(-10.0)
    assert comparison.baseline_arm.delta_p_loss == pytest.approx(0.0)
    assert comparison.strategy_arm.delta_mean == pytest.approx(-10.0)
    assert comparison.paired_mean_delta_change == pytest.approx(0.0)
    assert comparison.metric == "cash"
    assert comparison.loss_threshold == 90.0


def test_seeds_paired_requires_same_seed_and_trials() -> None:
    old = _ensemble("ens-old", "run-old", 42, 10)
    same = _ensemble("ens-new", "run-new", 42, 10)
    different_seed = _ensemble("ens-new", "run-new", 7, 10)
    different_trials = _ensemble("ens-new", "run-new", 42, 20)
    assert compare_ensembles(old, same, compared_at="t", cutoffs_differ=False).seeds_paired is True
    assert (
        compare_ensembles(old, different_seed, compared_at="t", cutoffs_differ=False).seeds_paired
        is False
    )
    assert (
        compare_ensembles(old, different_trials, compared_at="t", cutoffs_differ=False).seeds_paired
        is False
    )


def test_evidence_caveat_present_only_when_cutoffs_differ() -> None:
    old = _ensemble("ens-old", "run-old", 42, 10)
    new = _ensemble("ens-new", "run-new", 42, 10)
    assert (
        compare_ensembles(old, new, compared_at="t", cutoffs_differ=True).evidence_caveat
        is not None
    )
    assert (
        compare_ensembles(old, new, compared_at="t", cutoffs_differ=False).evidence_caveat is None
    )


def test_metric_mismatch_refused() -> None:
    old = _ensemble("ens-old", "run-old", 42, 10, metric="cash")
    new = _ensemble("ens-new", "run-new", 42, 10, metric="pipeline")
    with pytest.raises(ValueError, match="different metrics"):
        compare_ensembles(old, new, compared_at="t", cutoffs_differ=False)


def test_loss_threshold_mismatch_refused() -> None:
    old = _ensemble("ens-old", "run-old", 42, 10, loss_threshold=90.0)
    new = _ensemble("ens-new", "run-new", 42, 10, loss_threshold=80.0)
    with pytest.raises(ValueError, match="different loss thresholds"):
        compare_ensembles(old, new, compared_at="t", cutoffs_differ=False)


def test_gate_reevaluation_uses_new_trial_values() -> None:
    registration = GateRegistration(
        id="reg-1",
        run_id="run-old",
        ensemble_id="ens-old",
        gates=[
            GateDefinition(name="mean holds", metric="mean", operator=">", threshold=95.0),
            GateDefinition(name="loss capped", metric="p_loss", operator="<=", threshold=0.5),
        ],
        registered_at="2026-03-01T00:00:00.000000Z",
        ensemble_existed_at_registration=True,
    )
    new = _ensemble("ens-new", "run-new", 42, 10)
    # New trial values: mean 80, p_loss 0.8 -> both gates fail.
    reevaluation = reevaluate_gates(
        registration, new, [70.0, 80.0, 90.0, 80.0], [140.0, 140.0, 140.0, 140.0]
    )
    assert reevaluation.registration_id == "reg-1"
    assert reevaluation.ensemble_id == "ens-new"
    assert reevaluation.all_passed is False
    assert [outcome.passed for outcome in reevaluation.outcomes] == [False, False]
    assert reevaluation.outcomes[0].observed == pytest.approx(80.0)
    assert reevaluation.outcomes[1].observed == pytest.approx(0.75)
    # The registration targeted a different ensemble: pre-registered.
    assert reevaluation.pre_registered is True


def test_threshold_drift_matches_same_variable_and_mode() -> None:
    def _search(
        variable: str, mode: str, threshold: float | None, reachable: bool
    ) -> ThresholdSearchResult:
        return ThresholdSearchResult(
            run_id="r",
            ensemble_id="e",
            metric="cash",
            variable=variable,
            mode=mode,  # type: ignore[arg-type]
            target=0.5,
            direction="decreasing",
            bounds=(60.0, 140.0),
            threshold=threshold,
            reachable=reachable,
            iterations=8,
            trials_per_evaluation=10,
            tolerance=0.5,
            loss_threshold=90.0,
            seed=42,
            protocol="sprint4-v1",
        )

    rows = threshold_drift(
        _search("cash", "p_loss", 89.84, True), _search("cash", "p_loss", 95.10, True)
    )
    assert len(rows) == 1
    assert rows[0].old_threshold == pytest.approx(89.84)
    assert rows[0].new_threshold == pytest.approx(95.10)

    # Different variable or mode: no row, honestly absent.
    assert (
        threshold_drift(_search("cash", "p_loss", 89.84, True), _search("cac", "p_loss", 1.0, True))
        == []
    )
    assert (
        threshold_drift(
            _search("cash", "p_loss", 89.84, True), _search("cash", "arm_flip", 1.0, True)
        )
        == []
    )
    assert threshold_drift(None, _search("cash", "p_loss", 1.0, True)) == []
    assert threshold_drift(_search("cash", "p_loss", 1.0, True), None) == []

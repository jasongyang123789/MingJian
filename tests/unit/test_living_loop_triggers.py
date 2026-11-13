"""Unit tests for living-loop trigger evaluation (Sprint 9, pure).

Covers window selection (exclusive lower / inclusive upper bound,
deterministic ordering), all three trigger kinds (fire / quiet /
no-data), the deviation consecutive-run rule, gate-trigger model
restrictions (no paired metrics, baseline arm only, p_loss needs a
loss threshold), and the all-or-nothing missing-reference refusal.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from planagent.services.calibration.firewall import format_cutoff, normalize_cutoff
from planagent.services.living_loop.models import (
    DeviationTrigger,
    GateTrigger,
    LoopObservationRead,
    ThresholdTrigger,
)
from planagent.services.living_loop.triggers import evaluate_triggers, select_window
from planagent.services.robustness.models import GateDefinition


def _observation(obs_id: str, field: str, value: float, observed_at: str) -> LoopObservationRead:
    return LoopObservationRead(
        id=obs_id,
        loop_id="loop-1",
        field=field,
        value=value,
        observed_at=observed_at,
        recorded_at=observed_at,
    )


def _window() -> list[LoopObservationRead]:
    return [
        _observation("obs-1", "cash", 90.0, "2026-03-10T00:00:00.000000Z"),
        _observation("obs-2", "cash", 70.0, "2026-03-20T00:00:00.000000Z"),
        _observation("obs-3", "cash", 55.0, "2026-03-25T00:00:00.000000Z"),
        _observation("obs-4", "pipeline", 1.2, "2026-03-22T00:00:00.000000Z"),
    ]


# ------------------------------------------------------------------ window


def test_select_window_excludes_lower_bound_includes_upper() -> None:
    window = select_window(
        _window(),
        after=normalize_cutoff(datetime(2026, 3, 10)),
        up_to=normalize_cutoff(datetime(2026, 3, 20)),
    )
    assert [item.id for item in window] == ["obs-2"]


def test_select_window_no_lower_bound_takes_all_up_to_cutoff() -> None:
    window = select_window(_window(), after=None, up_to=normalize_cutoff(datetime(2026, 3, 22)))
    assert [item.id for item in window] == ["obs-1", "obs-2", "obs-4"]


def test_select_window_orders_by_observed_at_then_id() -> None:
    shuffled = list(reversed(_window()))
    window = select_window(shuffled, after=None, up_to=normalize_cutoff(datetime(2026, 4, 1)))
    assert [item.id for item in window] == ["obs-1", "obs-2", "obs-4", "obs-3"]


# -------------------------------------------------------------- threshold


def test_threshold_trigger_fires_on_latest_value() -> None:
    outcomes = evaluate_triggers(
        [ThresholdTrigger(name="cash floor", field="cash", operator="<", threshold=60.0)],
        _window(),
        baseline_final_state={},
    )
    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.fired is True
    assert outcome.status == "fired"
    assert outcome.observed_value == 55.0
    assert outcome.observation_ids == ["obs-1", "obs-2", "obs-3"]
    assert outcome.observed_values == [90.0, 70.0, 55.0]


def test_threshold_trigger_quiet_when_latest_value_holds() -> None:
    outcomes = evaluate_triggers(
        [ThresholdTrigger(name="cash floor", field="cash", operator="<", threshold=50.0)],
        _window(),
        baseline_final_state={},
    )
    assert outcomes[0].fired is False
    assert outcomes[0].status == "quiet"


def test_threshold_trigger_ignores_older_breach_once_recovered() -> None:
    window = [
        _observation("obs-1", "cash", 40.0, "2026-03-10T00:00:00.000000Z"),
        _observation("obs-2", "cash", 80.0, "2026-03-20T00:00:00.000000Z"),
    ]
    outcomes = evaluate_triggers(
        [ThresholdTrigger(name="cash floor", field="cash", operator="<", threshold=60.0)],
        window,
        baseline_final_state={},
    )
    # The latest value holds: the trigger tests the current state, and the
    # older breach stays visible in observed_values without firing.
    assert outcomes[0].fired is False
    assert outcomes[0].observed_values == [40.0, 80.0]


def test_trigger_with_no_field_observations_is_no_data() -> None:
    outcomes = evaluate_triggers(
        [ThresholdTrigger(name="churn watch", field="churn", operator=">", threshold=0.1)],
        _window(),
        baseline_final_state={},
    )
    assert outcomes[0].status == "no_data"
    assert outcomes[0].fired is False
    assert outcomes[0].observed_value is None


# ------------------------------------------------------------------- gate


def test_gate_trigger_mean_over_window() -> None:
    outcomes = evaluate_triggers(
        [
            GateTrigger(
                name="mean cash",
                field="cash",
                gate=GateDefinition(name="g", metric="mean", operator="<", threshold=75.0),
            )
        ],
        _window(),
        baseline_final_state={},
    )
    outcome = outcomes[0]
    # mean(90, 70, 55) = 71.67 < 75 -> fires.
    assert outcome.fired is True
    assert outcome.status == "fired"
    assert outcome.observed_value == pytest.approx(71.66666666666667)


def test_gate_trigger_p_loss_needs_loss_threshold() -> None:
    with pytest.raises(ValidationError, match="loss_threshold"):
        GateTrigger(
            name="p loss",
            field="cash",
            gate=GateDefinition(name="g", metric="p_loss", operator=">", threshold=0.5),
        )


def test_gate_trigger_p_loss_over_observations() -> None:
    outcomes = evaluate_triggers(
        [
            GateTrigger(
                name="p loss",
                field="cash",
                gate=GateDefinition(name="g", metric="p_loss", operator=">", threshold=0.5),
                loss_threshold=80.0,
            )
        ],
        _window(),
        baseline_final_state={},
    )
    # 2 of 3 observations below 80 -> p_loss 2/3 > 0.5 -> fires.
    assert outcomes[0].fired is True
    assert outcomes[0].observed_value == pytest.approx(2 / 3)


def test_gate_trigger_refuses_paired_metrics() -> None:
    with pytest.raises(ValidationError, match="paired statistic"):
        GateTrigger(
            name="delta",
            field="cash",
            gate=GateDefinition(
                name="g", metric="mean_delta", operator=">", threshold=0.0, arm="paired"
            ),
        )


def test_gate_trigger_refuses_non_baseline_arm() -> None:
    with pytest.raises(ValidationError, match="must be 'baseline'"):
        GateTrigger(
            name="strategy mean",
            field="cash",
            gate=GateDefinition(
                name="g", metric="mean", operator=">", threshold=0.0, arm="strategy"
            ),
        )


# -------------------------------------------------------------- deviation


def test_deviation_trigger_requires_consecutive_breaches() -> None:
    window = [
        _observation("obs-1", "cash", 60.0, "2026-03-10T00:00:00.000000Z"),
        _observation("obs-2", "cash", 98.0, "2026-03-15T00:00:00.000000Z"),
        _observation("obs-3", "cash", 55.0, "2026-03-20T00:00:00.000000Z"),
    ]
    outcomes = evaluate_triggers(
        [
            DeviationTrigger(
                name="cash drift",
                field="cash",
                tolerance=10.0,
                consecutive=2,
                reference_value=100.0,
            )
        ],
        window,
        baseline_final_state={},
    )
    # Breaches at obs-1 and obs-3 are separated by an in-tolerance
    # reading: longest run is 1, required 2 -> quiet.
    assert outcomes[0].fired is False
    assert outcomes[0].consecutive_breaches == 1
    assert outcomes[0].observed_value == pytest.approx(45.0)


def test_deviation_trigger_fires_on_consecutive_run() -> None:
    window = [
        _observation("obs-1", "cash", 60.0, "2026-03-10T00:00:00.000000Z"),
        _observation("obs-2", "cash", 55.0, "2026-03-15T00:00:00.000000Z"),
        _observation("obs-3", "cash", 99.0, "2026-03-20T00:00:00.000000Z"),
    ]
    outcomes = evaluate_triggers(
        [
            DeviationTrigger(
                name="cash drift",
                field="cash",
                tolerance=10.0,
                consecutive=2,
                reference_value=100.0,
            )
        ],
        window,
        baseline_final_state={},
    )
    assert outcomes[0].fired is True
    assert outcomes[0].consecutive_breaches == 2


def test_deviation_trigger_uses_baseline_final_state_reference() -> None:
    outcomes = evaluate_triggers(
        [DeviationTrigger(name="cash drift", field="cash", tolerance=5.0, consecutive=1)],
        _window(),
        baseline_final_state={"cash": 100.0},
    )
    assert outcomes[0].fired is True
    assert outcomes[0].reference_value == 100.0


def test_deviation_trigger_missing_baseline_reference_raises() -> None:
    with pytest.raises(ValueError, match="no reference value"):
        evaluate_triggers(
            [DeviationTrigger(name="cash drift", field="cash", tolerance=5.0, consecutive=1)],
            _window(),
            baseline_final_state={"pipeline": 1.0},
        )


def test_evaluation_preserves_trigger_order_and_mixed_kinds() -> None:
    outcomes = evaluate_triggers(
        [
            ThresholdTrigger(name="t", field="cash", operator="<", threshold=60.0),
            GateTrigger(
                name="g",
                field="cash",
                gate=GateDefinition(name="g", metric="p50", operator=">", threshold=0.0),
            ),
            DeviationTrigger(name="d", field="cash", tolerance=1.0, consecutive=1),
        ],
        _window(),
        baseline_final_state={"cash": 100.0},
    )
    assert [outcome.name for outcome in outcomes] == ["t", "g", "d"]
    assert [outcome.kind.value for outcome in outcomes] == ["threshold", "gate", "deviation"]


def test_format_cutoff_round_trip_for_window_bounds() -> None:
    assert format_cutoff(normalize_cutoff(datetime(2026, 3, 1, 12, 30))) == (
        "2026-03-01T12:30:00.000000Z"
    )

"""Tests for the two-value output (Step 4, 2026-11-24; Ho 10:51/10:55).

(a) normal value + (b) opportunity-leg contribution, separately stated,
never merged. Goldens are the frozen decomposition's measured tick3
numbers (anchor-frozen-decomposition-2026-11-24/REPORT.md §1/§3,
anchor arm, trials=20, seed 42): full P50/replay, frozen-both P50
(= replay — degenerate frozen MC), per-leg frozen P50s, yr3 actuals.
"""

from __future__ import annotations

import pytest

from planagent.services.variables.models import (
    VariableDefinition,
    VariableDistribution,
)
from planagent.services.variables.opportunities import detect_discount_prompts
from planagent.services.variables.opportunity_value import (
    LegInput,
    OutcomeRecord,
    TwoValueRequest,
    compute_two_value_output,
    discounted_growth_contribution,
)


def _rec(p50: float, replay: float | None, **kw) -> OutcomeRecord:
    return OutcomeRecord(
        metric="revenue",
        unit="RMB m",
        horizon_tick=3,
        horizon_label="yr3",
        p50=p50,
        replay=replay,
        seed=42,
        trials=20,
        **kw,
    )


def _desay_2015_two_leg() -> TwoValueRequest:
    return TwoValueRequest(
        case_id="desay-2015",
        metric="revenue",
        unit="RMB m",
        horizon_tick=3,
        horizon_label="yr3",
        full=_rec(7541.0392, 6503.7701),
        stripped_all=_rec(4789.2662, 4789.2662),
        legs=[
            LegInput(
                leg_id="backlog", label="order-book backlog", stripped=_rec(5145.5631, 5145.5631)
            ),
            LegInput(leg_id="adas", label="ADAS chain", stripped=_rec(6105.8924, 6105.8924)),
        ],
        actual=5408.74,
        sizing="decision_time",
        legs_note="backlog_conversion=0; adas_coupling=0 + adas_share_coupling=0",
    )


def _desay_2020_two_leg() -> TwoValueRequest:
    return TwoValueRequest(
        case_id="desay-2020",
        metric="revenue",
        unit="RMB m",
        horizon_tick=3,
        horizon_label="yr3",
        full=_rec(29726.4454, 24801.2145),
        stripped_all=_rec(11411.4313, 11411.4313),
        legs=[
            LegInput(
                leg_id="backlog", label="order-book backlog", stripped=_rec(13276.7288, 13276.7288)
            ),
            LegInput(leg_id="adas", label="ADAS chain", stripped=_rec(22213.8106, 22213.8106)),
        ],
        actual=21908,
        sizing="decision_time",
        legs_note="backlog_conversion=0; adas_coupling=0 + adas_share_coupling=0",
    )


def test_desay_2015_two_value_matches_frozen_decomposition() -> None:
    out = compute_two_value_output(_desay_2015_two_leg())
    # Per-leg clean contributions (replay level).
    by_id = {c.leg_id: c for c in out.contributions}
    assert by_id["backlog"].clean_contribution == pytest.approx(1358.21, abs=0.01)
    assert by_id["adas"].clean_contribution == pytest.approx(397.88, abs=0.01)
    assert by_id["backlog"].clean_pct_of_overshoot == pytest.approx(63.7, abs=0.1)
    assert by_id["adas"].clean_pct_of_overshoot == pytest.approx(18.7, abs=0.1)
    # Total clean + interaction (legs are near-additive, -2.4%).
    assert out.opportunity_total_clean == pytest.approx(1714.50, abs=0.01)
    assert out.interaction_clean == pytest.approx(-41.58, abs=0.01)
    # Apparent total carries the ensemble-vs-path gap.
    assert out.opportunity_total_apparent == pytest.approx(2751.77, abs=0.01)
    assert out.ensemble_gap == pytest.approx(1037.27, abs=0.01)
    # (a) normal, both levels; residual vs the yr3 actual.
    assert out.normal_frozen_p50 == pytest.approx(4789.27, abs=0.01)
    assert out.normal_adjusted_p50 == pytest.approx(5826.54, abs=0.01)
    assert out.residual_adjusted_p50 == pytest.approx(417.80, abs=0.01)
    assert out.residual_adjusted_pct == pytest.approx(7.7, abs=0.1)
    assert out.residual_frozen_p50 == pytest.approx(-619.47, abs=0.01)
    # Combined reference is the identity, never a forecast.
    assert out.combined_reference_p50 == pytest.approx(7541.04, abs=0.01)
    assert out.sizing == "decision_time"
    assert out.legs_stripped == ["backlog", "adas"]
    assert any("degenerate" in note for note in out.notes)


def test_desay_2020_two_value_matches_frozen_decomposition() -> None:
    out = compute_two_value_output(_desay_2020_two_leg())
    by_id = {c.leg_id: c for c in out.contributions}
    assert by_id["backlog"].clean_contribution == pytest.approx(11524.49, abs=0.01)
    assert by_id["adas"].clean_contribution == pytest.approx(2587.40, abs=0.01)
    # One leg alone exceeds the whole overshoot — real, not an error.
    assert by_id["backlog"].clean_pct_of_overshoot == pytest.approx(147.4, abs=0.1)
    assert out.opportunity_total_clean == pytest.approx(13389.78, abs=0.01)
    assert out.interaction_clean == pytest.approx(-722.11, abs=0.01)
    assert out.opportunity_total_apparent == pytest.approx(18315.01, abs=0.01)
    assert out.ensemble_gap == pytest.approx(4925.23, abs=0.01)
    # Ho's quoted normal: two legs off, -25.4% vs the yr3 actual.
    assert out.normal_adjusted_p50 == pytest.approx(16336.66, abs=0.01)
    assert out.residual_adjusted_p50 == pytest.approx(-5571.34, abs=0.01)
    assert out.residual_adjusted_pct == pytest.approx(-25.4, abs=0.1)
    # The frozen normal sits far below the actual: zeroing the legs
    # overshoots — the fix is a partial cut, not zeroing (report §0).
    assert out.normal_frozen_p50 == pytest.approx(11411.43, abs=0.01)
    assert out.residual_frozen_pct == pytest.approx(-47.9, abs=0.1)
    assert out.combined_reference_p50 == pytest.approx(29726.45, abs=0.01)


def test_mismatched_pairs_raise_instead_of_mixing() -> None:
    base = _desay_2015_two_leg()
    with pytest.raises(ValueError, match="metric"):
        compute_two_value_output(
            base.model_copy(
                update={"stripped_all": _rec(1.0, 1.0).model_copy(update={"metric": "profit"})}
            )
        )
    with pytest.raises(ValueError, match="seed"):
        compute_two_value_output(
            base.model_copy(update={"stripped_all": _rec(1.0, 1.0).model_copy(update={"seed": 7})})
        )
    with pytest.raises(ValueError, match="trials"):
        compute_two_value_output(
            base.model_copy(
                update={"stripped_all": _rec(1.0, 1.0).model_copy(update={"trials": 50})}
            )
        )
    with pytest.raises(ValueError, match="horizon_tick"):
        compute_two_value_output(
            base.model_copy(
                update={"stripped_all": _rec(1.0, 1.0).model_copy(update={"horizon_tick": 5})}
            )
        )


def test_missing_replay_keeps_apparent_but_not_clean() -> None:
    req = _desay_2015_two_leg()
    req = req.model_copy(
        update={"full": _rec(7541.0392, None), "stripped_all": _rec(4789.2662, None)}
    )
    out = compute_two_value_output(req)
    assert out.opportunity_total_clean is None
    assert out.interaction_clean is None
    assert out.normal_adjusted_p50 is None
    assert out.ensemble_gap is None
    assert out.opportunity_total_apparent == pytest.approx(2751.77, abs=0.01)
    assert out.normal_frozen_p50 == pytest.approx(4789.27, abs=0.01)
    assert all(c.clean_contribution is None for c in out.contributions)


def test_discounted_growth_prompt_derives_arithmetic_contribution() -> None:
    variables = [
        VariableDefinition(
            id="revenue",
            unit="RMB m",
            distribution=VariableDistribution(type="triangular", min=6200, mode=6799.06, max=7400),
            evidence_ref="estimate: test",
        ),
        VariableDefinition(
            id="revenue_growth",
            unit="per-year",
            distribution=VariableDistribution(type="triangular", min=0.05, mode=0.15, max=0.30),
            evidence_ref="estimate: test",
            description="无采用时的年均收入增长率",
            observed_value=0.2739,
            observed_label="2020年收入同比 +27.39%（恢复年）",
        ),
    ]
    prompts = detect_discount_prompts(variables, 5)
    assert len(prompts) == 1
    contrib = discounted_growth_contribution(prompts[0])
    assert contrib.opportunity_id == "discounted-growth:revenue_growth"
    # TRACK9 §4.1: projected 22810.01 vs 13675.34 at horizon 5.
    assert contrib.projected_observed == pytest.approx(22810.01, abs=0.01)
    assert contrib.projected_discounted == pytest.approx(13675.34, abs=0.01)
    assert contrib.contribution == pytest.approx(9134.67, abs=0.01)
    assert contrib.horizon_ticks == 5
    assert contrib.caveat


def test_discounted_prompt_without_level_pair_has_no_contribution() -> None:
    variables = [
        VariableDefinition(
            id="revenue_growth",
            unit="per-year",
            distribution=VariableDistribution(type="triangular", min=0.05, mode=0.15, max=0.30),
            evidence_ref="estimate: test",
            observed_value=0.2739,
            observed_label="2020年收入同比 +27.39%（恢复年）",
        ),
    ]
    prompts = detect_discount_prompts(variables, 5)
    assert len(prompts) == 1
    contrib = discounted_growth_contribution(prompts[0])
    assert contrib.contribution is None
    assert contrib.projected_observed is None

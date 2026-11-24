"""Tests for the Step 1 downside headline (H1/H2/saturation).

Pure-function tests only: no runs, no database, no network. The frozen
numbers cited here are the e047f50 OFF baseline and Track C ON numbers
(TRACK-C §4.3) — they pin the arithmetic, they are not fitted to any
case. The saturation tests prove the verdict follows from the
arithmetic, not from a case name: the same growth factors with a wider
depth support, and the same support with slower factors, must both
flip the verdict.
"""

from __future__ import annotations

import pytest

from planagent.services.simulation.downside_headline import (
    INFORMATIVE,
    SATURATED,
    STRUCTURAL,
    assess_decline_saturation,
    assess_loss_saturation,
    downside_drag,
    max_window_rise,
    max_window_rise_over_support,
    relative_shortfall,
    saturation_label_zh,
)


# ---------------------------------------------------------------------------
# H1 — downside drag (frozen TRACK-C §4.3 numbers).
# ---------------------------------------------------------------------------


def test_drag_2020_b_revenue_matches_track_c() -> None:
    drag = downside_drag(
        off_p50=38721.6944,
        off_p10=36137.8763,
        on_p50=36376.64,
        on_p10=20637.44,
    )
    assert drag.delta_p50_pct == pytest.approx(-6.1, abs=0.05)
    assert drag.delta_p10_pct == pytest.approx(-42.9, abs=0.05)


def test_drag_2020_anchor_revenue_matches_track_c() -> None:
    # ON anchor values from Track C raw-gap-c (03b), OFF from the e047f50 rerun.
    drag = downside_drag(
        off_p50=60303.1553,
        off_p10=50560.3128,
        on_p50=49130.2548,
        on_p10=27233.0219,
    )
    assert drag.delta_p50_pct == pytest.approx(-18.5, abs=0.05)
    assert drag.delta_p10_pct == pytest.approx(-46.1, abs=0.05)


def test_drag_2015_b_and_huawei_b_revenue() -> None:
    # ON values from Track C raw-gap-c / raw-gap-c-classic (06b files).
    drag_2015 = downside_drag(
        off_p50=8778.0068, off_p10=8407.7518, on_p50=8587.644, on_p10=4599.9537
    )
    assert drag_2015.delta_p50_pct == pytest.approx(-2.2, abs=0.05)
    assert drag_2015.delta_p10_pct == pytest.approx(-45.3, abs=0.05)
    drag_huawei = downside_drag(
        off_p50=1339.6083, off_p10=1218.2159, on_p50=1283.6213, on_p10=662.0589
    )
    assert drag_huawei.delta_p50_pct == pytest.approx(-4.2, abs=0.05)
    assert drag_huawei.delta_p10_pct == pytest.approx(-45.7, abs=0.05)


def test_drag_zero_off_baseline_is_refused() -> None:
    with pytest.raises(ValueError):
        downside_drag(off_p50=0.0, off_p10=10.0, on_p50=9.0, on_p10=9.0)
    with pytest.raises(ValueError):
        downside_drag(off_p50=10.0, off_p10=0.0, on_p50=9.0, on_p10=9.0)


# ---------------------------------------------------------------------------
# H2 — relative shortfall against the arm's OWN OFF P10.
# ---------------------------------------------------------------------------


def test_shortfall_counts_strictly_below_own_off_p10() -> None:
    # 10 of 20 below; a value exactly at the threshold does NOT count.
    values = [100.0] * 10 + [200.0] * 9 + [150.0]
    assert relative_shortfall(values, 150.0) == 0.5


def test_shortfall_empty_ensemble_is_zero() -> None:
    assert relative_shortfall([], 150.0) == 0.0


def test_shortfall_old_anchor_threshold_would_be_uninformative() -> None:
    # The old (wrong) threshold — the anchor's OFF P10 — makes a B arm
    # whose whole distribution sits below the anchor score 1.00.
    # The own-P10 threshold on the same values is informative instead.
    on_values = [30000.0 + 1000.0 * i for i in range(20)]  # 30000..49000
    assert relative_shortfall(on_values, 50560.3128) == 1.0  # anchor P10
    assert relative_shortfall(on_values, 36137.8763) == 0.35  # own OFF P10


# ---------------------------------------------------------------------------
# Window rise — reproduces the diagnosis table (plan §1.2).
# ---------------------------------------------------------------------------


def test_max_window_rise_reproduces_diagnosis_table() -> None:
    assert max_window_rise(1.0) == pytest.approx(0.626, abs=0.002)
    assert max_window_rise(2.0) == pytest.approx(0.558, abs=0.002)
    assert max_window_rise(3.0) == pytest.approx(0.504, abs=0.002)
    assert max_window_rise(2.0, persistent=1.0) == pytest.approx(0.462, abs=0.002)


def test_max_window_rise_over_support_is_the_most_favourable_form() -> None:
    assert max_window_rise_over_support() == pytest.approx(0.626, abs=0.002)
    assert max_window_rise_over_support((2.0, 3.0)) == pytest.approx(
        0.558, abs=0.002
    )


def test_max_window_rise_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError):
        max_window_rise(0.0)
    with pytest.raises(ValueError):
        max_window_rise(2.0, persistent=1.5)
    with pytest.raises(ValueError):
        max_window_rise_over_support(())


# ---------------------------------------------------------------------------
# Saturation — decline_p on the mode path (plan §1.2/§1.3).
# ---------------------------------------------------------------------------

RISE = 0.626  # most favourable single-tick rise (duration=1), diagnosis §1.2


def test_decline_2020_mode_path_is_saturated() -> None:
    result = assess_decline_saturation(
        [1.621, 1.5959, 1.5183, 1.4873], depth_high=0.35, max_rise=RISE
    )
    assert result.category == SATURATED
    assert result.required_depth == pytest.approx(0.524, abs=0.002)
    assert result.slowest_growth == pytest.approx(1.4873)
    assert "饱和" in result.label_zh and "支撑外" in result.label_zh


def test_decline_2015_mode_path_is_informative() -> None:
    result = assess_decline_saturation(
        [1.2316, 1.2614, 1.2613, 1.2622], depth_high=0.35, max_rise=RISE
    )
    assert result.category == INFORMATIVE
    # Binding tick is the slowest (1.2316): (1 − 1/1.2316) / 0.626 ≈ 0.300.
    # (The plan's 0.206 is the jump-threshold at the representative g≈1.26.)
    assert result.required_depth == pytest.approx(0.300, abs=0.002)


def test_decline_same_factors_flip_with_wider_support() -> None:
    """No case is hardcoded saturated: widen the support, same factors flip."""
    result = assess_decline_saturation(
        [1.621, 1.5959, 1.5183, 1.4873], depth_high=0.60, max_rise=RISE
    )
    assert result.category == INFORMATIVE
    assert result.required_depth == pytest.approx(0.524, abs=0.002)


def test_decline_same_support_flips_with_slower_growth() -> None:
    """No support is hardcoded either: slower factors flip at depth 0.35."""
    result = assess_decline_saturation(
        [1.20, 1.22, 1.19, 1.21], depth_high=0.35, max_rise=RISE
    )
    assert result.category == INFORMATIVE


def test_decline_structural_when_mode_path_already_falls() -> None:
    # The Nokia end: a mode path that declines with no shock at all.
    result = assess_decline_saturation(
        [0.92, 0.95, 0.88, 0.97], depth_high=0.35, max_rise=RISE
    )
    assert result.category == STRUCTURAL
    assert result.required_depth is None
    assert "结构性" in result.label_zh


def test_decline_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError):
        assess_decline_saturation([], depth_high=0.35, max_rise=RISE)
    with pytest.raises(ValueError):
        assess_decline_saturation([1.5], depth_high=0.0, max_rise=RISE)
    with pytest.raises(ValueError):
        assess_decline_saturation([1.5], depth_high=0.35, max_rise=0.0)


# ---------------------------------------------------------------------------
# Saturation — p_loss on the mode path (plan §1.5).
# ---------------------------------------------------------------------------


def test_loss_2020_and_2015_mode_paths_are_saturated() -> None:
    result_2020 = assess_loss_saturation(5.842, depth_high=0.35)
    assert result_2020.category == SATURATED
    assert result_2020.required_cumulative_hit == pytest.approx(0.829, abs=0.002)
    result_2015 = assess_loss_saturation(2.473, depth_high=0.35)
    assert result_2015.category == SATURATED
    assert result_2015.required_cumulative_hit == pytest.approx(0.596, abs=0.002)


def test_loss_informative_when_cumulative_growth_is_small() -> None:
    result = assess_loss_saturation(1.2, depth_high=0.35)
    assert result.category == INFORMATIVE
    assert result.required_cumulative_hit == pytest.approx(0.167, abs=0.002)


def test_loss_structural_when_mode_path_ends_below_start() -> None:
    result = assess_loss_saturation(0.8, depth_high=0.35)
    assert result.category == STRUCTURAL
    assert result.required_cumulative_hit is None


def test_loss_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError):
        assess_loss_saturation(0.0, depth_high=0.35)
    with pytest.raises(ValueError):
        assess_loss_saturation(2.0, depth_high=0.0)


def test_saturation_label_zh_rejects_unknown_category() -> None:
    with pytest.raises(ValueError):
        saturation_label_zh("nope")

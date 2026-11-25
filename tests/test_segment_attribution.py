"""Tests for the realized segment attribution (Huawei rethink §4, 2026-11-25).

Goldens are the rethink report §4.2/§10 numbers (RMB 100M, i.e. 亿):

- overseas leg +1167.04 (1204.1 - 926.4655 x 4%),
- domestic offset -241.71 (647.7 - 926.4655 x 96%),
- net +925.33 against a gap of +925.53 — residual -0.20 is source
  rounding (segment actuals sum to 1851.8, the reported total is
  1852), tolerated by the 0.25 balance band, not hidden.
"""

from __future__ import annotations

import pytest

from planagent.services.variables.segment_attribution import (
    SegmentAttributionInput,
    attribute_residual_by_segment,
    compare_opportunity_estimates,
)

#: Huawei-2010 sourced numbers (rethink §10.1).
HUAWEI_NORMAL_VALUE = 926.4655
HUAWEI_ACTUAL_TOTAL = 1852
HUAWEI_BASE_SHARES = {"overseas": 0.04, "domestic": 0.96}
HUAWEI_ACTUALS = {"overseas": 1204.1, "domestic": 647.7}


def _huawei_input() -> SegmentAttributionInput:
    return SegmentAttributionInput(
        normal_value=HUAWEI_NORMAL_VALUE,
        actual_total=HUAWEI_ACTUAL_TOTAL,
        base_shares=dict(HUAWEI_BASE_SHARES),
        actuals=dict(HUAWEI_ACTUALS),
    )


def test_huawei_attribution_golden() -> None:
    out = attribute_residual_by_segment(_huawei_input())
    by_segment = {leg.segment: leg for leg in out.legs}
    assert by_segment["overseas"].contribution == pytest.approx(1167.04, abs=0.01)
    assert by_segment["overseas"].normal_caliber == pytest.approx(37.06, abs=0.01)
    assert by_segment["domestic"].contribution == pytest.approx(-241.71, abs=0.01)
    assert by_segment["domestic"].normal_caliber == pytest.approx(889.41, abs=0.01)
    assert out.net == pytest.approx(925.33, abs=0.01)
    assert out.gap == pytest.approx(925.53, abs=0.01)
    # The 0.2 residue is source rounding, recorded not hidden.
    assert out.residual == pytest.approx(-0.20, abs=0.01)
    assert out.balanced is True
    assert out.sizing == "retrospective"


def test_attribution_rejects_non_retrospective_sizing() -> None:
    with pytest.raises(ValueError, match="retrospective"):
        attribute_residual_by_segment(
            SegmentAttributionInput(
                normal_value=HUAWEI_NORMAL_VALUE,
                actual_total=HUAWEI_ACTUAL_TOTAL,
                base_shares=dict(HUAWEI_BASE_SHARES),
                actuals=dict(HUAWEI_ACTUALS),
                sizing="decision_time",
            )
        )


def test_attribution_rejects_mismatched_segments() -> None:
    with pytest.raises(ValueError, match="must match"):
        attribute_residual_by_segment(
            SegmentAttributionInput(
                normal_value=HUAWEI_NORMAL_VALUE,
                actual_total=HUAWEI_ACTUAL_TOTAL,
                base_shares=dict(HUAWEI_BASE_SHARES),
                actuals={"overseas": 1204.1},
            )
        )


def test_attribution_rejects_shares_not_summing_to_one() -> None:
    with pytest.raises(ValueError, match="must sum to 1"):
        attribute_residual_by_segment(
            SegmentAttributionInput(
                normal_value=HUAWEI_NORMAL_VALUE,
                actual_total=HUAWEI_ACTUAL_TOTAL,
                base_shares={"overseas": 0.04, "domestic": 0.90},
                actuals=dict(HUAWEI_ACTUALS),
            )
        )


def test_attribution_flags_real_imbalance() -> None:
    """A residual beyond the rounding band is a real imbalance, not
    rounding: balanced False, with the warning note."""
    out = attribute_residual_by_segment(
        SegmentAttributionInput(
            normal_value=HUAWEI_NORMAL_VALUE,
            actual_total=2000,  # wrong total: gap 1073.53 vs net 925.33
            base_shares=dict(HUAWEI_BASE_SHARES),
            actuals=dict(HUAWEI_ACTUALS),
        )
    )
    assert out.balanced is False
    assert out.residual == pytest.approx(-148.20, abs=0.01)
    assert any("UNBALANCED" in note for note in out.notes)


def test_cross_check_huawei_agrees() -> None:
    """Satellite (b) 1167.04 vs the attribution's overseas leg 1167.04:
    zero relative difference — the two routes are the same assumption
    under two algorithms, so agreement is expected, not a discovery."""
    check = compare_opportunity_estimates(satellite_b=1167.04, attribution_b=1167.04)
    assert check.relative_difference == pytest.approx(0.0, abs=1e-9)
    assert check.within_tolerance is True
    assert check.alarm is False


def test_cross_check_alarms_on_disagreement() -> None:
    """A 22.9% disagreement exceeds the ±15% band: alarm."""
    check = compare_opportunity_estimates(satellite_b=900.0, attribution_b=1167.04)
    assert check.relative_difference == pytest.approx(0.229, abs=0.001)
    assert check.within_tolerance is False
    assert check.alarm is True


def test_cross_check_zero_attribution_leg_alarms() -> None:
    check = compare_opportunity_estimates(satellite_b=100.0, attribution_b=0.0)
    assert check.relative_difference is None
    assert check.alarm is True

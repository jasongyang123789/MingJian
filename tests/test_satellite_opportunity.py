"""Tests for the satellite scenario model (Huawei rethink, 2026-11-25).

The satellite prices an opportunity that lives OUTSIDE the model as
overseas revenue = addressable market x share. Goldens are the
rethink report §3/§10 numbers (all in RMB 100M, i.e. 亿):

- retrospective (b) ≈ 1167.04: realized overseas 1204.1 minus
  normal-caliber overseas 926.4655 x 4% = 37.06. The 2010 market is
  the IMPLIED addressable market (realized overseas / Gartner share
  15.7% = 7669.43) — derived, not observed — because the Gartner
  market ($78.6B ≈ 6508.1) x 15.7% gives 1021.8, not 1204.1: Huawei's
  overseas revenue spans more than the Gartner market definition.
- decision-time sensitivity (rethink §3.2 grid): overseas-growth mode
  30%/yr -> overseas ~114.4 -> (b) ~77; 40% -> ~203; 50% -> ~442.
"""

from __future__ import annotations

import pytest

from planagent.services.variables.satellite_opportunity import (
    LogisticShare,
    MarketPoint,
    SatelliteScenario,
    SharePoint,
    ShareTrajectory,
    satellite_leg_input,
    satellite_overseas,
    satellite_overseas_from_growth,
    share_at,
)

#: Huawei-2010 sourced numbers (rethink §10.1).
HUAWEI_NORMAL_VALUE = 926.4655
HUAWEI_OVERSEAS_ACTUAL = 1204.1
HUAWEI_OVERSEAS_SHARE_2000 = 0.04
HUAWEI_SHARE_2010 = 0.157


def _huawei_retrospective_scenario() -> SatelliteScenario:
    # Implied addressable market, computed from the sourced numbers in
    # the test (not hardcoded): realized overseas / Gartner share.
    implied_market_2010 = HUAWEI_OVERSEAS_ACTUAL / HUAWEI_SHARE_2010
    return SatelliteScenario(
        case_id="huawei-2000",
        metric="revenue",
        unit="RMB 100M",
        base_year=2000,
        base_overseas=8.3,
        horizon_year=2010,
        market=[MarketPoint(year=2010, p50=implied_market_2010)],
        share=ShareTrajectory(
            kind="table", points=[SharePoint(year=2010, share=HUAWEI_SHARE_2010)]
        ),
        normal_value=HUAWEI_NORMAL_VALUE,
        normal_overseas_share=HUAWEI_OVERSEAS_SHARE_2000,
        sizing="retrospective",
        market_source="Gartner 2010 global carrier network infrastructure market ($78.6B) via China Daily 2011-04-28",
        share_source="Gartner via China Daily 2011-04-28: Huawei 15.7% of the 2010 global carrier network infrastructure market",
        market_basis="implied: realized overseas 1204.1 / share 0.157 = 7669.43 — DERIVED, not observed",
        share_basis="Gartner 2010 share 15.7%",
    )


def test_huawei_retrospective_b_is_1167() -> None:
    result = satellite_overseas(_huawei_retrospective_scenario())
    assert result.overseas_p50 == pytest.approx(HUAWEI_OVERSEAS_ACTUAL, abs=0.01)
    assert result.normal_overseas == pytest.approx(37.06, abs=0.01)
    assert result.opportunity_b_p50 == pytest.approx(1167.04, abs=0.01)
    assert result.sizing == "retrospective"
    assert result.share_at_horizon == pytest.approx(HUAWEI_SHARE_2010)
    # No band claimed: P10/P90 stay None rather than inventing one.
    assert result.overseas_p10 is None
    assert result.opportunity_b_p10 is None
    # The derived-market basis is recorded, not hidden.
    assert any("DERIVED" in note for note in result.notes)
    assert any("retrospective" in note for note in result.notes)


def test_huawei_retrospective_b_with_market_band() -> None:
    """A ±10% market band propagates to the (b) band; the P50 is unchanged."""
    scenario = _huawei_retrospective_scenario()
    market = scenario.market[0]
    scenario = scenario.model_copy(
        update={
            "market": [
                MarketPoint(year=2010, p50=market.p50, p10=market.p50 * 0.9, p90=market.p50 * 1.1)
            ]
        }
    )
    result = satellite_overseas(scenario)
    assert result.opportunity_b_p50 == pytest.approx(1167.04, abs=0.01)
    assert result.opportunity_b_p10 == pytest.approx(1167.04 - 120.41, abs=0.01)
    assert result.opportunity_b_p90 == pytest.approx(1167.04 + 120.41, abs=0.01)


def test_decision_time_sensitivity_grid() -> None:
    """Rethink §3.2 grid: even an aggressive 50%/yr ex-ante overseas
    growth assumption reaches only ~442 — under half the gap. The
    ex-ante (b) can never cover the realized gap."""
    sensitivity = satellite_overseas_from_growth(
        base_overseas=8.3,
        growth_low=0.20,
        growth_mode=0.30,
        growth_high=0.50,
        years=10,
        normal_overseas=HUAWEI_NORMAL_VALUE * HUAWEI_OVERSEAS_SHARE_2000,
    )
    assert sensitivity.overseas_p50 == pytest.approx(114.4, abs=0.1)
    assert sensitivity.opportunity_b_p50 == pytest.approx(77.3, abs=0.1)
    assert sensitivity.opportunity_b_p90 == pytest.approx(441.5, abs=0.1)
    assert sensitivity.opportunity_b_p90 < 925.53 / 2  # under half the gap
    assert sensitivity.opportunity_b_p10 == pytest.approx(14.3, abs=0.1)


def test_growth_sensitivity_rejects_inverted_triple() -> None:
    with pytest.raises(ValueError, match="low <= mode <= high"):
        satellite_overseas_from_growth(
            base_overseas=8.3,
            growth_low=0.40,
            growth_mode=0.30,
            growth_high=0.50,
            years=10,
            normal_overseas=37.06,
        )


def test_share_table_interpolates_and_holds_endpoints() -> None:
    trajectory = ShareTrajectory(
        kind="table",
        points=[
            SharePoint(year=2000, share=0.03),
            SharePoint(year=2005, share=0.08),
            SharePoint(year=2010, share=0.157),
        ],
    )
    assert share_at(trajectory, 2000) == pytest.approx(0.03)
    assert share_at(trajectory, 2010) == pytest.approx(0.157)
    # Linear interpolation: 2002 is 2/5 of the way 0.03 -> 0.08.
    assert share_at(trajectory, 2002) == pytest.approx(0.05)
    # Outside the range: hold the nearest endpoint (a milestone table
    # does not extrapolate a trend it never stated).
    assert share_at(trajectory, 1998) == pytest.approx(0.03)
    assert share_at(trajectory, 2012) == pytest.approx(0.157)


def test_share_logistic_curve() -> None:
    trajectory = ShareTrajectory(
        kind="logistic",
        logistic=LogisticShare(ceiling=0.20, steepness=0.5, midpoint_year=2005),
    )
    assert share_at(trajectory, 2005) == pytest.approx(0.10)
    assert share_at(trajectory, 2000) < share_at(trajectory, 2005)
    assert share_at(trajectory, 2010) > share_at(trajectory, 2005)
    assert share_at(trajectory, 2010) < 0.20


def test_scenario_requires_horizon_market_point() -> None:
    with pytest.raises(ValueError, match="no point for horizon year"):
        SatelliteScenario(
            case_id="huawei-2000",
            base_year=2000,
            base_overseas=8.3,
            horizon_year=2010,
            market=[MarketPoint(year=2005, p50=1000.0)],
            share=ShareTrajectory(
                kind="table", points=[SharePoint(year=2010, share=0.157)]
            ),
            normal_value=HUAWEI_NORMAL_VALUE,
            normal_overseas_share=0.04,
            sizing="retrospective",
        )


def test_satellite_leg_input_builds_p50_only_leg() -> None:
    scenario = _huawei_retrospective_scenario()
    result = satellite_overseas(scenario)
    leg = satellite_leg_input(
        leg_id="overseas_expansion",
        label="overseas expansion (3G/NGN cycle)",
        scenario=scenario,
        result=result,
        horizon_tick=10,
        horizon_label="yr10",
    )
    assert leg.source == "satellite"
    assert leg.sizing == "retrospective"
    assert leg.stripped.p50 == pytest.approx(37.06, abs=0.01)
    assert leg.scenario is not None
    assert leg.scenario.p50 == pytest.approx(1204.1, abs=0.01)
    # P50-only: no replay is fabricated for the clean level.
    assert leg.stripped.replay is None
    assert leg.scenario.replay is None
    assert leg.satellite_params is not None
    assert "Gartner" in leg.satellite_params.share_source
    assert "DERIVED" in leg.satellite_params.market_basis

"""Tests for the milestone scoring rule (effective 2026-11-20).

Rule: per node, actual outside [P10, P90] -> FAIL; else width > frozen
baseline width W0 -> FAIL; else |P50 - actual| / actual <= 35% -> PASS,
otherwise PARTIAL. Case verdict = worst node.

Band numbers below are the real e047f50 ensembles (seed 42, trials 20),
independently extracted from backtest-e047f50.db / desay-gap-c.db
(state_snapshots of the 20 baseline trial runs of the anchor Monte
Carlo ensembles) — NOT fitted, and NOT copied from the module under
test: the W0 freeze test pins the module constants against these
independently read values. The B-replay node errors are auxiliary
information only; the verdict never uses them.

W0 re-determination (2026-11-25, Ho 2026-11-24 13:44 — "W0 on the ON
caliber"): the Desay W0s were re-frozen on downside ON, trials 50,
seed 42, FBOOK model (mainline b14527f). The ON50 bands below are the
trials50 merge rerun bands (milestone-scores.json) for 2015/2020 and
the desay-2018 case DB band for 2018. The OFF/ON (trials-20) bands
above are kept as historical inputs: the OFF bands still fail
out-of-band under any W0, and the widening tests use them as
synthetic inputs. The 2015/2020 "ON fails via width cap" tests are
superseded by the re-determination (see below) — the cap now bites
only for bands wider than the ON-calibrated W0.
"""

from __future__ import annotations

import pytest

from planagent.evaluation.milestone import (
    BASELINE_BAND_WIDTHS,
    POINT_ERROR_THRESHOLD,
    band_edge_distance,
    old_rule_verdict,
    score_milestone_case,
    score_milestone_node,
)

# --- Real anchor bands (tick-3 revenue for Desay, share for Nokia) --------
# OFF = e047f50 re-run (backtest-e047f50.db); ON = Track C downside-default-ON
# run (desay-gap-c.db). Actuals: Desay yr3 revenue (RMB m), Nokia share.
DESAY_2015_OFF = {"p10": 6798.1106, "p50": 7271.8835, "p90": 8096.0692}
DESAY_2015_ON = {"p10": 5157.3955, "p50": 6850.8303, "p90": 7821.9627}
DESAY_2020_OFF = {"p10": 24538.3122, "p50": 27440.41, "p90": 29557.4679}
DESAY_2020_ON = {"p10": 19892.8362, "p50": 25462.1399, "p90": 27787.0191}
# ON50 = trials50 merge rerun on b14527f (milestone-scores.json),
# downside ON, trials 50, seed 42 — the bands the re-frozen W0s are
# read from. 2018 is NON-INDEPENDENT (case DB, 734ffdd).
DESAY_2015_ON50 = {"p10": 5222.3945, "p50": 6487.505, "p90": 7793.4624}
DESAY_2020_ON50 = {"p10": 17510.4529, "p50": 22353.714, "p90": 26384.8537}
DESAY_2018_ON50 = {"p10": 12076.7565, "p50": 15177.4829, "p90": 17888.6415}
NOKIA_YR3 = {"p10": 0.2155, "p50": 0.2553, "p90": 0.3282}
NOKIA_YR5 = {"p10": 0.0534, "p50": 0.0955, "p90": 0.1625}

ACTUAL_2015 = 5408.74
ACTUAL_2020 = 21908.0
ACTUAL_2018 = 9569.0
ACTUAL_NOKIA_YR3 = 0.27
ACTUAL_NOKIA_YR5 = 0.064


def _score(band, actual, w0):
    return score_milestone_node(
        p10=band["p10"], p50=band["p50"], p90=band["p90"],
        actual=actual, baseline_width=w0,
    )


# --- Frozen W0 --------------------------------------------------------------
def test_frozen_baseline_widths_match_db_extraction():
    """W0 constants equal the widths independently read from the ON
    (trials50, downside ON) bands they freeze (re-determined
    2026-11-25; the old OFF values 1297.9586 / 5019.1557 /
    3482.8424 are superseded — see the module docstring)."""
    assert BASELINE_BAND_WIDTHS == {
        ("desay-2015", "revenue", 3): 2571.0679,
        ("desay-2020", "revenue", 3): 8874.4008,
        ("desay-2018", "revenue", 3): 5811.885,
        ("nokia", "market_share", 3): 0.1127,
        ("nokia", "market_share", 5): 0.1091,
    }
    # And each Desay value equals P90-P10 of the ON50 band it freezes.
    assert BASELINE_BAND_WIDTHS[("desay-2015", "revenue", 3)] == pytest.approx(
        DESAY_2015_ON50["p90"] - DESAY_2015_ON50["p10"], abs=1e-9
    )
    assert BASELINE_BAND_WIDTHS[("desay-2020", "revenue", 3)] == pytest.approx(
        DESAY_2020_ON50["p90"] - DESAY_2020_ON50["p10"], abs=1e-9
    )
    assert BASELINE_BAND_WIDTHS[("desay-2018", "revenue", 3)] == pytest.approx(
        DESAY_2018_ON50["p90"] - DESAY_2018_ON50["p10"], abs=1e-9
    )
    assert BASELINE_BAND_WIDTHS[("nokia", "market_share", 3)] == pytest.approx(
        NOKIA_YR3["p90"] - NOKIA_YR3["p10"], abs=1e-9
    )
    assert BASELINE_BAND_WIDTHS[("nokia", "market_share", 5)] == pytest.approx(
        NOKIA_YR5["p90"] - NOKIA_YR5["p10"], abs=1e-9
    )


def test_point_error_threshold_reuses_magnitude_threshold():
    assert POINT_ERROR_THRESHOLD == 0.35


# --- Desay: the artifact is repaired ----------------------------------------
def test_desay_2015_off_fails_out_of_band():
    s = _score(DESAY_2015_OFF, ACTUAL_2015, BASELINE_BAND_WIDTHS[("desay-2015", "revenue", 3)])
    assert s.verdict == "FAIL" and s.reason == "out_of_band"
    assert s.in_band is False
    assert s.point_error == pytest.approx(0.3444, abs=1e-4)  # +34.4%, auxiliary only


def test_desay_2015_trials20_on_band_still_trips_new_cap():
    # The trials-20 ON band (width 2664.5672) is wider than the
    # re-frozen trials-50 ON W0 (2571.0679), so it still fails via
    # the cap — the cap still bites for bands wider than the new W0.
    # Under the OLD rule this was a PASS (actual inside the widened band).
    assert old_rule_verdict(p10=DESAY_2015_ON["p10"], p90=DESAY_2015_ON["p90"], actual=ACTUAL_2015) == "PASS"
    s = _score(DESAY_2015_ON, ACTUAL_2015, BASELINE_BAND_WIDTHS[("desay-2015", "revenue", 3)])
    assert s.verdict == "FAIL" and s.reason == "width_exceeds_baseline"
    assert s.in_band is True  # in band, yet FAIL — the cap is doing the work
    assert s.width_ratio == pytest.approx(2664.5672 / 2571.0679, abs=0.01)
    assert s.point_error == pytest.approx(0.2666, abs=1e-4)  # +26.7%, auxiliary only


def test_desay_2015_on50_passes_under_on_caliber_w0():
    # W0 re-determination (2026-11-25): the trials-50 ON band IS the
    # frozen width now, so the width leg passes by construction and
    # the verdict turns on in-band + point error: in band, +19.9%.
    s = _score(DESAY_2015_ON50, ACTUAL_2015, BASELINE_BAND_WIDTHS[("desay-2015", "revenue", 3)])
    assert s.verdict == "PASS" and s.reason == "point_error_pass"
    assert s.in_band is True and s.width_ratio == pytest.approx(1.0)
    assert s.point_error == pytest.approx(0.1994, abs=1e-4)  # +19.9%


def test_desay_2020_off_fails_out_of_band():
    s = _score(DESAY_2020_OFF, ACTUAL_2020, BASELINE_BAND_WIDTHS[("desay-2020", "revenue", 3)])
    assert s.verdict == "FAIL" and s.reason == "out_of_band"
    assert s.point_error == pytest.approx(0.2525, abs=1e-4)  # +25.3%


def test_desay_2020_on50_passes_under_on_caliber_w0():
    # Same re-determination consequence as 2015: the trials-50 ON
    # band (width = new W0) passes — in band, point error +2.0%.
    # The old trials-20 ON band (width 7894.1829) no longer trips
    # the new cap either (ratio 0.89) — the re-determination moved
    # the goalposts as ordered (Ho 2026-11-24 13:44), it did not
    # change the model.
    s = _score(DESAY_2020_ON50, ACTUAL_2020, BASELINE_BAND_WIDTHS[("desay-2020", "revenue", 3)])
    assert s.verdict == "PASS" and s.reason == "point_error_pass"
    assert s.in_band is True and s.width_ratio == pytest.approx(1.0)
    assert s.point_error == pytest.approx(0.0203, abs=1e-4)  # +2.0%
    s_old = _score(DESAY_2020_ON, ACTUAL_2020, BASELINE_BAND_WIDTHS[("desay-2020", "revenue", 3)])
    assert s_old.verdict == "PASS" and s_old.width_ratio == pytest.approx(
        7894.1829 / 8874.4008, abs=0.01
    )


def test_desay_2018_on50_fails_out_of_band():
    # NON-INDEPENDENT case: the yr3 actual (9569) sits below the
    # ON50 band's lower edge (12076.76) — out of band, so FAIL
    # regardless of the width cap (width = new W0 exactly, ratio 1.0).
    # This is the node the D2C shape fix (2026-11-25) has to move.
    s = _score(DESAY_2018_ON50, ACTUAL_2018, BASELINE_BAND_WIDTHS[("desay-2018", "revenue", 3)])
    assert s.verdict == "FAIL" and s.reason == "out_of_band"
    assert s.in_band is False and s.width_ratio == pytest.approx(1.0)
    assert s.point_error == pytest.approx(0.5861, abs=1e-4)  # +58.6%


# --- Nokia: unchanged ---------------------------------------------------------
def test_nokia_yr3_passes_point_error_small():
    for band in (NOKIA_YR3, NOKIA_YR3):  # OFF and ON bands are identical (share untouched)
        s = _score(band, ACTUAL_NOKIA_YR3, BASELINE_BAND_WIDTHS[("nokia", "market_share", 3)])
        assert s.verdict == "PASS" and s.reason == "point_error_pass"
        assert s.in_band is True and s.width_ratio == pytest.approx(1.0)
        assert s.point_error == pytest.approx(0.0544, abs=1e-4)  # +5.4%


def test_nokia_yr5_partial_point_error_large():
    s = _score(NOKIA_YR5, ACTUAL_NOKIA_YR5, BASELINE_BAND_WIDTHS[("nokia", "market_share", 5)])
    assert s.verdict == "PARTIAL" and s.reason == "point_error_partial"
    assert s.in_band is True and s.width_ratio == pytest.approx(1.0)
    assert s.point_error == pytest.approx(0.4922, abs=1e-4)  # +49.2%


def test_nokia_case_verdict_is_worst_node_partial():
    nodes = [
        _score(NOKIA_YR3, ACTUAL_NOKIA_YR3, BASELINE_BAND_WIDTHS[("nokia", "market_share", 3)]),
        _score(NOKIA_YR5, ACTUAL_NOKIA_YR5, BASELINE_BAND_WIDTHS[("nokia", "market_share", 5)]),
    ]
    assert [n.verdict for n in nodes] == ["PASS", "PARTIAL"]
    assert score_milestone_case(nodes) == "PARTIAL"


# --- Bandwidth robustness: widening can never improve a verdict -------------
@pytest.mark.parametrize(
    "off_band,actual,w0",
    [
        (DESAY_2015_OFF, ACTUAL_2015, 1297.9586),
        (DESAY_2020_OFF, ACTUAL_2020, 5019.1557),
    ],
)
def test_widening_off_band_until_it_covers_actual_still_fails(off_band, actual, w0):
    """Synthetic widening of the OFF band until the actual is covered.

    The verdict stays FAIL — via the width cap, not via out-of-band.
    This is the property the old rule violated (widening flipped it to
    PASS) and the guarantee the new rule locks in.
    """
    # Widen the lower tail in steps until the actual is inside.
    p10, p90 = off_band["p10"], off_band["p90"]
    widened = dict(off_band)
    while actual < widened["p10"]:
        widened["p10"] -= 100.0
        s = _score(widened, actual, w0)
        assert s.verdict == "FAIL", f"widening improved the verdict at P10={widened['p10']}"
    assert widened["p10"] <= actual <= widened["p90"]
    s = _score(widened, actual, w0)
    assert s.verdict == "FAIL" and s.reason == "width_exceeds_baseline"
    # Same from the top: raise P90 far past the actual — still FAIL
    # (actual still below P10, so the reason stays out_of_band; the
    # point is the verdict never improves).
    widened_up = dict(off_band, p90=off_band["p90"] + 10 * w0)
    s = _score(widened_up, actual, w0)
    assert s.verdict == "FAIL" and s.reason == "out_of_band"


def test_widening_an_in_band_pass_beyond_cap_flips_it_to_fail():
    s0 = _score(NOKIA_YR3, ACTUAL_NOKIA_YR3, BASELINE_BAND_WIDTHS[("nokia", "market_share", 3)])
    assert s0.verdict == "PASS"
    # Widen P90 up by 50% of W0: actual still in band, but width > W0.
    wider = dict(NOKIA_YR3, p90=NOKIA_YR3["p90"] + 0.5 * 0.1127)
    s = _score(wider, ACTUAL_NOKIA_YR3, BASELINE_BAND_WIDTHS[("nokia", "market_share", 3)])
    assert s.verdict == "FAIL" and s.reason == "width_exceeds_baseline"


def test_widening_within_cap_keeps_pass():
    # Synthetic band with headroom (width 0.08 < W0 0.1127): widen P90 by
    # 0.01, width 0.09 still <= W0 — verdict unchanged. (The real Nokia
    # yr3 band has zero headroom: its width IS W0, so any widening trips
    # the cap — that is the cap working as designed.)
    band = {"p10": 0.22, "p50": 0.2553, "p90": 0.30}
    s0 = _score(band, ACTUAL_NOKIA_YR3, BASELINE_BAND_WIDTHS[("nokia", "market_share", 3)])
    assert s0.verdict == "PASS"
    wider = dict(band, p90=0.31)
    s = _score(wider, ACTUAL_NOKIA_YR3, BASELINE_BAND_WIDTHS[("nokia", "market_share", 3)])
    assert s.verdict == "PASS"


def test_honest_residual_widening_within_cap_can_cover_actual():
    """Documented limitation, pinned as a test so nobody claims otherwise.

    Widening WITHIN the baseline cap can still bring an out-of-band
    actual inside and flip FAIL -> PASS. The rule only guards against
    widening BEYOND the baseline (the artifact at hand). Eliminating
    every widening flip would need a frozen baseline band (rejected:
    it judges one prediction by another prediction's distribution).
    """
    # Desay 2015 OFF is out of band by 1389.37 below P10 — more than W0,
    # so no within-cap widening can cover it. Use a synthetic near-miss
    # instead: actual 100 below P10, width headroom W0 - width = 500.
    band = {"p10": 1000.0, "p50": 1100.0, "p90": 1200.0}
    s_before = _score(band, 900.0, 700.0)
    assert s_before.verdict == "FAIL" and s_before.reason == "out_of_band"
    covered = dict(band, p10=900.0)  # width 300 <= W0 700, actual now in band
    s_after = _score(covered, 900.0, 700.0)
    assert s_after.verdict == "PASS"  # residual: within-cap widening flips it


# --- Threshold boundary + case aggregation ------------------------------------
def test_point_error_boundary_35_percent():
    # |P50 - actual| / actual == 0.35 exactly -> PASS; just above -> PARTIAL.
    base = {"p10": 60.0, "p50": 135.0, "p90": 140.0}
    assert _score(base, 100.0, 100.0).verdict == "PASS"
    assert _score(dict(base, p50=135.01), 100.0, 100.0).verdict == "PARTIAL"


def test_case_verdict_worst_node_ordering():
    def node(verdict):
        if verdict == "FAIL":
            return _score({"p10": 90.0, "p50": 100.0, "p90": 110.0}, 200.0, 100.0)
        if verdict == "PARTIAL":
            # In band, but |100-70|/70 = 42.9% > 35%.
            return _score({"p10": 60.0, "p50": 100.0, "p90": 140.0}, 70.0, 100.0)
        return _score({"p10": 90.0, "p50": 100.0, "p90": 110.0}, 100.0, 100.0)

    assert score_milestone_case([node("PASS"), node("PASS")]) == "PASS"
    assert score_milestone_case([node("PASS"), node("PARTIAL")]) == "PARTIAL"
    assert score_milestone_case([node("PARTIAL"), node("FAIL")]) == "FAIL"


def test_old_rule_reproduces_the_artifact():
    """Old rule: Desay OFF FAIL, ON PASS; Nokia nodes in band."""
    assert old_rule_verdict(p10=DESAY_2015_OFF["p10"], p90=DESAY_2015_OFF["p90"], actual=ACTUAL_2015) == "FAIL"
    assert old_rule_verdict(p10=DESAY_2015_ON["p10"], p90=DESAY_2015_ON["p90"], actual=ACTUAL_2015) == "PASS"
    assert old_rule_verdict(p10=DESAY_2020_OFF["p10"], p90=DESAY_2020_OFF["p90"], actual=ACTUAL_2020) == "FAIL"
    assert old_rule_verdict(p10=DESAY_2020_ON["p10"], p90=DESAY_2020_ON["p90"], actual=ACTUAL_2020) == "PASS"
    assert old_rule_verdict(p10=NOKIA_YR3["p10"], p90=NOKIA_YR3["p90"], actual=ACTUAL_NOKIA_YR3) == "PASS"
    assert old_rule_verdict(p10=NOKIA_YR5["p10"], p90=NOKIA_YR5["p90"], actual=ACTUAL_NOKIA_YR5) == "PASS"


# --- Input validation ----------------------------------------------------------
def test_invalid_inputs_raise():
    with pytest.raises(ValueError):
        score_milestone_node(p10=110.0, p50=100.0, p90=90.0, actual=100.0, baseline_width=10.0)
    with pytest.raises(ValueError):
        score_milestone_node(p10=90.0, p50=100.0, p90=110.0, actual=100.0, baseline_width=0.0)
    with pytest.raises(ValueError):
        score_milestone_node(p10=90.0, p50=100.0, p90=110.0, actual=0.0, baseline_width=10.0)
    with pytest.raises(ValueError):
        score_milestone_case([])


def test_node_score_carries_all_intermediates():
    s = _score(DESAY_2015_ON, ACTUAL_2015, BASELINE_BAND_WIDTHS[("desay-2015", "revenue", 3)])
    assert (s.p10, s.p50, s.p90, s.actual) == (5157.3955, 6850.8303, 7821.9627, 5408.74)
    assert s.width == pytest.approx(2664.5672, abs=1e-9)
    assert s.baseline_width == 2571.0679
    assert s.width_ratio == pytest.approx(2664.5672 / 2571.0679)
    assert s.in_band is True


# --- Band-edge distance (added 2026-11-24, diagnostic only) ----------------
# Definition: below the band p10 - actual; above the band actual - p90;
# inside the band min(actual - p10, p90 - actual); exactly 0 on an edge.
# The distance never changes the verdict — these tests pin the value
# alongside the (unchanged) verdict for each position.
def test_band_edge_distance_in_band_near_lower_edge():
    s = _score({"p10": 100.0, "p50": 110.0, "p90": 120.0}, 102.0, 100.0)
    assert s.verdict == "PASS"
    assert s.band_edge_distance == pytest.approx(2.0)
    assert s.band_edge_distance_rel == pytest.approx(2.0 / 102.0)


def test_band_edge_distance_in_band_near_upper_edge():
    s = _score({"p10": 100.0, "p50": 110.0, "p90": 120.0}, 118.0, 100.0)
    assert s.verdict == "PASS"
    assert s.band_edge_distance == pytest.approx(2.0)
    assert s.band_edge_distance_rel == pytest.approx(2.0 / 118.0)


def test_band_edge_distance_below_band():
    s = _score({"p10": 100.0, "p50": 110.0, "p90": 120.0}, 90.0, 100.0)
    assert s.verdict == "FAIL" and s.reason == "out_of_band"
    assert s.band_edge_distance == pytest.approx(10.0)
    assert s.band_edge_distance_rel == pytest.approx(10.0 / 90.0)


def test_band_edge_distance_above_band():
    s = _score({"p10": 100.0, "p50": 110.0, "p90": 120.0}, 130.0, 100.0)
    assert s.verdict == "FAIL" and s.reason == "out_of_band"
    assert s.band_edge_distance == pytest.approx(10.0)
    assert s.band_edge_distance_rel == pytest.approx(10.0 / 130.0)


def test_band_edge_distance_exactly_on_edge_is_zero():
    for actual in (100.0, 120.0):
        s = _score({"p10": 100.0, "p50": 110.0, "p90": 120.0}, actual, 100.0)
        assert s.in_band is True
        assert s.band_edge_distance == 0.0
        assert s.band_edge_distance_rel == 0.0


def test_band_edge_distance_helper_direct():
    assert band_edge_distance(100.0, 120.0, 90.0) == pytest.approx(10.0)
    assert band_edge_distance(100.0, 120.0, 130.0) == pytest.approx(10.0)
    assert band_edge_distance(100.0, 120.0, 102.0) == pytest.approx(2.0)
    assert band_edge_distance(100.0, 120.0, 100.0) == 0.0
    assert band_edge_distance(100.0, 120.0, 120.0) == 0.0
    with pytest.raises(ValueError):
        band_edge_distance(120.0, 100.0, 110.0)


def test_band_edge_distance_real_node_desay_2015_on():
    # Real A/C-run node: actual 5408.74 inside [5157.3955, 7821.9627],
    # 251.3445 above the lower edge (still FAIL via the width cap).
    s = _score(DESAY_2015_ON, ACTUAL_2015, BASELINE_BAND_WIDTHS[("desay-2015", "revenue", 3)])
    assert s.verdict == "FAIL" and s.reason == "width_exceeds_baseline"
    assert s.band_edge_distance == pytest.approx(5408.74 - 5157.3955, abs=1e-9)
    assert s.band_edge_distance_rel == pytest.approx((5408.74 - 5157.3955) / 5408.74)

"""Milestone scoring for classic-case backtests — band-in + baseline-width
cap + point-error grading (effective 2026-11-20).

This module is the single source of truth for the milestone verdict. Do
not re-implement the rule in analysis / harness scripts; import from here.

Old rule (e047f50 re-run, pre-registered; superseded 2026-11-20)
---------------------------------------------------------------
A milestone node passed iff the realized actual fell inside the anchor
ensemble's P10–P90 band at that tick. That rule rewards wider bands:
after the downside mechanism was switched ON by default (Track C,
2026-11-20), the shock fattened the lower tail and both Desay cases
flipped FAIL -> PASS although the point prediction got *worse* (B-replay
yr3 node error 2015: -4.1% -> -9.4%; 2020: -24.6% -> -28.7%). The two
"passes" were a bandwidth artifact, not improved prediction.

New rule (Ho, 2026-11-20: "milestone band rule made robust to bandwidth")
---------------------------------------------------------------------------
Per node, with W0 the frozen baseline width of the same case / field /
tick under the e047f50 OFF run (seed 42, trials 20; see
``BASELINE_BAND_WIDTHS``):

1. actual outside [P10, P90] -> FAIL (``out_of_band``);
2. else (P90 - P10) > W0 -> FAIL (``width_exceeds_baseline``);
3. else |P50 - actual| / actual <= 35% -> PASS, otherwise PARTIAL.

The case verdict is the worst node verdict (FAIL > PARTIAL > PASS).
Huawei keeps its qualitative verdict and is NOT scored by this rule
(explicit carve-out: its milestones are qualitative — 2005 overseas
revenue overtaking domestic, the BT 21CN win — and no numeric band
applies).

Why 35%: it directly reuses the magnitude partial-pass threshold already
in the pre-registered scoring protocol (magnitude P50 relative error
<= 35% is partial pass). It is not a newly fitted constant.

Bandwidth-robustness guarantee
------------------------------
Widening a band (fixed P50 and actual, P10 down / P90 up) can never
improve a verdict: it can only hold it or push it toward FAIL, via the
width cap in step 2. Locked by tests in ``tests/test_milestone_scoring.py``
(synthetic widening of the OFF band until it covers the actual still
scores FAIL, via the cap).

Honest residual: widening *within* the baseline cap can still bring an
actual inside the band and flip a verdict — this rule only guards
against widening *beyond* the baseline (the artifact at hand: 2015
2.05x, 2020 1.57x baseline width). Eliminating every widening flip
would need a frozen baseline band (use the OFF band to judge the ON
actual), which was rejected: judging one prediction's distribution by
another prediction's distribution ignores the current distribution
entirely. See ``research/strategy-engine/backtest-scoring-rules.md``
for the full alternatives record (pure-median-error, Winkler interval
score, frozen baseline band, relative-width cap).

Incomparability: changing the rule is a calibration change, not a model
change. Scores under the old rule and the new rule are not directly
comparable. By design the OFF verdicts are unchanged (both Desay cases
still FAIL, Nokia still PARTIAL, Huawei still PASS); only the ON
verdicts change (both Desay cases flip back to FAIL).

Band-edge distance (added 2026-11-24, trials50 rerun — diagnostic only)
------------------------------------------------------------------------
``MilestoneNodeScore`` also carries ``band_edge_distance`` (absolute,
>= 0) and ``band_edge_distance_rel`` (absolute / |actual|): how far the
actual sits from the nearest band edge — below the band ``p10 - actual``,
above the band ``actual - p90``, inside the band ``min(actual - p10,
p90 - actual)`` (0 exactly on an edge). It is a *diagnostic*: it never
changes the verdict, the 35% line, or W0. It exists so a verdict flip
between runs can be read at a glance (a node that was 800 below the band
and is now 50 below it is still FAIL, but it is a near-miss, not the
same miss). The pure helper ``band_edge_distance`` is exported for
analysis / rescoring scripts to reuse instead of re-implementing it.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Point-error threshold for PASS vs PARTIAL. Reuses the magnitude
#: partial-pass threshold from the pre-registered scoring protocol
#: (magnitude P50 relative error <= 35% is partial pass); not fitted.
POINT_ERROR_THRESHOLD = 0.35

#: Absolute tolerance when comparing a band width against its frozen
#: baseline cap. Band endpoints are stored rounded to 4 decimals, so
#: float noise on the subtraction is ~1e-12 at these magnitudes; 1e-9
#: is far above that noise and far below any meaningful width change.
_WIDTH_TOLERANCE = 1e-9

#: Frozen baseline widths W0: the P90-P10 width of the anchor ensemble
#: band for the same case / field / tick under the e047f50 OFF run
#: (seed 42, trials 20). Source DB: ``backtest-e047f50.db``
#: (~/workspace/research/strategy-engine/backtest-rerun-2026-11-19-e047f50/),
#: ``state_snapshots`` of the 20 baseline trial runs of the anchor
#: Monte Carlo ensembles (share: ``03-anchor-monte-carlo.json``,
#: revenue: ``03b-anchor-monte-carlo-revenue.json``), percentile =
#: linear interpolation, the same definition as the re-run analyze
#: scripts. Key: (case, state field, anchor tick).
#:
#: - desay-2015 revenue tick 3: ensemble 5119b81b-e552-41be-990a-20d590ee847c
#:   (base run eb32fb20-e4cd-4bcb-b8cf-a171e0f9d77c).
#: - desay-2020 revenue tick 3: ensemble ca3d9e0d-4986-449f-a598-de1f6f09c0a8
#:   (base run fc7550f4-2b1d-49f5-a859-10a98036d8de).
#: - nokia market_share ticks 3/5: ensemble ed7e3435-3c16-4c77-8d23-186b2f4dfd8b
#:   (base run 453f8429-86bc-4d2b-bbd8-99894c28f1ac).
BASELINE_BAND_WIDTHS: dict[tuple[str, str, int], float] = {
    ("desay-2015", "revenue", 3): 1297.9586,
    ("desay-2020", "revenue", 3): 5019.1557,
    ("nokia", "market_share", 3): 0.1127,
    ("nokia", "market_share", 5): 0.1091,
}

#: Verdict ordering, worst first. A case verdict is the worst node verdict.
_VERDICT_RANK = {"FAIL": 2, "PARTIAL": 1, "PASS": 0}

MilestoneVerdict = str  # one of "PASS" | "PARTIAL" | "FAIL"


@dataclass(frozen=True)
class MilestoneNodeScore:
    """Full scoring record for one milestone node (all intermediates)."""

    verdict: MilestoneVerdict
    in_band: bool
    width: float
    baseline_width: float
    width_ratio: float
    point_error: float
    p10: float
    p50: float
    p90: float
    actual: float
    reason: str  # "out_of_band" | "width_exceeds_baseline" | "point_error_pass" | "point_error_partial"
    band_edge_distance: float  # >= 0; diagnostic only, never changes the verdict
    band_edge_distance_rel: float  # band_edge_distance / |actual|; diagnostic only


def band_edge_distance(p10: float, p90: float, actual: float) -> float:
    """Distance from the actual to the nearest edge of the [P10, P90] band.

    Pure helper for analysis / rescoring scripts (same definition as the
    ``band_edge_distance`` field on ``MilestoneNodeScore``). Always >= 0:
    below the band ``p10 - actual``, above the band ``actual - p90``,
    inside the band ``min(actual - p10, p90 - actual)`` — exactly 0 when
    the actual sits on an edge. Diagnostic only; it does not enter the
    verdict.
    """
    if p10 > p90:
        raise ValueError(f"band endpoints must satisfy p10 <= p90, got {p10}, {p90}")
    if actual < p10:
        return p10 - actual
    if actual > p90:
        return actual - p90
    return min(actual - p10, p90 - actual)


def band_width(p10: float, p90: float) -> float:
    """P90-P10 width of a band."""
    return p90 - p10


def relative_bandwidth(p10: float, p90: float, actual: float) -> float:
    """(P90-P10)/actual — consistency cross-check only, not the rule.

    Reported alongside the verdict because it agrees with the new rule
    on the Desay nodes (OFF 24.0%/22.9% pass the 35% line, ON 49.3%/36.0%
    fail it) but must not be the rule itself: Nokia's yr5 share band is
    ~170% of a near-zero actual, which would wrongly kill its partial
    pass, and 2020 ON sits only 1.0pp over the line.
    """
    if actual == 0:
        raise ValueError("relative_bandwidth needs a nonzero actual")
    return (p90 - p10) / abs(actual)


def old_rule_verdict(p10: float, p90: float, actual: float) -> MilestoneVerdict:
    """The superseded rule: PASS iff the actual lies in [P10, P90].

    Kept only so rescoring scripts can print the old/new comparison
    table from the same inputs. Do not use for new scores.
    """
    return "PASS" if p10 <= actual <= p90 else "FAIL"


def score_milestone_node(
    *,
    p10: float,
    p50: float,
    p90: float,
    actual: float,
    baseline_width: float,
    point_error_threshold: float = POINT_ERROR_THRESHOLD,
) -> MilestoneNodeScore:
    """Score one milestone node under the 2026-11-20 rule.

    Order matters: out-of-band fails first, then the width cap, then
    the point-error grade. The width cap is checked even when the
    actual is in band — that is the whole point of the change: a band
    widened beyond its frozen baseline cannot buy a pass.
    """
    if not (p10 <= p50 <= p90):
        raise ValueError(f"band endpoints must satisfy p10 <= p50 <= p90, got {p10}, {p50}, {p90}")
    if baseline_width <= 0:
        raise ValueError(f"baseline_width must be positive, got {baseline_width}")
    if actual == 0:
        raise ValueError("milestone point error is undefined for actual == 0")
    if not 0 <= point_error_threshold <= 1:
        raise ValueError(f"point_error_threshold must lie in [0, 1], got {point_error_threshold}")

    width = band_width(p10, p90)
    in_band = p10 <= actual <= p90
    point_error = abs(p50 - actual) / abs(actual)
    width_ratio = width / baseline_width
    edge_distance = band_edge_distance(p10, p90, actual)
    edge_distance_rel = edge_distance / abs(actual)

    if not in_band:
        verdict: MilestoneVerdict = "FAIL"
        reason = "out_of_band"
    elif width - baseline_width > _WIDTH_TOLERANCE:
        verdict = "FAIL"
        reason = "width_exceeds_baseline"
    elif point_error <= point_error_threshold:
        verdict = "PASS"
        reason = "point_error_pass"
    else:
        verdict = "PARTIAL"
        reason = "point_error_partial"

    return MilestoneNodeScore(
        verdict=verdict,
        in_band=in_band,
        width=width,
        baseline_width=baseline_width,
        width_ratio=width_ratio,
        point_error=point_error,
        p10=p10,
        p50=p50,
        p90=p90,
        actual=actual,
        reason=reason,
        band_edge_distance=edge_distance,
        band_edge_distance_rel=edge_distance_rel,
    )


def score_milestone_case(node_scores: list[MilestoneNodeScore]) -> MilestoneVerdict:
    """Case verdict = worst node verdict (FAIL > PARTIAL > PASS)."""
    if not node_scores:
        raise ValueError("score_milestone_case needs at least one node score")
    return max((s.verdict for s in node_scores), key=lambda v: _VERDICT_RANK[v])

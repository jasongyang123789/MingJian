"""Headline口径 for the downside mechanism (blindspot Step 1).

The downside shock moves ensemble tails a lot (2020 B revenue P10 −42.9%)
while the binary headline statistics (``decline_p`` / ``p_loss``) stay 0.0
on fast-growth cases — the threshold those statistics test sits outside
the shock distribution's support (see the blindspot plan, ITEM-1).
This module is the **report-layer** headline: pure functions over stored
ensemble summaries and trial values. It changes no simulation behaviour,
no shock parameter, no scoring rule, and no stored ensemble.

Three pieces, all pre-registered (PRE-REGISTRATION.md) before any use:

- :func:`downside_drag` (H1): ON vs OFF displacement of P50 / P10, in %.
- :func:`relative_shortfall` (H2): fraction of ON trial final values below
  the arm's **own** OFF P10. The old threshold (the anchor's OFF P10) is
  wrong — a B arm whose whole distribution sits below the anchor scores
  1.00 against it and says nothing about itself.
- :func:`assess_decline_saturation` / :func:`assess_loss_saturation`:
  whether ``decline_p`` / ``p_loss`` can even move on the mode growth path.
  The arithmetic is the plan's §1.2/§1.3: a tick-over-tick decline needs
  ``depth > (1 - 1/g) / Δw`` where ``Δw`` is the largest single-tick rise
  of the shock window. The depth support upper bound and the growth
  factors are **parameters**, never case names — the same factors with a
  wider support, or the same support with slower factors, must change
  the verdict, and the unit tests prove both directions.

The window rise is measured with the product's own
:class:`~planagent.services.simulation.downside.DownsideState.window`
(not a re-implementation), scanned the way the diagnosis script did:
start on a 0.1 grid, ticks 0..7, per duration / persistent form.
"""

from __future__ import annotations

from dataclasses import dataclass

from planagent.services.distributions.aggregation import ROUND_DECIMALS
from planagent.services.simulation.downside import DownsideState

#: Saturation categories. ``saturated`` means the statistic cannot move on
#: the mode path because the required shock sits above the depth support;
#: ``structural`` means the mode path already declines with no shock at
#: all (the other end of the same binary statistic); ``informative``
#: means the threshold lies inside the support, so the statistic can
#: actually discriminate.
SATURATED = "saturated"
STRUCTURAL = "structural"
INFORMATIVE = "informative"

_SATURATION_LABELS_ZH = {
    SATURATED: "饱和（saturated）——阈值在冲击支撑外",
    STRUCTURAL: "结构性下跌（structural）——无冲击即下跌",
    INFORMATIVE: "有信息量（informative）——阈值在冲击支撑内",
}


def saturation_label_zh(category: str) -> str:
    """Chinese report label for a saturation category."""

    try:
        return _SATURATION_LABELS_ZH[category]
    except KeyError:
        raise ValueError(f"Unknown saturation category: {category!r}") from None


@dataclass(frozen=True)
class DownsideDrag:
    """H1: ON vs OFF displacement of one arm's ensemble (percent)."""

    delta_p50_pct: float
    delta_p10_pct: float


def downside_drag(
    *,
    off_p50: float,
    off_p10: float,
    on_p50: float,
    on_p10: float,
) -> DownsideDrag:
    """Return the H1 drag of an ON ensemble against its OFF twin.

    ``(ON − OFF) / OFF × 100`` for P50 and P10, same case, same arm, same
    metric. Full precision is kept here; callers round for display.
    A zero OFF baseline is a broken ensemble, refused loudly.
    """

    if off_p50 == 0.0:
        raise ValueError("downside_drag needs a non-zero OFF P50.")
    if off_p10 == 0.0:
        raise ValueError("downside_drag needs a non-zero OFF P10.")
    return DownsideDrag(
        delta_p50_pct=100.0 * (on_p50 - off_p50) / off_p50,
        delta_p10_pct=100.0 * (on_p10 - off_p10) / off_p10,
    )


def relative_shortfall(on_final_values: list[float], off_p10: float) -> float:
    """Return the H2 relative shortfall.

    Fraction of ON trial final values strictly below the arm's **own**
    OFF P10. This is exactly the ``p_loss`` a Monte Carlo run would
    report with ``loss_threshold`` set to that P10 — same trials, same
    threshold, same counting — so it reuses the harness's shortfall
    mechanism without re-running the ensemble. Rounded to the engine's
    state precision (4 decimals), like ``p_loss``. An empty ensemble
    reports 0.0, matching :func:`summarize_samples`.
    """

    if not on_final_values:
        return 0.0
    below = sum(1 for value in on_final_values if value < off_p10)
    return round(below / len(on_final_values), ROUND_DECIMALS)


def max_window_rise(duration: float, persistent: float = 0.0) -> float:
    """Largest single-tick rise of the shock window for one form.

    Scans the window start on a 0.1 grid (0.0–5.9) and ticks 0..7,
    exactly as the blindspot diagnosis did, but calling the product's
    own :meth:`DownsideState.window`. ``duration`` is the window length
    in ticks; ``persistent`` 0.0 is the cyclical bump, 1.0 the step that
    stays down. The rise is what multiplies ``depth`` in the decline
    inequality, so the *largest* rise is the most favourable alignment
    for a decline — the bound the saturation test needs.
    """

    if duration <= 0.0:
        raise ValueError("max_window_rise needs a positive duration.")
    if not 0.0 <= persistent <= 1.0:
        raise ValueError("max_window_rise needs persistent in [0, 1].")
    best = 0.0
    for start_tenths in range(0, 60):
        start = start_tenths / 10.0
        probe = DownsideState(
            fields=("revenue",),
            occurs=1.0,
            depth=0.20,
            start=start,
            duration=duration,
            persistent=persistent,
        )
        windows = [probe.window(tick) for tick in range(0, 8)]
        best = max(best, max(windows[i + 1] - windows[i] for i in range(7)))
    return best


def max_window_rise_over_support(
    durations: tuple[float, ...] = (1.0, 2.0, 3.0),
    persistent_values: tuple[float, ...] = (0.0, 1.0),
) -> float:
    """Largest single-tick window rise over the whole shock support.

    The most favourable alignment any in-support shock can achieve.
    Callers pass the duration / persistent support of the case's shock
    distribution (data, not logic); the defaults are the canonical
    triangular(1, 2, 3) duration support with both window forms.
    """

    if not durations:
        raise ValueError("max_window_rise_over_support needs durations.")
    if not persistent_values:
        raise ValueError("max_window_rise_over_support needs persistent values.")
    return max(
        max_window_rise(duration, persistent)
        for duration in durations
        for persistent in persistent_values
    )


@dataclass(frozen=True)
class DeclineSaturation:
    """Saturation assessment for ``decline_p`` on the mode growth path."""

    category: str
    #: Depth the slowest mode-path tick would need (None when structural).
    required_depth: float | None
    #: Upper end of the depth distribution's support (a parameter).
    depth_high: float
    #: Largest single-tick window rise used in the inequality.
    max_rise: float
    #: Slowest mode-path tick growth factor.
    slowest_growth: float

    @property
    def label_zh(self) -> str:
        return saturation_label_zh(self.category)


def assess_decline_saturation(
    growth_factors: list[float],
    depth_high: float,
    max_rise: float,
) -> DeclineSaturation:
    """Assess whether ``decline_p`` can move on the mode growth path.

    ``growth_factors`` are the no-shock per-tick growth factors (OFF
    replay trajectory ratios). A tick declines under a shock of depth
    ``d`` in the most favourable alignment when
    ``d > (1 - 1/g) / max_rise``; the binding tick is the slowest one.
    If any mode-path tick already grows below 1, the path declines with
    no shock at all — structural, the opposite end of the same binary
    statistic, and it must not be reported as shock-driven signal.
    """

    if not growth_factors:
        raise ValueError("assess_decline_saturation needs growth factors.")
    if depth_high <= 0.0:
        raise ValueError("assess_decline_saturation needs a positive depth_high.")
    if max_rise <= 0.0:
        raise ValueError("assess_decline_saturation needs a positive max_rise.")
    slowest = min(growth_factors)
    if slowest < 1.0:
        return DeclineSaturation(
            category=STRUCTURAL,
            required_depth=None,
            depth_high=depth_high,
            max_rise=max_rise,
            slowest_growth=slowest,
        )
    required = (1.0 - 1.0 / slowest) / max_rise
    category = SATURATED if required > depth_high else INFORMATIVE
    return DeclineSaturation(
        category=category,
        required_depth=required,
        depth_high=depth_high,
        max_rise=max_rise,
        slowest_growth=slowest,
    )


@dataclass(frozen=True)
class LossSaturation:
    """Saturation assessment for ``p_loss`` on the mode growth path."""

    category: str
    #: Cumulative shock the final value would need (None when structural).
    required_cumulative_hit: float | None
    #: Upper end of the depth distribution's support (a parameter).
    depth_high: float
    #: Mode-path cumulative growth (final / initial).
    cumulative_growth: float

    @property
    def label_zh(self) -> str:
        return saturation_label_zh(self.category)


def assess_loss_saturation(
    cumulative_growth: float, depth_high: float
) -> LossSaturation:
    """Assess whether ``p_loss`` can move on the mode growth path.

    The final value ends below its starting value only when the
    cumulative shock exceeds ``1 - 1/cumulative_growth`` — and no
    single shock can exceed the depth support, so the requirement is
    compared directly against ``depth_high``. A cumulative growth
    below 1 means the path ends below its start with no shock at all.
    """

    if cumulative_growth <= 0.0:
        raise ValueError("assess_loss_saturation needs positive cumulative growth.")
    if depth_high <= 0.0:
        raise ValueError("assess_loss_saturation needs a positive depth_high.")
    if cumulative_growth < 1.0:
        return LossSaturation(
            category=STRUCTURAL,
            required_cumulative_hit=None,
            depth_high=depth_high,
            cumulative_growth=cumulative_growth,
        )
    required = 1.0 - 1.0 / cumulative_growth
    category = SATURATED if required > depth_high else INFORMATIVE
    return LossSaturation(
        category=category,
        required_cumulative_hit=required,
        depth_high=depth_high,
        cumulative_growth=cumulative_growth,
    )

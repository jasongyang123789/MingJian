"""Satellite scenario model for out-of-model opportunities (Huawei rethink, 2026-11-25).

The leg-difference method can only measure legs that exist in the
model. Huawei-2000's opportunity — overseas expansion in the 3G/NGN
cycle — is a market that exists in the world but not in the model, so
the leg set is empty and (b) = 0 by arithmetic. The fix is to give the
opportunity an existence OUTSIDE the model: a small satellite model
that prices it as ``overseas revenue = addressable market x share``,
then feeds the result back into the two-value output as a satellite
leg (:class:`LegInput` with ``source="satellite"``).

Why market x share, not a growth rate on overseas revenue? The
overseas explosion is the product of two things: the market was flat
(~$88B implied in 2000 -> $78.6B Gartner 2010) while Huawei's share
went ~3% -> 15.7% — a share-gain story in a flat market, i.e. an
S-curve, not a growth-rate error. A single overseas growth rate
(64.5%/yr realized) looks like a parameter error; split into market
x share it becomes an identifiable market-entry curve.

Two calibers, one mechanism (the ``sizing`` field pins which):

- ``retrospective``: market and share are calibrated from realized
  data — the satellite puts the realized numbers into a market x
  share structure. (b) is then the realized overseas leg (Huawei:
  ~1167). This is the scoring (b).
- ``decision_time``: market and share carry decision-time
  distributions (wide), or the growth-rate sensitivity form
  (:func:`satellite_overseas_from_growth`). (b) is then the ex-ante
  value of the opportunity (Huawei: ~77 at a 30%/yr overseas-growth
  mode, ~442 even at an aggressive 50%/yr) — it can never cover the
  realized gap, and must never be presented as if it could.

Honest boundary (rethink §10.3): the satellite (b) and the segment
attribution's overseas leg are the SAME assumption under two
algorithms (both are realized overseas minus normal-caliber
overseas), not two independent pieces of evidence. Their agreement
is an arithmetic cross-check, not independent confirmation — the
independent evidence is the realized segment actuals themselves.

Pure functions: no I/O, no randomness, no LLM. Shares are fractions
(0-1); market and revenue share the case's money unit.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .opportunity_value import LegInput, OutcomeRecord, SatelliteParams, Sizing

__all__ = [
    "GrowthSensitivity",
    "LogisticShare",
    "MarketPoint",
    "SatelliteResult",
    "SatelliteScenario",
    "SharePoint",
    "ShareTrajectory",
    "satellite_leg_input",
    "satellite_overseas",
    "satellite_overseas_from_growth",
    "share_at",
]


class MarketPoint(BaseModel):
    """Addressable-market size at one year, with an optional band."""

    model_config = ConfigDict(extra="forbid")

    year: int
    p50: float = Field(gt=0)
    p10: float | None = Field(default=None, gt=0)
    p90: float | None = Field(default=None, gt=0)


class SharePoint(BaseModel):
    """Share at one year of a table trajectory (fraction, 0-1)."""

    model_config = ConfigDict(extra="forbid")

    year: int
    share: float = Field(ge=0, le=1)


class LogisticShare(BaseModel):
    """Logistic share curve: share(t) = L / (1 + exp(-k (t - t0)))."""

    model_config = ConfigDict(extra="forbid")

    ceiling: float = Field(gt=0, le=1)
    steepness: float = Field(gt=0)
    midpoint_year: float


class ShareTrajectory(BaseModel):
    """A share trajectory in one of two forms.

    ``logistic`` is the smooth S-curve; ``table`` is the yearly form,
    which is also how milestone jumps are expressed (BT's 2005
    selection is a jump from the 2004 share to the 2005 share — a
    table row, not a smooth curve). A table interpolates linearly
    between bracketing years and holds the nearest endpoint outside
    its range.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["logistic", "table"]
    logistic: LogisticShare | None = None
    points: list[SharePoint] | None = None

    @model_validator(mode="after")
    def _check_form(self) -> ShareTrajectory:
        if self.kind == "logistic":
            if self.logistic is None:
                raise ValueError("logistic trajectory requires 'logistic'")
            if self.points is not None:
                raise ValueError("logistic trajectory must not carry 'points'")
        else:
            if not self.points:
                raise ValueError("table trajectory requires non-empty 'points'")
            years = [p.year for p in self.points]
            if len(set(years)) != len(years):
                raise ValueError("table trajectory years must be unique")
        return self


class SatelliteScenario(BaseModel):
    """Inputs to the satellite scenario model."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    metric: str = "revenue"
    unit: str = ""
    base_year: int
    base_overseas: float = Field(ge=0)
    horizon_year: int
    market: list[MarketPoint] = Field(min_length=1)
    share: ShareTrajectory
    # The main-model normal value (B P50) at the horizon, and the
    # base-year overseas share of it: normal-caliber overseas revenue
    # is normal_value * normal_overseas_share ("opportunity legs at
    # normal levels").
    normal_value: float
    normal_overseas_share: float = Field(ge=0, le=1)
    sizing: Sizing
    market_source: str = ""
    share_source: str = ""
    # Basis notes. Retrospective calibration MUST say when a number is
    # derived (implied market = realized overseas / share) rather than
    # observed — an implied market is not market data.
    market_basis: str = ""
    share_basis: str = ""

    @model_validator(mode="after")
    def _check_horizon(self) -> SatelliteScenario:
        if not any(point.year == self.horizon_year for point in self.market):
            raise ValueError(
                f"market series has no point for horizon year {self.horizon_year}"
            )
        if self.horizon_year < self.base_year:
            raise ValueError("horizon_year must not precede base_year")
        return self


class SatelliteResult(BaseModel):
    """Satellite overseas revenue at the horizon + (b)."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    metric: str
    unit: str = ""
    horizon_year: int
    sizing: Sizing
    market_at_horizon: float
    share_at_horizon: float
    overseas_p50: float
    overseas_p10: float | None = None
    overseas_p90: float | None = None
    normal_overseas: float
    opportunity_b_p50: float
    opportunity_b_p10: float | None = None
    opportunity_b_p90: float | None = None
    notes: list[str] = Field(default_factory=list)


class GrowthSensitivity(BaseModel):
    """Decision-time sensitivity in growth-rate form.

    Overseas revenue at the horizon from a triangular overseas-growth
    assumption: low -> P10, mode -> P50, high -> P90. The growth form
    is the rethink §3.2 sensitivity grid — it prices the opportunity
    ex ante; it is NOT the market x share model and must not be
    mistaken for a second estimate of the realized leg.
    """

    model_config = ConfigDict(extra="forbid")

    base_overseas: float
    growth_low: float
    growth_mode: float
    growth_high: float
    years: int
    overseas_p10: float
    overseas_p50: float
    overseas_p90: float
    normal_overseas: float
    opportunity_b_p10: float
    opportunity_b_p50: float
    opportunity_b_p90: float
    notes: list[str] = Field(default_factory=list)


def share_at(trajectory: ShareTrajectory, year: int) -> float:
    """Share at `year` under the trajectory (fraction, 0-1)."""
    if trajectory.kind == "logistic":
        curve = trajectory.logistic
        assert curve is not None  # validated by the model
        return curve.ceiling / (1.0 + math.exp(-curve.steepness * (year - curve.midpoint_year)))
    points = sorted(trajectory.points or [], key=lambda p: p.year)
    if year <= points[0].year:
        return points[0].share
    if year >= points[-1].year:
        return points[-1].share
    for before, after in zip(points, points[1:]):
        if before.year <= year <= after.year:
            span = after.year - before.year
            weight = (year - before.year) / span if span else 0.0
            return before.share + weight * (after.share - before.share)
    return points[-1].share  # unreachable; the ranges above cover it


def satellite_overseas(scenario: SatelliteScenario) -> SatelliteResult:
    """Overseas revenue at the horizon + (b) from market x share.

    overseas(horizon) = M(horizon) x s(horizon); (b) = overseas -
    normal-caliber overseas (normal value x base-year overseas share).
    Percentiles combine the market band with the point share (the
    share trajectory is a point curve here; a banded share is a
    decision-time extension, not needed for the retrospective golden).
    """
    market = next(p for p in scenario.market if p.year == scenario.horizon_year)
    share = share_at(scenario.share, scenario.horizon_year)
    overseas_p50 = market.p50 * share
    overseas_p10 = market.p10 * share if market.p10 is not None else None
    overseas_p90 = market.p90 * share if market.p90 is not None else None
    normal_overseas = scenario.normal_value * scenario.normal_overseas_share
    notes: list[str] = []
    if scenario.market_source:
        notes.append(f"Market source: {scenario.market_source}")
    if scenario.share_source:
        notes.append(f"Share source: {scenario.share_source}")
    if scenario.market_basis:
        notes.append(f"Market basis: {scenario.market_basis}")
    if scenario.share_basis:
        notes.append(f"Share basis: {scenario.share_basis}")
    notes.append(
        f"Sizing {scenario.sizing}: "
        + (
            "market and share calibrated from realized data; (b) sizes the "
            "realized overseas leg, it is not a decision-time parameter."
            if scenario.sizing == "retrospective"
            else "market and share carry decision-time distributions; (b) is "
            "the ex-ante value of the opportunity and cannot cover a "
            "realized burst."
        )
    )
    return SatelliteResult(
        case_id=scenario.case_id,
        metric=scenario.metric,
        unit=scenario.unit,
        horizon_year=scenario.horizon_year,
        sizing=scenario.sizing,
        market_at_horizon=market.p50,
        share_at_horizon=share,
        overseas_p50=overseas_p50,
        overseas_p10=overseas_p10,
        overseas_p90=overseas_p90,
        normal_overseas=normal_overseas,
        opportunity_b_p50=overseas_p50 - normal_overseas,
        opportunity_b_p10=(
            overseas_p10 - normal_overseas if overseas_p10 is not None else None
        ),
        opportunity_b_p90=(
            overseas_p90 - normal_overseas if overseas_p90 is not None else None
        ),
        notes=notes,
    )


def satellite_overseas_from_growth(
    *,
    base_overseas: float,
    growth_low: float,
    growth_mode: float,
    growth_high: float,
    years: int,
    normal_overseas: float,
) -> GrowthSensitivity:
    """Decision-time sensitivity: overseas(t) = base x (1 + g)^t.

    The triangular growth assumption maps low -> P10, mode -> P50,
    high -> P90. The rethink's sensitivity grid (mode 30%/yr -> ~77;
    40% -> ~203; 50% -> ~442) is this form. The low (20%/yr) is a
    stated assumption for the P10, not a sourced number.
    """
    if not (growth_low <= growth_mode <= growth_high):
        raise ValueError("growth assumption must satisfy low <= mode <= high")
    if years < 0:
        raise ValueError("years must be non-negative")
    overseas_p10 = base_overseas * (1.0 + growth_low) ** years
    overseas_p50 = base_overseas * (1.0 + growth_mode) ** years
    overseas_p90 = base_overseas * (1.0 + growth_high) ** years
    return GrowthSensitivity(
        base_overseas=base_overseas,
        growth_low=growth_low,
        growth_mode=growth_mode,
        growth_high=growth_high,
        years=years,
        overseas_p10=overseas_p10,
        overseas_p50=overseas_p50,
        overseas_p90=overseas_p90,
        normal_overseas=normal_overseas,
        opportunity_b_p10=overseas_p10 - normal_overseas,
        opportunity_b_p50=overseas_p50 - normal_overseas,
        opportunity_b_p90=overseas_p90 - normal_overseas,
        notes=[
            "Growth-rate sensitivity form (rethink §3.2 grid): ex-ante "
            "pricing only. The P10 low (20%/yr) is a stated assumption, "
            "not a sourced number; the mode (30%/yr) and upside points "
            "(40%/50%/yr) are the report's sensitivity grid."
        ],
    )


def satellite_leg_input(
    *,
    leg_id: str,
    label: str,
    scenario: SatelliteScenario,
    result: SatelliteResult,
    horizon_tick: int,
    horizon_label: str = "",
) -> LegInput:
    """Build the satellite :class:`LegInput` for a two-value request.

    ``stripped`` is the satellite model at normal caliber (normal
    overseas revenue); ``scenario`` is the satellite model at scenario
    caliber (overseas revenue at the horizon). Their difference is
    (b). Records are P50-only: the satellite has no seeded replay, so
    clean contributions are unavailable and reported as None, never
    fabricated — exactly like a P50-only OutcomeRecord.
    """
    if result.horizon_year != scenario.horizon_year:
        raise ValueError("result horizon does not match the scenario horizon")
    return LegInput(
        leg_id=leg_id,
        label=label,
        stripped=OutcomeRecord(
            metric=scenario.metric,
            unit=scenario.unit,
            horizon_tick=horizon_tick,
            horizon_label=horizon_label,
            p50=result.normal_overseas,
            replay=None,
        ),
        source="satellite",
        scenario=OutcomeRecord(
            metric=scenario.metric,
            unit=scenario.unit,
            horizon_tick=horizon_tick,
            horizon_label=horizon_label,
            p50=result.overseas_p50,
            replay=None,
        ),
        sizing=scenario.sizing,
        satellite_params=SatelliteParams(
            market_source=scenario.market_source,
            share_source=scenario.share_source,
            market_basis=scenario.market_basis,
            share_basis=scenario.share_basis,
        ),
    )

"""Realized segment attribution (Huawei rethink §4, 2026-11-25).

The cross-check for the satellite model: decompose the realized gap
(actual - normal value) into per-segment legs using realized segment
actuals. No new model, no new parameters — an identity decomposition:

    gap = actual_total - normal_value
        = SUM over segments of (actual[segment] - normal_value x base_share[segment])
        = overseas leg + domestic offset (+ ...)

The normal-caliber split is the base-year mix ("opportunity legs at
normal levels", same convention as the satellite's normal overseas).
For Huawei-2010: overseas leg +1167.0, domestic offset -241.7, net
+925.3 against a gap of +925.5 — the 0.2 residue is source rounding
(the segment actuals sum to 1851.8, the reported total is 1852), and
the balance check tolerates it explicitly rather than hiding it.

Two attached diagnostics come free with the decomposition, and matter
more than (b) itself: the normal value overshot domestic by ~37%
(the model was wrong in both directions — domestic too high, overseas
missing — and the two errors partly cancelled in the total), and the
domestic offset mixes model error with the unobservable counterfactual
(would domestic have been higher without the overseas push?).

Honest boundary (rethink §10.3): the attribution's overseas leg and
the satellite's (b) are the SAME assumption under two algorithms
(both are realized overseas minus normal-caliber overseas), so their
agreement is an arithmetic cross-check, not independent confirmation.
:func:`compare_opportunity_estimates` is that cross-check: it alarms
when the two routes disagree beyond the tolerance band (±15%).

Pure functions: no I/O, no randomness, no LLM. Retrospective only:
the inputs ARE realized actuals, so the sizing is always
``retrospective`` — an attribution must never be labeled
``decision_time``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .opportunity_value import Sizing

__all__ = [
    "BALANCE_TOLERANCE",
    "CROSS_CHECK_TOLERANCE",
    "CrossCheckResult",
    "SegmentAttribution",
    "SegmentAttributionInput",
    "SegmentLeg",
    "attribute_residual_by_segment",
    "compare_opportunity_estimates",
]

#: The balance tolerance for the identity check: the legs must sum to
#: the gap within this. 0.25 covers the Huawei source-rounding residue
#: (segment actuals 1204.1 + 647.7 = 1851.8 vs reported total 1852 —
#: a 0.2 residue) with a small margin; anything larger is a real
#: imbalance (wrong shares, wrong actuals, missing segment), not
#: rounding.
BALANCE_TOLERANCE = 0.25

#: The cross-check alarm band: the satellite (b) and the attribution's
#: overseas leg must agree within this relative difference, or the
#: cross-check alarms (rethink §8).
CROSS_CHECK_TOLERANCE = 0.15


class SegmentAttributionInput(BaseModel):
    """Inputs to the realized segment attribution."""

    model_config = ConfigDict(extra="forbid")

    normal_value: float
    actual_total: float
    # Base-year mix: segment -> share of the normal value. Must sum to
    # 1 (the whole normal value is allocated across segments).
    base_shares: dict[str, float]
    # Realized actuals per segment; keys must match base_shares.
    actuals: dict[str, float]
    sizing: Sizing = "retrospective"

    @model_validator(mode="after")
    def _check_inputs(self) -> SegmentAttributionInput:
        if set(self.actuals) != set(self.base_shares):
            raise ValueError("actuals keys must match base_shares keys")
        total_share = sum(self.base_shares.values())
        if abs(total_share - 1.0) > 1e-9:
            raise ValueError(f"base_shares must sum to 1, got {total_share}")
        if any(share < 0 for share in self.base_shares.values()):
            raise ValueError("base_shares must be non-negative")
        return self


class SegmentLeg(BaseModel):
    """One segment's leg: realized actual minus normal-caliber level."""

    model_config = ConfigDict(extra="forbid")

    segment: str
    base_share: float
    normal_caliber: float
    actual: float
    contribution: float


class SegmentAttribution(BaseModel):
    """The attribution: per-segment legs + the identity check."""

    model_config = ConfigDict(extra="forbid")

    legs: list[SegmentLeg]
    net: float
    gap: float
    residual: float
    balanced: bool
    sizing: Sizing
    notes: list[str] = Field(default_factory=list)


class CrossCheckResult(BaseModel):
    """Satellite (b) vs the attribution's overseas leg."""

    model_config = ConfigDict(extra="forbid")

    satellite_b: float
    attribution_b: float
    relative_difference: float | None
    tolerance: float
    within_tolerance: bool
    alarm: bool
    notes: list[str] = Field(default_factory=list)


def attribute_residual_by_segment(
    attribution_input: SegmentAttributionInput,
) -> SegmentAttribution:
    """Decompose the gap into per-segment legs.

    Leg[segment] = actual[segment] - normal_value x base_share[segment].
    net = sum(legs); gap = actual_total - normal_value; residual = net
    - gap (source rounding when the segment actuals do not sum exactly
    to the reported total); balanced = |residual| <= BALANCE_TOLERANCE.
    """
    if attribution_input.sizing != "retrospective":
        raise ValueError(
            "segment attribution uses realized actuals, so its sizing is "
            "always 'retrospective' — it must never be labeled 'decision_time'"
        )
    legs: list[SegmentLeg] = []
    for segment in sorted(attribution_input.base_shares):
        share = attribution_input.base_shares[segment]
        normal_caliber = attribution_input.normal_value * share
        actual = attribution_input.actuals[segment]
        legs.append(
            SegmentLeg(
                segment=segment,
                base_share=share,
                normal_caliber=normal_caliber,
                actual=actual,
                contribution=actual - normal_caliber,
            )
        )
    net = sum(leg.contribution for leg in legs)
    gap = attribution_input.actual_total - attribution_input.normal_value
    residual = net - gap
    balanced = abs(residual) <= BALANCE_TOLERANCE
    notes = [
        "Identity: legs sum to the gap within source rounding "
        f"(residual {residual:.2f}, tolerance {BALANCE_TOLERANCE})."
    ]
    if not balanced:
        notes.append(
            "UNBALANCED: the legs do not sum to the gap — check the base "
            "shares, the segment actuals, and whether a segment is missing."
        )
    return SegmentAttribution(
        legs=legs,
        net=net,
        gap=gap,
        residual=residual,
        balanced=balanced,
        sizing=attribution_input.sizing,
        notes=notes,
    )


def compare_opportunity_estimates(
    *,
    satellite_b: float,
    attribution_b: float,
    tolerance: float = CROSS_CHECK_TOLERANCE,
) -> CrossCheckResult:
    """Cross-check the satellite (b) against the attribution's leg.

    The attribution leg is the reference: it is computed directly
    from realized segment actuals. relative_difference =
    |satellite - attribution| / |attribution|; the check alarms when
    it exceeds `tolerance` (±15% default). Agreement is an arithmetic
    cross-check, not independent confirmation — both routes share the
    'normal caliber by base-year mix' assumption (rethink §10.3).
    """
    if attribution_b == 0:
        return CrossCheckResult(
            satellite_b=satellite_b,
            attribution_b=attribution_b,
            relative_difference=None,
            tolerance=tolerance,
            within_tolerance=False,
            alarm=True,
            notes=["Attribution leg is zero: no relative difference is defined."],
        )
    relative = abs(satellite_b - attribution_b) / abs(attribution_b)
    within = relative <= tolerance
    return CrossCheckResult(
        satellite_b=satellite_b,
        attribution_b=attribution_b,
        relative_difference=relative,
        tolerance=tolerance,
        within_tolerance=within,
        alarm=not within,
        notes=[
            "Satellite (b) vs attribution leg: agreement is an arithmetic "
            "cross-check, not independent confirmation — both routes share "
            "the 'normal caliber by base-year mix' assumption."
        ],
    )

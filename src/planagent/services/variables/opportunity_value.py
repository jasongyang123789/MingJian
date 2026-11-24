"""Two-value output: normal forecast (a) + opportunity contribution (b).

Ho 2026-11-24 10:51, corrected 10:55: the model KEEPS computing the
opportunity legs (order-book backlog, ADAS, NEV, burst) — nothing is
deleted or recalibrated away — but their contribution is reported as a
SECOND value, separately stated, never merged into the normal value:

- (a) normal value: the forecast with the opportunity legs at
  normal/baseline levels. Operationally this is the leg-stripped base
  from the frozen decomposition (anchor-frozen-decomposition-2026-11-24):
  re-run the case with the opportunity legs zeroed (``backlog_conversion
  = 0``, ``adas_coupling = 0 + adas_share_coupling = 0``,
  ``nev_coupling = 0``) and take that outcome.
- (b) opportunity value: the legs' incremental contribution,
  ``full outcome - leg-stripped outcome``.

Two levels are carried because the frozen decomposition proved they
differ by the ensemble-vs-path gap (tick3: +1037.27 desay-2015,
+4925.23 desay-2020):

- REPLAY level (clean): the same seeded path with the legs on vs off.
  This is the causal leg effect on one path. A frozen MC is degenerate
  (all variables pinned, stddev 0), so a frozen P50 equals its replay.
- P50 level (apparent): the full ensemble P50 minus the frozen P50.
  This includes the ensemble-vs-path gap.

And two normals follow from them:

- ``normal_frozen``: the leg-stripped outcome itself (frozen P50 /
  frozen replay). A real outcome of a real run.
- ``normal_adjusted``: ``full P50 - total clean leg contribution`` —
  the P50 with only the clean (replay-level) leg effects removed, the
  ensemble-vs-path gap retained. This is the number Ho quoted for the
  Desay validation ("2015 three legs off +4.5%, 2020 two legs off
  -25.4%" vs yr3 actuals). Identity: ``normal_adjusted =
  normal_frozen + (ensemble gap of the full run) - (ensemble gap of
  the stripped run)``; with a degenerate frozen MC the second gap is
  zero, so ``normal_adjusted = normal_frozen + ensemble_gap``.

``combined_reference`` is the identity ``normal + opportunity = full
outcome`` (both levels). It is labelled a reference, NEVER a forecast
and NEVER to be scored: the two values must stay separate.

Per-leg contributions do NOT sum to the total in general: legs
interact (frozen report: two-leg interaction -2.4% / -5.1%). The total
is always ``full - all-legs-off``; per-leg values are single-leg
conditionals (that leg off, the others on). ``interaction_clean``
reports the difference explicitly.

``sizing`` is REQUIRED on every output and is part of the hindsight
firewall: ``decision_time`` means the opportunity-leg values come from
decision-time evidence; ``retrospective`` means they were sized from
post-decision / fitted data (diagnostic sizing only — a retrospective
(b) sizes the miss, it is not a decision-time parameter and must never
be presented as one).

Pure functions: no I/O, no randomness, no LLM. The caller produces
the paired runs (full + stripped) — e.g. the frozen-decomposition
harness — and this module turns them into the two-value output.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .opportunities import KeyOpportunityPrompt

#: Sizing provenance — see the module docstring. Required, never defaulted.
Sizing = Literal["decision_time", "retrospective"]


class OutcomeRecord(BaseModel):
    """One outcome of one run at one horizon tick.

    ``p50`` is the ensemble median; ``replay`` is the single seeded
    replay value on the same path (None when the caller has no replay,
    e.g. a P50-only summary — clean contributions are then unavailable
    and reported as None, never fabricated).
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str | None = None
    metric: str
    unit: str = ""
    horizon_tick: int
    horizon_label: str = ""
    p50: float
    replay: float | None = None
    seed: int | None = None
    trials: int | None = None


class LegInput(BaseModel):
    """One opportunity leg + its leg-off outcome record."""

    model_config = ConfigDict(extra="forbid")

    leg_id: str
    label: str = ""
    stripped: OutcomeRecord


class TwoValueRequest(BaseModel):
    """Inputs to the two-value computation."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    metric: str
    unit: str = ""
    horizon_tick: int
    horizon_label: str = ""
    full: OutcomeRecord
    stripped_all: OutcomeRecord
    legs: list[LegInput] = Field(default_factory=list)
    actual: float | None = None
    sizing: Sizing
    legs_note: str = ""


class LegContribution(BaseModel):
    """One leg's incremental contribution (full minus leg-off)."""

    model_config = ConfigDict(extra="forbid")

    leg_id: str
    label: str = ""
    clean_contribution: float | None = None
    apparent_contribution: float | None = None
    clean_pct_of_overshoot: float | None = None
    apparent_pct_of_overshoot: float | None = None


class ArithmeticContribution(BaseModel):
    """A (b) derived arithmetically from a discounted-growth prompt.

    The conditional the prompt already states: had the observed rate
    persisted, the level would be ``projected_observed``; at the
    discounted rate it is ``projected_discounted``. The difference is
    the extra contribution of NOT discounting — a partial-equilibrium
    illustration (compounds only this growth rate, excludes every other
    driver), never a leg difference. None when the prompt carries no
    projected levels (no paired level variable).
    """

    model_config = ConfigDict(extra="forbid")

    opportunity_id: str
    variable_id: str
    contribution: float | None = None
    projected_observed: float | None = None
    projected_discounted: float | None = None
    horizon_ticks: int
    basis_label: str = ""
    caveat: str = ""


class TwoValueOutput(BaseModel):
    """The two values, separately stated, never merged."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    metric: str
    unit: str = ""
    horizon_tick: int
    horizon_label: str = ""
    # (a) normal value — two levels, see the module docstring.
    normal_frozen_p50: float
    normal_frozen_replay: float | None = None
    normal_adjusted_p50: float | None = None
    # (b) opportunity value — total + per-leg attribution.
    opportunity_total_clean: float | None = None
    opportunity_total_apparent: float | None = None
    contributions: list[LegContribution] = Field(default_factory=list)
    interaction_clean: float | None = None
    # Diagnostics the coordinator's milestone rule needs.
    ensemble_gap: float | None = None
    combined_reference_p50: float
    sizing: Sizing
    # Validation against the actual, when supplied.
    actual: float | None = None
    overshoot_p50: float | None = None
    residual_frozen_p50: float | None = None
    residual_frozen_pct: float | None = None
    residual_adjusted_p50: float | None = None
    residual_adjusted_pct: float | None = None
    legs_stripped: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def _check_paired(full: OutcomeRecord, other: OutcomeRecord, what: str) -> None:
    """Paired records must describe the same case/metric/horizon/seed."""
    if other.metric != full.metric:
        raise ValueError(f"{what}: metric {other.metric!r} != full {full.metric!r}.")
    if other.unit != full.unit:
        raise ValueError(f"{what}: unit {other.unit!r} != full {full.unit!r}.")
    if other.horizon_tick != full.horizon_tick:
        raise ValueError(f"{what}: horizon_tick {other.horizon_tick} != full {full.horizon_tick}.")
    if other.seed is not None and full.seed is not None and other.seed != full.seed:
        raise ValueError(f"{what}: seed {other.seed} != full {full.seed}.")
    if other.trials is not None and full.trials is not None and other.trials != full.trials:
        raise ValueError(f"{what}: trials {other.trials} != full {full.trials}.")


def compute_two_value_output(request: TwoValueRequest) -> TwoValueOutput:
    """Compute (a) normal + (b) opportunity from paired run outcomes.

    ``request.full`` is the outcome with the opportunity legs on;
    ``request.stripped_all`` with all of them off; each ``legs`` entry
    with exactly that leg off. All records must share metric, unit,
    horizon_tick, and (when given) seed and trials — a mismatch raises
    :class:`ValueError` rather than silently mixing incomparable runs.
    """
    full = request.full
    stripped = request.stripped_all
    _check_paired(full, stripped, "stripped_all")
    for leg in request.legs:
        _check_paired(full, leg.stripped, f"leg {leg.leg_id!r}")

    notes: list[str] = []
    if request.legs_note:
        notes.append(request.legs_note)
    if stripped.p50 == stripped.replay and stripped.replay is not None:
        notes.append(
            "Frozen MC is degenerate (stripped P50 equals stripped replay): "
            "the stripped outcome is a single pinned path, not an ensemble median."
        )

    # (a) normal, frozen level: the leg-stripped outcome itself.
    normal_frozen_p50 = stripped.p50
    normal_frozen_replay = stripped.replay

    # Per-leg contributions, both levels.
    overshoot = full.p50 - request.actual if request.actual is not None else None
    contributions: list[LegContribution] = []
    clean_values: list[float | None] = []
    for leg in request.legs:
        clean: float | None = None
        if full.replay is not None and leg.stripped.replay is not None:
            clean = full.replay - leg.stripped.replay
        clean_values.append(clean)
        apparent = full.p50 - leg.stripped.p50
        contributions.append(
            LegContribution(
                leg_id=leg.leg_id,
                label=leg.label,
                clean_contribution=clean,
                apparent_contribution=apparent,
                clean_pct_of_overshoot=(
                    (100.0 * clean / overshoot)
                    if clean is not None and overshoot not in (None, 0.0)
                    else None
                ),
                apparent_pct_of_overshoot=(
                    (100.0 * apparent / overshoot) if overshoot not in (None, 0.0) else None
                ),
            )
        )

    # (b) opportunity total, both levels.
    total_clean: float | None = None
    if full.replay is not None and stripped.replay is not None:
        total_clean = full.replay - stripped.replay
    total_apparent = full.p50 - stripped.p50

    # Interaction: total clean minus the single-leg clean sum. Negative
    # means sub-additive (legs overlap); positive means super-additive.
    # Unavailable when any leg lacks a replay value.
    clean_sum: float | None = None
    if clean_values and all(v is not None for v in clean_values):
        clean_sum = sum(v for v in clean_values if v is not None)
    interaction: float | None = None
    if total_clean is not None and clean_sum is not None:
        interaction = total_clean - clean_sum

    # Ensemble-vs-path gap on the full run.
    ensemble_gap: float | None = None
    if full.replay is not None:
        ensemble_gap = full.p50 - full.replay

    # (a) normal, adjusted level: full P50 minus the clean leg effects
    # (gap retained). Identity: normal_adjusted = normal_frozen +
    # ensemble_gap(full) - ensemble_gap(stripped); the stripped gap is
    # zero for a degenerate frozen MC.
    normal_adjusted: float | None = None
    if total_clean is not None:
        normal_adjusted = full.p50 - total_clean

    output = TwoValueOutput(
        case_id=request.case_id,
        metric=request.metric,
        unit=request.unit,
        horizon_tick=request.horizon_tick,
        horizon_label=request.horizon_label,
        normal_frozen_p50=normal_frozen_p50,
        normal_frozen_replay=normal_frozen_replay,
        normal_adjusted_p50=normal_adjusted,
        opportunity_total_clean=total_clean,
        opportunity_total_apparent=total_apparent,
        contributions=contributions,
        interaction_clean=interaction,
        ensemble_gap=ensemble_gap,
        combined_reference_p50=full.p50,
        sizing=request.sizing,
        actual=request.actual,
        overshoot_p50=overshoot,
        residual_frozen_p50=(
            normal_frozen_p50 - request.actual if request.actual is not None else None
        ),
        residual_frozen_pct=(
            (100.0 * (normal_frozen_p50 - request.actual) / request.actual)
            if request.actual not in (None, 0.0)
            else None
        ),
        residual_adjusted_p50=(
            normal_adjusted - request.actual
            if normal_adjusted is not None and request.actual is not None
            else None
        ),
        residual_adjusted_pct=(
            (100.0 * (normal_adjusted - request.actual) / request.actual)
            if normal_adjusted is not None and request.actual not in (None, 0.0)
            else None
        ),
        legs_stripped=[leg.leg_id for leg in request.legs],
        notes=notes,
    )
    return output


def discounted_growth_contribution(
    prompt: KeyOpportunityPrompt,
) -> ArithmeticContribution:
    """Derive a (b) from a discounted-growth prompt's projected levels.

    ``contribution = projected_observed - projected_discounted`` at the
    prompt's horizon. Returns None contribution (with the levels) when
    the prompt carries no paired level variable. The prompt's own
    ``caveat`` is carried over verbatim: this is a partial-equilibrium
    illustration, not a leg difference.
    """
    observed = prompt.projected_observed
    discounted = prompt.projected_discounted
    contribution: float | None = None
    if observed is not None and discounted is not None:
        contribution = observed - discounted
    return ArithmeticContribution(
        opportunity_id=f"discounted-growth:{prompt.variable_id}",
        variable_id=prompt.variable_id,
        contribution=contribution,
        projected_observed=observed,
        projected_discounted=discounted,
        horizon_ticks=prompt.horizon_ticks,
        basis_label=prompt.observed_label,
        caveat=prompt.caveat,
    )


__all__ = [
    "ArithmeticContribution",
    "LegContribution",
    "LegInput",
    "OutcomeRecord",
    "Sizing",
    "TwoValueOutput",
    "TwoValueRequest",
    "compute_two_value_output",
    "discounted_growth_contribution",
]

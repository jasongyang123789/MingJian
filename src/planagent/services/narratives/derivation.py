"""Pure deterministic direction derivation (Sprint 14, Part A).

``derive_directions`` is a pure function of its inputs: no I/O, no
clock, no randomness, no new simulation runs. The service assembles
:class:`DerivationCandidate` records from the stored ensembles of
the anchor run's scenario family; the derivation applies three
versioned rules in fixed order and reports an outcome for EVERY
rule. Same inputs derive byte-identical results (canonical JSON +
SHA-256, Sprint 3 discipline).

Candidate set (assembled by the service, documented here because
the rules assume it): every COMPLETED run in the anchor run's
scenario family (root ancestor + descendants, the Sprint 10 family
rule) that has a stored ensemble, each ``(run, arm)`` pair one
candidate. Arms are the ensemble's two fixed summaries,
``baseline`` and ``strategy``.

The anchor run itself is a candidate only for rule 3. Rules 1
and 2 compare CANDIDATE DIRECTIONS ONLY: the anchor (the
undecided direction) is excluded. Rationale (fix/derive-exclude-anchor,
Desay backtest 2026-11-19): a sub-run forks at anchor tick 1, so
it applies one fewer arm growth step than the anchor over the
same horizon — on a 5-year horizon that is 20% of the horizon,
and the anchor's ensemble systematically outranks every arm, so
``highest_p50`` kept recommending "stay undecided". The anchor
stays visible as the ``baseline_control`` reference instead.

Rules, in evaluation order (``derivation-rules-v3``):

1. ``highest_p50`` — the candidate direction (any run except the
   anchor) with the highest P50.
   Tie-breaks, in order: lowest loss probability, lowest run id,
   lowest arm (``baseline`` before ``strategy``).
2. ``most_robust`` — the candidate direction (any run except the
   anchor) with the lowest loss
   probability. Tie-breaks, in order: a stored lower-tail expected
   shortfall beats none; higher RELATIVE expected shortfall wins
   (the tail mean as a fraction of the candidate's own P50,
   compared at 0.01 resolution — see ``_relative_shortfall`` for
   why the ratio, not the absolute value, is compared, and why
   sub-1pp differences are treated as ties); highest P50; lowest
   run id; lowest arm.
   Only lower-tail expected shortfall counts: the loss-probability
   primary already assumes lower-is-worse (loss = below the
   threshold), and upper-tail shortfall answers a different
   question. An upper-tail-only result is treated as absent, and
   the alpha of a deciding shortfall is pinned on the outcome so a
   mixed-alpha comparison stays auditable.
3. ``baseline_control`` — the anchor run's ``baseline`` arm, when
   the anchor has a stored ensemble.

A direction rule with no eligible candidate reports ``none``
(the anchor-only family case: rules 1–2 are ``none`` while rule
3 still produces the baseline control).

Dedup: rules run in fixed order; a rule that selects a
``(run, arm)`` pair already taken by an earlier rule reports
``duplicate`` (naming the earlier rule) and emits nothing. The
direction count is capped at ``MAX_DIRECTIONS`` (3 rules, so the
cap never binds in v1 — it guards future rule sets).

Names are mechanical, from the rule (``Highest P50``,
``Most robust``, ``Baseline``). Renaming is the mapping layer's
job; derivation never invents names. A rule that finds no
candidate reports ``none`` with the reason — nothing is
fabricated, and the derivation never creates runs or ensembles.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from planagent.services.narratives.models import (
    DERIVATION_RULE_NAMES,
    MAX_DIRECTIONS,
    DerivationRuleOutcome,
    DirectionDefinition,
)

DERIVATION_RULES_VERSION = "derivation-rules-v3"

RuleId = Literal["highest_p50", "most_robust", "baseline_control"]
ArmName = Literal["baseline", "strategy"]


@dataclass(frozen=True)
class DerivationCandidate:
    """One ``(run, arm)`` pair eligible for rule selection.

    ``expected_shortfall`` carries ONLY a lower-tail value from the
    run's stored robustness fragment; it is ``None`` when no
    expected-shortfall result is stored or when the stored result
    uses the upper tail. ``expected_shortfall_alpha`` pins the
    alpha the value was computed at, for audit.
    """

    run_id: str
    arm: ArmName
    ensemble_id: str
    p50: float
    p_loss: float
    expected_shortfall: float | None = None
    expected_shortfall_alpha: float | None = None


class DerivationResult(BaseModel):
    """The pure derivation result: a pure function of its inputs.

    Carries no ids or timestamps, so its canonical JSON (and
    SHA-256) is stable across repeated derivations over identical
    inputs. ``candidates`` is the evaluated set in canonical
    ``(run_id, arm)`` order — it lists the anchor's arms too, so
    the exclusion is auditable; the two direction rules select
    only among the non-anchor candidates. ``directions`` are the
    produced direction definitions in rule order.
    """

    model_config = ConfigDict(extra="forbid")

    anchor_run_id: str
    rules_version: str = DERIVATION_RULES_VERSION
    candidates: list[dict] = Field(default_factory=list)
    outcomes: list[DerivationRuleOutcome] = Field(default_factory=list)
    directions: list[DirectionDefinition] = Field(default_factory=list)


def _candidate_sort_key(candidate: DerivationCandidate) -> tuple[str, str]:
    return (candidate.run_id, candidate.arm)


def _highest_p50_key(candidate: DerivationCandidate) -> tuple[float, float, str, str]:
    return (-candidate.p50, candidate.p_loss, candidate.run_id, candidate.arm)


def _relative_shortfall(candidate: DerivationCandidate) -> float:
    """Lower-tail expected shortfall as a fraction of the P50.

    The stored shortfall is a tail mean in metric units (revenue,
    share, ...). Comparing it absolutely makes the tie-break a
    level comparison: arms that differ mainly by a multiplicative
    growth level are near-scale copies of one shape (in the four
    e047f50 backtest cases the revenue CV is near-constant within a
    case, so ES ≈ k·P50 with k ≈ 0.86–0.94), and absolute ES then
    re-selects the highest P50 whenever ``p_loss`` ties — which is
    why ``most_robust`` never forked from ``highest_p50`` there.
    The ratio measures how bad the tail is relative to what the arm
    itself promises, so a high-median arm with a relatively fat
    tail can lose to a lower-median arm with a relatively tight
    tail.

    The ratio is compared at 0.01 resolution (rounded to two
    decimals): at trials=20, alpha=0.05 the stored tail mean is a
    SINGLE trial, so sub-1pp differences are measurement noise, not
    robustness — the Huawei 2000 arms are exact scale copies whose
    relative shortfalls agree to 4e-7, and an unrounded comparison
    would fork on that noise. A non-positive P50 has no meaningful
    ratio and loses the tie-break (``-inf``); real revenue/share
    medians are positive. Known limitation of bucketing: two ratios
    straddling a .xx5 boundary can land in different buckets on a
    <1pp true difference; the comparison stays deterministic
    (same inputs, same buckets), and the verdicts it changes are
    sub-1pp by construction.
    """

    if candidate.expected_shortfall is None:
        return 0.0
    if candidate.p50 > 0:
        return round(candidate.expected_shortfall / candidate.p50, 2)
    return float("-inf")


def _most_robust_key(candidate: DerivationCandidate) -> tuple[float, int, float, float, str, str]:
    has_shortfall = 0 if candidate.expected_shortfall is not None else 1
    shortfall_key = -_relative_shortfall(candidate)
    return (
        candidate.p_loss,
        has_shortfall,
        shortfall_key,
        -candidate.p50,
        candidate.run_id,
        candidate.arm,
    )


def derive_directions(
    anchor_run_id: str, candidates: list[DerivationCandidate]
) -> DerivationResult:
    """Apply the v3 rules to a candidate set, in fixed rule order.

    ``highest_p50`` and ``most_robust`` select only among
    candidates whose run is not the anchor: the anchor is the
    undecided direction, not a candidate direction. ``baseline_control``
    still selects the anchor's ``baseline`` arm as the reference.
    """
    ordered = sorted(candidates, key=_candidate_sort_key)
    # Direction pool: every candidate except the anchor run's arms.
    # The anchor's ensemble applies one more growth step than any
    # sub-run forked at tick 1, so comparing it against arms
    # systematically favors "stay undecided" on short horizons.
    direction_pool = [c for c in ordered if c.run_id != anchor_run_id]
    no_direction_reason = (
        "No candidate direction has a stored ensemble "
        "(the anchor run is excluded from direction selection; "
        "it is reported by baseline_control)."
    )
    taken: dict[tuple[str, str], str] = {}
    outcomes: list[DerivationRuleOutcome] = []
    directions: list[DirectionDefinition] = []

    selections: list[tuple[RuleId, DerivationCandidate | None, str]] = [
        (
            "highest_p50",
            min(direction_pool, key=_highest_p50_key) if direction_pool else None,
            no_direction_reason,
        ),
        (
            "most_robust",
            min(direction_pool, key=_most_robust_key) if direction_pool else None,
            no_direction_reason,
        ),
        (
            "baseline_control",
            next(
                (
                    candidate
                    for candidate in ordered
                    if candidate.run_id == anchor_run_id and candidate.arm == "baseline"
                ),
                None,
            ),
            f"Anchor run {anchor_run_id} has no stored ensemble.",
        ),
    ]

    for rule_id, selected, empty_reason in selections:
        name = DERIVATION_RULE_NAMES[rule_id]
        if selected is None:
            outcomes.append(
                DerivationRuleOutcome(
                    rule_id=rule_id,
                    status="none",
                    reason=empty_reason,
                )
            )
            continue
        pair = (selected.run_id, selected.arm)
        if pair in taken:
            outcomes.append(
                DerivationRuleOutcome(
                    rule_id=rule_id,
                    status="duplicate",
                    reason=(
                        f"Selected ({selected.run_id}, {selected.arm}), already taken "
                        f"by rule {taken[pair]!r}."
                    ),
                    duplicate_of_rule=taken[pair],
                    source_run_id=selected.run_id,
                    arm=selected.arm,
                    p50=selected.p50,
                    p_loss=selected.p_loss,
                    expected_shortfall=selected.expected_shortfall,
                    expected_shortfall_alpha=selected.expected_shortfall_alpha,
                )
            )
            continue
        if len(directions) >= MAX_DIRECTIONS:
            outcomes.append(
                DerivationRuleOutcome(
                    rule_id=rule_id,
                    status="none",
                    reason=f"Direction cap of {MAX_DIRECTIONS} reached.",
                    source_run_id=selected.run_id,
                    arm=selected.arm,
                )
            )
            continue
        taken[pair] = rule_id
        outcomes.append(
            DerivationRuleOutcome(
                rule_id=rule_id,
                status="produced",
                reason=f"Selected ({selected.run_id}, {selected.arm}).",
                direction_name=name,
                source_run_id=selected.run_id,
                arm=selected.arm,
                p50=selected.p50,
                p_loss=selected.p_loss,
                expected_shortfall=selected.expected_shortfall,
                expected_shortfall_alpha=selected.expected_shortfall_alpha,
            )
        )
        directions.append(
            DirectionDefinition(
                name=name,
                source_run_id=selected.run_id,
                arm=selected.arm,
            )
        )

    return DerivationResult(
        anchor_run_id=anchor_run_id,
        candidates=[
            {
                "run_id": candidate.run_id,
                "arm": candidate.arm,
                "ensemble_id": candidate.ensemble_id,
                "p50": candidate.p50,
                "p_loss": candidate.p_loss,
                "expected_shortfall": candidate.expected_shortfall,
                "expected_shortfall_alpha": candidate.expected_shortfall_alpha,
            }
            for candidate in ordered
        ],
        outcomes=outcomes,
        directions=directions,
    )


__all__ = [
    "DERIVATION_RULES_VERSION",
    "DerivationCandidate",
    "DerivationResult",
    "derive_directions",
]

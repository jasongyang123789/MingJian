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

Rules, in evaluation order (``derivation-rules-v1``):

1. ``highest_p50`` — the candidate with the highest P50.
   Tie-breaks, in order: lowest loss probability, lowest run id,
   lowest arm (``baseline`` before ``strategy``).
2. ``most_robust`` — the candidate with the lowest loss
   probability. Tie-breaks, in order: a stored lower-tail expected
   shortfall beats none; higher expected-shortfall value wins (the
   tail mean is less bad); highest P50; lowest run id; lowest arm.
   Only lower-tail expected shortfall counts: the loss-probability
   primary already assumes lower-is-worse (loss = below the
   threshold), and upper-tail shortfall answers a different
   question. An upper-tail-only result is treated as absent, and
   the alpha of a deciding shortfall is pinned on the outcome so a
   mixed-alpha comparison stays auditable.
3. ``baseline_control`` — the anchor run's ``baseline`` arm, when
   the anchor has a stored ensemble.

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

DERIVATION_RULES_VERSION = "derivation-rules-v1"

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
    ``(run_id, arm)`` order; ``directions`` are the produced
    direction definitions in rule order.
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


def _most_robust_key(candidate: DerivationCandidate) -> tuple[float, int, float, float, str, str]:
    has_shortfall = 0 if candidate.expected_shortfall is not None else 1
    shortfall_key = (
        -candidate.expected_shortfall if candidate.expected_shortfall is not None else 0.0
    )
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
    """Apply the v1 rules to a candidate set, in fixed rule order."""
    ordered = sorted(candidates, key=_candidate_sort_key)
    taken: dict[tuple[str, str], str] = {}
    outcomes: list[DerivationRuleOutcome] = []
    directions: list[DirectionDefinition] = []

    selections: list[tuple[RuleId, DerivationCandidate | None, str]] = [
        (
            "highest_p50",
            min(ordered, key=_highest_p50_key) if ordered else None,
            "No candidate has a stored ensemble.",
        ),
        (
            "most_robust",
            min(ordered, key=_most_robust_key) if ordered else None,
            "No candidate has a stored ensemble.",
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

"""Unit tests for Sprint 14 deterministic direction derivation.

The derivation is pure: no I/O, no clock, no randomness, no new
runs. Tests pin the tie-break rules exactly (P50, loss probability,
lower-tail expected shortfall, run id, arm), the dedup behavior, the
all-none empty case, and byte-identity of repeated derivations.
No live LLM call is ever made.
"""

from __future__ import annotations

from planagent.services.distributions.canonical import canonical_json, sha256_hash
from planagent.services.narratives.derivation import (
    DERIVATION_RULES_VERSION,
    DerivationCandidate,
    derive_directions,
)
from planagent.services.narratives.service import _lower_tail_shortfall
from planagent.services.robustness.models import (
    ExpectedShortfallDetail,
    ExpectedShortfallResult,
)

RUN_A = "run-a"
RUN_B = "run-b"


def _candidate(
    run_id: str,
    arm: str,
    p50: float,
    p_loss: float,
    expected_shortfall: float | None = None,
    alpha: float | None = None,
) -> DerivationCandidate:
    return DerivationCandidate(
        run_id=run_id,
        arm=arm,  # type: ignore[arg-type]
        ensemble_id=f"ens-{run_id}",
        p50=p50,
        p_loss=p_loss,
        expected_shortfall=expected_shortfall,
        expected_shortfall_alpha=alpha,
    )


def test_derive_rules_version_pinned() -> None:
    assert DERIVATION_RULES_VERSION == "derivation-rules-v2"
    result = derive_directions(RUN_A, [])
    assert result.rules_version == "derivation-rules-v2"


def test_derive_highest_p50_tie_breaks_by_loss_then_run_then_arm() -> None:
    candidates = [
        _candidate(RUN_A, "baseline", 30.0, 0.2),
        _candidate(RUN_A, "strategy", 10.0, 0.1),
        _candidate(RUN_B, "strategy", 30.0, 0.1),
        _candidate(RUN_B, "baseline", 30.0, 0.1),
    ]
    result = derive_directions(RUN_A, candidates)
    highest = result.outcomes[0]
    assert highest.rule_id == "highest_p50"
    assert highest.status == "produced"
    # The anchor (run-a) is excluded from direction selection even
    # though its baseline ties at P50 30 with the lowest loss: the
    # pool is run-b only, where the two-way P50 tie at 30 breaks on
    # loss (0.1 both), then run id, then arm (baseline first).
    assert highest.source_run_id == RUN_B
    assert highest.arm == "baseline"
    assert highest.direction_name == "Highest P50"
    assert highest.p50 == 30.0
    assert highest.p_loss == 0.1


def test_derive_anchor_excluded_from_highest_p50_despite_highest_p50() -> None:
    # Desay shape: the anchor outranks every arm on P50 (it applies
    # one more growth step than any forked sub-run), yet the rule
    # must pick the best candidate DIRECTION, not the anchor.
    candidates = [
        _candidate(RUN_A, "baseline", 8051.90, 0.0),
        _candidate(RUN_A, "strategy", 8051.90, 0.0),
        _candidate("run-b", "baseline", 5958.21, 0.0),
        _candidate("run-b", "strategy", 5958.21, 0.0),
        _candidate("run-c", "baseline", 4680.12, 0.0),
        _candidate("run-c", "strategy", 4680.12, 0.0),
    ]
    result = derive_directions(RUN_A, candidates)
    highest = result.outcomes[0]
    assert highest.status == "produced"
    assert highest.source_run_id == "run-b"
    assert highest.p50 == 5958.21
    # The anchor is still reported, as the baseline control.
    control = result.outcomes[2]
    assert control.status == "produced"
    assert control.source_run_id == RUN_A
    assert control.arm == "baseline"


def test_derive_anchor_excluded_from_most_robust_despite_lowest_loss() -> None:
    candidates = [
        _candidate(RUN_A, "baseline", 10.0, 0.0),
        _candidate(RUN_A, "strategy", 10.0, 0.0),
        _candidate(RUN_B, "baseline", 50.0, 0.5),
        _candidate(RUN_B, "strategy", 40.0, 0.4),
    ]
    result = derive_directions(RUN_A, candidates)
    robust = result.outcomes[1]
    assert robust.status == "produced"
    # Anchor p_loss 0.0 is the lowest in the family, but the anchor
    # is not a direction: the rule takes the lowest-loss arm, run-b
    # strategy at 0.4.
    assert robust.source_run_id == RUN_B
    assert robust.arm == "strategy"
    assert robust.p_loss == 0.4


def test_derive_direction_rules_none_with_anchor_only_family() -> None:
    # No sub-run has an ensemble: the direction rules report none
    # (with the exclusion named), while baseline_control still
    # produces the anchor baseline as the reference.
    result = derive_directions(RUN_A, [_candidate(RUN_A, "baseline", 10.0, 0.1)])
    assert [outcome.status for outcome in result.outcomes] == [
        "none",
        "none",
        "produced",
    ]
    assert "anchor run is excluded" in result.outcomes[0].reason
    assert "anchor run is excluded" in result.outcomes[1].reason
    assert len(result.directions) == 1
    assert result.directions[0].name == "Baseline"
    # The anchor candidate is still listed, so the exclusion is auditable.
    assert result.candidates == [
        {
            "run_id": RUN_A,
            "arm": "baseline",
            "ensemble_id": "ens-run-a",
            "p50": 10.0,
            "p_loss": 0.1,
            "expected_shortfall": None,
            "expected_shortfall_alpha": None,
        }
    ]


def test_derive_most_robust_prefers_shortfall_then_p50() -> None:
    candidates = [
        # Anchor outranks everything on P50 but is excluded from
        # both direction rules.
        _candidate(RUN_A, "baseline", 99.0, 0.0),
        _candidate(RUN_B, "baseline", 50.0, 0.1, expected_shortfall=-5.0, alpha=0.05),
        _candidate(RUN_B, "strategy", 10.0, 0.1, expected_shortfall=-2.0, alpha=0.05),
    ]
    result = derive_directions(RUN_A, candidates)
    highest = result.outcomes[0]
    assert highest.source_run_id == RUN_B
    assert highest.arm == "baseline"
    robust = result.outcomes[1]
    assert robust.rule_id == "most_robust"
    assert robust.status == "produced"
    # Both direction candidates share p_loss 0.1: a stored shortfall
    # beats none, and the higher shortfall value (-2.0, the less-bad
    # tail) beats -5.0 — so most_robust picks the strategy arm even
    # though its P50 is lower.
    assert robust.source_run_id == RUN_B
    assert robust.arm == "strategy"
    assert robust.direction_name == "Most robust"
    assert robust.expected_shortfall == -2.0
    assert robust.expected_shortfall_alpha == 0.05


def test_derive_most_robust_falls_back_to_p50_without_shortfall() -> None:
    candidates = [
        _candidate(RUN_A, "baseline", 10.0, 0.1),
        _candidate(RUN_B, "baseline", 40.0, 0.1),
        _candidate("run-c", "strategy", 99.0, 0.5),
    ]
    result = derive_directions(RUN_A, candidates)
    robust = result.outcomes[1]
    assert robust.status == "produced"
    # Highest P50 takes run-c; most_robust then breaks the p_loss
    # tie between run-a and run-b on P50, with no shortfall stored.
    assert robust.source_run_id == RUN_B
    assert robust.expected_shortfall is None


def test_derive_baseline_control_selects_anchor_baseline() -> None:
    candidates = [
        _candidate(RUN_A, "strategy", 99.0, 0.0),
        _candidate(RUN_A, "baseline", 1.0, 0.9),
        _candidate(RUN_B, "baseline", 50.0, 0.5),
    ]
    result = derive_directions(RUN_A, candidates)
    control = result.outcomes[2]
    assert control.rule_id == "baseline_control"
    assert control.status == "produced"
    assert control.source_run_id == RUN_A
    assert control.arm == "baseline"
    assert control.direction_name == "Baseline"


def test_derive_baseline_control_none_without_anchor_ensemble() -> None:
    candidates = [_candidate(RUN_B, "baseline", 50.0, 0.5)]
    result = derive_directions(RUN_A, candidates)
    control = result.outcomes[2]
    assert control.status == "none"
    assert RUN_A in control.reason


def test_derive_duplicate_reported_and_not_emitted() -> None:
    # One candidate direction: it wins highest_p50, most_robust
    # duplicates it, baseline_control takes the distinct anchor
    # baseline.
    result = derive_directions(
        RUN_A,
        [_candidate(RUN_A, "baseline", 10.0, 0.1), _candidate(RUN_B, "strategy", 20.0, 0.2)],
    )
    assert [outcome.status for outcome in result.outcomes] == [
        "produced",
        "duplicate",
        "produced",
    ]
    assert result.outcomes[1].duplicate_of_rule == "highest_p50"
    assert len(result.directions) == 2
    assert [direction.name for direction in result.directions] == [
        "Highest P50",
        "Baseline",
    ]


def test_derive_duplicate_names_earlier_rule_only() -> None:
    # highest_p50 and most_robust agree on (run-b, strategy);
    # baseline_control takes the distinct anchor baseline.
    candidates = [
        _candidate(RUN_A, "baseline", 5.0, 0.5),
        _candidate(RUN_B, "strategy", 80.0, 0.0),
    ]
    result = derive_directions(RUN_A, candidates)
    assert [outcome.status for outcome in result.outcomes] == [
        "produced",
        "duplicate",
        "produced",
    ]
    assert result.outcomes[1].duplicate_of_rule == "highest_p50"
    assert [direction.name for direction in result.directions] == [
        "Highest P50",
        "Baseline",
    ]


def test_derive_empty_candidates_all_rules_none() -> None:
    result = derive_directions(RUN_A, [])
    assert [outcome.status for outcome in result.outcomes] == ["none", "none", "none"]
    assert result.directions == []
    assert result.candidates == []


def test_derive_same_inputs_byte_identical() -> None:
    candidates = [
        _candidate(RUN_A, "baseline", 30.0, 0.2),
        _candidate(RUN_B, "strategy", 30.0, 0.1, expected_shortfall=-2.0, alpha=0.05),
    ]
    first = derive_directions(RUN_A, candidates)
    second = derive_directions(RUN_A, list(reversed(candidates)))
    first_dump = first.model_dump(mode="json")
    second_dump = second.model_dump(mode="json")
    assert canonical_json(first_dump) == canonical_json(second_dump)
    assert sha256_hash(first_dump) == sha256_hash(second_dump)


def test_derive_different_input_changes_hash() -> None:
    base = [_candidate(RUN_A, "baseline", 30.0, 0.2)]
    changed = [_candidate(RUN_A, "baseline", 31.0, 0.2)]
    first_hash = sha256_hash(derive_directions(RUN_A, base).model_dump(mode="json"))
    second_hash = sha256_hash(derive_directions(RUN_A, changed).model_dump(mode="json"))
    assert first_hash != second_hash


def test_derive_directions_carry_no_branches_or_pins() -> None:
    result = derive_directions(
        RUN_A, [_candidate(RUN_A, "baseline", 10.0, 0.1), _candidate(RUN_B, "strategy", 20.0, 0.2)]
    )
    for direction in result.directions:
        assert direction.mece_branches == []
        assert direction.deliberation_id is None


def test_derive_outcomes_cover_every_rule_in_order() -> None:
    result = derive_directions(RUN_A, [_candidate(RUN_A, "baseline", 10.0, 0.1)])
    assert [outcome.rule_id for outcome in result.outcomes] == [
        "highest_p50",
        "most_robust",
        "baseline_control",
    ]


# ---------------------------------------------------------------------------
# Lower-tail shortfall extraction (service helper, pure)
# ---------------------------------------------------------------------------


def _shortfall_result(tail: str) -> ExpectedShortfallResult:
    detail = ExpectedShortfallDetail(value=-3.5, threshold=-3.0, tail_count=1, n=5)
    strategy = ExpectedShortfallDetail(value=-1.5, threshold=-1.0, tail_count=1, n=5)
    return ExpectedShortfallResult(
        run_id=RUN_A,
        ensemble_id="ens-x",
        metric="cash",
        alpha=0.1,
        tail=tail,  # type: ignore[arg-type]
        baseline=detail,
        strategy=strategy,
        paired=detail,
        trial_values_hash="sha256:x",
        protocol="p1",
    )


def test_lower_tail_shortfall_returns_value_and_alpha() -> None:
    assert _lower_tail_shortfall(_shortfall_result("lower"), "baseline") == (-3.5, 0.1)
    assert _lower_tail_shortfall(_shortfall_result("lower"), "strategy") == (-1.5, 0.1)


def test_lower_tail_shortfall_ignores_upper_tail() -> None:
    assert _lower_tail_shortfall(_shortfall_result("upper"), "baseline") == (None, None)
    assert _lower_tail_shortfall(_shortfall_result("upper"), "strategy") == (None, None)


def test_lower_tail_shortfall_absent_without_result() -> None:
    assert _lower_tail_shortfall(None, "baseline") == (None, None)

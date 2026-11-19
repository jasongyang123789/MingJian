"""Unit tests for the deterministic completeness checks (Phase 4, Track 8).

Includes the two acceptance tests:

1. desay-2020 MUST flag the missing NEV chain AND the
   domain-controller substitution (missing_driver / missing_link, high).
2. The complete case (same situation, drivers present + linked) must
   NOT hallucinate missing drivers — no high-severity missing_driver.
"""

from __future__ import annotations

from planagent.services.redteam.completeness import run_completeness_checks
from planagent.services.redteam.models import CaseSnapshot, RedTeamVariable
from tests.redteam_cases import complete_case_snapshot, desay_2020_snapshot


def _by_kind_target(findings):
    return {(f.kind, f.target): f for f in findings}


def test_acceptance_desay2020_flags_nev_and_domain_controller() -> None:
    findings = run_completeness_checks(desay_2020_snapshot())
    by_key = _by_kind_target(findings)

    nev = by_key.get(("missing_driver", "nev_penetration"))
    assert nev is not None, f"NEV finding missing; got: {findings}"
    assert nev.severity == "high"
    assert nev.source == "completeness_check"
    assert nev.boundary_class == "fixable_defect"
    assert "decision-time" in nev.boundary_basis
    assert "NEV" in nev.evidence[0] or "nev" in nev.evidence[0].lower()
    assert nev.id == "rt-missing_driver-nev_penetration"

    dc = by_key.get(("missing_link", "domain_controller_substitution"))
    assert dc is not None, f"domain-controller finding missing; got: {findings}"
    assert dc.severity == "high"
    assert dc.source == "completeness_check"
    assert dc.boundary_class == "fixable_defect"
    assert "decision-time" in dc.boundary_basis
    assert dc.id == "rt-missing_link-domain_controller_substitution"


def test_acceptance_complete_case_no_high_missing_driver() -> None:
    findings = run_completeness_checks(complete_case_snapshot())
    high_missing = [f for f in findings if f.kind == "missing_driver" and f.severity == "high"]
    assert high_missing == [], f"hallucinated drivers: {high_missing}"
    assert findings == [], f"complete case should be clean; got: {findings}"


def test_desay2020_also_flags_adas_penetration_medium() -> None:
    findings = run_completeness_checks(desay_2020_snapshot())
    by_key = _by_kind_target(findings)
    adas = by_key.get(("missing_driver", "adas_penetration"))
    assert adas is not None
    assert adas.severity == "medium"
    assert adas.boundary_class == "fixable_defect"
    # The basis must name THIS driver, not another catalog entry's.
    assert "ADAS" in adas.boundary_basis
    assert "NEV" not in adas.boundary_basis


def test_desay2020_finding_ids_are_stable() -> None:
    first = run_completeness_checks(desay_2020_snapshot())
    second = run_completeness_checks(desay_2020_snapshot())
    assert [f.id for f in first] == [f.id for f in second]
    assert [f.model_dump(mode="json") for f in first] == [f.model_dump(mode="json") for f in second]


def test_no_findings_when_situation_names_no_driver() -> None:
    snapshot = CaseSnapshot(
        case_id="generic",
        decision_question="Should we launch the AI line?",
        variables=[
            RedTeamVariable(
                name="revenue_growth",
                distribution="triangular(0.05, 0.10, 0.20)",
                low=0.05,
                mode=0.10,
                high=0.20,
                evidence=["founder judgment"],
            )
        ],
        internal_situation="The team is 20 people; the market is growing.",
    )
    assert run_completeness_checks(snapshot) == []


def test_driver_present_but_unlinked_is_missing_link_medium() -> None:
    snapshot = desay_2020_snapshot()
    snapshot.variables.append(
        RedTeamVariable(
            name="nev_penetration",
            description="NEV share of new-car sales",
            distribution="triangular(0.05, 0.08, 0.20)",
            low=0.05,
            mode=0.08,
            high=0.20,
            evidence=["CAAM 2020 NEV penetration 5.4%"],
        )
    )
    findings = run_completeness_checks(snapshot)
    by_key = _by_kind_target(findings)
    # NEV driver no longer missing, but it moves nothing: unlinked.
    assert ("missing_driver", "nev_penetration") not in by_key
    unlinked = by_key.get(("missing_link", "nev_penetration"))
    assert unlinked is not None
    assert unlinked.severity == "medium"


def test_justified_discount_does_not_fire() -> None:
    # desay revenue_growth: mode 15% vs cited +27.39%, justified by
    # "恢复年" in its own evidence — the honest discount must not fire.
    findings = run_completeness_checks(desay_2020_snapshot())
    by_key = _by_kind_target(findings)
    assert ("unjustified_discount", "revenue_growth") not in by_key


def test_unjustified_discount_fires_without_reason() -> None:
    snapshot = CaseSnapshot(
        case_id="discount",
        decision_question="Grow or hold?",
        variables=[
            RedTeamVariable(
                name="revenue_growth",
                distribution="triangular(0.01, 0.05, 0.10)",
                low=0.01,
                mode=0.05,
                high=0.10,
                evidence=["Last year revenue grew +27.39%."],
            )
        ],
        internal_situation="Revenue grew strongly last year.",
    )
    findings = run_completeness_checks(snapshot)
    by_key = _by_kind_target(findings)
    discount = by_key.get(("unjustified_discount", "revenue_growth"))
    assert discount is not None
    assert discount.severity == "medium"
    assert "27.39" in discount.evidence[0]


def test_overconfident_parameter_fires_on_tight_triangular() -> None:
    snapshot = CaseSnapshot(
        case_id="tight",
        decision_question="Grow or hold?",
        variables=[
            RedTeamVariable(
                name="market_share",
                distribution="triangular(0.099, 0.10, 0.101)",
                low=0.099,
                mode=0.10,
                high=0.101,
                evidence=["audited disclosure"],
            )
        ],
        internal_situation="Share is roughly 10%.",
    )
    findings = run_completeness_checks(snapshot)
    by_key = _by_kind_target(findings)
    tight = by_key.get(("overconfident_parameter", "market_share"))
    assert tight is not None
    assert tight.severity == "medium"


def test_weak_assumption_fires_on_evidence_free_variable() -> None:
    snapshot = CaseSnapshot(
        case_id="weak",
        decision_question="Grow or hold?",
        variables=[
            RedTeamVariable(
                name="mystery_rate",
                distribution="triangular(0.0, 0.05, 0.10)",
                low=0.0,
                mode=0.05,
                high=0.10,
            )
        ],
        internal_situation="No drivers named here.",
    )
    findings = run_completeness_checks(snapshot)
    by_key = _by_kind_target(findings)
    weak = by_key.get(("weak_assumption", "mystery_rate"))
    assert weak is not None
    assert weak.severity == "low"


def test_no_generic_no_chain_finding() -> None:
    # There is deliberately no generic "no formulas" finding: the chain
    # gap is reported only through the specific, evidence-grounded
    # checks. A growth case whose situation names no catalog driver
    # stays clean.
    snapshot = CaseSnapshot(
        case_id="simple",
        decision_question="Grow or hold?",
        variables=[
            RedTeamVariable(
                name="revenue_growth",
                distribution="triangular(0.05, 0.10, 0.20)",
                low=0.05,
                mode=0.10,
                high=0.20,
                evidence=["judgment"],
            )
        ],
        formulas=[],
        internal_situation="The market is growing steadily.",
    )
    assert run_completeness_checks(snapshot) == []


def test_formula_link_silences_unlinked_driver() -> None:
    snapshot = complete_case_snapshot()
    findings = run_completeness_checks(snapshot)
    assert findings == []


def test_evidence_mention_does_not_count_as_coverage() -> None:
    # A passing NEV mention inside another variable's evidence must NOT
    # suppress the missing-driver finding: coverage scans name +
    # description only.
    snapshot = desay_2020_snapshot()
    assert any("NEV" in e for v in snapshot.variables for e in v.evidence)
    findings = run_completeness_checks(snapshot)
    by_key = _by_kind_target(findings)
    assert ("missing_driver", "nev_penetration") in by_key


__all__ = []

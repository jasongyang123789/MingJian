"""Phase 4 Track 10: deterministic driver-completeness meta-check.

Acceptance tests (from the track brief):
1. desay-2020 MUST flag the missing NEV chain as the TOP risk
   (kind missing_driver, severity high, ranked first, meta-check
   phrasing) — the exact miss in desay-backtest-2026-11-19/REPORT.md:
   the case had NO NEV-penetration variable and NO
   domain-controller-substitution variable, and nothing flagged it.
2. A case where the drivers ARE present (the full automotive template)
   must NOT flag missing drivers.

Setup mirrors tests/test_automotive_phase2_api.py (isolated SQLite
app per test, no network, no live LLM). The check itself is a pure
function; the API tests only prove the endpoint wires it through.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from planagent.config import reset_settings_cache
from planagent.db import reset_database_cache
from planagent.main import create_app
from planagent.services.completeness import (
    AUTOMOTIVE_DRIVER_REGISTRY,
    GENERAL_DRIVER_CHECKLIST,
    META_CHECK_PREFIX,
    UNCLASSIFIED_BASIS,
    BoundaryClass,
    CompletenessCase,
    FindingKind,
    FindingSeverity,
    FindingSource,
    RedTeamFinding,
    ResidualGap,
    run_completeness_check,
)
from planagent.simulation.domain_packs.automotive.pack import AutomotiveDomainPack

# --- desay-2020, verbatim from
# ~/workspace/research/strategy-engine/desay-backtest-2026-11-19/REPORT.md
# §案例二 "变量": the whole model was generic corporate variables.
# No NEV-penetration variable, no domain-controller-substitution
# variable — and nothing in the model flagged either absence.
DESAY_2020_VARIABLE_IDS = [
    "market_share",
    "base_growth",
    "disruptor_ceiling",
    "disruptor_rate",
    "disruptor_midpoint",
    "share_coupling",
    "revenue",
    "revenue_growth",
    "revenue_coupling",
    "profit",
    # R&D margin promotion (2026-11-20): the dead profit_growth /
    # profit_coupling variables are DELETED (the pack chain replaces
    # them) and the eight R&D decomposition variables take their
    # place — this is the new case variable table, synced from the
    # pack rerun harness. drivers_missing is UNCHANGED at 16: no
    # registry entry's model_elements names profit_growth,
    # profit_coupling, or any gross_*/rd_*/other_share id, so the
    # count is identical before and after.
    "gross_base",
    "gross_longrun",
    "gross_reversion",
    "rd_base",
    "rd_longrun",
    "rd_reversion",
    "rd_adoption",
    "other_share",
]
DESAY_2020_KEY_VARIABLES = ["market_share", "revenue", "profit"]


def build_database_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def setup_app(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(
        "PLANAGENT_DATABASE_URL", build_database_url(tmp_path / "completeness-test.db")
    )
    monkeypatch.setenv("PLANAGENT_EVENT_BUS_BACKEND", "memory")
    monkeypatch.setenv("PLANAGENT_INLINE_INGEST_DEFAULT", "true")
    monkeypatch.setenv("PLANAGENT_INLINE_SIMULATION_DEFAULT", "true")
    monkeypatch.setenv("PLANAGENT_OPENAI_API_KEY", "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    reset_settings_cache()
    reset_database_cache()


def desay_2020_case() -> CompletenessCase:
    return CompletenessCase(
        domain_id="automotive",
        variable_ids=list(DESAY_2020_VARIABLE_IDS),
        key_variables=list(DESAY_2020_KEY_VARIABLES),
    )


def desay_2020_residual_gap() -> ResidualGap:
    """The diagnostic-2020 §5.2 residual: with the NEV chain added at
    defensible 2020 values, B year-5 revenue reaches only 18212 vs the
    32557.18 actual. The fitted values needed to close the rest are
    indefensible at decision time — §6 acceptable limit."""
    return ResidualGap(
        id="revenue",
        target="revenue",
        actual=32557.18,
        model_with_fix=18212,
        unit="百万元",
        basis=(
            "§6 acceptable limit: closing the rest would need revenue_growth "
            "0.377–0.734 / revenue_coupling 0.83–2.83, indefensible at "
            "2020-12-31 — only knowable from post-decision data "
            "(diagnostic-2020 §5.2, §6)."
        ),
    )


def desay_2020_case_with_residual() -> CompletenessCase:
    case = desay_2020_case()
    case.residual_gaps = [desay_2020_residual_gap()]
    return case


def full_automotive_case() -> CompletenessCase:
    pack = AutomotiveDomainPack()
    return CompletenessCase(
        domain_id="automotive",
        variable_ids=[v["id"] for v in pack.template_variables()],
        formula_outputs=[f["output"] for f in pack.template_formulas()],
        rule_ids=["auto.material_cost_shock", "auto.rate_cut", "auto.nev_momentum"],
        assumption_data_keys=list(pack.template_assumption_data().keys()),
        key_variables=["revenue", "market_share", "production_volume", "tier1_gross_margin"],
    )


# ---------------------------------------------------------------------------
# Registry contents
# ---------------------------------------------------------------------------


def test_registry_has_sixteen_entries_with_unique_ids() -> None:
    ids = [e.id for e in AUTOMOTIVE_DRIVER_REGISTRY]
    assert len(ids) == 16
    assert len(set(ids)) == 16


def test_registry_entries_are_complete_and_valid() -> None:
    for entry in AUTOMOTIVE_DRIVER_REGISTRY:
        assert entry.name and entry.description
        assert entry.severity in {"high", "medium", "low"}
        assert 0 < entry.weight <= 1.0
        assert entry.drives, entry.id
        assert entry.model_elements, entry.id
        assert entry.evidence, entry.id
        assert entry.suggested_fix, entry.id


def test_registry_covers_the_packs_transmission_links() -> None:
    """Every transmission-link variable in the auto pack is in the registry.

    The registry is a snapshot of the pack's known links; if the pack
    gains a link and the registry does not, this test fails loudly
    instead of the check silently missing the new driver.
    """
    pack = AutomotiveDomainPack()
    template_ids = {v["id"] for v in pack.template_variables()}
    state_fields = {f.name for f in pack.state_fields}
    registry_elements = {el for e in AUTOMOTIVE_DRIVER_REGISTRY for el in e.model_elements}
    link_variables = {
        "nev_penetration",
        "nev_penetration_monthly_drift",
        "income_index",
        "income_growth_rate_annual",
        "lpr_proxy",
        "material_cost_index",
        "consumer_confidence_proxy",
        "policy_tax_rate",
        "trade_in_support",
        "pull_forward_stock",
        "chip_supply_index",
        "chip_lead_time_weeks",
        "price_index",
        "promo_rate",
        "price_cut_expectation",
        "generation_transition_index",
        "dms_mandate",
        "export_volume",
        "capacity_utilization",
        "dealer_inventory_coef",
        "annual_cut_rate",
        "payment_terms_months",
        "tier1_gross_margin",
    }
    assert link_variables <= template_ids | state_fields
    assert link_variables <= registry_elements


def test_registry_link_outputs_are_real_formula_outputs() -> None:
    """A link output must be something a formula/driver actually produces.

    Listing a bare state field (e.g. `revenue`, which no formula
    outputs) would make a complete case fail as `missing_link`.
    """
    pack = AutomotiveDomainPack()
    formula_outputs = {f["output"] for f in pack.template_formulas()}
    for entry in AUTOMOTIVE_DRIVER_REGISTRY:
        assert set(entry.link_outputs) <= formula_outputs, entry.id


def test_registry_every_entry_has_a_real_model_element() -> None:
    """Every entry is anchored in the pack: at least one element is a
    template variable, a formula output, a rule id, or an
    assumption-data key — never a free-floating invented id."""
    pack = AutomotiveDomainPack()
    template_ids = {v["id"] for v in pack.template_variables()}
    formula_outputs = {f["output"] for f in pack.template_formulas()}
    assumption_keys = set(pack.template_assumption_data().keys())
    rule_ids = {
        "auto.policy_tax_hike",
        "auto.price_war",
        "auto.inventory_overhang",
        "auto.chip_shortage",
        "auto.demand_surge",
        "auto.dms_mandate",
        "auto.generation_changeover",
        "auto.margin_pressure",
        "auto.export_hedge",
        "auto.subsidy_payback",
        "auto.material_cost_shock",
        "auto.rate_cut",
        "auto.nev_momentum",
    }
    real = template_ids | formula_outputs | assumption_keys | rule_ids
    for entry in AUTOMOTIVE_DRIVER_REGISTRY:
        assert set(entry.model_elements) & real, entry.id


def test_general_checklist_has_eight_questions() -> None:
    assert len(GENERAL_DRIVER_CHECKLIST) == 8
    assert len({item.id for item in GENERAL_DRIVER_CHECKLIST}) == 8
    for item in GENERAL_DRIVER_CHECKLIST:
        assert item.question and item.keywords and item.suggested_fix


# ---------------------------------------------------------------------------
# Finding shape (shared with Track 8 — use EXACTLY this)
# ---------------------------------------------------------------------------


def test_finding_shape_matches_the_shared_contract() -> None:
    report = run_completeness_check(desay_2020_case())
    finding = report.findings[0]
    assert isinstance(finding, RedTeamFinding)
    assert set(finding.model_dump().keys()) == {
        "id",
        "kind",
        "target",
        "severity",
        "summary",
        "evidence",
        "suggested_fix",
        "source",
        "boundary_class",
        "boundary_basis",
    }
    assert finding.source is FindingSource.COMPLETENESS_CHECK
    assert finding.kind in {
        FindingKind.MISSING_DRIVER,
        FindingKind.MISSING_LINK,
    }
    # JSON round-trip: the shape must survive the API boundary unchanged.
    round_tripped = RedTeamFinding.model_validate_json(finding.model_dump_json())
    assert round_tripped == finding


# ---------------------------------------------------------------------------
# Acceptance test 1: desay-2020 — NEV chain is the TOP risk
# ---------------------------------------------------------------------------


def test_desay_2020_flags_nev_chain_as_top_risk() -> None:
    report = run_completeness_check(desay_2020_case())
    assert report.registry == "automotive"
    assert report.drivers_checked == 16
    assert report.drivers_present == 0
    assert report.drivers_missing == 16

    top = report.top_finding
    assert top is not None
    assert report.findings[0] == top
    assert top.id == "completeness:nev_penetration"
    assert top.kind is FindingKind.MISSING_DRIVER
    assert top.severity is FindingSeverity.HIGH
    assert top.target == "revenue"
    assert top.summary.startswith(META_CHECK_PREFIX + ": NEV penetration chain")
    assert top.source is FindingSource.COMPLETENESS_CHECK
    assert top.evidence  # cited facts, incl. the 52.3% desay-2020 miss
    assert any("52.3%" in line for line in top.evidence)
    assert top.suggested_fix


def test_desay_2020_also_flags_domain_controller_substitution() -> None:
    report = run_completeness_check(desay_2020_case())
    by_id = {f.id: f for f in report.findings}
    dc = by_id["completeness:domain_controller_substitution"]
    assert dc.kind is FindingKind.MISSING_DRIVER
    assert dc.severity is FindingSeverity.HIGH
    assert dc.target == "revenue"
    # Ranked second: NEV first, domain-controller substitution second.
    assert report.findings[1].id == "completeness:domain_controller_substitution"
    # Only the TOP finding carries the meta-check phrasing.
    assert not dc.summary.startswith(META_CHECK_PREFIX)


def test_desay_2020_generic_adoption_does_not_count_as_nev() -> None:
    """The exact miss: `disruptor_rate` is a generic adoption curve,
    not the NEV chain. The check must not let it cover the NEV driver."""
    report = run_completeness_check(desay_2020_case())
    assert "completeness:nev_penetration" in {f.id for f in report.findings}


def test_desay_2020_coverage_lists_revenue_drivers_missing() -> None:
    report = run_completeness_check(desay_2020_case())
    revenue = report.coverage["revenue"]
    assert "nev_penetration" in revenue.missing
    assert "domain_controller_substitution" in revenue.missing
    assert revenue.present == []


# ---------------------------------------------------------------------------
# §6 boundary classification (diagnostic-2020 §6; Ho 2026-11-19 15:02)
# ---------------------------------------------------------------------------


def test_nev_finding_is_a_fixable_defect() -> None:
    """The meta-check's top finding must carry the §6 verdict: the NEV
    chain was encodable from decision-time public evidence, so its
    absence is a defect to fix — not a prediction limit."""
    report = run_completeness_check(desay_2020_case())
    top = report.top_finding
    assert top is not None
    assert top.boundary_class is BoundaryClass.FIXABLE_DEFECT
    assert "§6" in top.boundary_basis
    assert "2020-12-31" in top.boundary_basis


def test_all_registry_findings_are_fixable_defects() -> None:
    """Every registry entry is fixable_defect by admission: a driver
    enters the registry only when decision-time public evidence exists
    to encode it as a distribution."""
    report = run_completeness_check(desay_2020_case())
    for finding in report.findings:
        assert finding.boundary_class is BoundaryClass.FIXABLE_DEFECT, finding.id
        assert finding.boundary_basis, finding.id
        assert "§6" in finding.boundary_basis, finding.id


def test_missing_link_finding_inherits_the_entry_verdict() -> None:
    case = CompletenessCase(
        domain_id="automotive",
        variable_ids=["nev_penetration", "revenue"],
        key_variables=["revenue"],
    )
    report = run_completeness_check(case)
    link = next(f for f in report.findings if f.id == "completeness:nev_penetration:link")
    assert link.boundary_class is BoundaryClass.FIXABLE_DEFECT


def test_checklist_findings_are_unclassified_not_forced() -> None:
    case = CompletenessCase(
        domain_id="corporate",
        variable_ids=["market_share", "revenue_growth"],
        key_variables=["revenue"],
    )
    report = run_completeness_check(case)
    assert report.findings
    for finding in report.findings:
        assert finding.boundary_class is BoundaryClass.UNCLASSIFIED, finding.id
        assert finding.boundary_basis == UNCLASSIFIED_BASIS


def test_desay_2020_residual_gap_is_an_acceptable_limit() -> None:
    """The §6 demonstration: NEV-chain missing = fixable defect (top
    finding); the 18212 → 32557 remainder = acceptable limit. Both
    verdicts must appear in the same finding output."""
    report = run_completeness_check(desay_2020_case_with_residual())
    by_id = {f.id: f for f in report.findings}
    # The meta-check is unchanged: NEV still first, still a defect.
    assert report.findings[0].id == "completeness:nev_penetration"
    assert report.findings[0].boundary_class is BoundaryClass.FIXABLE_DEFECT
    residual = by_id["completeness:residual:revenue"]
    assert residual.kind is FindingKind.WEAK_ASSUMPTION
    assert residual.target == "revenue"
    assert residual.severity is FindingSeverity.MEDIUM
    assert residual.boundary_class is BoundaryClass.ACCEPTABLE_LIMIT
    assert "§6" in residual.boundary_basis
    assert "18212" in " ".join(residual.evidence)
    assert "32557.18" in " ".join(residual.evidence)
    assert "hindsight firewall" in residual.suggested_fix
    # The residual is a limit, so it never outranks a defect: it sorts
    # among the mediums, below every high-severity finding.
    high_ids = [f.id for f in report.findings if f.severity is FindingSeverity.HIGH]
    assert report.findings.index(residual) >= len(high_ids)


def test_no_residual_input_means_no_residual_finding() -> None:
    """The check has no actuals, so it cannot invent a residual. A
    residual finding only appears when the backtest/diagnostic flow
    supplies one."""
    report = run_completeness_check(desay_2020_case())
    assert not [f for f in report.findings if f.id.startswith("completeness:residual:")]


# ---------------------------------------------------------------------------
# Acceptance test 2: complete case — no missing drivers
# ---------------------------------------------------------------------------


def test_full_automotive_template_flags_nothing() -> None:
    report = run_completeness_check(full_automotive_case())
    assert report.registry == "automotive"
    assert report.drivers_checked == 16
    assert report.drivers_present == 16
    assert report.drivers_missing == 0
    assert report.findings == []
    assert report.top_finding is None


def test_full_automotive_template_without_assumption_data_flags_dc() -> None:
    """Documents the carrier: DC substitution lives in the template's
    assumption data (`fitment_lookup`), not in a variable. A case that
    binds the variables but drops the assumption data is genuinely
    missing the DC driver."""
    case = full_automotive_case()
    case.assumption_data_keys = []
    report = run_completeness_check(case)
    assert [f.id for f in report.findings] == ["completeness:domain_controller_substitution"]


# ---------------------------------------------------------------------------
# Missing link: present but unlinked
# ---------------------------------------------------------------------------


def test_present_but_unlinked_driver_is_missing_link() -> None:
    case = CompletenessCase(
        domain_id="automotive",
        variable_ids=["nev_penetration", "revenue"],
        key_variables=["revenue"],
    )
    report = run_completeness_check(case)
    by_id = {f.id: f for f in report.findings}
    assert by_id["completeness:nev_penetration:link"].kind is FindingKind.MISSING_LINK
    assert "completeness:nev_penetration" not in by_id


def test_present_and_linked_driver_passes() -> None:
    case = CompletenessCase(
        domain_id="automotive",
        variable_ids=["nev_penetration", "revenue"],
        driver_outputs=["nev_production_volume"],
        key_variables=["revenue"],
    )
    report = run_completeness_check(case)
    assert "completeness:nev_penetration" not in {f.id for f in report.findings}
    assert "completeness:nev_penetration:link" not in {f.id for f in report.findings}


# ---------------------------------------------------------------------------
# General checklist (domains without a registry)
# ---------------------------------------------------------------------------


def test_checklist_flags_open_questions_for_bare_corporate_case() -> None:
    case = CompletenessCase(
        domain_id="corporate",
        variable_ids=["market_share", "revenue_growth"],
        key_variables=["revenue"],
    )
    report = run_completeness_check(case)
    assert report.registry == "general-checklist"
    flagged = {f.id for f in report.findings}
    # `market_share` covers competition ("share"); `revenue_growth`
    # covers nothing else. The rest stay open questions.
    assert "completeness:checklist:competition" not in flagged
    assert "completeness:checklist:external_demand" in flagged
    assert "completeness:checklist:substitution" in flagged
    assert "completeness:checklist:policy" in flagged
    assert all(f.severity is FindingSeverity.MEDIUM for f in report.findings)
    assert all(f.source is FindingSource.COMPLETENESS_CHECK for f in report.findings)


def test_checklist_passes_when_every_question_is_covered() -> None:
    case = CompletenessCase(
        domain_id="corporate",
        variable_ids=[
            "market_demand_growth",
            "input_cost_index",
            "substitution_rate",
            "policy_tax_rate",
            "supply_capacity",
            "competitor_share",
            "interest_rate",
            "technology_platform",
        ],
        key_variables=["revenue"],
    )
    report = run_completeness_check(case)
    assert report.findings == []
    assert report.top_finding is None


def test_unknown_domain_falls_back_to_checklist() -> None:
    report = run_completeness_check(
        CompletenessCase(
            domain_id="military", variable_ids=["readiness"], key_variables=["readiness"]
        )
    )
    assert report.registry == "general-checklist"


# ---------------------------------------------------------------------------
# Determinism + ranking
# ---------------------------------------------------------------------------


def test_check_is_deterministic_under_input_shuffling() -> None:
    case = desay_2020_case()
    first = run_completeness_check(case).model_dump_json()
    shuffled = desay_2020_case()
    shuffled.variable_ids = list(reversed(shuffled.variable_ids))
    shuffled.key_variables = list(reversed(shuffled.key_variables))
    assert run_completeness_check(shuffled).model_dump_json() == first
    # And a repeat run is byte-identical.
    assert run_completeness_check(desay_2020_case()).model_dump_json() == first


def test_ranking_is_severity_then_weight() -> None:
    report = run_completeness_check(desay_2020_case())
    severities = [f.severity for f in report.findings]
    assert severities == sorted(
        severities, key=lambda s: {"high": 0, "medium": 1, "low": 2}[s.value]
    )
    highs = [f for f in report.findings if f.severity is FindingSeverity.HIGH]
    assert [f.id for f in highs] == [
        "completeness:nev_penetration",
        "completeness:domain_controller_substitution",
        "completeness:income",
        "completeness:lpr_financing",
        "completeness:raw_materials",
    ]


def test_finding_ids_are_stable() -> None:
    first = {f.id for f in run_completeness_check(desay_2020_case()).findings}
    second = {f.id for f in run_completeness_check(desay_2020_case()).findings}
    assert first == second
    assert all(i.startswith("completeness:") for i in first)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_api_check_desay_2020_flags_nev_top(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        response = client.post(
            "/completeness/check",
            json={
                "domain_id": "automotive",
                "variable_ids": DESAY_2020_VARIABLE_IDS,
                "key_variables": DESAY_2020_KEY_VARIABLES,
            },
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["top_finding"]["id"] == "completeness:nev_penetration"
    assert body["top_finding"]["kind"] == "missing_driver"
    assert body["top_finding"]["severity"] == "high"
    assert body["top_finding"]["summary"].startswith(META_CHECK_PREFIX)
    assert body["top_finding"]["source"] == "completeness_check"
    assert body["drivers_missing"] == 16


def test_api_check_desay_2020_with_residual_shows_both_verdicts(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    case = desay_2020_case_with_residual()
    with TestClient(create_app()) as client:
        response = client.post("/completeness/check", json=case.model_dump())
    assert response.status_code == 200, response.text
    body = response.json()
    by_id = {f["id"]: f for f in body["findings"]}
    assert by_id["completeness:nev_penetration"]["boundary_class"] == "fixable_defect"
    assert by_id["completeness:residual:revenue"]["boundary_class"] == "acceptable_limit"
    assert by_id["completeness:residual:revenue"]["kind"] == "weak_assumption"


def test_api_check_full_template_flags_nothing(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    case = full_automotive_case()
    with TestClient(create_app()) as client:
        response = client.post("/completeness/check", json=case.model_dump())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["findings"] == []
    assert body["top_finding"] is None
    assert body["drivers_missing"] == 0


def test_api_check_rejects_malformed_case(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        response = client.post("/completeness/check", json={"domain_id": "automotive", "bogus": 1})
    assert response.status_code == 422


def test_api_drivers_lists_automotive_registry(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        response = client.get("/completeness/drivers", params={"domain_id": "automotive"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["registry"] == "automotive"
    assert len(body["drivers"]) == 16
    assert body["drivers"][0]["id"] == "nev_penetration"
    assert body["drivers"][0]["boundary_class"] == "fixable_defect"
    assert "§6" in body["drivers"][0]["boundary_basis"]
    assert body["checklist"] == []


def test_api_drivers_falls_back_to_checklist(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        response = client.get("/completeness/drivers", params={"domain_id": "corporate"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["registry"] == "general-checklist"
    assert body["drivers"] == []
    assert len(body["checklist"]) == 8
    assert body["checklist"][0]["id"] == "external_demand"

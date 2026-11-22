"""Track C1 — ADAS penetration chain tests (gap audit §3 C1).

The chain is the audit's build spec (gap-audit-2026-11-20/REPORT.md
§3 C1): four triangular variables (``adas_ceiling`` / ``adas_rate`` /
``adas_midpoint`` / ``adas_coupling``) + the pack's
``adas_penetration`` STATE field reused as the penetration (no
duplicate intermediate) + a case-level logistic tick driver that
replaces the template's drift driver per-output at merge time + a
revenue tick driver that gains exactly one additive term
(``+ adas_coupling * adas_penetration``) + a share tick driver that
gains exactly one additive term
(``+ adas_share_coupling * adas_penetration`` — case-level only,
like ``share_coupling``). No interaction term; profit is untouched.

Division of labor with the existing channels (the design
precondition, TRACK-C1.md §1) — the tests below pin it, they do not
just document it:

- ``disruptor_adoption`` is BREADTH: any smart-cockpit/ADAS function
  (L0-L2 combined). ``adas_penetration`` is GRADE: L2 within new
  cars. The two terms are ADDITIVE and SEPARABLE: zeroing the ADAS
  couplings reproduces the pure-adoption path exactly, and zeroing
  adoption leaves the ADAS term carrying revenue on its own. If the
  same effect were counted twice, neither property would hold.
- The coupling's mode (0.25) is set by analogy to ``nev_coupling``,
  never from the intelligent-driving segment's 10.48% revenue share —
  that share includes L0/L1 content already priced by
  ``revenue_coupling``.

Tests are deterministic (fixed distributions) except where the
distribution itself is asserted. API tests use the isolated-SQLite +
in-memory-bus pattern from the Phase 2 automotive API tests.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from planagent.config import reset_settings_cache
from planagent.db import reset_database_cache
from planagent.main import create_app
from planagent.services.completeness import (
    BoundaryClass,
    CompletenessCase,
    FindingKind,
    FindingSeverity,
    run_completeness_check,
)
from planagent.services.redteam.completeness import run_completeness_checks
from planagent.services.variables.formulas import evaluate_tick_drivers
from planagent.services.variables.models import FormulaDefinition, VariableSet
from planagent.services.variables.presets import builtin_template
from planagent.services.variables.validator import merge_variable_sets
from planagent.simulation.domain_packs.automotive.template_spec import (
    TEMPLATE_FORMULAS,
    TEMPLATE_VARIABLES,
)
from tests.redteam_cases import complete_case_snapshot, desay_2020_snapshot

# --- Case-level chain formulas (the Desay attachment, shared with the
# C1 harness under research/strategy-engine/audit-fixes-2026-11-20/).
# The logistic replaces the template's drift driver per-output at
# merge; the revenue driver gains exactly one ADAS term; the share
# driver gains exactly one ADAS term with its own coupling.
# ---------------------------------------------------------------------


def adas_logistic_driver() -> dict:
    return {
        "output": "adas_penetration",
        "expression": {
            "op": "logistic",
            "args": [
                {
                    "op": "multiply",
                    "args": [
                        {"ref": "adas_rate"},
                        {"op": "subtract", "args": [{"ref": "tick"}, {"ref": "adas_midpoint"}]},
                    ],
                },
                {"ref": "adas_ceiling"},
            ],
        },
        "description": "L2 penetration S-curve (gap audit C1); reuses the pack state field.",
        "tick_driver": True,
    }


def _logistic(x: float, ceiling: float) -> float:
    return ceiling / (1.0 + math.exp(-x))


# --- Template shape -----------------------------------------------------


def test_adas_chain_variables_match_spec() -> None:
    by_id = {raw["id"]: raw for raw in TEMPLATE_VARIABLES}
    assert len(TEMPLATE_VARIABLES) == 67
    assert len(TEMPLATE_FORMULAS) == 37
    assert len([f for f in TEMPLATE_FORMULAS if f.get("tick_driver")]) == 34
    expected = {
        "adas_ceiling": (0.50, 0.65, 0.80),
        "adas_rate": (0.50, 0.70, 1.00),
        "adas_midpoint": (2.0, 3.0, 4.0),
        "adas_coupling": (0.10, 0.25, 0.40),
    }
    for var_id, (lo, mode, hi) in expected.items():
        raw = by_id[var_id]
        dist = raw["distribution"]
        assert dist["type"] == "triangular", var_id
        assert (dist["min"], dist["mode"], dist["max"]) == (lo, mode, hi), var_id
        assert raw["unit"], var_id
        assert raw["evidence_ref"], var_id
        assert "LABELED ASSUMPTION" in raw["evidence_ref"], var_id
    # The penetration is the pack state field (fixed 2025-caliber
    # value 0.649, MIIT combined-assist fitment) and the drift is an
    # endpoint average, not a fitted trend — both say so.
    pen = by_id["adas_penetration"]
    assert pen["distribution"] == {"type": "fixed", "value": 0.649}
    assert "2026-10" in pen["evidence_ref"]  # source publication, not decision time
    drift = by_id["adas_penetration_monthly_drift"]
    assert drift["distribution"] == {"type": "fixed", "value": 0.0081}
    assert "NOT a fitted trend" in drift["evidence_ref"]
    template = builtin_template("automotive")
    assert len(template.variables) == 67
    assert len(template.formulas) == 37


def test_adas_chain_planning_path_values() -> None:
    """At 2020 mode values the logistic gives 0.1286 / 0.2157 /
    0.325 / 0.4343 / 0.5214 at ticks 1..5 — tick 1 sits ON the 12%
    anchor (0.1286 vs 0.12), it does not drop below it the way the
    NEV chain's tick 1 (0.044) drops below its 0.054 start."""
    formula = FormulaDefinition.model_validate(adas_logistic_driver())
    scope = {"adas_ceiling": 0.65, "adas_rate": 0.70, "adas_midpoint": 3.0}
    got = [
        evaluate_tick_drivers([formula], scope, {}, tick)["adas_penetration"]
        for tick in (1, 2, 3, 4, 5)
    ]
    assert got == [0.1286, 0.2157, 0.325, 0.4343, 0.5214]
    assert abs(got[0] - 0.12) <= 0.01
    # 2015 outlook (midpoint 5.0): the grade curve starts near zero
    # and passes K/2 at tick 5.
    scope_2015 = {"adas_ceiling": 0.65, "adas_rate": 0.70, "adas_midpoint": 5.0}
    got_2015 = [
        evaluate_tick_drivers([formula], scope_2015, {}, tick)["adas_penetration"]
        for tick in (1, 2, 3, 4, 5)
    ]
    assert got_2015 == [0.0373, 0.0709, 0.1286, 0.2157, 0.325]


def test_adas_chain_merge_replaces_drift_driver() -> None:
    """Merging a case set carrying the logistic replaces the template's
    drift driver per-output: exactly one adas_penetration formula, the
    logistic — no duplicate penetration variable."""
    template = builtin_template("automotive")
    base = VariableSet(
        name=template.name,
        variables=list(template.variables),
        formulas=list(template.formulas),
        internal=dict(template.internal),
        assumption_data=dict(template.assumption_data),
    )
    case = VariableSet(
        name="case",
        variables=[],
        formulas=[FormulaDefinition.model_validate(adas_logistic_driver())],
    )
    merged = merge_variable_sets(base, case)
    by_output = [f for f in merged.formulas if f.output == "adas_penetration"]
    assert len(by_output) == 1
    assert by_output[0].tick_driver is True
    refs: set[str] = set()

    def _collect(node: object) -> None:
        if isinstance(node, dict):
            if set(node) == {"ref"}:
                refs.add(str(node["ref"]))
            for value in node.values():
                _collect(value)
        elif isinstance(node, list):
            for value in node:
                _collect(value)

    _collect(by_output[0].expression)
    assert refs == {"adas_rate", "adas_midpoint", "adas_ceiling", "tick"}
    # The template without a case keeps the drift driver.
    drift = [f for f in template.formulas if f.output == "adas_penetration"]
    assert len(drift) == 1
    assert drift[0].tick_driver is True


# --- Division of labor: the completeness + red-team checks ------------


def test_desay_2020_case_flags_adas_as_fixable_defect() -> None:
    """The old desay-2020 case (12 generic corporate variables, no
    ADAS variable) must flag the ADAS chain: missing_driver, medium,
    fixable defect — the audit's C1 verdict, not a prediction limit."""
    case = CompletenessCase(
        domain_id="automotive",
        variable_ids=[
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
            "profit_growth",
            "profit_coupling",
        ],
        key_variables=["market_share", "revenue", "profit"],
    )
    report = run_completeness_check(case)
    by_id = {f.id: f for f in report.findings}
    adas = by_id["completeness:adas_penetration"]
    assert adas.kind is FindingKind.MISSING_DRIVER
    assert adas.severity is FindingSeverity.MEDIUM
    assert adas.target == "revenue"
    assert adas.boundary_class is BoundaryClass.FIXABLE_DEFECT
    assert "§6" in adas.boundary_basis
    assert "2020-12-31" in adas.boundary_basis


def test_adas_present_and_linked_passes_completeness() -> None:
    """A case carrying the ADAS variables AND a driver outputting
    adas_penetration (the logistic) passes the ADAS entry — the
    check sees the chain, not just the ids."""
    case = CompletenessCase(
        domain_id="automotive",
        variable_ids=["adas_penetration", "adas_coupling", "revenue", "market_share"],
        driver_outputs=["adas_penetration"],
        key_variables=["revenue", "market_share"],
    )
    report = run_completeness_check(case)
    assert "completeness:adas_penetration" not in {f.id for f in report.findings}
    assert "completeness:adas_penetration:link" not in {f.id for f in report.findings}


def test_redteam_flags_adas_on_desay_2020_not_on_complete_case() -> None:
    """The deterministic red-team check is the audit's original
    evidence: desay-2020 names L2/智能驾驶 in its situation but has
    no ADAS variable, so it flags; the complete case (adas variable
    + share formula) does not."""
    desay_findings = run_completeness_checks(desay_2020_snapshot())
    assert "rt-missing_driver-adas_penetration" in {f.id for f in desay_findings}
    complete_findings = run_completeness_checks(complete_case_snapshot())
    assert "rt-missing_driver-adas_penetration" not in {f.id for f in complete_findings}


# --- API end-to-end ------------------------------------------------------


def build_database_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def setup_app(monkeypatch, tmp_path: Path, db_name: str = "planagent-adas-chain.db") -> None:
    monkeypatch.setenv("PLANAGENT_DATABASE_URL", build_database_url(tmp_path / db_name))
    monkeypatch.setenv("PLANAGENT_EVENT_BUS_BACKEND", "memory")
    monkeypatch.setenv("PLANAGENT_INLINE_INGEST_DEFAULT", "true")
    monkeypatch.setenv("PLANAGENT_INLINE_SIMULATION_DEFAULT", "true")
    monkeypatch.setenv("PLANAGENT_OPENAI_API_KEY", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_BASE_URL", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_PRIMARY_API_KEY", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_PRIMARY_BASE_URL", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_EXTRACTION_API_KEY", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_EXTRACTION_BASE_URL", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_REPORT_API_KEY", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_REPORT_BASE_URL", "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    reset_settings_cache()
    reset_database_cache()


def _fixed(variable_id: str, value: float) -> dict:
    return {
        "id": variable_id,
        "unit": "test",
        "distribution": {"type": "fixed", "value": value},
        "evidence_ref": "test: fixed for determinism",
    }


def _adoption_driver() -> dict:
    return {
        "output": "disruptor_adoption",
        "expression": {
            "op": "logistic",
            "args": [
                {
                    "op": "multiply",
                    "args": [
                        {"ref": "disruptor_rate"},
                        {
                            "op": "subtract",
                            "args": [{"ref": "tick"}, {"ref": "disruptor_midpoint"}],
                        },
                    ],
                },
                {"ref": "disruptor_ceiling"},
            ],
        },
        "description": "Smart-cockpit/ADAS adoption S-curve (test).",
        "tick_driver": True,
    }


def _share_driver_with_adas_term() -> dict:
    """Share grows at base_growth plus share_coupling * adoption plus
    adas_share_coupling * adas_penetration — exactly one ADAS term,
    capped at 0.85 like the harness."""
    return {
        "output": "market_share",
        "expression": {
            "op": "min",
            "args": [
                {
                    "op": "max",
                    "args": [
                        0,
                        {
                            "op": "multiply",
                            "args": [
                                {"ref": "market_share"},
                                {
                                    "op": "add",
                                    "args": [
                                        1,
                                        {
                                            "op": "add",
                                            "args": [
                                                {"ref": "base_growth"},
                                                {
                                                    "op": "add",
                                                    "args": [
                                                        {
                                                            "op": "multiply",
                                                            "args": [
                                                                {"ref": "share_coupling"},
                                                                {"ref": "disruptor_adoption"},
                                                            ],
                                                        },
                                                        {
                                                            "op": "multiply",
                                                            "args": [
                                                                {"ref": "adas_share_coupling"},
                                                                {"ref": "adas_penetration"},
                                                            ],
                                                        },
                                                    ],
                                                },
                                            ],
                                        },
                                    ],
                                },
                            ],
                        },
                    ],
                },
                0.85,
            ],
        },
        "description": "Share with the ADAS grade term (TRACK-C1).",
        "tick_driver": True,
    }


def _revenue_driver_with_adas_term() -> dict:
    """Revenue grows at revenue_growth plus revenue_coupling *
    adoption plus adas_coupling * adas_penetration — exactly one ADAS
    term, nothing else changed."""
    return {
        "output": "revenue",
        "expression": {
            "op": "max",
            "args": [
                0,
                {
                    "op": "multiply",
                    "args": [
                        {"ref": "revenue"},
                        {
                            "op": "add",
                            "args": [
                                1,
                                {
                                    "op": "add",
                                    "args": [
                                        {"ref": "revenue_growth"},
                                        {
                                            "op": "add",
                                            "args": [
                                                {
                                                    "op": "multiply",
                                                    "args": [
                                                        {"ref": "revenue_coupling"},
                                                        {"ref": "disruptor_adoption"},
                                                    ],
                                                },
                                                {
                                                    "op": "multiply",
                                                    "args": [
                                                        {"ref": "adas_coupling"},
                                                        {"ref": "adas_penetration"},
                                                    ],
                                                },
                                            ],
                                        },
                                    ],
                                },
                            ],
                        },
                    ],
                },
            ],
        },
        "description": "Revenue with the ADAS-chain term (TRACK-C1).",
        "tick_driver": True,
    }


def _growth_driver(field: str, growth: str, coupling: str, cap: bool) -> dict:
    inner = {
        "op": "multiply",
        "args": [
            {"ref": field},
            {
                "op": "add",
                "args": [
                    1,
                    {
                        "op": "add",
                        "args": [
                            {"ref": growth},
                            {
                                "op": "multiply",
                                "args": [{"ref": coupling}, {"ref": "disruptor_adoption"}],
                            },
                        ],
                    },
                ],
            },
        ],
    }
    floored = {"op": "max", "args": [0, inner]}
    expr = {"op": "min", "args": [floored, 0.85]} if cap else floored
    return {
        "output": field,
        "expression": expr,
        "description": f"{field} growth driver (test).",
        "tick_driver": True,
    }


def _chain_case_set(
    adas_coupling: float, adas_share_coupling: float, disruptor_ceiling: float = 0.85
) -> dict:
    variables = [
        _fixed("market_share", 0.066),
        _fixed("base_growth", 0.03),
        _fixed("disruptor_ceiling", disruptor_ceiling),
        _fixed("disruptor_rate", 1.0),
        _fixed("disruptor_midpoint", 3.0),
        _fixed("share_coupling", 0.25),
        _fixed("revenue", 6799.06),
        _fixed("revenue_growth", 0.15),
        _fixed("revenue_coupling", 0.25),
        _fixed("profit", 518.15),
        _fixed("profit_growth", 0.12),
        _fixed("profit_coupling", 0.15),
        _fixed("adas_penetration", 0.12),
        _fixed("adas_coupling", adas_coupling),
        _fixed("adas_share_coupling", adas_share_coupling),
        # Chain path pinned at the 2020 mode values (planning path);
        # without these the logistic would read the template's
        # sampled triangulars and the trajectory would not be the plan.
        _fixed("adas_ceiling", 0.65),
        _fixed("adas_rate", 0.70),
        _fixed("adas_midpoint", 3.0),
        # Neutralized inventory channel: the yearly test case carries no
        # monthly inventory dynamics (see the Track 7 report).
        _fixed("production_volume", 2531.1),
        _fixed("sales_volume_retail", 1740.4),
        _fixed("sales_volume_wholesale", 1740.4),
        _fixed("dealer_inventory_coef", 1.2),
    ]
    formulas = [
        _adoption_driver(),
        adas_logistic_driver(),
        _share_driver_with_adas_term(),
        _revenue_driver_with_adas_term(),
        _growth_driver("profit", "profit_growth", "profit_coupling", cap=False),
    ]
    return {"name": "adas-chain-test-case", "variables": variables, "formulas": formulas}


def _create_chain_run(
    client: TestClient,
    adas_coupling: float,
    adas_share_coupling: float = 0.10,
    disruptor_ceiling: float = 0.85,
) -> dict:
    payload = {
        "company_id": "adas-chain-test",
        "company_name": "ADAS Chain Test",
        "market": "auto-electronics-china",
        "domain_id": "automotive",
        "actor_template": "tier1_supplier",
        "tick_count": 5,
        "seed": 7,
        "decision_time": "2020-12-31T00:00:00Z",
        "variable_template_id": "builtin:automotive",
        "variable_set": _chain_case_set(adas_coupling, adas_share_coupling, disruptor_ceiling),
    }
    created = client.post("/simulation/runs", json=payload)
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "COMPLETED"
    return created.json()


def _trajectory(client: TestClient, run_id: str) -> dict[int, dict]:
    response = client.get(f"/runs/{run_id}/replay-package")
    assert response.status_code == 200, response.text
    pkg = response.json()["package"]
    if isinstance(pkg, str):
        import json

        pkg = json.loads(pkg)
    return {s["tick"]: s["state"] for s in pkg["snapshots"]}


def test_adas_chain_end_to_end_terms(monkeypatch, tmp_path: Path) -> None:
    """The full chain on the engine: the logistic L2 path drives the
    revenue term AND the share term; per-tick growth factors equal
    1 + growth + coupling*adoption + adas_coupling*penetration
    exactly (frozen values). Profit is untouched by the chain."""
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_chain_run(client, adas_coupling=0.10, adas_share_coupling=0.10)
        states = _trajectory(client, run["id"])
        assert sorted(states) == [0, 1, 2, 3, 4, 5]
        assert [states[t]["adas_penetration"] for t in (1, 2, 3, 4, 5)] == [
            0.1286,
            0.2157,
            0.325,
            0.4343,
            0.5214,
        ]
        revenue = {t: states[t]["revenue"] for t in states}
        share = {t: states[t]["market_share"] for t in states}
        profit = {t: states[t]["profit"] for t in states}
        assert revenue[0] == 6799.06
        assert share[0] == 0.066
        for tick in (1, 2, 3, 4, 5):
            adoption = _logistic(1.0 * (tick - 3.0), 0.85)
            pen = _logistic(0.70 * (tick - 3.0), 0.65)
            assert revenue[tick] / revenue[tick - 1] == pytest.approx(
                1 + 0.15 + 0.25 * adoption + 0.10 * pen, rel=2e-3
            ), tick
            assert share[tick] / share[tick - 1] == pytest.approx(
                1 + 0.03 + 0.25 * adoption + 0.10 * pen, rel=2e-3
            ), tick
            assert profit[tick] / profit[tick - 1] == pytest.approx(
                1 + 0.12 + 0.15 * adoption, rel=2e-3
            ), tick


def test_adas_chain_frozen_baseline_k_zero_is_no_chain(monkeypatch, tmp_path: Path) -> None:
    """Frozen-baseline control (diagnostic Appendix A): every variable
    fixed, only the ADAS couplings change. k=0 must reproduce the
    pure-adoption revenue AND share exactly, with the adoption
    trajectory bit-identical — the separability proof: the ADAS terms
    add nothing when zeroed and disturb nothing else."""
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        states_on = _trajectory(
            client, _create_chain_run(client, 0.10, 0.10)["id"]
        )
        states_off = _trajectory(
            client, _create_chain_run(client, 0.0, 0.0)["id"]
        )
        for tick in (1, 2, 3, 4, 5):
            # k=0: revenue and share are the pure disruptor-coupled path.
            # (disruptor_adoption is a within-tick intermediate, not a
            # snapshot state field, so the adoption path is proven by
            # the exact revenue/share factor match below, not by a
            # state read.)
            assert states_on[tick]["revenue"] > states_off[tick]["revenue"], tick
            assert states_on[tick]["market_share"] > states_off[tick]["market_share"], tick
            assert states_on[tick]["profit"] == pytest.approx(
                states_off[tick]["profit"], rel=1e-6
            ), tick
        expected_rev = 6799.06
        expected_share = 0.066
        for tick in (1, 2, 3, 4, 5):
            adoption = _logistic(1.0 * (tick - 3.0), 0.85)
            expected_rev = round(expected_rev * (1 + 0.15 + 0.25 * adoption), 4)
            expected_share = round(expected_share * (1 + 0.03 + 0.25 * adoption), 4)
            assert states_off[tick]["revenue"] == pytest.approx(expected_rev, rel=2e-3), tick
            assert states_off[tick]["market_share"] == pytest.approx(
                expected_share, rel=2e-3
            ), tick


def test_adas_chain_grade_without_breadth(monkeypatch, tmp_path: Path) -> None:
    """Division of labor, second leg: with breadth forced to zero
    (disruptor_ceiling 0.0, so adoption is 0 at every tick), the grade
    channel still carries revenue and share on its own — the L2 term
    is not a re-labeling of the adoption term."""
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_chain_run(
            client, 0.10, 0.10, disruptor_ceiling=0.0
        )
        states = _trajectory(client, run["id"])
        revenue = {t: states[t]["revenue"] for t in states}
        share = {t: states[t]["market_share"] for t in states}
        for tick in (1, 2, 3, 4, 5):
            # Adoption is zero by construction (ceiling 0.0): the
            # factors below match the ADAS-only formula exactly, which
            # is only possible if the adoption term contributed zero.
            pen = _logistic(0.70 * (tick - 3.0), 0.65)
            assert revenue[tick] / revenue[tick - 1] == pytest.approx(
                1 + 0.15 + 0.10 * pen, rel=2e-3
            ), tick
            assert share[tick] / share[tick - 1] == pytest.approx(
                1 + 0.03 + 0.10 * pen, rel=2e-3
            ), tick

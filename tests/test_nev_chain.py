"""Track 7 — NEV transmission chain tests (diagnostic build spec).

The chain is the diagnostic's exact spec
(``desay-backtest-2026-11-19/diagnostic-2020/new-parameter.md`` §2,
DIAGNOSTIC-2020.md §5.2): four triangular variables (``nev_ceiling`` /
``nev_rate`` / ``nev_midpoint`` / ``nev_coupling``) + the pack's
``nev_penetration`` STATE field reused as the penetration (no duplicate
intermediate) + a case-level logistic tick driver that replaces the
template's drift driver per-output at merge time + a revenue tick
driver that gains exactly one additive term
(``+ nev_coupling * nev_penetration``). No interaction term; share and
profit formulas are untouched; no domain-controller substitution
mechanism (diagnostic §5.1c: real but secondary).

Tests are deterministic (fixed distributions) except where the
distribution itself is asserted. API tests use the isolated-SQLite +
in-memory-bus pattern from the Phase 2 automotive API tests.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from planagent.config import reset_settings_cache
from planagent.db import reset_database_cache
from planagent.main import create_app
from planagent.services.distributions import sample_variable_set
from planagent.services.variables.formulas import (
    evaluate_formulas,
    evaluate_tick_drivers,
)
from planagent.services.variables.models import (
    FormulaDefinition,
    VariableDefinition,
    VariableSet,
)
from planagent.services.variables.presets import builtin_template
from planagent.services.variables.validator import merge_variable_sets
from planagent.simulation.domain_packs import registry as domain_pack_registry
from planagent.simulation.domain_packs.automotive.template_spec import (
    TEMPLATE_FORMULAS,
    TEMPLATE_VARIABLES,
)

# --- Case-level chain formulas (the Desay attachment, shared with the
# harness under research/strategy-engine/desay-backtest-2026-11-19/
# autopack-rerun/). The logistic replaces the template's drift driver
# per-output at merge; the revenue driver gains exactly one term.
# ---------------------------------------------------------------------


def nev_logistic_driver() -> dict:
    return {
        "output": "nev_penetration",
        "expression": {
            "op": "logistic",
            "args": [
                {
                    "op": "multiply",
                    "args": [
                        {"ref": "nev_rate"},
                        {"op": "subtract", "args": [{"ref": "tick"}, {"ref": "nev_midpoint"}]},
                    ],
                },
                {"ref": "nev_ceiling"},
            ],
        },
        "description": "NEV penetration S-curve (diagnostic §5.2); reuses the pack state field.",
        "tick_driver": True,
    }


def _logistic(x: float, ceiling: float) -> float:
    return ceiling / (1.0 + math.exp(-x))


# --- Template shape -----------------------------------------------------


def test_nev_chain_variables_match_diagnostic_spec() -> None:
    by_id = {raw["id"]: raw for raw in TEMPLATE_VARIABLES}
    # R&D margin promotion (2026-11-20): the B-pack +4 margin
    # variables are REPLACED by +8 R&D variables (gross_base,
    # gross_longrun, gross_reversion, rd_base, rd_longrun,
    # rd_reversion, rd_adoption, other_share) and the +4 formulas by
    # +6 (disruptor_adoption default, revenue passthrough anchor,
    # gross_margin, rd_intensity, net_margin, profit) — the
    # passthrough is the extra formula beyond the original +3 spec:
    # see the template docstring's merge-order note. Tick drivers
    # 33 -> 39 (all six chain drivers are drivers).
    assert len(TEMPLATE_VARIABLES) == 69
    assert len(TEMPLATE_FORMULAS) == 42
    assert len([f for f in TEMPLATE_FORMULAS if f.get("tick_driver")]) == 39
    expected = {
        "nev_ceiling": (0.30, 0.40, 0.60),
        "nev_rate": (0.50, 0.70, 1.00),
        "nev_midpoint": (3.0, 4.0, 5.0),
        "nev_coupling": (0.10, 0.25, 0.40),
    }
    for var_id, (lo, mode, hi) in expected.items():
        raw = by_id[var_id]
        dist = raw["distribution"]
        assert dist["type"] == "triangular", var_id
        assert (dist["min"], dist["mode"], dist["max"]) == (lo, mode, hi), var_id
        assert raw["unit"], var_id
        assert raw["evidence_ref"], var_id
    template = builtin_template("automotive")
    # R&D margin promotion (2026-11-20): 61 -> 69 variables, 36 -> 42
    # formulas (see the count comment above).
    assert len(template.variables) == 69
    assert len(template.formulas) == 42


def test_nev_chain_planning_path_values() -> None:
    """At mode values the logistic gives 0.044/0.079/0.133/0.200 at
    ticks 1..4 — tick 4 is exactly the 2025 20% plan target."""
    formula = FormulaDefinition.model_validate(nev_logistic_driver())
    scope = {"nev_ceiling": 0.40, "nev_rate": 0.70, "nev_midpoint": 4.0}
    got = [
        evaluate_tick_drivers([formula], scope, {}, tick)["nev_penetration"]
        for tick in (1, 2, 3, 4, 5)
    ]
    assert got == [0.0436, 0.0791, 0.1327, 0.2, 0.2673]
    # The realized path (0.50/0.90/2.0) tracks actual 2021-2024
    # penetration (13.4/25.6/31.6/40.9%) to within 4pp. NOTE: the
    # diagnostic claims "within 2pp" (new-parameter.md §3), but the
    # tick-3 value is 0.3555 vs the actual 0.316 — a 3.95pp gap — so
    # the honest bound is 4pp, not 2pp. Corrected here and in the
    # Track 7 report's reconciliation section.
    realized = {"nev_ceiling": 0.50, "nev_rate": 0.90, "nev_midpoint": 2.0}
    got_realized = [
        evaluate_tick_drivers([formula], realized, {}, tick)["nev_penetration"]
        for tick in (1, 2, 3, 4)
    ]
    for got_v, actual in zip(got_realized, (0.134, 0.256, 0.316, 0.409)):
        assert abs(got_v - actual) <= 0.04


def test_nev_chain_merge_replaces_drift_driver() -> None:
    """Merging a case set carrying the logistic replaces the template's
    drift driver per-output: exactly one nev_penetration formula, the
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
        formulas=[FormulaDefinition.model_validate(nev_logistic_driver())],
    )
    merged = merge_variable_sets(base, case)
    by_output = [f for f in merged.formulas if f.output == "nev_penetration"]
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
    assert refs == {"nev_rate", "nev_midpoint", "nev_ceiling", "tick"}
    # The template without a case keeps the drift driver.
    drift = [f for f in template.formulas if f.output == "nev_penetration"]
    assert len(drift) == 1
    assert drift[0].tick_driver is True


def test_rd_decomposition_drivers_are_linear_and_clamped() -> None:
    """R&D margin promotion: the decomposition's legs are LINEAR
    (each tick closes 25% of the ORIGINAL gap — tick 4 closes 75%,
    leaving 25%), net_margin is the identity gross - rd - other
    clamped to [0.02, 0.25], and profit is same-tick revenue x
    net_margin. This supersedes the B-pack linear/clamp test (the
    single-regression net margin is gone) and pins the M1 correction
    (TRACK-B §2's "(0.75)^3 ≈ 42%" was a documentation error) at the
    formula level, per leg.
    """
    template = builtin_template("automotive")
    by_output = {f.output: f for f in template.formulas}
    for output in (
        "disruptor_adoption",
        "revenue",
        "gross_margin",
        "rd_intensity",
        "net_margin",
        "profit",
    ):
        assert output in by_output, output
        assert by_output[output].tick_driver is True, output
    # The adoption default is the bare number 0.0.
    assert by_output["disruptor_adoption"].expression == 0.0
    # The revenue driver is the identity passthrough (self-reference).
    assert by_output["revenue"].expression == {"ref": "revenue"}
    drivers = [
        by_output[o]
        for o in (
            "disruptor_adoption",
            "revenue",
            "gross_margin",
            "rd_intensity",
            "net_margin",
            "profit",
        )
    ]
    # Gross 0.30 -> 0.22, rd 0.05 -> 0.09, other fixed 0.05, zero
    # adoption (the template default): linear legs
    # gross 0.30 / 0.28 / 0.26 / 0.24 / 0.22 and
    # rd 0.05 / 0.06 / 0.07 / 0.08 / 0.09, so net is
    # 0.20 / 0.17 / 0.14 / 0.11 / 0.08 (tick 5 closes 100%).
    scope = {
        "gross_base": 0.30,
        "gross_longrun": 0.22,
        "gross_reversion": 0.25,
        "rd_base": 0.05,
        "rd_longrun": 0.09,
        "rd_reversion": 0.25,
        "rd_adoption": 0.01,
        "other_share": 0.05,
    }
    state = {"revenue": 1000.0}
    expected_gross = [0.30, 0.28, 0.26, 0.24, 0.22]
    expected_rd = [0.05, 0.06, 0.07, 0.08, 0.09]
    expected_net = [0.20, 0.17, 0.14, 0.11, 0.08]
    for tick, (g, r, n) in enumerate(
        zip(expected_gross, expected_rd, expected_net), start=1
    ):
        out = evaluate_tick_drivers(drivers, scope, state, tick)
        assert out["disruptor_adoption"] == 0.0
        assert out["gross_margin"] == pytest.approx(g), tick
        assert out["rd_intensity"] == pytest.approx(r), tick
        # t=1 identity: net = gross - rd - other, before the clamp.
        assert out["net_margin"] == pytest.approx(n), tick
        assert out["profit"] == pytest.approx(round(1000.0 * n, 4)), tick
        assert out["revenue"] == 1000.0
    # Adoption term: with adoption fixed at 0.5 the R&D leg rises by
    # 0.01 x 0.5 = 0.005 at every tick, so the net margin FALLS by
    # 0.005 (the coupling moved from the net margin to the R&D leg).
    adoption_driver = FormulaDefinition.model_validate(
        {
            "output": "disruptor_adoption",
            "tick_driver": True,
            "expression": 0.5,
            "description": "test: fixed adoption",
        }
    )
    drivers_with_adoption = [adoption_driver, *drivers[1:]]
    out = evaluate_tick_drivers(drivers_with_adoption, scope, state, 2)
    assert out["rd_intensity"] == pytest.approx(0.065)
    assert out["net_margin"] == pytest.approx(0.165)
    # Clamp rails: a net above the rail and a net below it.
    for gross, rd, other, expected in (
        (0.30, 0.005, 0.005, 0.25),  # 0.29 -> 0.25
        (0.05, 0.05, 0.05, 0.02),  # -0.05 -> 0.02
    ):
        out = evaluate_tick_drivers(
            drivers,
            {
                **scope,
                "gross_base": gross,
                "gross_longrun": gross,
                "rd_base": rd,
                "rd_longrun": rd,
                "other_share": other,
                "rd_adoption": 0.0,
            },
            state,
            1,
        )
        assert out["net_margin"] == pytest.approx(expected), (gross, rd, other)


def test_rd_decomposition_t1_identity_matches_case_modes() -> None:
    """R&D margin promotion: at tick 1 each leg sits at its base, so
    the net margin is exactly base gross - base rd - other_share.
    This pins the Desay case wiring modes (EVIDENCE.md §2.2): 2015
    0.2696 - 0.076 - 0.0958 = 0.0978 and 2020
    0.2339 - 0.1202 - 0.0375 = 0.0762 — the same values the B-pack
    margin_base modes carried, now decomposed.
    """
    template = builtin_template("automotive")
    by_output = {f.output: f for f in template.formulas}
    drivers = [
        by_output[o]
        for o in (
            "disruptor_adoption",
            "revenue",
            "gross_margin",
            "rd_intensity",
            "net_margin",
            "profit",
        )
    ]
    state = {"revenue": 1000.0}
    for gross, rd, other, expected_net in (
        (0.2696, 0.076, 0.0958, 0.0978),
        (0.2339, 0.1202, 0.0375, 0.0762),
    ):
        out = evaluate_tick_drivers(
            drivers,
            {
                "gross_base": gross,
                "gross_longrun": gross,
                "gross_reversion": 0.25,
                "rd_base": rd,
                "rd_longrun": rd,
                "rd_reversion": 0.25,
                "rd_adoption": 0.0,
                "other_share": other,
            },
            state,
            1,
        )
        assert out["gross_margin"] == pytest.approx(gross)
        assert out["rd_intensity"] == pytest.approx(rd)
        assert out["net_margin"] == pytest.approx(expected_net), (gross, rd, other)
        assert out["profit"] == pytest.approx(round(1000.0 * expected_net, 4))


def test_profit_chain_merge_order_profit_reads_same_tick_revenue() -> None:
    """Profit-chain pack: a case revenue driver replaces the template's
    revenue passthrough IN PLACE, so it evaluates BEFORE net_margin /
    profit and profit reads SAME-TICK revenue — the Track B semantics.
    Without the passthrough anchor, the template profit driver would
    sit before the appended case revenue driver and read pre-tick
    revenue (one-tick lag). This test pins the merge order that
    prevents the lag.
    """
    template = builtin_template("automotive")
    base = VariableSet(
        name=template.name,
        variables=list(template.variables),
        formulas=list(template.formulas),
        internal=dict(template.internal),
        assumption_data=dict(template.assumption_data),
    )
    case_revenue = {
        "output": "revenue",
        "tick_driver": True,
        "description": "case revenue grows 10% per tick",
        "expression": {
            "op": "multiply",
            "args": [{"ref": "revenue"}, 1.10],
        },
    }
    case = VariableSet(
        name="case",
        variables=[
            VariableDefinition.model_validate(
                {
                    "id": "gross_base",
                    "unit": "rate",
                    "distribution": {"type": "fixed", "value": 0.20},
                    "evidence_ref": "test",
                }
            ),
            VariableDefinition.model_validate(
                {
                    "id": "gross_longrun",
                    "unit": "rate",
                    "distribution": {"type": "fixed", "value": 0.20},
                    "evidence_ref": "test",
                }
            ),
            VariableDefinition.model_validate(
                {
                    "id": "rd_base",
                    "unit": "rate",
                    "distribution": {"type": "fixed", "value": 0.05},
                    "evidence_ref": "test",
                }
            ),
            VariableDefinition.model_validate(
                {
                    "id": "rd_longrun",
                    "unit": "rate",
                    "distribution": {"type": "fixed", "value": 0.05},
                    "evidence_ref": "test",
                }
            ),
            VariableDefinition.model_validate(
                {
                    "id": "other_share",
                    "unit": "rate",
                    "distribution": {"type": "fixed", "value": 0.05},
                    "evidence_ref": "test",
                }
            ),
        ],
        formulas=[FormulaDefinition.model_validate(case_revenue)],
    )
    merged = merge_variable_sets(base, case)
    outputs = [f.output for f in merged.formulas if f.tick_driver]
    # The case revenue driver sits at the passthrough's template
    # position — before the decomposition legs, net_margin and
    # profit — not appended at the end.
    assert outputs.index("revenue") < outputs.index("gross_margin")
    assert outputs.index("gross_margin") < outputs.index("rd_intensity")
    assert outputs.index("rd_intensity") < outputs.index("net_margin")
    assert outputs.index("net_margin") < outputs.index("profit")
    assert len([o for o in outputs if o == "revenue"]) == 1
    drivers = [f for f in merged.formulas if f.tick_driver]
    # Full scope + state: the merged driver list is the whole template
    # graph, so every other driver needs its variables/fields present
    # (sampled template values + INITIAL derived values + pack state
    # defaults, decomposition legs pinned to net 0.10). The initial
    # formulas (demand growth rate, tax level factor, pull-forward
    # stock) are part of the tick-driver scope in the engine
    # (variable_scope = sampled + derived), so they belong here too.
    sampled = sample_variable_set(
        VariableSet(variables=list(template.variables)), random.Random(7)
    )
    derived = evaluate_formulas(
        [f for f in template.formulas if not f.tick_driver], sampled
    )
    scope = {
        **sampled,
        **derived,
        "gross_base": 0.20,
        "gross_longrun": 0.20,
        "gross_reversion": 0.25,
        "rd_base": 0.05,
        "rd_longrun": 0.05,
        "rd_reversion": 0.25,
        "rd_adoption": 0.0,
        "other_share": 0.05,
    }
    pack = domain_pack_registry.get("automotive")
    state = {field.name: float(field.default) for field in pack.state_fields}
    state["revenue"] = 1000.0
    out1 = evaluate_tick_drivers(drivers, scope, state, 1)
    # Same-tick: revenue grows to 1100 first, profit is 1100 x 0.10 —
    # not 1000 x 0.10 (the one-tick-lag value).
    assert out1["revenue"] == pytest.approx(1100.0)
    assert out1["profit"] == pytest.approx(110.0)


# --- API end-to-end ------------------------------------------------------


def build_database_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def setup_app(monkeypatch, tmp_path: Path, db_name: str = "planagent-nev-chain.db") -> None:
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


def _revenue_driver_with_nev_term() -> dict:
    """The diagnostic's exact revenue formula: one additive NEV term,
    nothing else changed."""
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
                                                        {"ref": "nev_coupling"},
                                                        {"ref": "nev_penetration"},
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
        "description": "Revenue with the NEV-chain term (diagnostic §5.2).",
        "tick_driver": True,
    }


def _chain_case_set(nev_coupling: float) -> dict:
    variables = [
        _fixed("market_share", 0.066),
        _fixed("base_growth", 0.03),
        _fixed("disruptor_ceiling", 0.85),
        _fixed("disruptor_rate", 1.0),
        _fixed("disruptor_midpoint", 3.0),
        _fixed("share_coupling", 0.25),
        _fixed("revenue", 6799.06),
        _fixed("revenue_growth", 0.15),
        _fixed("revenue_coupling", 0.25),
        _fixed("profit", 518.15),
        _fixed("profit_growth", 0.12),
        _fixed("profit_coupling", 0.15),
        _fixed("nev_penetration", 0.054),
        _fixed("nev_coupling", nev_coupling),
        # Chain path pinned at the diagnostic's mode values (planning
        # path); without these the logistic would read the template's
        # sampled triangulars and the trajectory would not be the plan.
        _fixed("nev_ceiling", 0.40),
        _fixed("nev_rate", 0.70),
        _fixed("nev_midpoint", 4.0),
        # Neutralized inventory channel: the yearly test case carries no
        # monthly inventory dynamics (see the Track 7 report).
        _fixed("production_volume", 2531.1),
        _fixed("sales_volume_retail", 1740.4),
        _fixed("sales_volume_wholesale", 1740.4),
        _fixed("dealer_inventory_coef", 1.2),
    ]
    formulas = [
        _adoption_driver(),
        nev_logistic_driver(),
        _growth_driver("market_share", "base_growth", "share_coupling", cap=True),
        _revenue_driver_with_nev_term(),
        _growth_driver("profit", "profit_growth", "profit_coupling", cap=False),
    ]
    return {"name": "nev-chain-test-case", "variables": variables, "formulas": formulas}


def _create_chain_run(client: TestClient, nev_coupling: float) -> dict:
    payload = {
        "company_id": "nev-chain-test",
        "company_name": "NEV Chain Test",
        "market": "auto-electronics-china",
        "domain_id": "automotive",
        "actor_template": "tier1_supplier",
        "tick_count": 5,
        "seed": 7,
        "decision_time": "2020-12-31T00:00:00Z",
        "variable_template_id": "builtin:automotive",
        "variable_set": _chain_case_set(nev_coupling),
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


def test_nev_chain_end_to_end_revenue_term(monkeypatch, tmp_path: Path) -> None:
    """The full chain on the engine: the logistic penetration drives the
    dual-track splits AND the revenue term; per-tick revenue growth
    equals 1 + rg + rc*adoption + k*pen exactly (frozen values)."""
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_chain_run(client, nev_coupling=0.25)
        states = _trajectory(client, run["id"])
        assert sorted(states) == [0, 1, 2, 3, 4, 5]
        # Planning path, ticks 1..4 (tick 5: 0.2673).
        assert [states[t]["nev_penetration"] for t in (1, 2, 3, 4)] == [
            0.0436,
            0.0791,
            0.1327,
            0.2,
        ]
        assert states[5]["nev_penetration"] == 0.2673
        # Dual-track splits follow the chain penetration, not the drift.
        for tick in (1, 2, 3, 4, 5):
            state = states[tick]
            assert state["nev_production_volume"] == round(
                state["production_volume"] * state["nev_penetration"], 4
            ), tick
            assert state["ice_production_volume"] == round(
                state["production_volume"] * (1 - state["nev_penetration"]), 4
            ), tick
        # Revenue growth factors, tick by tick, from the diagnostic formula.
        revenue = {t: states[t]["revenue"] for t in states}
        assert revenue[0] == 6799.06
        for tick in (1, 2, 3, 4, 5):
            adoption = _logistic(1.0 * (tick - 3.0), 0.85)
            pen = _logistic(0.70 * (tick - 4.0), 0.40)
            expected_factor = 1 + 0.15 + 0.25 * adoption + 0.25 * pen
            assert revenue[tick] / revenue[tick - 1] == pytest.approx(expected_factor, rel=2e-3), (
                tick
            )


def test_nev_chain_frozen_baseline_k_zero_is_no_chain(monkeypatch, tmp_path: Path) -> None:
    """Frozen-baseline control (diagnostic Appendix A): every variable
    fixed, only nev_coupling changes. k=0 must reproduce the no-chain
    revenue exactly, and k=0.25 must sit above it by the NEV term."""
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        states_on = _trajectory(client, _create_chain_run(client, 0.25)["id"])
        states_off = _trajectory(client, _create_chain_run(client, 0.0)["id"])
        revenue_on = {t: states_on[t]["revenue"] for t in states_on}
        revenue_off = {t: states_off[t]["revenue"] for t in states_off}
        # k=0: revenue is the pure disruptor-coupled path.
        expected = 6799.06
        for tick in (1, 2, 3, 4, 5):
            adoption = _logistic(1.0 * (tick - 3.0), 0.85)
            expected = round(expected * (1 + 0.15 + 0.25 * adoption), 4)
            assert revenue_off[tick] == pytest.approx(expected, rel=2e-3), tick
        # k=0.25 lifts every tick and the year-5 readout; share and
        # profit are untouched by the chain (same in both runs).
        for tick in (1, 2, 3, 4, 5):
            assert revenue_on[tick] > revenue_off[tick], tick
            assert states_on[tick]["market_share"] == pytest.approx(
                states_off[tick]["market_share"], rel=1e-6
            ), tick
            assert states_on[tick]["profit"] == pytest.approx(
                states_off[tick]["profit"], rel=1e-6
            ), tick


def test_automotive_override_directions_accepted(monkeypatch, tmp_path: Path) -> None:
    """Track 7: variable-override directions (the directions workflow the
    Desay auto-pack backtest uses for its arms) accept a company-backed
    automotive anchor — the domain gates in the narratives service and
    the scenario-branch runner cover automotive alongside corporate.
    The child forks at tick 1 with nev_coupling pinned to 0.10 and its
    revenue must sit below the k=0.25 anchor's at every tick."""
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        anchor = _create_chain_run(client, 0.25)
        response = client.post(
            f"/runs/{anchor['id']}/directions/override",
            json={
                "directions": [
                    {
                        "name": "A skeptical NEV",
                        "overrides": {"nev_coupling": 0.10},
                        "arm": "baseline",
                        "mece_branches": [],
                        "resample_variables": True,
                        "fork_step": 1,
                    }
                ]
            },
        )
        assert response.status_code == 201, response.text
        outcome = response.json()["outcomes"][0]
        assert outcome["status"] == "stored", response.text
        child_id = outcome["child_run_id"]
        assert child_id
        anchor_states = _trajectory(client, anchor["id"])
        child_states = _trajectory(client, child_id)
        # Child tick t is the anchor's year t+1 (fork at tick 1, 4
        # transitions vs the anchor's 5 — the known derive-anchor
        # artifact). The lower coupling must show up as lower revenue
        # at every tick, and the chain logistic must be live in the
        # forked child (planning path at the child's own tick index).
        for tick in (1, 2, 3, 4):
            assert child_states[tick]["revenue"] < anchor_states[tick + 1]["revenue"], tick
            assert child_states[tick]["nev_penetration"] == pytest.approx(
                _logistic(0.70 * (tick - 4.0), 0.40),
                rel=2e-3,  # snapshots round state to 4dp
            ), tick

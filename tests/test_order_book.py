"""Track 11 — order-book (backlog) mechanism tests (Track 7 §7 spec).

The backlog term is the SHAPE term to the NEV chain's LEVEL term
(``diagnostic-2020/DIAGNOSTIC-2020.md`` §4, §5.3; Track 7 report §7):
model growth is non-decreasing per tick while the desay-2020 actuals
decelerate, so no monotone channel can express the front-loaded shape.
The mechanism adds one additive revenue term
(``+ backlog_conversion * order_backlog / revenue``) whose stock
decays as the order surge passes, so per-tick growth FALLS even while
penetration and adoption keep rising. The NEV chain stays a level
term; the two channels are separately decomposable (frozen-baseline
per channel — here, ``backlog_conversion = 0``).

Mechanics (case-attached, following the NEV-chain pattern — the
template carries the variables + state fields, generic runs keep them
dormant):

- Two initial formulas: ``order_intake = order_intake_rate * revenue``
  and ``order_backlog = order_intake_rate * revenue`` — the opening
  backlog stock is one year of intake, a LABELED ASSUMPTION (the order
  stock itself was never disclosed; the 2020 case's announced
  annualised orders ~70亿 ≈ one year of revenue is the flow anchor).
  The opening book/flow are bound as case VARIABLES, not initial
  formulas: merge is per-output, so an initial formula and a tick
  driver cannot share an output id (the driver replaces the formula —
  caught by test, see the level-shift guard's history). The opening
  values are ``order_intake_rate * mode revenue`` (2020: 1.0 ×
  6799.06), exactly like ``nev_penetration``'s opening level, which
  is likewise a bound variable.
- Three tick drivers, in list order: the revenue driver reads the
  PRE-tick backlog, then the intake driver decays the flow
  (``intake * (1 - order_decay)``), then the backlog driver updates
  the stock (``backlog + intake - conversion * backlog``, floored at
  0). The converted amount in a tick is exactly
  ``backlog_conversion * pre-tick backlog`` — the amount the revenue
  term adds.

On the spec's unit validation ("with ``order_decay`` = 0 and constant
intake, the backlog term must reduce to a constant level shift"): the
only reading under which the term is EXACTLY constant is constant
intake RATE — new orders proportional to revenue, so the backlog
grows at the revenue rate and ``backlog / revenue`` stays fixed. With
a constant ABSOLUTE flow the term humps then decays as revenue
outgrows the book (that decay is the shape mechanism itself, pinned
in the shape test below). The level-shift test below therefore uses
the proportional-intake driver with ``order_decay`` = 0 and the book
opened at its steady state; the docstring there states the reading.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from planagent.config import reset_settings_cache
from planagent.db import reset_database_cache
from planagent.main import create_app
from planagent.services.variables.presets import builtin_template
from planagent.simulation.domain_packs import registry as domain_pack_registry
from planagent.simulation.domain_packs.automotive.template_spec import (
    TEMPLATE_FORMULAS,
    TEMPLATE_VARIABLES,
)


def _logistic(x: float, ceiling: float) -> float:
    return ceiling / (1.0 + math.exp(-x))


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


def _nev_logistic_driver() -> dict:
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
        "description": "NEV penetration S-curve (diagnostic §5.2).",
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


def _revenue_driver_with_backlog() -> dict:
    """Full Desay revenue driver: base growth + adoption coupling +
    NEV-chain term + exactly one backlog term. No interaction term."""
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
                                                    "op": "add",
                                                    "args": [
                                                        {
                                                            "op": "multiply",
                                                            "args": [
                                                                {"ref": "nev_coupling"},
                                                                {"ref": "nev_penetration"},
                                                            ],
                                                        },
                                                        {
                                                            "op": "multiply",
                                                            "args": [
                                                                {"ref": "backlog_conversion"},
                                                                {
                                                                    "op": "divide",
                                                                    "args": [
                                                                        {"ref": "order_backlog"},
                                                                        {"ref": "revenue"},
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
                    ],
                },
            ],
        },
        "description": "Revenue with the NEV-chain term and the backlog term (Track 11).",
        "tick_driver": True,
    }


def _revenue_driver_backlog_only() -> dict:
    """Minimal revenue driver for the level-shift guard: base growth
    plus exactly one backlog term, no adoption / NEV terms."""
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
                                            "op": "multiply",
                                            "args": [
                                                {"ref": "backlog_conversion"},
                                                {
                                                    "op": "divide",
                                                    "args": [
                                                        {"ref": "order_backlog"},
                                                        {"ref": "revenue"},
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
        "description": "Revenue with the backlog term only (level-shift guard).",
        "tick_driver": True,
    }


def _intake_decay_driver() -> dict:
    return {
        "output": "order_intake",
        "expression": {
            "op": "multiply",
            "args": [
                {"ref": "order_intake"},
                {"op": "subtract", "args": [1, {"ref": "order_decay"}]},
            ],
        },
        "description": "New-orders flow decays by (1 - order_decay) per tick.",
        "tick_driver": True,
    }


def _backlog_update_driver() -> dict:
    return {
        "output": "order_backlog",
        "expression": {
            "op": "max",
            "args": [
                0,
                {
                    "op": "subtract",
                    "args": [
                        {
                            "op": "add",
                            "args": [{"ref": "order_backlog"}, {"ref": "order_intake"}],
                        },
                        {
                            "op": "multiply",
                            "args": [{"ref": "backlog_conversion"}, {"ref": "order_backlog"}],
                        },
                    ],
                },
            ],
        },
        "description": "Backlog updates as backlog + intake - converted, floored at 0.",
        "tick_driver": True,
    }


def _proportional_intake_driver() -> dict:
    """Unit-guard driver ONLY: intake proportional to (post-tick)
    revenue at a constant rate — the constant-intake-RATE reading of
    the spec's unit validation. Reads ``order_decay`` so the
    ``decay = 0`` precondition is load-bearing (any nonzero decay
    breaks the constant shift). Never used in a backtest case."""
    return {
        "output": "order_intake",
        "expression": {
            "op": "multiply",
            "args": [
                {
                    "op": "multiply",
                    "args": [{"ref": "order_intake_rate"}, {"ref": "revenue"}],
                },
                {"op": "subtract", "args": [1, {"ref": "order_decay"}]},
            ],
        },
        "description": "Constant-rate intake (unit guard only, not a backtest driver).",
        "tick_driver": True,
    }


# --- Template shape -----------------------------------------------------


def test_order_book_variables_match_spec() -> None:
    by_id = {raw["id"]: raw for raw in TEMPLATE_VARIABLES}
    # R&D margin promotion (2026-11-20): 61 -> 69 variables, 36 -> 42
    # formulas (the revenue-passthrough merge anchor is one of the six
    # chain formulas; see the template docstring).
    # Margin-profit transmission (2026-11-20): 69 -> 70 variables.
    assert len(TEMPLATE_VARIABLES) == 70
    assert len(TEMPLATE_FORMULAS) == 42
    expected = {
        "order_backlog": ("fixed", 0.0),
        "order_intake": ("fixed", 0.0),
        "order_intake_rate": ("triangular", (0.50, 1.00, 1.50)),
        "backlog_conversion": ("triangular", (0.30, 0.40, 0.60)),
        "order_decay": ("triangular", (0.10, 0.25, 0.40)),
    }
    for var_id, (kind, dist_v) in expected.items():
        raw = by_id[var_id]
        dist = raw["distribution"]
        assert dist["type"] == kind, var_id
        if kind == "fixed":
            assert dist["value"] == dist_v, var_id
        else:
            assert (dist["min"], dist["mode"], dist["max"]) == dist_v, var_id
        assert raw["unit"], var_id
        assert raw["evidence_ref"], var_id
    template = builtin_template("automotive")
    # R&D margin promotion (2026-11-20): 61 -> 69 variables, 36 -> 42
    # formulas (the revenue-passthrough merge anchor is one of the six
    # chain formulas; see the template docstring).
    # Margin-profit transmission (2026-11-20): 69 -> 70 variables.
    assert len(template.variables) == 70
    assert len(template.formulas) == 42
    fields = {f.name: float(f.default) for f in domain_pack_registry.get("automotive").state_fields}
    assert len(fields) == 50
    assert fields["order_backlog"] == 0.0
    assert fields["order_intake"] == 0.0


# --- API harness (mirrors test_nev_chain.py) -----------------------------


def build_database_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def setup_app(monkeypatch, tmp_path: Path, db_name: str = "planagent-order-book.db") -> None:
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


def _backlog_case_set(
    backlog_conversion: float,
    order_decay: float = 0.25,
    order_intake_rate: float = 1.0,
) -> dict:
    """Full 2020-mode Desay case set: adoption + NEV chain + backlog.
    Fixed values throughout, so the trajectory is deterministic. The
    opening book/flow are bound as variables at one year of intake
    (intake_rate * mode revenue = 6799.06); see the module docstring
    for why they are variables, not initial formulas."""
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
        _fixed("nev_coupling", 0.25),
        _fixed("nev_ceiling", 0.40),
        _fixed("nev_rate", 0.70),
        _fixed("nev_midpoint", 4.0),
        _fixed("order_backlog", 6799.06),
        _fixed("order_intake", 6799.06),
        _fixed("order_intake_rate", order_intake_rate),
        _fixed("backlog_conversion", backlog_conversion),
        _fixed("order_decay", order_decay),
        _fixed("production_volume", 2531.1),
        _fixed("sales_volume_retail", 1740.4),
        _fixed("sales_volume_wholesale", 1740.4),
        _fixed("dealer_inventory_coef", 1.2),
    ]
    formulas = [
        _adoption_driver(),
        _nev_logistic_driver(),
        _growth_driver("market_share", "base_growth", "share_coupling", cap=True),
        _revenue_driver_with_backlog(),
        _growth_driver("profit", "profit_growth", "profit_coupling", cap=False),
        _intake_decay_driver(),
        _backlog_update_driver(),
    ]
    return {"name": "order-book-test-case", "variables": variables, "formulas": formulas}


def _level_shift_case_set() -> dict:
    """Level-shift guard case: revenue_growth 0.10, conversion 0.50,
    intake rate 0.6875, decay 0.0, book opened at its steady state
    (backlog = revenue, so backlog/revenue = 1.0 exactly). With the
    proportional-intake driver the steady state is exact: growth is
    1 + 0.10 + 0.50 * 1.0 = 1.60 every tick, and the book stays equal
    to revenue. (Steady-state check: x = (1-c)x/(1+rg+cx) + r gives
    x = 1 for c = 0.50, rg = 0.10, r = 0.6875.)"""
    variables = [
        _fixed("revenue", 6799.06),
        _fixed("revenue_growth", 0.10),
        _fixed("order_backlog", 6799.06),
        _fixed("order_intake", 0.6875 * 6799.06),
        _fixed("order_intake_rate", 0.6875),
        _fixed("backlog_conversion", 0.50),
        _fixed("order_decay", 0.0),
    ]
    formulas = [
        _revenue_driver_backlog_only(),
        _proportional_intake_driver(),
        _backlog_update_driver(),
    ]
    return {"name": "order-book-level-shift", "variables": variables, "formulas": formulas}


def _create_run(client: TestClient, case_set: dict, tick_count: int = 5) -> dict:
    payload = {
        "company_id": "order-book-test",
        "company_name": "Order Book Test",
        "market": "auto-electronics-china",
        "domain_id": "automotive",
        "actor_template": "tier1_supplier",
        "tick_count": tick_count,
        "seed": 7,
        "decision_time": "2020-12-31T00:00:00Z",
        "variable_template_id": "builtin:automotive",
        "variable_set": case_set,
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


def _simulate_backlog(
    revenue0: float = 6799.06,
    backlog_conversion: float = 0.40,
    order_decay: float = 0.25,
    order_intake_rate: float = 1.0,
) -> tuple[dict[int, float], dict[int, float], dict[int, float]]:
    """Independent replication of the driver math (same equations,
    written separately): revenue / backlog / intake per tick, each
    rounded to 4dp like the engine. Returns (revenue, backlog,
    intake) keyed by tick."""
    revenue = {0: revenue0}
    backlog = {0: round(order_intake_rate * revenue0, 4)}
    intake = {0: round(order_intake_rate * revenue0, 4)}
    for tick in range(1, 6):
        adoption = _logistic(1.0 * (tick - 3.0), 0.85)
        pen = _logistic(0.70 * (tick - 4.0), 0.40)
        factor = (
            1
            + 0.15
            + 0.25 * adoption
            + 0.25 * pen
            + backlog_conversion * backlog[tick - 1] / revenue[tick - 1]
        )
        revenue[tick] = round(revenue[tick - 1] * factor, 4)
        intake[tick] = round(intake[tick - 1] * (1 - order_decay), 4)
        backlog[tick] = round(
            max(0, backlog[tick - 1] + intake[tick] - backlog_conversion * backlog[tick - 1]),
            4,
        )
    return revenue, backlog, intake


# --- Unit validation 1: constant intake rate = constant level shift ----


def test_order_book_constant_intake_rate_is_level_shift(monkeypatch, tmp_path: Path) -> None:
    """Spec §7 validation 1, under the constant-intake-RATE reading
    (see the module docstring): with order_decay = 0 and new orders
    proportional to revenue, the backlog term is exactly constant, so
    per-tick growth is exactly constant — a level shift with NO shape
    change. This regression-guards the NEV-chain results: at steady
    state the backlog channel cannot bend the growth profile."""
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        states = _trajectory(client, _create_run(client, _level_shift_case_set())["id"])
        assert sorted(states) == [0, 1, 2, 3, 4, 5]
        assert states[0]["order_backlog"] == pytest.approx(6799.06, rel=1e-6)
        assert states[0]["order_intake"] == pytest.approx(0.6875 * 6799.06, rel=1e-3)
        revenue = {t: states[t]["revenue"] for t in states}
        factors = [revenue[t] / revenue[t - 1] for t in (1, 2, 3, 4, 5)]
        for factor in factors:
            assert factor == pytest.approx(1.60, rel=1e-3), factors
        # The book tracks revenue exactly at the steady state, and the
        # path is the no-backlog path (1.10^t) scaled by a constant
        # growth-rate shift (1.60/1.10)^t.
        for tick in (1, 2, 3, 4, 5):
            assert states[tick]["order_backlog"] == pytest.approx(revenue[tick], rel=1e-3), tick
            assert revenue[tick] == pytest.approx(6799.06 * 1.60**tick, rel=1e-3), tick


# --- Shape: decaying intake makes per-tick growth FALL -------------------


def test_order_book_decay_produces_falling_growth(monkeypatch, tmp_path: Path) -> None:
    """The shape property the monotone channels cannot express: at
    2020 mode values (conversion 0.40, decay 0.25, intake rate 1.0)
    per-tick revenue growth FALLS tick by tick even while adoption
    and NEV penetration keep rising — because the backlog term
    (conversion * backlog / revenue) shrinks as the order surge
    passes. The trajectory matches an independent replication of
    the driver equations tick by tick."""
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        states = _trajectory(client, _create_run(client, _backlog_case_set(0.40))["id"])
        revenue = {t: states[t]["revenue"] for t in states}
        backlog = {t: states[t]["order_backlog"] for t in states}
        intake = {t: states[t]["order_intake"] for t in states}
        assert states[0]["order_backlog"] == pytest.approx(6799.06, rel=1e-6)
        assert states[0]["order_intake"] == pytest.approx(6799.06, rel=1e-6)
        factors = [revenue[t] / revenue[t - 1] for t in (1, 2, 3, 4, 5)]
        assert factors == sorted(factors, reverse=True), factors
        assert all(factors[i] > factors[i + 1] for i in range(len(factors) - 1)), factors
        # The backlog term itself shrinks every tick.
        terms = [0.40 * backlog[t - 1] / revenue[t - 1] for t in (1, 2, 3, 4, 5)]
        assert terms == sorted(terms, reverse=True), terms
        # The intake flow decays geometrically; the book first builds
        # (intake still exceeds conversion) and then drains below its
        # opening level as the surge passes.
        assert intake[1] == pytest.approx(6799.06 * 0.75, rel=1e-3)
        assert backlog[2] > backlog[1] > backlog[0]
        assert backlog[5] < backlog[0]
        # Independent replication agrees tick by tick.
        exp_rev, exp_backlog, exp_intake = _simulate_backlog()
        for tick in (1, 2, 3, 4, 5):
            assert revenue[tick] == pytest.approx(exp_rev[tick], rel=2e-3), tick
            assert backlog[tick] == pytest.approx(exp_backlog[tick], rel=2e-3), tick
            assert intake[tick] == pytest.approx(exp_intake[tick], rel=2e-3), tick


# --- Frozen baseline: conversion 0 reproduces the no-backlog path -------


def test_order_book_frozen_baseline_conversion_zero_is_no_backlog(
    monkeypatch, tmp_path: Path
) -> None:
    """Frozen-baseline control (diagnostic Appendix A, per channel):
    every variable fixed, only backlog_conversion changes. 0.0 must
    reproduce the pure NEV-chain revenue exactly, and 0.40 must sit
    above it at every tick; share and profit are untouched by the
    backlog channel (same in both runs)."""
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        states_on = _trajectory(client, _create_run(client, _backlog_case_set(0.40))["id"])
        states_off = _trajectory(client, _create_run(client, _backlog_case_set(0.0))["id"])
        revenue_on = {t: states_on[t]["revenue"] for t in states_on}
        revenue_off = {t: states_off[t]["revenue"] for t in states_off}
        exp_rev, _, _ = _simulate_backlog(backlog_conversion=0.0)
        for tick in (1, 2, 3, 4, 5):
            assert revenue_off[tick] == pytest.approx(exp_rev[tick], rel=2e-3), tick
            assert revenue_on[tick] > revenue_off[tick], tick
            assert states_on[tick]["market_share"] == pytest.approx(
                states_off[tick]["market_share"], rel=1e-6
            ), tick
            assert states_on[tick]["profit"] == pytest.approx(
                states_off[tick]["profit"], rel=1e-6
            ), tick
        # With conversion 0 the book only accumulates (nothing leaves).
        assert states_off[5]["order_backlog"] > states_off[0]["order_backlog"]


# --- Generic automotive runs are exactly unaffected ----------------------


def test_order_book_generic_run_unaffected(monkeypatch, tmp_path: Path) -> None:
    """A generic automotive run (built-in template, no backlog
    drivers attached) leaves the book empty and revenue at its pack
    default: the new state fields and template variables are dormant
    unless a case attaches the mechanism."""
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        payload = {
            "company_id": "order-book-generic",
            "company_name": "Generic Automotive",
            "market": "auto-electronics-china",
            "domain_id": "automotive",
            "actor_template": "tier1_supplier",
            "tick_count": 5,
            "seed": 7,
            "decision_time": "2020-12-31T00:00:00Z",
            "variable_template_id": "builtin:automotive",
            "variable_set": {"name": "generic", "variables": [], "formulas": []},
        }
        created = client.post("/simulation/runs", json=payload)
        assert created.status_code == 201, created.text
        states = _trajectory(client, created.json()["id"])
        for tick in (0, 1, 2, 3, 4, 5):
            assert states[tick]["order_backlog"] == 0.0, tick
            assert states[tick]["order_intake"] == 0.0, tick
            assert states[tick]["revenue"] == 100.0, tick

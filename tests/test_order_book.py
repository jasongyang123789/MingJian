"""Track 11 order-book (backlog) mechanism tests — Track A revision (2026-11-20).

The backlog term is the SHAPE term to the NEV chain's LEVEL term
(``diagnostic-2020/DIAGNOSTIC-2020.md`` §4, §5.3; Track 7 report §7):
model growth is non-decreasing per tick while the desay-2020 actuals
decelerate, so no monotone channel can express the front-loaded shape.

RESTATED CRITERION (Track A, 2026-11-20 — replaces Track 7 §7 as
literally written). The old wording ("yr-3 and yr-5 signed errors
moving toward each other") is UNACHIEVABLE by any positive additive
term (Track 11 proof: every positive early boost compounds into year 5,
so the signed gap grows whenever the late terms add anything — measured
22.0→33.2pp on 2015 and 37.4→43.6pp on 2020 at e047f50). The criterion
is now: **per-tick growth becomes decreasing AND both absolute errors
shrink** (yr-3 replay and yr-5 P50, each vs its actual). Historical
reports (TRACK11-ORDER-BOOK.md, the e047f50 re-run REPORT.md) keep the
old wording as history; this file, ``docs/causal-chain-pattern.md`` §5
and the Track A harness pin the new wording. The shape tests below lock
the first half (falling growth at 2020 AND 2015 mode values); the second
half (absolute errors shrink) is asserted by the Track A re-run
analysis, not by a unit test — it needs the ensemble.

MECHANISM (Track A revision of the Track 11 drivers). The Track 11
mechanism failed the 2015 control: the backlog term HUMPED before it
decayed (0.102, 0.119, 0.102, 0.078 at Track 11; e047f50 B-replay
factors [1.2316, 1.2614, 1.2613, 1.2622] still rising) because decay
acted only on the FLOW while conversion (~0.40) roughly balanced the
intake flow, so the stock sat near 1300–1400 while revenue grew. The
revision is structural — no parameter was tuned to the 2015 actuals
(hindsight firewall: the values below are the template/case MODES,
set before the run):

- Conversion applies to the POOL AVAILABLE DURING THE TICK
  (opening book + this tick's new orders): the revenue driver gains
  ``+ backlog_conversion * (order_backlog + order_intake) / revenue``,
  where ``order_intake`` is the DECAYED flow of this tick. New orders
  placed during the year can convert within the same year; the
  converted amount is exactly ``backlog_conversion * pool``, so the
  revenue term still equals the converted amount (the Track 11
  accounting identity is preserved).
- The pool lapses as adoption rises: the backlog driver updates the
  stock as ``max(0, pool * (1 - backlog_conversion - disruptor_adoption))``.
  Unfulfilled orders for superseded tech lapse as smart-cockpit/ADAS
  adoption rises; the lapse rate is the adoption level itself — an
  in-model quantity, no new parameter. (Screening evidence: adding the
  flow-decay rate to the stock lapse as well exhausts the book early
  and fails the shape grid 8/12; the flow decay still governs the
  intake flow itself. See the Track A report.)
- Driver order within a tick is load-bearing: adoption, NEV, share,
  INTAKE (decays the flow), REVENUE (reads the decayed flow and the
  pre-tick book), profit, BACKLOG (reads the decayed flow, adoption
  and the pre-tick book). Intake must precede revenue, or revenue
  would read last tick's flow.

The opening book/flow are bound as case VARIABLES (one year of intake
at the intake-rate mode), not initial formulas: merge is per-output,
so an initial formula and a tick driver cannot share an output id
(the driver replaces the formula — caught by test during Track 11).
``order_intake_rate`` itself is PINNED FIXED at its mode in the
backtest cases (Track A task 2, option (ii)): it is sampled but unread
by any driver, so sampling it only consumes RNG stream and implies an
uncertainty propagation that does not happen. The pin changes no
trajectory (locked by ``test_order_intake_rate_is_inert`` below); the
ensemble does not propagate intake-rate uncertainty until real
order-book calibration data exists. The engine-level alternative
(initial formula + tick driver coexisting on one output) was assessed
and NOT taken: it would weaken two core invariants (duplicate-output
rejection in ``validate_formulas``; per-output override in
``merge_variable_sets``) for uncalibrated parameters. It is
behavior-preserving for all existing runs (the template's only initial
formulas are ``demand_growth_rate`` / ``demand_level_factor`` /
``pull_forward_stock_initial`` — no case driver targets them), but the
trade-off is not worth it now; see the Track A report §2.

On the spec's unit validation ("with ``order_decay`` = 0 and constant
intake, the backlog term must reduce to a constant level shift"): the
only reading under which the term is EXACTLY constant is constant
intake RATE — new orders proportional to revenue. With the revised
drivers and the intake driver running BEFORE revenue (so it reads
pre-tick revenue), the steady state is growth exactly 1.60 with
``order_backlog / revenue`` = 0.3125 (re-derived in the level-shift
test below; the old 1.00 book/revenue ratio belonged to the Track 11
driver equations). The level-shift test below therefore opens the book
at 0.3125 x revenue and pins adoption at 0.0.
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


def _triangular(variable_id: str, low: float, mode: float, high: float) -> dict:
    return {
        "id": variable_id,
        "unit": "test",
        "distribution": {"type": "triangular", "min": low, "mode": mode, "max": high},
        "evidence_ref": "test: triangular for the inertness check",
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


def _backlog_term() -> dict:
    """Track A revenue term: conversion * (pre-tick book + this tick's
    decayed intake) / pre-tick revenue. Reads ``order_intake`` AFTER
    the intake driver has decayed it (driver order is load-bearing)."""
    return {
        "op": "multiply",
        "args": [
            {"ref": "backlog_conversion"},
            {
                "op": "divide",
                "args": [
                    {
                        "op": "add",
                        "args": [{"ref": "order_backlog"}, {"ref": "order_intake"}],
                    },
                    {"ref": "revenue"},
                ],
            },
        ],
    }


def _revenue_driver_with_backlog() -> dict:
    """Full Desay revenue driver: base growth + adoption coupling +
    NEV-chain term + exactly one backlog term (Track A: conversion on
    the available pool). No interaction term."""
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
                                                        _backlog_term(),
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
        "description": "Revenue with the NEV-chain term and the backlog term (Track A).",
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
                                        _backlog_term(),
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
    """Track A stock update: the available pool (pre-tick book + this
    tick's decayed intake) loses conversion AND the adoption lapse,
    floored at 0. The lapse is the adoption level itself — no new
    parameter. At extreme draws (conversion + adoption > 1) the pool
    is fully exhausted and the floor binds; the term can never go
    negative."""
    return {
        "output": "order_backlog",
        "expression": {
            "op": "max",
            "args": [
                0,
                {
                    "op": "multiply",
                    "args": [
                        {
                            "op": "add",
                            "args": [{"ref": "order_backlog"}, {"ref": "order_intake"}],
                        },
                        {
                            "op": "subtract",
                            "args": [
                                1,
                                {
                                    "op": "add",
                                    "args": [
                                        {"ref": "backlog_conversion"},
                                        {"ref": "disruptor_adoption"},
                                    ],
                                },
                            ],
                        },
                    ],
                },
            ],
        },
        "description": "Backlog updates as (backlog + intake) * (1 - conversion - adoption), floored at 0 (Track A).",
        "tick_driver": True,
    }


def _proportional_intake_driver() -> dict:
    """Unit-guard driver ONLY: intake proportional to (pre-tick)
    revenue at a constant rate — the constant-intake-RATE reading of
    the spec's unit validation. Runs BEFORE revenue, so it reads the
    pre-tick revenue. Reads ``order_decay`` so the ``decay = 0``
    precondition is load-bearing (any nonzero decay breaks the
    constant shift). Never used in a backtest case."""
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
    # Merge (2026-11-23): 61 -> 76 variables, 36 -> 44 formulas
    # (C1 +6/+1, R&D +8/+6, transmission +1/+0, Track A intake
    # anchor +0/+1; the revenue-passthrough merge anchor is one of
    # the seven chain formulas; see the template docstring).
    assert len(TEMPLATE_VARIABLES) == 76
    assert len(TEMPLATE_FORMULAS) == 44
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
    # Merge (2026-11-23): 61 -> 76 variables, 36 -> 44 formulas
    # (C1 +6/+1, R&D +8/+6, transmission +1/+0, Track A intake
    # anchor +0/+1; the revenue-passthrough merge anchor is one of
    # the seven chain formulas; see the template docstring).
    assert len(template.variables) == 76
    assert len(template.formulas) == 44
    fields = {f.name: float(f.default) for f in domain_pack_registry.get("automotive").state_fields}
    assert len(fields) == 51
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
    backlog_conversion: float = 0.40,
    order_decay: float = 0.25,
    order_intake_rate: float = 1.0,
    revenue0: float = 6799.06,
    book0: float = 6799.06,
    revenue_growth: float = 0.15,
    revenue_coupling: float = 0.25,
    disruptor_rate: float = 1.0,
    disruptor_midpoint: float = 3.0,
    disruptor_ceiling: float = 0.85,
    nev_rate: float = 0.70,
    nev_midpoint: float = 4.0,
    nev_ceiling: float = 0.40,
    nev_penetration0: float = 0.054,
) -> dict:
    """Full Desay case set: adoption + NEV chain + backlog (Track A
    drivers). Fixed values throughout, so the trajectory is
    deterministic. Defaults are the 2020 MODE values; the 2015 shape
    test overrides them. Driver order is load-bearing: intake decays
    the flow BEFORE revenue reads it, and the backlog updates last.
    The opening book/flow are bound as variables at one year of intake
    (intake_rate * mode revenue); see the module docstring for why
    they are variables, not initial formulas."""
    variables = [
        _fixed("market_share", 0.066),
        _fixed("base_growth", 0.03),
        _fixed("disruptor_ceiling", disruptor_ceiling),
        _fixed("disruptor_rate", disruptor_rate),
        _fixed("disruptor_midpoint", disruptor_midpoint),
        _fixed("share_coupling", 0.25),
        _fixed("revenue", revenue0),
        _fixed("revenue_growth", revenue_growth),
        _fixed("revenue_coupling", revenue_coupling),
        _fixed("profit", 518.15),
        _fixed("profit_growth", 0.12),
        _fixed("profit_coupling", 0.15),
        _fixed("nev_penetration", nev_penetration0),
        _fixed("nev_coupling", 0.25),
        _fixed("nev_ceiling", nev_ceiling),
        _fixed("nev_rate", nev_rate),
        _fixed("nev_midpoint", nev_midpoint),
        _fixed("order_backlog", book0),
        _fixed("order_intake", book0),
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
        _intake_decay_driver(),
        _revenue_driver_with_backlog(),
        _growth_driver("profit", "profit_growth", "profit_coupling", cap=False),
        _backlog_update_driver(),
    ]
    return {"name": "order-book-test-case", "variables": variables, "formulas": formulas}


def _level_shift_case_set() -> dict:
    """Level-shift guard case: revenue_growth 0.10, conversion 0.50,
    intake rate 0.6875, decay 0.0, adoption pinned 0.0, book opened at
    the Track A steady state (backlog / revenue = 0.3125). With the
    proportional-intake driver (reading PRE-tick revenue — it runs
    before revenue) the steady state is exact: growth is
    1 + 0.10 + 0.50 * (0.3125 + 0.6875) = 1.60 every tick, and the book
    stays at 0.3125 x revenue. (Steady-state check: revenue
    R_t = 1.10 * R + 0.5 * (B + 0.6875 * R) = 1.60 * R when B = 0.3125
    * R; book B_t = (B + 0.6875 * R) * (1 - 0.5 - 0) = 0.5 * R = 0.3125
    * R_t.)"""
    variables = [
        _fixed("revenue", 6799.06),
        _fixed("revenue_growth", 0.10),
        _fixed("disruptor_adoption", 0.0),
        _fixed("order_backlog", 0.3125 * 6799.06),
        _fixed("order_intake", 0.6875 * 6799.06),
        _fixed("order_intake_rate", 0.6875),
        _fixed("backlog_conversion", 0.50),
        _fixed("order_decay", 0.0),
    ]
    formulas = [
        _proportional_intake_driver(),
        _revenue_driver_backlog_only(),
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
    backlog0: float = 6799.06,
    backlog_conversion: float = 0.40,
    order_decay: float = 0.25,
    revenue_growth: float = 0.15,
    revenue_coupling: float = 0.25,
    nev_coupling: float = 0.25,
    disruptor_rate: float = 1.0,
    disruptor_midpoint: float = 3.0,
    disruptor_ceiling: float = 0.85,
    nev_rate: float = 0.70,
    nev_midpoint: float = 4.0,
    nev_ceiling: float = 0.40,
    ticks: int = 5,
) -> tuple[dict[int, float], dict[int, float], dict[int, float], dict[int, float]]:
    """Independent replication of the Track A driver math (same
    equations, written separately): revenue / backlog / intake / the
    backlog term per tick, each rounded to 4dp like the engine.
    Per tick: the intake decays first, then the revenue term converts
    the available pool (pre-tick book + decayed intake), then the pool
    loses conversion and the adoption lapse. Returns (revenue, backlog,
    intake, term) keyed by tick."""
    revenue = {0: revenue0}
    backlog = {0: backlog0}
    intake = {0: backlog0}
    term: dict[int, float] = {}
    for tick in range(1, ticks + 1):
        adoption = _logistic(disruptor_rate * (tick - disruptor_midpoint), disruptor_ceiling)
        pen = _logistic(nev_rate * (tick - nev_midpoint), nev_ceiling)
        intake[tick] = round(intake[tick - 1] * (1 - order_decay), 4)
        pool = backlog[tick - 1] + intake[tick]
        term[tick] = backlog_conversion * pool / revenue[tick - 1]
        factor = 1 + revenue_growth + revenue_coupling * adoption + nev_coupling * pen + term[tick]
        revenue[tick] = round(revenue[tick - 1] * factor, 4)
        backlog[tick] = round(max(0, pool * (1 - backlog_conversion - adoption)), 4)
    return revenue, backlog, intake, term


# --- Unit validation 1: constant intake rate = constant level shift ----


def test_order_book_constant_intake_rate_is_level_shift(monkeypatch, tmp_path: Path) -> None:
    """Restated-criterion unit validation 1, under the
    constant-intake-RATE reading (see the module docstring): with
    order_decay = 0, adoption pinned 0.0 and new orders proportional
    to revenue, the backlog term is exactly constant, so per-tick
    growth is exactly constant — a level shift with NO shape change.
    This regression-guards the NEV-chain results: at steady state the
    backlog channel cannot bend the growth profile. Track A
    re-derivation: the intake driver runs before revenue (reading
    pre-tick revenue), so the steady state is growth 1.60 with the
    book at 0.3125 x revenue (not 1.00 x as under the Track 11
    equations)."""
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        states = _trajectory(client, _create_run(client, _level_shift_case_set())["id"])
        assert sorted(states) == [0, 1, 2, 3, 4, 5]
        assert states[0]["order_backlog"] == pytest.approx(0.3125 * 6799.06, rel=1e-3)
        assert states[0]["order_intake"] == pytest.approx(0.6875 * 6799.06, rel=1e-3)
        revenue = {t: states[t]["revenue"] for t in states}
        factors = [revenue[t] / revenue[t - 1] for t in (1, 2, 3, 4, 5)]
        for factor in factors:
            assert factor == pytest.approx(1.60, rel=1e-3), factors
        # The book tracks revenue at the steady-state ratio, and the
        # path is the no-backlog path (1.10^t) scaled by a constant
        # growth-rate shift (1.60/1.10)^t. The intake each tick is the
        # rate times the PRE-tick revenue (intake runs before revenue).
        for tick in (1, 2, 3, 4, 5):
            assert states[tick]["order_backlog"] == pytest.approx(
                0.3125 * revenue[tick], rel=1e-3
            ), tick
            assert states[tick]["order_intake"] == pytest.approx(
                0.6875 * revenue[tick - 1], rel=1e-3
            ), tick
            assert revenue[tick] == pytest.approx(6799.06 * 1.60**tick, rel=1e-3), tick


# --- Shape: decaying intake + adoption lapse makes growth FALL --------


def test_order_book_decay_produces_falling_growth(monkeypatch, tmp_path: Path) -> None:
    """The shape property the monotone channels cannot express, at
    2020 MODE values (conversion 0.40, decay 0.25, intake rate 1.0):
    per-tick revenue growth FALLS tick by tick even while adoption
    and NEV penetration keep rising — because the backlog term
    (conversion * pool / revenue) shrinks as the order surge passes
    and the pool lapses with adoption. Scored horizon is ticks 1–4
    (the Desay child replay has ticks 0–4); the trajectory matches an
    independent replication of the driver equations tick by tick."""
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        states = _trajectory(
            client, _create_run(client, _backlog_case_set(0.40), tick_count=4)["id"]
        )
        revenue = {t: states[t]["revenue"] for t in states}
        backlog = {t: states[t]["order_backlog"] for t in states}
        intake = {t: states[t]["order_intake"] for t in states}
        assert states[0]["order_backlog"] == pytest.approx(6799.06, rel=1e-6)
        assert states[0]["order_intake"] == pytest.approx(6799.06, rel=1e-6)
        factors = [revenue[t] / revenue[t - 1] for t in (1, 2, 3, 4)]
        assert factors == sorted(factors, reverse=True), factors
        assert all(factors[i] > factors[i + 1] for i in range(len(factors) - 1)), factors
        # The backlog term itself shrinks every tick, and the book
        # drains from tick 1 (the pool loses conversion + adoption
        # lapse faster than the decaying intake replenishes it).
        terms = [0.40 * (backlog[t - 1] + intake[t]) / revenue[t - 1] for t in (1, 2, 3, 4)]
        assert terms == sorted(terms, reverse=True), terms
        assert intake[1] == pytest.approx(6799.06 * 0.75, rel=1e-3)
        assert backlog[0] > backlog[1] > backlog[2] > backlog[3] > backlog[4]
        # Independent replication agrees tick by tick.
        exp_rev, exp_backlog, exp_intake, _ = _simulate_backlog(ticks=4)
        for tick in (1, 2, 3, 4):
            assert revenue[tick] == pytest.approx(exp_rev[tick], rel=2e-3), tick
            assert backlog[tick] == pytest.approx(exp_backlog[tick], rel=2e-3), tick
            assert intake[tick] == pytest.approx(exp_intake[tick], rel=2e-3), tick


def test_order_book_2015_mode_falling_growth(monkeypatch, tmp_path: Path) -> None:
    """The 2015 control, at 2015 MODE values — the case the Track 11
    mechanism failed (e047f50 B-replay factors [1.2316, 1.2614, 1.2613,
    1.2622], still rising, because the term humped before it decayed).
    Under the Track A drivers the small book (0.25x revenue) also
    yields falling per-tick growth on the scored horizon (ticks 1–4):
    the pool converts within the year and lapses with adoption, so the
    term falls from tick 1 instead of humping. Modes only — no
    parameter was tuned to the 2015 actuals (hindsight firewall)."""
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        case = _backlog_case_set(
            backlog_conversion=0.40,
            order_decay=0.25,
            order_intake_rate=0.25,
            revenue0=3668.25,
            book0=917.06,
            revenue_growth=0.10,
            revenue_coupling=0.15,
            disruptor_rate=0.8,
            disruptor_midpoint=4.0,
            disruptor_ceiling=0.85,
            nev_rate=0.5,
            nev_midpoint=5.0,
            nev_ceiling=0.30,
            nev_penetration0=0.0135,
        )
        states = _trajectory(client, _create_run(client, case, tick_count=4)["id"])
        revenue = {t: states[t]["revenue"] for t in states}
        backlog = {t: states[t]["order_backlog"] for t in states}
        intake = {t: states[t]["order_intake"] for t in states}
        factors = [revenue[t] / revenue[t - 1] for t in (1, 2, 3, 4)]
        assert factors == sorted(factors, reverse=True), factors
        assert all(factors[i] > factors[i + 1] for i in range(len(factors) - 1)), factors
        terms = [0.40 * (backlog[t - 1] + intake[t]) / revenue[t - 1] for t in (1, 2, 3, 4)]
        assert terms == sorted(terms, reverse=True), terms
        assert backlog[0] > backlog[1] > backlog[2] > backlog[3] > backlog[4]
        exp_rev, exp_backlog, exp_intake, _ = _simulate_backlog(
            revenue0=3668.25,
            backlog0=917.06,
            backlog_conversion=0.40,
            order_decay=0.25,
            revenue_growth=0.10,
            revenue_coupling=0.15,
            nev_coupling=0.25,
            disruptor_rate=0.8,
            disruptor_midpoint=4.0,
            disruptor_ceiling=0.85,
            nev_rate=0.5,
            nev_midpoint=5.0,
            nev_ceiling=0.30,
            ticks=4,
        )
        for tick in (1, 2, 3, 4):
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
    backlog channel (same in both runs). With conversion 0 the book
    still drains via the adoption lapse, so it ends below its opening
    level (it no longer accumulates as under the Track 11 update)."""
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        states_on = _trajectory(client, _create_run(client, _backlog_case_set(0.40))["id"])
        states_off = _trajectory(client, _create_run(client, _backlog_case_set(0.0))["id"])
        revenue_on = {t: states_on[t]["revenue"] for t in states_on}
        revenue_off = {t: states_off[t]["revenue"] for t in states_off}
        exp_rev, _, _, _ = _simulate_backlog(backlog_conversion=0.0)
        for tick in (1, 2, 3, 4, 5):
            assert revenue_off[tick] == pytest.approx(exp_rev[tick], rel=2e-3), tick
            assert revenue_on[tick] > revenue_off[tick], tick
            assert states_on[tick]["market_share"] == pytest.approx(
                states_off[tick]["market_share"], rel=1e-6
            ), tick
            assert states_on[tick]["profit"] == pytest.approx(
                states_off[tick]["profit"], rel=1e-6
            ), tick
        # With conversion 0 the book only lapses (adoption), so it
        # drains below its opening level.
        assert states_off[5]["order_backlog"] < states_off[0]["order_backlog"]


# --- Intake rate is inert: pinning it fixed changes nothing -------------


def test_order_intake_rate_is_inert(monkeypatch, tmp_path: Path) -> None:
    """Track A task 2, option (ii): ``order_intake_rate`` is sampled
    but unread by any driver, so its value cannot move a trajectory.
    The same case set with the rate triangular(0.50, 1.00, 1.50) and
    with it fixed at its mode 1.00 must produce identical replay
    trajectories at the same seed. That is why the backtest harness
    pins it fixed at the mode: the pin removes a misleading draw
    (sampled-but-unread implies an uncertainty propagation that does
    not happen) and changes no trajectory — only the RNG stream
    position for later random draws in real runs, which the re-run
    measures at the P50 level."""
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        base = _backlog_case_set(0.40)
        triangular = _backlog_case_set(0.40)
        triangular["variables"] = [
            _triangular("order_intake_rate", 0.50, 1.00, 1.50)
            if v["id"] == "order_intake_rate"
            else v
            for v in triangular["variables"]
        ]
        states_fixed = _trajectory(client, _create_run(client, base, tick_count=4)["id"])
        states_tri = _trajectory(client, _create_run(client, triangular, tick_count=4)["id"])
        for tick in (0, 1, 2, 3, 4):
            assert states_fixed[tick]["revenue"] == pytest.approx(
                states_tri[tick]["revenue"], rel=1e-9
            ), tick
            assert states_fixed[tick]["order_backlog"] == pytest.approx(
                states_tri[tick]["order_backlog"], rel=1e-9
            ), tick
            assert states_fixed[tick]["order_intake"] == pytest.approx(
                states_tri[tick]["order_intake"], rel=1e-9
            ), tick


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

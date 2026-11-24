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
and the Track A harness pin the new wording.
STEP-1 REFINEMENT (2026-11-24, finite-book depletion): the
mechanism-level pin is the BACKLOG TERM falling every tick (the book
depletes geometrically, so the term — the mechanism's own output —
shrinks monotonically) plus the opening fall of total growth (the
anti-hump guard: under Track 11 total factors ROSE from tick 1).
Total-factor monotonicity through the whole horizon is NOT pinned at
synthetic mode values: the adoption/NEV couplings are monotone RISING
channels, and once the term has burned off (tick 3–4 at mode values)
they take over and total growth rises again — that handover is the
mechanism working as designed (the opportunity leg is front-loaded;
after it burns off, base + coupling growth takes over). The shape
tests below lock the term's fall, the geometric depletion and the
opening fall at 2020 AND 2015 mode values, plus a tick-by-tick
replication. Total-factor falling through the horizon is verified on
the REAL cases, not the synthetic controls: the step-1 four-case
rerun (downside ON, seed 42, trials 50) has B-replay factors
[1.2599, 1.1796, 1.0694, 0.9763] (2015) and [1.7271, 1.3917, 1.2342,
1.1253] (2020), falling on every tick. The second half of the
criterion (absolute errors shrink) is asserted by the step-1 re-run
analysis, not by a unit test — it needs the ensemble.

MECHANISM (step 1, 2026-11-24 — FINITE-BOOK DEPLETION, replaces both
the Track 11 stock form and the Track A pool form). History: the
Track 11 mechanism failed the 2015 control (the backlog term HUMPED
before it decayed because decay acted only on the FLOW while
conversion (~0.40) roughly balanced the intake flow, so the stock sat
near 1300–1400 while revenue grew). Track A revised it to a POOL form
(term on pre-tick book + decayed intake, pool lapsing with adoption) —
but that form was NEVER run by any backtest harness: the tests pinned
it while every rerun harness (e047f50 → A/C → trials50) kept its own
Track 11 stock driver (term ``c*B/R``, update ``B + I - c*B``), and
Track A's own rerun made the 2015 yr-3 replay error WORSE (-4.1% →
+15.2%, its new-criterion checks all NO). Step 1 unifies the three
layers (template driver + tests + harness) on one form, chosen by
offline screening on the trials50 replay paths (OLD reproduced
exactly; FBOOK yr-3 replay errors +3.4%/+8.8%/−11.7%/−9.0% vs OLD
+19.9%/+20.2%/+20.0%/+13.2%; the pool form screened HOTTER, +24.9%/
+21.2% on the anchor paths) and confirmed by a full four-case rerun
(downside ON, seed 42, trials 50 — see the step-1 report):

- The revenue term is UNCHANGED: ``+ backlog_conversion *
  order_backlog / revenue`` on the PRE-TICK book. The converted
  amount is exactly ``backlog_conversion * book``, so the Track 11
  accounting identity (revenue term = converted amount) is preserved.
- The stock update is the change: ``B' = max(0, B * (1 -
  backlog_conversion))`` — the FINITE decision-time opening book
  depletes geometrically (mean delivery lag 1/c, ~2.5y at mode 0.40,
  inside the SOP-lag evidence 1.67–3.33y). The intake flow NO LONGER
  replenishes the convertible stock: later orders' delivery is carried
  by ``revenue_growth``, which is calibrated on TOTAL historical
  growth and already includes normal order conversion — replenishing
  the stock on top of it double-counts. The old stock form made the
  term a PERPETUAL growth premium (intake ≈ 1x revenue re-fills the
  book every tick, so ``c*B/R`` ≈ +10pp/+38pp per tick forever,
  horizon-unbounded); the pool form converted this tick's intake with
  no SOP lag (tick-1 term 0.65–0.93). Under depletion the total
  backlog uplift is FINITE and front-loaded.
- The stock update lives in the TEMPLATE (``TEMPLATE_FORMULAS``,
  right after the revenue passthrough — a merge anchor). A case must
  NOT supply its own backlog-update driver: one on the same output
  would replace the anchor in place and silently reintroduce its own
  form (that is exactly how the drift happened). Locked by
  ``test_template_backlog_driver_governs`` below (template-governed
  run == case-driver run, tick by tick).
- Driver order within a tick is load-bearing: adoption, NEV, share,
  INTAKE (decays the flow), REVENUE (reads the pre-tick book),
  BACKLOG (drains exactly what revenue converted), profit. The intake
  driver still runs (it decays the diagnostic flow) but the flow is
  unread by any driver under this form — locked by
  ``test_order_intake_is_inert_for_revenue`` below (twin runs with
  intake 6799.06 vs 0.0 have identical revenue/backlog trajectories).

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

On the spec's OLD unit validation ("with ``order_decay`` = 0 and
constant intake, the backlog term must reduce to a constant level
shift"): it does NOT hold under finite-book depletion BY DESIGN — a
finite book cannot produce a perpetual level shift, and the level-shift
test is replaced below by the finite-uplift test (the book depletes
geometrically, the term falls every tick, the total uplift converges).
A constant term would require a perpetually replenished stock, which
is exactly the defect this revision removes.
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

#: Sentinel for "omit the downside key entirely" (Track C default ON).
#: Passing None means an explicit ``downside: null`` (opt-out).
_OMIT = object()
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
    """Step-1 revenue term: conversion * pre-tick book / pre-tick
    revenue. The intake flow is NOT in the term (finite-book
    depletion: only the decision-time opening book converts)."""
    return {
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
    }


def _revenue_driver_with_backlog() -> dict:
    """Full Desay revenue driver: base growth + adoption coupling +
    NEV-chain term + exactly one backlog term (step 1: conversion on
    the pre-tick book only). No interaction term."""
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
        "description": "Revenue with the NEV-chain term and the backlog term (step 1 finite-book depletion).",
        "tick_driver": True,
    }


def _revenue_driver_backlog_only() -> dict:
    """Minimal revenue driver for the finite-uplift guard: base growth
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
    """Step-1 stock update: the finite book depletes geometrically
    at the conversion rate — B' = max(0, B * (1 - conversion)).
    The intake flow does NOT replenish the book (its delivery is
    carried by revenue_growth). Identical to the template's merge
    anchor; the template-governance test below asserts the two agree
    tick by tick when the case drops this driver."""
    return {
        "output": "order_backlog",
        "expression": {
            "op": "max",
            "args": [
                0,
                {
                    "op": "multiply",
                    "args": [
                        {"ref": "order_backlog"},
                        {
                            "op": "subtract",
                            "args": [1, {"ref": "backlog_conversion"}],
                        },
                    ],
                },
            ],
        },
        "description": "Backlog updates as backlog * (1 - conversion), floored at 0 (step 1 finite-book depletion).",
        "tick_driver": True,
    }


# --- Template shape -----------------------------------------------------


def test_order_book_variables_match_spec() -> None:
    by_id = {raw["id"]: raw for raw in TEMPLATE_VARIABLES}
    # Merge (2026-11-23): 61 -> 76 variables, 36 -> 44 formulas
    # (C1 +6/+1, R&D +8/+6, transmission +1/+0, Track A intake
    # anchor +0/+1; the revenue-passthrough merge anchor is one of
    # the seven chain formulas; see the template docstring).
    # Step 1 (2026-11-24): 44 -> 45 formulas (the order_backlog
    # finite-book-depletion merge anchor, right after the revenue
    # passthrough).
    assert len(TEMPLATE_VARIABLES) == 76
    assert len(TEMPLATE_FORMULAS) == 45
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
    # Step 1 (2026-11-24): 44 -> 45 formulas (backlog-update anchor).
    assert len(template.variables) == 76
    assert len(template.formulas) == 45
    # The template carries the backlog-update driver (finite-book
    # depletion) right after the revenue passthrough, and it is the
    # ONLY backlog-update driver in the template.
    assert [f for f in TEMPLATE_FORMULAS if f["output"] == "order_backlog"]
    assert [f["output"] for f in TEMPLATE_FORMULAS].index("order_backlog") == (
        [f["output"] for f in TEMPLATE_FORMULAS].index("revenue") + 1
    )
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
    """Full Desay case set: adoption + NEV chain + backlog (step-1
    finite-book drivers). Fixed values throughout, so the trajectory
    is deterministic. Defaults are the 2020 MODE values; the 2015
    shape test overrides them. Driver order is load-bearing: intake
    decays the flow BEFORE revenue reads the pre-tick book, and the
    backlog updates after revenue (draining exactly what revenue
    converted). The opening book/flow are bound as variables at one
    year of intake (intake_rate * mode revenue); see the module
    docstring for why they are variables, not initial formulas."""
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


def _finite_book_case_set() -> dict:
    """Finite-uplift guard case: revenue_growth 0.10, conversion
    0.50, decay 0.25, adoption pinned 0.0, book opened at half of
    revenue (B0 = 0.5 * R0). Under finite-book depletion the book
    halves every tick (B_t = B0 * 0.5^t) and the backlog term falls
    every tick, so per-tick growth FALLS toward the 1.10 base rate —
    the total uplift converges instead of compounding forever. The
    intake flow still decays each tick (the driver runs) but is
    unread, so it cannot move revenue: the twin run with intake 0.0
    must produce the identical revenue trajectory (locked by
    ``test_order_intake_is_inert_for_revenue``)."""
    variables = [
        _fixed("revenue", 6799.06),
        _fixed("revenue_growth", 0.10),
        _fixed("disruptor_adoption", 0.0),
        _fixed("order_backlog", 0.5 * 6799.06),
        _fixed("order_intake", 6799.06),
        _fixed("order_intake_rate", 1.0),
        _fixed("backlog_conversion", 0.50),
        _fixed("order_decay", 0.25),
    ]
    formulas = [
        _intake_decay_driver(),
        _revenue_driver_backlog_only(),
        _backlog_update_driver(),
    ]
    return {"name": "order-book-finite-uplift", "variables": variables, "formulas": formulas}


def _create_run(
    client: TestClient,
    case_set: dict,
    tick_count: int = 5,
    downside: dict | None | object = _OMIT,
) -> dict:
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
    if downside is not _OMIT:
        payload["downside"] = downside
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
    intake0: float | None = None,
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
    """Independent replication of the step-1 driver math (same
    equations, written separately): revenue / backlog / intake / the
    backlog term per tick, each rounded to 4dp like the engine.
    Per tick: the intake decays first (diagnostic only — it enters
    neither the term nor the book), then the revenue term converts
    the pre-tick book, then the book depletes geometrically at the
    conversion rate. Returns (revenue, backlog, intake, term) keyed
    by tick."""
    revenue = {0: revenue0}
    backlog = {0: backlog0}
    intake = {0: backlog0 if intake0 is None else intake0}
    term: dict[int, float] = {}
    for tick in range(1, ticks + 1):
        adoption = _logistic(disruptor_rate * (tick - disruptor_midpoint), disruptor_ceiling)
        pen = _logistic(nev_rate * (tick - nev_midpoint), nev_ceiling)
        intake[tick] = round(intake[tick - 1] * (1 - order_decay), 4)
        term[tick] = backlog_conversion * backlog[tick - 1] / revenue[tick - 1]
        factor = 1 + revenue_growth + revenue_coupling * adoption + nev_coupling * pen + term[tick]
        revenue[tick] = round(revenue[tick - 1] * factor, 4)
        backlog[tick] = round(max(0, backlog[tick - 1] * (1 - backlog_conversion)), 4)
    return revenue, backlog, intake, term


# --- Unit validation 1: the finite book depletes, the uplift converges -


def test_order_book_finite_book_depletes_and_uplift_converges(monkeypatch, tmp_path: Path) -> None:
    """Step-1 unit validation 1: with conversion 0.50 the book halves
    every tick (B_t = B0 * 0.5^t) and the backlog term falls every
    tick, so per-tick growth FALLS toward the 1.10 base rate instead
    of sitting at a constant level shift. The old level-shift
    property is gone BY DESIGN (a finite book cannot produce a
    perpetual shift — that was the defect); what is pinned instead
    is finiteness: the book is 1/32 of its opening level by tick 5
    and the total uplift converges (the tick-5 factor is within 1pp
    of the 1.10 base rate, vs 1.35 at tick 1)."""
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        states = _trajectory(client, _create_run(client, _finite_book_case_set())["id"])
        assert sorted(states) == [0, 1, 2, 3, 4, 5]
        assert states[0]["order_backlog"] == pytest.approx(0.5 * 6799.06, rel=1e-6)
        assert states[0]["order_intake"] == pytest.approx(6799.06, rel=1e-6)
        revenue = {t: states[t]["revenue"] for t in states}
        backlog = {t: states[t]["order_backlog"] for t in states}
        intake = {t: states[t]["order_intake"] for t in states}
        for tick in (1, 2, 3, 4, 5):
            assert backlog[tick] == pytest.approx(0.5 * 6799.06 * 0.5**tick, rel=1e-3), tick
            assert intake[tick] == pytest.approx(6799.06 * 0.75**tick, rel=1e-3), tick
        factors = [revenue[t] / revenue[t - 1] for t in (1, 2, 3, 4, 5)]
        assert factors == sorted(factors, reverse=True), factors
        assert all(factors[i] > factors[i + 1] for i in range(len(factors) - 1)), factors
        assert factors[0] == pytest.approx(1.35, rel=1e-3), factors
        assert factors[-1] == pytest.approx(1.10, abs=0.01), factors
        # Independent replication agrees tick by tick.
        exp_rev, exp_backlog, exp_intake, _ = _simulate_backlog(
            revenue0=6799.06, backlog0=0.5 * 6799.06, intake0=6799.06,
            backlog_conversion=0.50,
            order_decay=0.25, revenue_growth=0.10, revenue_coupling=0.0,
            nev_coupling=0.0, disruptor_rate=1.0, disruptor_midpoint=3.0,
            disruptor_ceiling=0.85, nev_rate=0.70, nev_midpoint=4.0,
            nev_ceiling=0.40, ticks=5,
        )
        for tick in (1, 2, 3, 4, 5):
            assert revenue[tick] == pytest.approx(exp_rev[tick], rel=2e-3), tick
            assert backlog[tick] == pytest.approx(exp_backlog[tick], rel=2e-3), tick
            assert intake[tick] == pytest.approx(exp_intake[tick], rel=2e-3), tick


# --- Shape: the depleting book makes growth FALL ------------------------


def test_order_book_decay_produces_falling_growth(monkeypatch, tmp_path: Path) -> None:
    """The shape property the monotone channels cannot express, at
    2020 MODE values (conversion 0.40, decay 0.25, intake rate 1.0):
    the backlog term (conversion * pre-tick book / revenue) FALLS
    every tick as the finite book depletes geometrically, and total
    growth falls with it while the term dominates (ticks 1–3). The
    tick-4 uptick is the coupling handover, not a failure: the
    adoption/NEV couplings are monotone RISING channels, and once the
    term has burned off (0.029 by tick 4) they take over — see the
    module docstring. What is pinned is the term's fall, the
    geometric depletion, the opening fall (the anti-hump guard: under
    Track 11 the factors ROSE from tick 1), and a tick-by-tick
    replication. Scored horizon is ticks 1–4 (the Desay child replay
    has ticks 0–4).

    Track C: explicitly opted out — the shape pin is exact (strictly
    falling terms + tick-by-tick replication), and the default shock
    breaks the monotonicity it exists to guard.
    """
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        states = _trajectory(
            client,
            _create_run(client, _backlog_case_set(0.40), tick_count=4, downside=None)["id"],
        )
        revenue = {t: states[t]["revenue"] for t in states}
        backlog = {t: states[t]["order_backlog"] for t in states}
        intake = {t: states[t]["order_intake"] for t in states}
        assert states[0]["order_backlog"] == pytest.approx(6799.06, rel=1e-6)
        assert states[0]["order_intake"] == pytest.approx(6799.06, rel=1e-6)
        factors = [revenue[t] / revenue[t - 1] for t in (1, 2, 3, 4)]
        # Opening fall (anti-hump): the term dominates ticks 1–3.
        assert factors[0] > factors[1] > factors[2], factors
        # The backlog term itself shrinks every tick, and the book
        # drains geometrically from tick 1 (the intake flow does not
        # replenish it).
        terms = [0.40 * backlog[t - 1] / revenue[t - 1] for t in (1, 2, 3, 4)]
        assert terms == sorted(terms, reverse=True), terms
        assert all(terms[i] > terms[i + 1] for i in range(len(terms) - 1)), terms
        assert intake[1] == pytest.approx(6799.06 * 0.75, rel=1e-3)
        assert backlog[0] > backlog[1] > backlog[2] > backlog[3] > backlog[4]
        for tick in (1, 2, 3, 4):
            assert backlog[tick] == pytest.approx(6799.06 * 0.6**tick, rel=1e-3), tick
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
    Under finite-book depletion the small book (0.25x revenue) also
    yields a falling backlog term from tick 1 (0.10 → 0.049 → 0.025 →
    0.013) and an opening fall of total growth (the anti-hump guard);
    the tick-3/4 uptick is the coupling handover (the small term
    burns off faster, so the rising adoption/NEV couplings take over
    sooner — see the module docstring). Modes only — no parameter was
    tuned to the 2015 actuals (hindsight firewall).

    Track C: explicitly opted out — the pin is an exact tick-by-tick
    replication, and the default shock would multiply the revenue
    factors away from it.
    """
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
        states = _trajectory(client, _create_run(client, case, tick_count=4, downside=None)["id"])
        revenue = {t: states[t]["revenue"] for t in states}
        backlog = {t: states[t]["order_backlog"] for t in states}
        intake = {t: states[t]["order_intake"] for t in states}
        factors = [revenue[t] / revenue[t - 1] for t in (1, 2, 3, 4)]
        # Opening fall (anti-hump): the term dominates tick 1–2.
        assert factors[0] > factors[1], factors
        terms = [0.40 * backlog[t - 1] / revenue[t - 1] for t in (1, 2, 3, 4)]
        assert terms == sorted(terms, reverse=True), terms
        assert all(terms[i] > terms[i + 1] for i in range(len(terms) - 1)), terms
        assert backlog[0] > backlog[1] > backlog[2] > backlog[3] > backlog[4]
        for tick in (1, 2, 3, 4):
            assert backlog[tick] == pytest.approx(917.06 * 0.6**tick, rel=1e-3), tick
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
    is FROZEN at its opening level (B' = B * (1 - 0) = B): nothing
    converts, nothing replenishes — the geometric-depletion form
    makes the frozen book a fixed point, where the Track 11 stock
    form accumulated it and the Track A pool form lapsed it with
    adoption.

    Track C: explicitly opted out — the control is an exact-equality
    device between two runs, and the default shock's draws depend on
    the variable set, so the two runs would draw different shocks.
    """
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        states_on = _trajectory(
            client, _create_run(client, _backlog_case_set(0.40), downside=None)["id"]
        )
        states_off = _trajectory(
            client, _create_run(client, _backlog_case_set(0.0), downside=None)["id"]
        )
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
        # With conversion 0 the book is frozen at its opening level.
        assert states_off[5]["order_backlog"] == pytest.approx(
            states_off[0]["order_backlog"], rel=1e-9
        )


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
    measures at the P50 level.

    Track C: explicitly opted out — the two runs differ in RNG stream
    position (fixed vs sampled rate), and the default shock's draws
    depend on the stream, so the trajectories would diverge for a
    reason unrelated to the rate.
    """
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
        states_fixed = _trajectory(client, _create_run(client, base, tick_count=4, downside=None)["id"])
        states_tri = _trajectory(client, _create_run(client, triangular, tick_count=4, downside=None)["id"])
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
    unless a case attaches the mechanism.

    Track C: explicitly opted out (``downside: null``) — the default
    shock would move revenue off its pack default, which is not what
    this test guards (it guards the order-book mechanism's dormancy).
    """
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
            "downside": None,
        }
        created = client.post("/simulation/runs", json=payload)
        assert created.status_code == 201, created.text
        states = _trajectory(client, created.json()["id"])
        for tick in (0, 1, 2, 3, 4, 5):
            assert states[tick]["order_backlog"] == 0.0, tick
            assert states[tick]["order_intake"] == 0.0, tick
            assert states[tick]["revenue"] == 100.0, tick


# --- The template driver governs: dropping the case driver changes nothing


def test_template_backlog_driver_governs(monkeypatch, tmp_path: Path) -> None:
    """Step-1 promotion lock: the template carries the backlog-update
    driver (merge anchor, right after the revenue passthrough), so a
    case that drops its own backlog-update driver must produce the
    IDENTICAL trajectory tick by tick. This is the guard against the
    drift this step found: the Track A pool form was pinned by the
    tests while every harness kept its own Track 11 stock driver, so
    the tested form and the run form diverged silently. If a case
    reintroduces its own driver on the same output, it replaces the
    anchor in place — the merge keeps exactly one order_backlog
    driver either way (asserted in
    ``test_order_book_variables_match_spec`` for the template side).

    Track C: explicitly opted out (``downside: null``) — the two runs
    must agree exactly, and the default shock would only add noise
    both runs share (same seed, same variable set), but the pin is an
    exact-equality device and the shock is unrelated to it.
    """
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        with_driver = _backlog_case_set(0.40)
        template_only = _backlog_case_set(0.40)
        template_only["formulas"] = [
            f for f in template_only["formulas"] if f["output"] != "order_backlog"
        ]
        assert len(template_only["formulas"]) == len(with_driver["formulas"]) - 1
        states_with = _trajectory(
            client, _create_run(client, with_driver, tick_count=5, downside=None)["id"]
        )
        states_tpl = _trajectory(
            client, _create_run(client, template_only, tick_count=5, downside=None)["id"]
        )
        for tick in (0, 1, 2, 3, 4, 5):
            assert states_tpl[tick]["revenue"] == pytest.approx(
                states_with[tick]["revenue"], rel=1e-9
            ), tick
            assert states_tpl[tick]["order_backlog"] == pytest.approx(
                states_with[tick]["order_backlog"], rel=1e-9
            ), tick
            assert states_tpl[tick]["order_intake"] == pytest.approx(
                states_with[tick]["order_intake"], rel=1e-9
            ), tick
            assert states_tpl[tick]["profit"] == pytest.approx(
                states_with[tick]["profit"], rel=1e-9
            ), tick


def test_order_intake_is_inert_for_revenue(monkeypatch, tmp_path: Path) -> None:
    """Under finite-book depletion the intake flow is a decaying
    diagnostic: it enters neither the revenue term nor the stock
    update. Twin runs with the opening intake at 6799.06 and at 0.0
    must produce identical revenue AND backlog trajectories (the
    intake state itself still decays in the first run and stays 0.0
    in the second). This is why the harness may keep its intake
    driver for diagnostics without it moving any scored quantity.

    Track C: explicitly opted out (``downside: null``) — exact
    equality between two runs, same reason as the frozen baseline.
    """
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        with_intake = _backlog_case_set(0.40)
        no_intake = _backlog_case_set(0.40)
        no_intake["variables"] = [
            _fixed("order_intake", 0.0) if v["id"] == "order_intake" else v
            for v in no_intake["variables"]
        ]
        states_with = _trajectory(
            client, _create_run(client, with_intake, tick_count=5, downside=None)["id"]
        )
        states_without = _trajectory(
            client, _create_run(client, no_intake, tick_count=5, downside=None)["id"]
        )
        for tick in (0, 1, 2, 3, 4, 5):
            assert states_without[tick]["revenue"] == pytest.approx(
                states_with[tick]["revenue"], rel=1e-9
            ), tick
            assert states_without[tick]["order_backlog"] == pytest.approx(
                states_with[tick]["order_backlog"], rel=1e-9
            ), tick
        assert states_with[5]["order_intake"] == pytest.approx(
            6799.06 * 0.75**5, rel=1e-3
        )
        assert states_without[5]["order_intake"] == 0.0

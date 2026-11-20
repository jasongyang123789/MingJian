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
D2C REFINEMENT (2026-11-25, Ho-approved Option A — lag-shaped
delivery, supersedes the step-1 geometric form). The step-1 pin (the
backlog term falling every tick) is SUPERSEDED: the geometric rate
converted 45% of the book in year 1 and caused the desay-2018 tick-1
overshoot (83% of it; the diagnosis). The mechanism-level pin is now
the SCHEDULE: the delivery fraction is 0 at tick 1 (the SOP-lag
floor — orders won in a year need at least 1–2 years to convert to
revenue, Ho confirmed 2026-11-25), peaks at tick 3 (45% of the
opening book) and exhausts the book by tick 5; the backlog term is
therefore 0 at tick 1, peaks at tick 3 and dies by tick 6, and total
growth rises to the schedule mode and falls after it. The Track A
criterion's first half ("per-tick growth becomes decreasing") does
NOT hold under D2C by design — growth rises to tick 3 — and is
replaced by the schedule pin plus the real-case validation: the
desay-2018 counterfactual (diagnosis §5.2) put the yr3 milestone
inside the band at +16.1% with this exact schedule and the tick-1
brake, and the D2C four-case rerun (downside ON, seed 42, trials 50)
is what decides the criterion now. The second half of the criterion
(absolute errors shrink) is asserted by the rerun analysis, not by a
unit test — it needs the ensemble.

MECHANISM (D2C, 2026-11-25 — LAG-SHAPED DELIVERY, replaces the
step-1 geometric form). History: the Track 11 mechanism failed the
2015 control (the backlog term HUMPED before it decayed because decay
acted only on the FLOW while conversion (~0.40) roughly balanced the
intake flow, so the stock sat near 1300–1400 while revenue grew).
Track A revised it to a POOL form (term on pre-tick book + decayed
intake, pool lapsing with adoption) — but that form was NEVER run by
any backtest harness: the tests pinned it while every rerun harness
(e047f50 → A/C → trials50) kept its own Track 11 stock driver (term
``c*B/R``, update ``B + I - c*B``), and Track A's own rerun made the
2015 yr-3 replay error WORSE (-4.1% → +15.2%, its new-criterion checks
all NO). Step 1 unified the three layers (template driver + tests +
harness) on finite-book depletion (``B' = B*(1-c)``), chosen by offline
screening and confirmed by a full four-case rerun — but the geometric
rate still converted 45% of the book in year 1, and the desay-2018
diagnosis (2026-11-25) showed that tick-1 conversion is 83% of the
2018 yr3 overshoot. D2C replaces the rate with a lag-shaped schedule
of fractions of the OPENING book, (0, 0.15, 0.45, 0.30, 0.10) for
ticks 1–5, plus a tick-1 downturn brake for negative-anchor cases:

- The revenue term is ``+ backlog_delivery_fraction *
  order_backlog_opening / revenue``. The delivered amount is exactly
  ``backlog_delivery_fraction * opening book``, so the Track 11
  accounting identity (revenue term = delivered amount) is preserved.
  ``backlog_delivery_fraction`` is a template tick driver (a merge
  anchor before the revenue passthrough): the schedule gated by
  ``backlog_conversion`` — min(1, backlog_conversion / 0.30) is 1 on
  the whole calibrated support (0.30–0.60) and 0 exactly when the leg
  is frozen off, so the leg-freeze interface (frozen-baseline
  decomposition, two-value module) keeps working. The schedule is
  DETERMINISTIC (not sampled): the counterfactual that validated it
  used fixed fractions.
- The stock update is ``B' = max(0, B - backlog_delivery_fraction *
  order_backlog_opening)`` — the FINITE decision-time opening book
  drains by the scheduled delivery (mean delivery lag ~3.35 ticks,
  inside the SOP-lag evidence 1.67–3.33y widened by vintage mix).
  The intake flow NO LONGER replenishes the convertible stock: later
  orders' delivery is carried by ``revenue_growth``, which is
  calibrated on TOTAL historical growth and already includes normal
  order conversion — replenishing the stock on top of it
  double-counts. Under the schedule the total backlog uplift is
  FINITE and lag-shaped (nothing in year 1, mode in year 3).
- The downturn brake adds ``downturn_brake * (tick == 1)`` to the
  revenue driver's growth sum — tick-1 growth only. When the
  anchor-year realized growth is negative, the brake is (anchor-year
  growth − revenue_growth mode): 2018 −0.1501; 2015/2020 anchor years
  positive, brake 0. Decision-point data only; never fitted to
  post-decision actuals (hindsight firewall).
- The stock update and the delivery-fraction driver live in the
  TEMPLATE (``TEMPLATE_FORMULAS`` — the fraction driver before the
  revenue passthrough, the update right after it; both merge anchors).
  A case must NOT supply its own drivers on either output: one on the
  same output would replace the anchor in place and silently
  reintroduce its own form (that is exactly how the drift happened).
  Locked by ``test_template_backlog_driver_governs`` below (template-
  governed run == case-driver run, tick by tick).
- Driver order within a tick is load-bearing: adoption, NEV, share,
  INTAKE (decays the flow), DELIVERY FRACTION (this tick's fraction),
  REVENUE (reads the fraction and the opening book), BACKLOG (drains
  exactly what revenue converted), profit. The intake driver still
  runs (it decays the diagnostic flow) but the flow is unread by any
  driver under this form — locked by
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
test is replaced below by the finite-uplift test (the book drains on
the schedule, the term is 0 at tick 1, peaks at tick 3 and dies by
tick 6, the total uplift converges). A constant term would require a
perpetually replenished stock, which is exactly the defect this
revision removes.
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
    """D2C revenue term: this tick's fraction of the OPENING book
    (backlog_delivery_fraction, 0 in tick 1) times the opening book,
    over pre-tick revenue. The intake flow is NOT in the term
    (finite-book depletion: only the decision-time opening book
    converts, on the lag-shaped schedule)."""
    return {
        "op": "multiply",
        "args": [
            {"ref": "backlog_delivery_fraction"},
            {
                "op": "divide",
                "args": [
                    {"ref": "order_backlog_opening"},
                    {"ref": "revenue"},
                ],
            },
        ],
    }


def _brake_term() -> dict:
    """D2C downturn brake: downturn_brake * (tick == 1) — tick-1
    growth only, via the min/max tick indicator (the formula
    language has no conditionals). 0 for growth-year anchors."""
    return {
        "op": "multiply",
        "args": [
            {"ref": "downturn_brake"},
            {
                "op": "max",
                "args": [
                    0,
                    {
                        "op": "min",
                        "args": [1, {"op": "subtract", "args": [2, {"ref": "tick"}]}],
                    },
                ],
            },
        ],
    }


def _revenue_driver_with_backlog() -> dict:
    """Full Desay revenue driver: base growth + adoption coupling +
    NEV-chain term + exactly one backlog term (D2C: this tick's
    fraction of the opening book) + the tick-1 downturn brake.
    No interaction term."""
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
                                                            "op": "add",
                                                            "args": [
                                                                _backlog_term(),
                                                                _brake_term(),
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
        "description": "Revenue with the NEV-chain term, the D2C backlog term and the tick-1 brake.",
        "tick_driver": True,
    }


def _revenue_driver_backlog_only() -> dict:
    """Minimal revenue driver for the finite-uplift guard: base growth
    plus exactly one backlog term plus the tick-1 brake, no adoption /
    NEV terms."""
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
                                                _backlog_term(),
                                                _brake_term(),
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
    """D2C stock update: the finite book depletes by the scheduled
    delivery — B' = max(0, B - backlog_delivery_fraction *
    order_backlog_opening). The intake flow does NOT replenish the
    book (its delivery is carried by revenue_growth). Identical to
    the template's merge anchor; the template-governance test below
    asserts the two agree tick by tick when the case drops this
    driver."""
    return {
        "output": "order_backlog",
        "expression": {
            "op": "max",
            "args": [
                0,
                {
                    "op": "subtract",
                    "args": [
                        {"ref": "order_backlog"},
                        {
                            "op": "multiply",
                            "args": [
                                {"ref": "backlog_delivery_fraction"},
                                {"ref": "order_backlog_opening"},
                            ],
                        },
                    ],
                },
            ],
        },
        "description": "Backlog drains by the scheduled delivery, floored at 0 (D2C lag-shaped depletion).",
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
    # D2C (2026-11-25): 76 -> 78 variables (order_backlog_opening +
    # downturn_brake, both fixed), 45 -> 46 formulas (the
    # backlog_delivery_fraction merge anchor, before the revenue
    # passthrough).
    # 2026-11-25 adjustment: 78 -> 79 variables (backlog_delivery_fast,
    # fixed 0.0; no new formula — the blend lives inside the
    # delivery-fraction formula).
    # A2 rebase (2026-11-26): 79 -> 82 variables, 46 -> 50 formulas
    # (audit-A2 +3/+4: template_revenue / accounts_receivable /
    # price_cut_factor variables + accounts_receivable /
    # accounts_receivable_next / cash / price_cut_factor drivers;
    # counts verified by AST on the merged template_spec.py —
    # 82 unique variable ids, 50 unique formula outputs).
    assert len(TEMPLATE_VARIABLES) == 82
    assert len(TEMPLATE_FORMULAS) == 50
    expected = {
        "order_backlog": ("fixed", 0.0),
        "order_backlog_opening": ("fixed", 0.0),
        "order_intake": ("fixed", 0.0),
        "order_intake_rate": ("triangular", (0.50, 1.00, 1.50)),
        "backlog_conversion": ("triangular", (0.30, 0.40, 0.60)),
        "order_decay": ("triangular", (0.10, 0.25, 0.40)),
        "downturn_brake": ("fixed", 0.0),
        "backlog_delivery_fast": ("fixed", 0.0),
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
    # D2C (2026-11-25): 76 -> 78 variables, 45 -> 46 formulas
    # (delivery-fraction anchor).
    # 2026-11-25 adjustment: 78 -> 79 variables
    # (backlog_delivery_fast; no new formula).
    # A2 rebase (2026-11-26): 79 -> 82 variables, 46 -> 50 formulas;
    # state fields 52 -> 54 (+ price_cut_factor / accounts_receivable).
    assert len(template.variables) == 82
    assert len(template.formulas) == 50
    # The template carries the backlog-update driver (finite-book
    # depletion) right after the revenue passthrough, and it is the
    # ONLY backlog-update driver in the template.
    assert [f for f in TEMPLATE_FORMULAS if f["output"] == "order_backlog"]
    assert [f["output"] for f in TEMPLATE_FORMULAS].index("order_backlog") == (
        [f["output"] for f in TEMPLATE_FORMULAS].index("revenue") + 1
    )
    # D2C: the template carries the delivery-fraction driver, exactly
    # once, BEFORE the revenue passthrough (both readers — the revenue
    # term and the backlog update — must see this tick's fraction).
    assert len([f for f in TEMPLATE_FORMULAS if f["output"] == "backlog_delivery_fraction"]) == 1
    assert [f["output"] for f in TEMPLATE_FORMULAS].index("backlog_delivery_fraction") < (
        [f["output"] for f in TEMPLATE_FORMULAS].index("revenue")
    )
    fields = {f.name: float(f.default) for f in domain_pack_registry.get("automotive").state_fields}
    assert len(fields) == 54  # D2C 52 + A2 2 (price_cut_factor / accounts_receivable); merged pack.py has 54 unique StateFieldSpec entries
    assert fields["order_backlog"] == 0.0
    assert fields["order_intake"] == 0.0
    assert fields["backlog_delivery_fraction"] == 0.0


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
    downturn_brake: float = 0.0,
    backlog_delivery_fast: float = 0.0,
) -> dict:
    """Full Desay case set: adoption + NEV chain + backlog (D2C
    lag-shaped drivers). Fixed values throughout, so the trajectory
    is deterministic. Defaults are the 2020 MODE values; the 2015
    shape test overrides them. Driver order is load-bearing: intake
    decays the flow BEFORE revenue reads this tick's delivery
    fraction, and the backlog updates after revenue (draining
    exactly what revenue converted). The opening book/flow are bound
    as variables at one year of intake (intake_rate * mode revenue);
    order_backlog_opening is bound at the same book value (the frozen
    tick-0 level the schedule delivers fractions of); downturn_brake
    is 0.0 unless the test binds it (the 2018 brake test binds
    -0.1501). See the module docstring for why the book is a
    variable, not an initial formula."""
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
        _fixed("order_backlog_opening", book0),
        _fixed("downturn_brake", downturn_brake),
        _fixed("backlog_delivery_fast", backlog_delivery_fast),
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
    revenue (B0 = 0.5 * R0). Under the D2C schedule the book delivers
    nothing in tick 1 (the SOP-lag floor), 15% in tick 2, 45% in tick
    3, 30% in tick 4 and the last 10% in tick 5, so the backlog term
    is 0 at tick 1, peaks at tick 3 and is gone by tick 6 — the total
    uplift converges instead of compounding forever. The intake flow
    still decays each tick (the driver runs) but is unread, so it
    cannot move revenue: the twin run with intake 0.0 must produce
    the identical revenue trajectory (locked by
    ``test_order_intake_is_inert_for_revenue``)."""
    variables = [
        _fixed("revenue", 6799.06),
        _fixed("revenue_growth", 0.10),
        _fixed("disruptor_adoption", 0.0),
        _fixed("order_backlog", 0.5 * 6799.06),
        _fixed("order_backlog_opening", 0.5 * 6799.06),
        _fixed("downturn_brake", 0.0),
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


#: D2C delivery schedule (ticks 1..5): fractions of the opening book
#: delivered per tick. Must match BACKLOG_DELIVERY_SCHEDULE in the
#: template spec.
_DELIVERY_SCHEDULE = (0.0, 0.15, 0.45, 0.30, 0.10)

#: Fast delivery schedule (2026-11-25 adjustment, Ho-approved): the
#: same uniform-lag discretization with ZERO widening — the D2U
#: variant tested in the desay-2018 diagnosis. Must match
#: BACKLOG_DELIVERY_SCHEDULE_FAST in the template spec. Selected
#: when the book's long-lag programs have already reached SOP at the
#: decision point (desay-2020 binds it via backlog_delivery_fast = 1).
_DELIVERY_SCHEDULE_FAST = (0.0, 0.20, 0.60, 0.20, 0.0)


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
    downturn_brake: float = 0.0,
    fast: bool = False,
    ticks: int = 5,
) -> tuple[dict[int, float], dict[int, float], dict[int, float], dict[int, float]]:
    """Independent replication of the D2C driver math (same
    equations, written separately): revenue / backlog / intake / the
    backlog term per tick, each rounded to 4dp like the engine.
    Per tick: the intake decays first (diagnostic only — it enters
    neither the term nor the book), then the delivery fraction is
    gated by backlog_conversion (1 on its calibrated support, 0 when
    frozen off), then the revenue term delivers this tick's fraction
    of the OPENING book (plus the tick-1 brake), then the book drains
    by exactly the delivered amount. Returns (revenue, backlog,
    intake, term) keyed by tick."""
    revenue = {0: revenue0}
    backlog = {0: backlog0}
    intake = {0: backlog0 if intake0 is None else intake0}
    term: dict[int, float] = {}
    gate = min(1.0, backlog_conversion / 0.30) if backlog_conversion else 0.0
    sched = _DELIVERY_SCHEDULE_FAST if fast else _DELIVERY_SCHEDULE
    for tick in range(1, ticks + 1):
        adoption = _logistic(disruptor_rate * (tick - disruptor_midpoint), disruptor_ceiling)
        pen = _logistic(nev_rate * (tick - nev_midpoint), nev_ceiling)
        intake[tick] = round(intake[tick - 1] * (1 - order_decay), 4)
        frac = gate * (sched[tick - 1] if tick <= len(sched) else 0.0)
        term[tick] = frac * backlog0 / revenue[tick - 1]
        brake = downturn_brake if tick == 1 else 0.0
        factor = 1 + revenue_growth + revenue_coupling * adoption + nev_coupling * pen + term[tick] + brake
        revenue[tick] = round(revenue[tick - 1] * factor, 4)
        backlog[tick] = round(max(0, backlog[tick - 1] - frac * backlog0), 4)
    return revenue, backlog, intake, term


# --- Unit validation 1: the finite book depletes, the uplift converges -


def test_order_book_finite_book_depletes_and_uplift_converges(monkeypatch, tmp_path: Path) -> None:
    """D2C unit validation 1: the book delivers nothing in tick 1
    (the SOP-lag floor — the signature of the lag-shaped schedule),
    15% in tick 2, 45% in tick 3, 30% in tick 4 and the last 10% in
    tick 5, so the book is 1.00 / 0.85 / 0.40 / 0.10 / 0.00 of its
    opening level after ticks 1–5 and the backlog term is 0 at tick 1,
    peaks at tick 3 and is gone by tick 6. The tick-1 factor is
    exactly the 1.10 base rate (no immediate conversion — the 2018
    defect is absent by construction), and the total uplift converges
    (the book is empty after tick 5, so later growth is base +
    couplings only). The old level-shift property is gone BY DESIGN
    (a finite book cannot produce a perpetual shift — that was the
    defect); what is pinned instead is finiteness: the schedule
    exhausts the book and the term peaks and dies."""
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        states = _trajectory(client, _create_run(client, _finite_book_case_set())["id"])
        assert sorted(states) == [0, 1, 2, 3, 4, 5]
        assert states[0]["order_backlog"] == pytest.approx(0.5 * 6799.06, rel=1e-6)
        assert states[0]["order_intake"] == pytest.approx(6799.06, rel=1e-6)
        revenue = {t: states[t]["revenue"] for t in states}
        backlog = {t: states[t]["order_backlog"] for t in states}
        intake = {t: states[t]["order_intake"] for t in states}
        # The book drains on the schedule, not geometrically.
        opening = 0.5 * 6799.06
        for tick, remaining in ((1, 1.00), (2, 0.85), (3, 0.40), (4, 0.10), (5, 0.00)):
            assert backlog[tick] == pytest.approx(opening * remaining, rel=1e-3), tick
            assert intake[tick] == pytest.approx(6799.06 * 0.75**tick, rel=1e-3), tick
        # The delivery fraction itself follows the schedule.
        for tick, frac in ((1, 0.0), (2, 0.15), (3, 0.45), (4, 0.30), (5, 0.10)):
            assert states[tick]["backlog_delivery_fraction"] == pytest.approx(frac, abs=1e-9), tick
        factors = [revenue[t] / revenue[t - 1] for t in (1, 2, 3, 4, 5)]
        # Tick 1 is exactly the base rate: nothing delivers in year 1.
        assert factors[0] == pytest.approx(1.10, rel=1e-3), factors
        # The term peaks at tick 3 (the schedule mode) and falls after.
        assert factors[2] > factors[3] > factors[4], factors
        assert factors[2] > factors[1] > factors[0], factors
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


# --- Fast schedule (2026-11-25 adjustment) ------------------------------


def test_delivery_schedules_sum_to_one_and_share_length() -> None:
    """Both schedules exhaust the book (sum 1) and share a length,
    so the blend in _delivery_fraction_expr is well-defined, and
    tick 1 is 0 under both (Ho's 1-2y floor)."""
    from planagent.simulation.domain_packs.automotive.template_spec import (
        BACKLOG_DELIVERY_SCHEDULE,
        BACKLOG_DELIVERY_SCHEDULE_FAST,
    )

    assert sum(BACKLOG_DELIVERY_SCHEDULE) == pytest.approx(1.0)
    assert sum(BACKLOG_DELIVERY_SCHEDULE_FAST) == pytest.approx(1.0)
    assert len(BACKLOG_DELIVERY_SCHEDULE) == len(BACKLOG_DELIVERY_SCHEDULE_FAST)
    assert BACKLOG_DELIVERY_SCHEDULE[0] == 0.0
    assert BACKLOG_DELIVERY_SCHEDULE_FAST[0] == 0.0


def test_fast_schedule_delivers_uniform_lag_profile(monkeypatch, tmp_path: Path) -> None:
    """2026-11-25 adjustment: with backlog_delivery_fast = 1 the
    delivery fraction follows the fast schedule [0, .20, .60, .20, 0]
    (the uniform-lag discretization with zero widening) — 80% of the
    book by tick 3 vs 60% on the default — and the book drains
    1.00 / 0.80 / 0.20 / 0.00. With flag 0 the fractions are the
    default schedule exactly (the blend is exact at the endpoints,
    not approximate). Tick 1 stays 0 under both profiles (Ho's 1-2y
    floor). Independent replication agrees tick by tick.
    """
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        fast = _trajectory(
            client,
            _create_run(
                client,
                _backlog_case_set(0.40, backlog_delivery_fast=1.0),
                tick_count=4,
                downside=None,
            )["id"],
        )
        default = _trajectory(
            client,
            _create_run(client, _backlog_case_set(0.40), tick_count=4, downside=None)["id"],
        )
        assert sorted(fast) == [0, 1, 2, 3, 4]
        # The fast delivery fraction follows the fast schedule.
        for tick, frac in ((1, 0.0), (2, 0.20), (3, 0.60), (4, 0.20)):
            assert fast[tick]["backlog_delivery_fraction"] == pytest.approx(frac, abs=1e-9), tick
        # The book drains on the fast schedule.
        for tick, remaining in ((1, 1.00), (2, 0.80), (3, 0.20), (4, 0.00)):
            assert fast[tick]["order_backlog"] == pytest.approx(6799.06 * remaining, rel=1e-3), tick
        # Flag 0 is the default schedule exactly.
        for tick, frac in ((1, 0.0), (2, 0.15), (3, 0.45), (4, 0.30)):
            assert default[tick]["backlog_delivery_fraction"] == pytest.approx(frac, abs=1e-9), tick
        # Fast delivers more by tick 3, so the tick-3 revenue is higher.
        assert fast[3]["revenue"] > default[3]["revenue"]
        # Independent replication agrees tick by tick (fast profile).
        exp_rev, exp_backlog, _, _ = _simulate_backlog(fast=True)
        for tick in (1, 2, 3, 4):
            assert fast[tick]["revenue"] == pytest.approx(exp_rev[tick], rel=2e-3), tick
            assert fast[tick]["order_backlog"] == pytest.approx(exp_backlog[tick], rel=2e-3), tick


# --- Shape: the depleting book makes growth FALL ------------------------


def test_order_book_decay_produces_falling_growth(monkeypatch, tmp_path: Path) -> None:
    """The shape property the monotone channels cannot express, at
    2020 MODE values (conversion 0.40, decay 0.25, intake rate 1.0):
    under the D2C schedule the backlog term is 0 at tick 1 (the
    SOP-lag floor — no immediate conversion), peaks at tick 3 (the
    schedule mode, 45% of the opening book) and falls after, and the
    book drains on the schedule (1.00 / 0.85 / 0.40 / 0.10 after
    ticks 1–4). Total growth therefore RISES to tick 3 and falls at
    tick 4 — the hump is the schedule's mode, not a failure: the
    step-1 "opening fall" pin is superseded by D2C, which moves the
    boost later (the 2018 diagnosis: the tick-1 overshoot was the
    defect, and the counterfactual validated this exact shape on the
    real 2018 case). What is pinned is the tick-1 zero, the t3 peak,
    the scheduled drain, the fall after the peak, and a tick-by-tick
    replication. Scored horizon is ticks 1–4 (the Desay child replay
    has ticks 0–4).

    Track C: explicitly opted out — the shape pin is exact (the
    schedule fractions + tick-by-tick replication), and the default
    shock breaks the monotonicity it exists to guard.
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
        # Tick-1 zero (the SOP-lag floor): no backlog boost in year 1.
        assert states[1]["backlog_delivery_fraction"] == pytest.approx(0.0, abs=1e-9)
        # The book drains on the schedule.
        for tick, remaining in ((1, 1.00), (2, 0.85), (3, 0.40), (4, 0.10)):
            assert backlog[tick] == pytest.approx(6799.06 * remaining, rel=1e-3), tick
        assert intake[1] == pytest.approx(6799.06 * 0.75, rel=1e-3)
        # The backlog term itself is 0 at tick 1, peaks at tick 3 and
        # falls after (term = fraction * opening / pre-tick revenue).
        terms = [
            states[t]["backlog_delivery_fraction"] * 6799.06 / revenue[t - 1]
            for t in (1, 2, 3, 4)
        ]
        assert terms[0] == pytest.approx(0.0, abs=1e-9), terms
        assert terms[2] > terms[1] > 0, terms
        assert terms[2] > terms[3] > 0, terms
        # Total growth rises to the schedule mode and falls after it.
        assert factors[0] < factors[1] < factors[2], factors
        assert factors[2] > factors[3], factors
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
    Under the D2C schedule the small book (0.25x revenue) also
    delivers nothing in tick 1, peaks at tick 3 and drains on the
    schedule (1.00 / 0.85 / 0.40 / 0.10); total growth rises to the
    schedule mode and falls after it. Modes only — no parameter was
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
        # Tick-1 zero (the SOP-lag floor) and the scheduled drain.
        assert states[1]["backlog_delivery_fraction"] == pytest.approx(0.0, abs=1e-9)
        for tick, remaining in ((1, 1.00), (2, 0.85), (3, 0.40), (4, 0.10)):
            assert backlog[tick] == pytest.approx(917.06 * remaining, rel=1e-3), tick
        terms = [
            states[t]["backlog_delivery_fraction"] * 917.06 / revenue[t - 1]
            for t in (1, 2, 3, 4)
        ]
        assert terms[0] == pytest.approx(0.0, abs=1e-9), terms
        assert terms[2] > terms[1] > 0, terms
        assert terms[2] > terms[3] > 0, terms
        # Total growth rises to the schedule mode and falls after it.
        assert factors[0] < factors[1] < factors[2], factors
        assert factors[2] > factors[3], factors
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
    backlog channel (same in both runs). With conversion 0 the gate
    is 0, so the delivery fraction is 0 at every tick and the book
    is FROZEN at its opening level (B' = B - 0 = B): nothing
    converts, nothing replenishes — the scheduled form with a zero
    gate makes the frozen book a fixed point, where the Track 11
    stock form accumulated it and the Track A pool form lapsed it
    with adoption.

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
        # D2C: at tick 1 the ON run equals the OFF run exactly — the
        # schedule delivers nothing in year 1, so there is no tick-1
        # boost to distinguish them. From tick 2 the ON run sits above.
        assert revenue_on[1] == pytest.approx(revenue_off[1], rel=1e-9)
        for tick in (1, 2, 3, 4, 5):
            assert revenue_off[tick] == pytest.approx(exp_rev[tick], rel=2e-3), tick
            if tick >= 2:
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
        # D2C: the delivery-fraction driver still runs (it is a
        # template driver), so the fraction follows the schedule —
        # but with a zero opening book it moves nothing.
        for tick, frac in ((1, 0.0), (2, 0.15), (3, 0.45), (4, 0.30), (5, 0.10)):
            assert states[tick]["backlog_delivery_fraction"] == pytest.approx(frac, abs=1e-9), tick


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

# --- D2C: the downturn brake hits tick 1 only ----------------------------


def test_downturn_brake_hits_tick_1_only(monkeypatch, tmp_path: Path) -> None:
    """D2C brake control: twin runs at 2020 mode values, one with
    downturn_brake = -0.1501 (the 2018 value: anchor-year -10.01%
    minus revenue_growth mode +5%), one with 0.0. The braked run's
    tick-1 growth factor is exactly 0.1501 lower; the brake term
    itself is tick-1 only, but the tick-2+ factors differ by exactly
    the backlog-term denominator effect (the smaller tick-1 base
    raises the later terms, which divide by pre-tick revenue); the
    book trajectory is identical (the brake does not touch the book).
    The replication agrees tick by tick.

    Track C: explicitly opted out (``downside: null``) — exact
    equality between two runs.
    """
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        unbraked = _backlog_case_set(0.40, downturn_brake=0.0)
        braked = _backlog_case_set(0.40, downturn_brake=-0.1501)
        states_off = _trajectory(
            client, _create_run(client, unbraked, tick_count=5, downside=None)["id"]
        )
        states_on = _trajectory(
            client, _create_run(client, braked, tick_count=5, downside=None)["id"]
        )
        rev_off = {t: states_off[t]["revenue"] for t in states_off}
        rev_on = {t: states_on[t]["revenue"] for t in states_on}
        f_off = [rev_off[t] / rev_off[t - 1] for t in (1, 2, 3, 4, 5)]
        f_on = [rev_on[t] / rev_on[t - 1] for t in (1, 2, 3, 4, 5)]
        assert f_off[0] - f_on[0] == pytest.approx(0.1501, abs=1e-6)
        # The brake term itself is tick-1 only, but the tick-2+ factors
        # are NOT identical: the backlog term divides by pre-tick
        # revenue, so the braked run's smaller tick-1 base mechanically
        # raises its later backlog terms (a denominator effect, not a
        # second brake). What is pinned is that the difference is
        # exactly that denominator effect — the replication below
        # encodes it — and that the book is untouched by the brake.
        for tick in (2, 3, 4, 5):
            term_off = states_off[tick]["backlog_delivery_fraction"] * 6799.06 / rev_off[tick - 1]
            term_on = states_on[tick]["backlog_delivery_fraction"] * 6799.06 / rev_on[tick - 1]
            assert f_on[tick - 1] - f_off[tick - 1] == pytest.approx(
                term_on - term_off, abs=1e-6
            ), tick
            assert states_on[tick]["order_backlog"] == pytest.approx(
                states_off[tick]["order_backlog"], rel=1e-9
            ), tick
        # The tick-1 shortfall persists (the braked level stays below),
        # though the denominator effect partly compensates it.
        for tick in (1, 2, 3, 4, 5):
            assert rev_on[tick] < rev_off[tick], tick
        assert rev_on[1] == pytest.approx(rev_off[1] * (f_on[0] / f_off[0]), rel=1e-9)
        exp_rev, exp_backlog, _, _ = _simulate_backlog(
            downturn_brake=-0.1501, ticks=5
        )
        for tick in (1, 2, 3, 4, 5):
            assert rev_on[tick] == pytest.approx(exp_rev[tick], rel=2e-3), tick
            assert states_on[tick]["order_backlog"] == pytest.approx(
                exp_backlog[tick], rel=2e-3
            ), tick


# --- D2C: the conversion gate zeroes the fraction when frozen off ------


def test_conversion_gate_zeroes_delivery_fraction(monkeypatch, tmp_path: Path) -> None:
    """D2C gate control: with backlog_conversion = 0 the delivery
    fraction is 0 at every tick (min(1, 0 / 0.30) = 0), so the book
    is frozen at its opening level and revenue is the pure NEV-chain
    path — the leg-freeze interface the frozen-baseline decomposition
    and the two-value opportunity module rely on. With conversion
    0.40 the gate is 1 on the whole calibrated support and the
    fraction follows the schedule.

    Track C: explicitly opted out (``downside: null``) — exact
    equality device.
    """
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        states_off = _trajectory(
            client,
            _create_run(client, _backlog_case_set(0.0), tick_count=5, downside=None)["id"],
        )
        states_on = _trajectory(
            client,
            _create_run(client, _backlog_case_set(0.40), tick_count=5, downside=None)["id"],
        )
        for tick in (1, 2, 3, 4, 5):
            assert states_off[tick]["backlog_delivery_fraction"] == pytest.approx(0.0, abs=1e-9), tick
            assert states_on[tick]["backlog_delivery_fraction"] == pytest.approx(
                _DELIVERY_SCHEDULE[tick - 1], abs=1e-9
            ), tick
        assert states_off[5]["order_backlog"] == pytest.approx(
            states_off[0]["order_backlog"], rel=1e-9
        )

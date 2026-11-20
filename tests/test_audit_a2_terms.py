"""Audit A2 (2026-11-20): annual-cut / payment-terms conduction.

The gap audit found `annual_cut_rate` and `payment_terms_months` were
sampled but read by NO formula, while `tier1_gross_margin` had a driver.
These tests pin the conduction the fix adds, with EXACT recomputation
from the seed-7 sampled values (the engine rounds every driver output
to 4 decimals, so the recomputation rounds identically at each step):

- cut -> price: `price_cut_factor` compounds monthly at (1 - cut/12)
  and drags the `price_index` target; the margin driver prices the cut
  directly, (cut/12) x (1 - margin), plus the (material - price) gap.
- terms -> cash: receivables re-derive as template_revenue x terms each
  tick (monthly ticks) and cash absorbs the change, so cash +
  receivables is conserved exactly every tick.

Draw neutrality: the two new template variables (`template_revenue`,
`accounts_receivable`) are FIXED, so they consume no RNG draw; the
seed-7 draws of the pre-existing sampled variables must equal the
values probed on e047f50 before the fix. TEMPLATE-level neutrality
alone is not enough: merge replaces a case variable IN PLACE at the
template position of the same id, so a draw-consuming template
variable whose id collides with a case variable pulls that variable
forward in the merged draw order (the first A2 run named the sales
base `revenue` and moved 7 Desay draws — see
`test_merged_draw_order_matches_e047f50`). The sales base is therefore
named `template_revenue`, which collides with no case id.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from planagent.config import reset_settings_cache
from planagent.db import reset_database_cache
from planagent.main import create_app
from planagent.services.completeness.registry import AUTOMOTIVE_DRIVER_REGISTRY
from planagent.services.distributions.sampler import rng_for_seed, sample_variable_set
from planagent.services.variables.models import VariableSet
from planagent.services.variables.presets import builtin_template
from planagent.services.variables.validator import merge_variable_sets
from planagent.simulation.domain_packs.automotive.pack import AutomotiveDomainPack
from planagent.simulation.domain_packs.automotive.template_spec import TEMPLATE_VARIABLES

# Seed-7 sampled values of the plain builtin automotive template
# (probe script /tmp/a2-probe-t1-mainline.py, same construction and
# seed 7 as these tests, run in the mainline worktree at f5a188f).
# SEED7_CUT / SEED7_TERMS still equal the values probed on e047f50;
# SEED7_MARGIN was re-based to f5a188f: mainline evolution between
# e047f50 and f5a188f added draw-consuming template variables
# (rd_adoption / adas / funnel triangulars), rotating the draw stream
# so the tier1 draw moved 0.1896 -> 0.2181. A2 itself does NOT move
# the order (its 3 new template variables are all FIXED, no draw) —
# the A2 worktree probes the identical 0.21805445346732885. If a
# template change moves the draw stream, these pins fail loudly
# instead of silently shifting every downstream number.
SEED7_CUT = 0.03549270741846863
SEED7_TERMS = 6.292533275151277
SEED7_MARGIN = 0.21805445346732885


def build_database_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def setup_app(monkeypatch, tmp_path: Path, db_name: str = "planagent-a2.db") -> None:
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


def automotive_payload(**overrides) -> dict:
    payload: dict = {
        "company_id": "auto-test-oem",
        "company_name": "Auto Test OEM",
        "market": "china-auto",
        "domain_id": "automotive",
        "actor_template": "tier1_supplier",
        "tick_count": 6,
        "seed": 7,
        "variable_template_id": "builtin:automotive",
    }
    payload.update(overrides)
    return payload


def _create_run(client: TestClient, **overrides) -> dict:
    created = client.post("/simulation/runs", json=automotive_payload(**overrides))
    assert created.status_code == 201, created.text
    return created.json()


def _fixed_override(variable_id: str, value: float) -> dict:
    return {
        "name": f"{variable_id}-override",
        "variables": [
            {
                "id": variable_id,
                "unit": "test",
                "distribution": {"type": "fixed", "value": value},
                "evidence_ref": "test-override",
            }
        ],
    }


def _fixed_overrides(**values: float) -> dict:
    """Multi-variable fixed override set: each variable is replaced
    in place at its template position, same merge as _fixed_override."""
    return {
        "name": "multi-override",
        "variables": [
            {
                "id": variable_id,
                "unit": "test",
                "distribution": {"type": "fixed", "value": value},
                "evidence_ref": "test-override",
            }
            for variable_id, value in values.items()
        ],
    }


def _trajectory(client: TestClient, run_id: str) -> list[dict]:
    resp = client.get(f"/runs/{run_id}/automotive/trajectory")
    assert resp.status_code == 200, resp.text
    return resp.json()["points"]


def _sampled(client: TestClient, run_id: str) -> dict:
    resp = client.get(f"/runs/{run_id}/determinism")
    assert resp.status_code == 200, resp.text
    return resp.json().get("sampled_values", {})


def _states(points: list[dict]) -> list[dict]:
    assert [p["tick"] for p in points] == [0, 1, 2, 3, 4, 5, 6]
    return [p["state"] for p in points]


def test_cut_factor_compounds_monthly_and_drags_price_and_margin(
    monkeypatch, tmp_path: Path
) -> None:
    """At seed 7 the cut compounds to ~(1 - cut/12)^6 and price/margin
    follow the driver arithmetic exactly (recomputed tick by tick)."""
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        sampled = _sampled(client, run["id"])
        # Draw neutrality: the fix must not move any pre-existing draw.
        assert sampled["annual_cut_rate"] == SEED7_CUT
        assert sampled["payment_terms_months"] == SEED7_TERMS
        assert sampled["tier1_gross_margin"] == SEED7_MARGIN
        cut = sampled["annual_cut_rate"]
        states = _states(_trajectory(client, run["id"]))
        # Recompute the driver chain with the engine's per-tick rounding.
        # Material is fixed 1.0 here, so the price target is the factor
        # itself and the margin gap is (1 - price).
        factor, price, margin = 1.0, 1.0, sampled["tier1_gross_margin"]
        expected = [(factor, price, margin)]
        for _ in range(6):
            factor = round(factor * (1 - cut / 12), 4)
            price = round(price + 0.5 * (factor - price), 4)
            margin = round(
                margin - ((cut / 12) * (1 - margin) + 0.02 * (1 - price)), 4
            )
            expected.append((factor, price, margin))
        for tick, (exp_factor, exp_price, exp_margin) in enumerate(expected):
            state = states[tick]
            assert state["price_cut_factor"] == exp_factor, tick
            assert state["price_index"] == exp_price, tick
            assert state["tier1_gross_margin"] == exp_margin, tick
        # Direction: the cut is a real drag, not a no-op. (The compounded
        # factor differs from the unrounded power by <0.001 because the
        # engine rounds every tick; the exact path is pinned above.)
        assert states[6]["price_cut_factor"] < 1.0
        assert abs(states[6]["price_cut_factor"] - (1 - cut / 12) ** 6) < 0.001
        assert states[6]["price_index"] < 1.0
        assert states[6]["tier1_gross_margin"] < SEED7_MARGIN


def test_payment_terms_move_receivables_and_cash_with_conservation(
    monkeypatch, tmp_path: Path
) -> None:
    """Terms set the receivables stock; cash absorbs the change, so
    cash + receivables is conserved every tick. Two shocks isolate
    each leg: longer terms at fixed revenue, and higher revenue at
    sampled terms."""
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        base = _create_run(client)
        sampled = _sampled(client, base["id"])
        terms = sampled["payment_terms_months"]
        base_states = _states(_trajectory(client, base["id"]))
        # Base: revenue stays 100 (fixed), so receivables jump once on
        # tick 1 (opening 600 trued up to sampled terms) and then sit
        # flat; cash takes the one-time step and then sits flat.
        assert base_states[6]["accounts_receivable"] == round(100 * terms, 4)
        assert base_states[6]["cash"] == round(100 - (round(100 * terms, 4) - 600.0), 4)
        assert base_states[6]["cash"] == base_states[1]["cash"]
        for state in base_states:
            assert abs((state["cash"] + state["accounts_receivable"]) - 700.0) < 0.001

        # Terms shock: 9 months at revenue 100 -> AR 900, cash -200.
        shocked = _create_run(
            client, variable_set=_fixed_override("payment_terms_months", 9.0)
        )
        sh_states = _states(_trajectory(client, shocked["id"]))
        assert sh_states[6]["accounts_receivable"] == 900.0
        assert sh_states[6]["cash"] == -200.0
        assert sh_states[6]["cash"] < base_states[6]["cash"]
        assert sh_states[6]["accounts_receivable"] > base_states[6]["accounts_receivable"]
        for state in sh_states:
            assert abs((state["cash"] + state["accounts_receivable"]) - 700.0) < 0.001

        # Revenue shock: template_revenue 200 at sampled terms -> AR doubles,
        # cash falls by 100 x terms on tick 1.
        rev = _create_run(client, variable_set=_fixed_override("template_revenue", 200.0))
        rev_states = _states(_trajectory(client, rev["id"]))
        assert rev_states[6]["accounts_receivable"] == round(200 * terms, 4)
        assert rev_states[6]["cash"] == round(100 - (round(200 * terms, 4) - 600.0), 4)
        assert rev_states[6]["cash"] < base_states[6]["cash"]
        for state in rev_states:
            assert abs((state["cash"] + state["accounts_receivable"]) - 700.0) < 0.001


def test_stressed_cut_drags_price_and_margin_below_base(monkeypatch, tmp_path: Path) -> None:
    """The stressed 10%+ regime (C4 scenario lever) drags price and
    margin below the base run at the same seed.

    The comparison is only valid from the SAME starting margin:
    pinning `annual_cut_rate` to fixed removes its draw, which
    rotates the downstream draw stream — at seed 7 the tier1 draw
    moves 0.2181 -> 0.2546, so a naive stressed-vs-base comparison
    compares two different starting margins (and the stressed run's
    higher start outweighs the stronger cut drag: 0.2138 vs 0.2031).
    The stressed run therefore also pins `tier1_gross_margin` to the
    base run's own sampled value, so the ONLY difference between the
    runs is the cut.
    """
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        base = _create_run(client)
        base_sampled = _sampled(client, base["id"])
        base_states = _states(_trajectory(client, base["id"]))
        stressed = _create_run(
            client,
            variable_set=_fixed_overrides(
                annual_cut_rate=0.10,
                tier1_gross_margin=base_sampled["tier1_gross_margin"],
            ),
        )
        st_sampled = _sampled(client, stressed["id"])
        # Same starting margin in both runs: the comparison below
        # isolates the cut effect.
        assert st_sampled["tier1_gross_margin"] == base_sampled["tier1_gross_margin"]
        st_states = _states(_trajectory(client, stressed["id"]))
        assert abs(st_states[6]["price_cut_factor"] - (1 - 0.10 / 12) ** 6) < 0.001
        assert st_states[6]["price_index"] < base_states[6]["price_index"]
        assert st_states[6]["tier1_gross_margin"] < base_states[6]["tier1_gross_margin"]
        assert st_states[6]["price_cut_factor"] < base_states[6]["price_cut_factor"]


def test_registry_tier1_economics_links_the_conduction() -> None:
    """The completeness registry must list the conduction outputs, not
    just the margin — the audit's B2 point was that 'present' is not
    'conducted'."""
    entry = next(e for e in AUTOMOTIVE_DRIVER_REGISTRY if e.id == "tier1_economics")
    assert set(entry.link_outputs) == {
        "price_cut_factor",
        "price_index",
        "tier1_gross_margin",
        "accounts_receivable",
        "cash",
    }
    pack = AutomotiveDomainPack()
    formula_outputs = {f["output"] for f in pack.template_formulas()}
    assert set(entry.link_outputs) <= formula_outputs
    assert {"price_index", "accounts_receivable", "cash"} <= set(entry.drives)


def test_new_level_variables_are_fixed_and_bind_state_fields() -> None:
    """`template_revenue` / `accounts_receivable` / `price_cut_factor` are
    fixed generic levels (no RNG draw) that bind the pack state fields,
    so the drivers can read them; the sampled values stay the
    Ho-authorized SIMULATED terms. `price_cut_factor` is the seed the
    price-cut tick driver evolves from (1.0 = no cut yet); without it
    as a variable, the `price_index` driver's reference to it is
    unknown in any evaluation scope built from sampled variables
    (hub A2 full suite: test_calibration_transmission failed on it)."""
    by_id = {raw["id"]: raw for raw in TEMPLATE_VARIABLES}
    # 82 = 79 on the f5a188f mainline template + A2's 3 fixed variables
    # (template_revenue / accounts_receivable / price_cut_factor);
    # the e047f50-era pin of 64 was superseded by mainline evolution.
    assert len(TEMPLATE_VARIABLES) == 82
    assert by_id["template_revenue"]["distribution"] == {"type": "fixed", "value": 100.0}
    assert by_id["accounts_receivable"]["distribution"] == {"type": "fixed", "value": 600.0}
    assert by_id["price_cut_factor"]["distribution"] == {"type": "fixed", "value": 1.0}
    # The commercial-terms values themselves are untouched.
    assert by_id["annual_cut_rate"]["distribution"] == {
        "type": "triangular",
        "min": 0.03,
        "mode": 0.04,
        "max": 0.05,
    }
    assert by_id["payment_terms_months"]["distribution"] == {
        "type": "triangular",
        "min": 2.0,
        "mode": 6.0,
        "max": 9.0,
    }
    for var_id in ("annual_cut_rate", "payment_terms_months"):
        assert by_id[var_id]["evidence_ref"].startswith("simulated:industry-average"), var_id
    # tier1_gross_margin's evidence was re-based by mainline (2026-11-20
    # hindsight-leak fix) from simulated industry-average to the Desay
    # calibration moments; its distribution is unchanged.
    assert by_id["tier1_gross_margin"]["evidence_ref"].startswith(
        "desay-evidence:calibration-simulated-generation-2026-11-20"
    )


# --- Merged draw order (regression: the first A2 run broke this) --------

# The Desay-2015 case's FULL variable list (28 vars), distributions
# verbatim from the A2 backtest harness
# (track-a2/run_desay_a2.py). Only id + distribution affect sampling;
# evidence refs are short placeholders (the validator requires one).
# The list must be COMPLETE: the 16 non-base variables overlap
# template ids and are replaced in place with the CASE distributions —
# sampling the 12 base variables alone reproduces NEITHER the live
# draws (the template versions of those 16 consume a different number
# of RNG draws) nor the bug.
_DESAY_2015_A2_VARS = [
    {"id": "market_share", "unit": "share",
     "distribution": {"type": "triangular", "min": 0.25, "mode": 0.3, "max": 0.35},
     "scope_tags": ["smart"]},
    {"id": "base_growth", "unit": "per-year",
     "distribution": {"type": "triangular", "min": -0.02, "mode": 0.02, "max": 0.05},
     "scope_tags": ["traditional"]},
    {"id": "disruptor_ceiling", "unit": "share",
     "distribution": {"type": "triangular", "min": 0.7, "mode": 0.85, "max": 0.95},
     "scope_tags": ["smart"]},
    {"id": "disruptor_rate", "unit": "per-year",
     "distribution": {"type": "triangular", "min": 0.6, "mode": 0.8, "max": 1.0},
     "scope_tags": ["smart"]},
    {"id": "disruptor_midpoint", "unit": "years",
     "distribution": {"type": "triangular", "min": 3.0, "mode": 4.0, "max": 5.0},
     "scope_tags": ["smart"]},
    {"id": "share_coupling", "unit": "per-unit-adoption",
     "distribution": {"type": "triangular", "min": 0.15, "mode": 0.25, "max": 0.35},
     "scope_tags": ["smart"]},
    {"id": "revenue", "unit": "RMB m",
     "distribution": {"type": "triangular", "min": 3200, "mode": 3668.25, "max": 4100},
     "scope_tags": ["traditional"]},
    {"id": "revenue_growth", "unit": "per-year",
     "distribution": {"type": "triangular", "min": 0.0, "mode": 0.1, "max": 0.25},
     "scope_tags": ["traditional"]},
    {"id": "revenue_coupling", "unit": "per-unit-adoption",
     "distribution": {"type": "triangular", "min": 0.1, "mode": 0.15, "max": 0.25},
     "scope_tags": ["smart"]},
    {"id": "profit", "unit": "RMB m",
     "distribution": {"type": "triangular", "min": 300, "mode": 358.87, "max": 420},
     "scope_tags": ["traditional"]},
    {"id": "profit_growth", "unit": "per-year",
     "distribution": {"type": "triangular", "min": 0.0, "mode": 0.08, "max": 0.2},
     "scope_tags": ["traditional"]},
    {"id": "profit_coupling", "unit": "per-unit-adoption",
     "distribution": {"type": "triangular", "min": 0.05, "mode": 0.1, "max": 0.2},
     "scope_tags": ["smart"]},
    {"id": "production_volume", "unit": "10k units",
     "distribution": {"type": "triangular", "min": 2309.76, "mode": 2459.76, "max": 2609.76},
     "scope_tags": ["traditional"]},
    {"id": "sales_volume_retail", "unit": "10k units",
     "distribution": {"type": "fixed", "value": 1691.4},
     "scope_tags": ["traditional"]},
    {"id": "sales_volume_wholesale", "unit": "10k units",
     "distribution": {"type": "fixed", "value": 1691.4},
     "scope_tags": ["traditional"]},
    {"id": "dealer_inventory_coef", "unit": "x",
     "distribution": {"type": "fixed", "value": 1.2},
     "scope_tags": ["traditional"]},
    {"id": "nev_penetration", "unit": "share",
     "distribution": {"type": "triangular", "min": 0.01, "mode": 0.0135, "max": 0.018},
     "scope_tags": ["smart"]},
    {"id": "nev_ceiling", "unit": "share",
     "distribution": {"type": "triangular", "min": 0.2, "mode": 0.3, "max": 0.5},
     "scope_tags": ["smart"]},
    {"id": "nev_rate", "unit": "per-year",
     "distribution": {"type": "triangular", "min": 0.4, "mode": 0.5, "max": 0.7},
     "scope_tags": ["smart"]},
    {"id": "nev_midpoint", "unit": "years",
     "distribution": {"type": "triangular", "min": 4.0, "mode": 5.0, "max": 6.0},
     "scope_tags": ["smart"]},
    {"id": "order_backlog", "unit": "RMB m",
     "distribution": {"type": "fixed", "value": 917.06},
     "scope_tags": ["traditional"]},
    {"id": "order_intake", "unit": "RMB m",
     "distribution": {"type": "fixed", "value": 917.06},
     "scope_tags": ["traditional"]},
    {"id": "order_intake_rate", "unit": "per-year",
     "distribution": {"type": "triangular", "min": 0.15, "mode": 0.25, "max": 0.4},
     "scope_tags": ["traditional"]},
    {"id": "backlog_conversion", "unit": "per-year",
     "distribution": {"type": "triangular", "min": 0.3, "mode": 0.4, "max": 0.6},
     "scope_tags": ["traditional"]},
    {"id": "order_decay", "unit": "per-year",
     "distribution": {"type": "triangular", "min": 0.1, "mode": 0.25, "max": 0.4},
     "scope_tags": ["traditional"]},
    {"id": "annual_cut_rate", "unit": "per-year",
     "distribution": {"type": "triangular", "min": 0.03, "mode": 0.04, "max": 0.05},
     "scope_tags": ["traditional"]},
    {"id": "payment_terms_months", "unit": "months",
     "distribution": {"type": "triangular", "min": 2.0, "mode": 6.0, "max": 9.0},
     "scope_tags": ["traditional"]},
    {"id": "accounts_receivable", "unit": "RMB m",
     "distribution": {"type": "fixed", "value": 1834.12},
     "scope_tags": ["traditional"]},
]
for _v in _DESAY_2015_A2_VARS:
    _v["evidence_ref"] = "estimate: test pin (distribution verbatim from the Desay-2015 A2 harness)"

# Seed-7 sampled values of the merged (builtin automotive template +
# Desay-2015 base variables) set, re-based to the f5a188f BASELINE
# (probe script /tmp/a2-probe-base.py, builtin template, same case
# construction and seed 7 as this test, run in the mainline worktree
# at f5a188f). The e047f50 pins were superseded by mainline evolution
# between e047f50 and f5a188f — the template gained several
# draw-consuming variables (rd_adoption / adas / funnel triangulars),
# which rotated the draw stream; A2 itself does NOT move the order
# (its 3 new template variables — template_revenue,
# price_cut_factor, accounts_receivable — are all FIXED, no draw).
# What this test protects is that the A2-merged template reproduces
# the f5a188f baseline values exactly. If a template change moves the
# merged draw order, these pins fail instead of silently re-basing
# every backtest number.
_F5A188F_SEED7 = {
    "revenue": 3696.7882486771286,
    "market_share": 0.28805320527443623,
    "base_growth": 9.761760509998871e-05,
    "disruptor_ceiling": 0.7664620863947169,
    "disruptor_rate": 0.7570940671322591,
    "disruptor_midpoint": 4.3935782970902695,
    "share_coupling": 0.21012094143040966,
    "revenue_growth": 0.1336352935153098,
}


def test_merged_draw_order_matches_e047f50() -> None:
    """Merging the builtin automotive template with a case that binds
    `revenue` (draw-consuming) must NOT move any pre-existing draw.

    Regression: the first A2 version named the template sales-base
    variable `revenue`. Merge replaces a case variable IN PLACE at the
    template position of the same id, so the case's `revenue` was
    pulled forward from its case-list position to template position
    61, rotating the draw order of the seven draw-consuming case
    variables ahead of it (revenue/market_share/base_growth/
    disruptor_*/share_coupling all resampled; the live Desay re-run
    was confounded and had to be discarded). Renaming the proxy to
    `template_revenue` restores the f5a188f merged order exactly:
    the three appended template variables are FIXED (no draw), so the
    case block draws in the same order as on f5a188f — verified by
    the _F5A188F_SEED7 pins above, probed on the f5a188f baseline
    itself (the e047f50 pins were superseded by mainline evolution,
    not by A2). Sampling uses formulas=[]: formulas never affect
    sampling, and this isolates the draw order.
    """
    template = builtin_template("automotive")
    base_set = VariableSet(
        name=template.name,
        variables=template.variables,
        formulas=[],
        internal=template.internal,
        assumption_data=template.assumption_data,
    )
    case_set = VariableSet(
        name="desay-2015-base",
        variables=_DESAY_2015_A2_VARS,
        formulas=[],
        internal={},
    )
    merged = merge_variable_sets(base_set, case_set)
    # The case's `revenue` must still sit in the appended case block
    # (after the template variables), never at a template position.
    ids = [v.id for v in merged.variables]
    assert ids.index("revenue") > ids.index("market_share")
    assert "template_revenue" in ids
    sampled = sample_variable_set(merged, rng_for_seed(7), {})
    for var_id, expected in _F5A188F_SEED7.items():
        assert sampled[var_id] == expected, var_id

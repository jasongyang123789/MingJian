"""Track 4 — B2B funnel conversion + satisfaction feedback as one-click
features (automotive domain pack).

The 8-stage Tier-1 chain (customer development -> lead funnel -> RFQ /
contract -> demand management -> product matching -> project management
-> manufacturing follow-up -> delivery satisfaction) is modeled, not
overridden by hand: attaching the built-in automotive template is the
one click. Conversion rates are tick-driver outputs from sampled base
rates; pipeline stocks flow into each other with per-stage attrition
(a lossless funnel would drift the overall conversion to 1.0); the
delivery-satisfaction score feeds BACK into next tick's lead-to-RFQ
rate, RFQ win rate, and prospect inflow with a one-tick lag (the RFQ
drivers run before the satisfaction driver in the tick-driver order).

Covers: driver math at fixed scope (feedback direction, clamps,
stock conservation with attrition, the overall-conversion identity),
the two funnel rules, and end-to-end API runs (funnel trajectory,
satisfaction feedback loop via initial_state overrides, determinism,
and the evidence-triggered complaint / RFQ rules).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from planagent.config import reset_settings_cache
from planagent.db import reset_database_cache
from planagent.main import create_app
from planagent.services.variables import evaluate_tick_drivers
from planagent.services.variables.presets import builtin_template
from planagent.simulation.domain_packs import registry as domain_pack_registry
from planagent.simulation.rules import RuleRegistry

FUNNEL_FIELDS = (
    "funnel_prospects",
    "funnel_leads",
    "funnel_rfqs",
    "funnel_contracts",
    "funnel_projects",
    "funnel_deliveries_total",
    "funnel_prospects_total",
    "funnel_prospect_to_lead_rate",
    "funnel_lead_to_rfq_rate",
    "funnel_rfq_win_rate",
    "funnel_contract_to_project_rate",
    "funnel_project_to_delivery_rate",
    "funnel_overall_conversion",
    "delivery_satisfaction",
)

# Fixed scope for driver-math unit tests: bases at their template modes,
# gain 1.0, attrition at template defaults, chip supply normal.
_FIXED_SCOPE: dict[str, float] = {
    "prospect_inflow_monthly": 4.0,
    "funnel_prospect_to_lead_base": 0.25,
    "funnel_lead_to_rfq_base": 0.30,
    "funnel_rfq_win_base": 0.25,
    "funnel_contract_to_project_base": 0.90,
    "funnel_project_to_delivery_base": 0.92,
    "satisfaction_feedback_gain": 1.0,
    "funnel_prospect_attrition": 0.10,
    "funnel_lead_attrition": 0.10,
    "funnel_rfq_attrition": 0.05,
    "funnel_contract_attrition": 0.05,
    "funnel_project_attrition": 0.02,
    "chip_supply_index": 1.0,
}


def _funnel_drivers() -> list:
    template = builtin_template("automotive")
    return [
        formula
        for formula in template.formulas
        if formula.tick_driver and formula.output.startswith(("funnel", "delivery"))
    ]


def _default_state() -> dict[str, float]:
    pack = domain_pack_registry.get("automotive")
    return {field.name: float(field.default) for field in pack.state_fields}


def _run_drivers(scope: dict[str, float], state: dict[str, float], tick: int) -> dict[str, float]:
    updates = evaluate_tick_drivers(_funnel_drivers(), scope, state, tick)
    next_state = dict(state)
    next_state.update({key: value for key, value in updates.items() if key in next_state})
    return next_state


# ---------------------------------------------------------------- unit ---


def test_funnel_rates_follow_satisfaction_with_one_tick_lag() -> None:
    """The feedback loop: last tick's satisfaction scales the RFQ rates
    and the prospect inflow; the direction and magnitude are exact.
    (Satisfaction travels in the STATE — the driver scope lets the
    current state win over sampled values, exactly as in the engine.)"""

    low_state = _default_state()
    low_state["delivery_satisfaction"] = 0.4
    low = _run_drivers(_FIXED_SCOPE, low_state, tick=1)
    high_state = _default_state()
    high_state["delivery_satisfaction"] = 0.9
    high = _run_drivers(_FIXED_SCOPE, high_state, tick=1)
    # Factor is (1 + 1.0 x (satisfaction - 0.75)): 0.65 low, 1.15 high.
    assert low["funnel_lead_to_rfq_rate"] == pytest.approx(0.30 * 0.65)
    assert high["funnel_lead_to_rfq_rate"] == pytest.approx(0.30 * 1.15)
    assert low["funnel_rfq_win_rate"] == pytest.approx(0.25 * 0.65)
    assert high["funnel_rfq_win_rate"] == pytest.approx(0.25 * 1.15)
    # Prospect inflow (referral channel) moves the same way: 4 x 0.65 /
    # 4 x 1.15 new prospects, visible in the cumulative total.
    assert low["funnel_prospects_total"] == pytest.approx(120.0 + 4.0 * 0.65)
    assert high["funnel_prospects_total"] == pytest.approx(120.0 + 4.0 * 1.15)
    # Top-of-funnel rate has no satisfaction link.
    assert low["funnel_prospect_to_lead_rate"] == high["funnel_prospect_to_lead_rate"] == 0.25


def test_funnel_rates_are_clamped() -> None:
    """Rates never leave [0, 0.95] (project-to-delivery: [0, 0.99])
    even at extreme satisfaction / base values."""

    extreme_state = _default_state()
    extreme_state["delivery_satisfaction"] = 1.0
    extreme = _run_drivers(
        {
            **_FIXED_SCOPE,
            "funnel_lead_to_rfq_base": 0.9,
            "funnel_rfq_win_base": 0.9,
        },
        extreme_state,
        tick=1,
    )
    assert extreme["funnel_lead_to_rfq_rate"] == pytest.approx(0.95)
    assert extreme["funnel_rfq_win_rate"] == pytest.approx(0.95)
    zero_state = _default_state()
    zero_state["delivery_satisfaction"] = 0.0
    zero_sat = _run_drivers(_FIXED_SCOPE, zero_state, tick=1)
    assert zero_sat["funnel_lead_to_rfq_rate"] == pytest.approx(0.30 * 0.25)
    assert zero_sat["funnel_rfq_win_rate"] == pytest.approx(0.25 * 0.25)
    assert zero_sat["funnel_prospects_total"] == pytest.approx(120.0 + 4.0 * 0.25)


def test_funnel_stock_conservation_with_attrition() -> None:
    """One tick from the pack defaults, at mode bases and neutral
    satisfaction (0.75, so the feedback factor is exactly 1.0): every
    stock is hand-computable, which pins the flow + attrition math."""

    state = _run_drivers(_FIXED_SCOPE, _default_state(), 1)
    # Flows: new leads 40x0.25=10, new RFQs 12x0.30=3.6, new contracts
    # 4x0.25=1, new projects 2x0.90=1.8, deliveries 6x0.92=5.52.
    # Stocks: previous + inflow - outflow - attrition.
    assert state["funnel_prospects"] == pytest.approx(40 + 4 - 10 - 40 * 0.10)
    assert state["funnel_leads"] == pytest.approx(12 + 10 - 3.6 - 12 * 0.10)
    assert state["funnel_rfqs"] == pytest.approx(4 + 3.6 - 1 - 4 * 0.05)
    assert state["funnel_contracts"] == pytest.approx(2 + 1 - 1.8 - 2 * 0.05)
    assert state["funnel_projects"] == pytest.approx(6 + 1.8 - 5.52 - 6 * 0.02)
    assert state["funnel_deliveries_total"] == pytest.approx(12 + 5.52)
    assert state["funnel_prospects_total"] == pytest.approx(120 + 4)
    # Overall conversion is the identity deliveries/prospects (driver
    # outputs are rounded to 4 decimals, hence the tolerance).
    assert state["funnel_overall_conversion"] == pytest.approx((12 + 5.52) / (120 + 4), abs=1e-4)
    # Satisfaction moves 20% toward its delivery target 0.4+0.6x0.92.
    assert state["delivery_satisfaction"] == pytest.approx(0.75 + 0.2 * (0.952 - 0.75))


def test_funnel_long_horizon_stocks_stabilize_and_overall_stays_bounded() -> None:
    """Attrition is what makes the funnel a funnel: over 36 ticks the
    stocks settle to a positive steady state instead of draining or
    exploding, and the overall conversion stays below 1 (it converges
    toward the product of the stage yields, ~0.41, from below)."""

    state = _default_state()
    for tick in range(1, 37):
        # Satisfaction travels in the state (the driver scope lets the
        # current state win), so no scope update is needed per tick.
        state = _run_drivers(_FIXED_SCOPE, state, tick)
        assert all(state[field] >= 0 for field in FUNNEL_FIELDS)
        assert 0 <= state["delivery_satisfaction"] <= 1
        assert 0 <= state["funnel_overall_conversion"] < 1
    # Stocks neither collapse to zero nor run away.
    assert 5 < state["funnel_prospects"] < 25
    assert 3 < state["funnel_leads"] < 20
    assert 3 < state["funnel_rfqs"] < 25
    assert 0.5 < state["funnel_contracts"] < 10
    assert 0.5 < state["funnel_projects"] < 10
    # Cumulative totals are monotonic; the overall ratio is the identity.
    assert state["funnel_deliveries_total"] > 12
    assert state["funnel_prospects_total"] > 120
    assert state["funnel_overall_conversion"] == pytest.approx(
        state["funnel_deliveries_total"] / state["funnel_prospects_total"], abs=1e-4
    )


def test_funnel_rules_shape() -> None:
    rules_root = Path(__file__).resolve().parent.parent / "rules"
    rules = RuleRegistry(rules_root).get_rules("automotive")
    by_id = {rule.rule_id: rule for rule in rules}
    slip = by_id["auto.delivery_satisfaction_slip"]
    assert slip.action_id == "improve_delivery_quality"
    assert [effect.target for effect in slip.effects] == ["delivery_satisfaction"]
    assert slip.effects[0].value == -0.05
    assert "late delivery" in slip.trigger_keywords
    momentum = by_id["auto.rfq_momentum"]
    assert momentum.action_id == "accelerate_rfq_response"
    assert [effect.target for effect in momentum.effects] == ["funnel_rfqs"]
    assert momentum.effects[0].value == 1.0
    assert "new RFQ" in momentum.trigger_keywords


# ------------------------------------------------------------------ API ---


def build_database_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def setup_app(monkeypatch, tmp_path: Path, db_name: str = "planagent-funnel.db") -> None:
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
        "company_id": "funnel-test-oem",
        "company_name": "Funnel Test OEM",
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


def _snapshots(client: TestClient, run_id: str) -> list[dict]:
    package = client.get(f"/runs/{run_id}/replay-package")
    assert package.status_code == 200, package.text
    return package.json()["package"]["snapshots"]


def _accept_claim(client: TestClient, content_text: str) -> None:
    ingested = client.post(
        "/ingest/runs",
        json={
            "requested_by": "funnel-test",
            "items": [
                {
                    "source_type": "research",
                    "source_url": "https://example.com/funnel-evidence",
                    "title": "Funnel evidence",
                    "content_text": content_text,
                    "published_at": "2026-01-05T08:00:00Z",
                }
            ],
        },
    )
    assert ingested.status_code == 201, ingested.text
    items = client.get("/review/items")
    assert items.status_code == 200
    assert len(items.json()) == 1
    accepted = client.post(
        f"/review/items/{items.json()[0]['id']}/accept",
        json={"reviewer_id": "funnel-test"},
    )
    assert accepted.status_code == 200, accepted.text


def test_funnel_runs_end_to_end_with_builtin_template(monkeypatch, tmp_path: Path) -> None:
    """One click: an automotive run with the built-in template computes
    the whole funnel — rates, stocks, satisfaction, overall conversion
    — with no manual variable overrides."""

    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        assert run["status"] == "COMPLETED"
        snapshots = _snapshots(client, run["id"])
        assert len(snapshots) == 7
        tick_zero = snapshots[0]["state"]
        for field in FUNNEL_FIELDS:
            assert field in tick_zero
        assert tick_zero["funnel_prospects"] == 40.0
        assert tick_zero["funnel_deliveries_total"] == 12.0
        assert tick_zero["delivery_satisfaction"] == 0.75
        deliveries = [s["state"]["funnel_deliveries_total"] for s in snapshots]
        prospects_total = [s["state"]["funnel_prospects_total"] for s in snapshots]
        assert deliveries == sorted(deliveries)  # cumulative, monotonic
        assert prospects_total == sorted(prospects_total)
        assert prospects_total[-1] > prospects_total[0]
        for snapshot in snapshots[1:]:
            state = snapshot["state"]
            for rate in (
                "funnel_prospect_to_lead_rate",
                "funnel_lead_to_rfq_rate",
                "funnel_rfq_win_rate",
                "funnel_contract_to_project_rate",
                "funnel_project_to_delivery_rate",
                "funnel_overall_conversion",
            ):
                assert 0 <= state[rate] <= 1, (rate, state[rate])
            assert 0 <= state["delivery_satisfaction"] <= 1
            for stock in (
                "funnel_prospects",
                "funnel_leads",
                "funnel_rfqs",
                "funnel_contracts",
                "funnel_projects",
            ):
                assert state[stock] >= 0, (stock, state[stock])
            # The overall conversion is the identity, every tick.
            assert state["funnel_overall_conversion"] == pytest.approx(
                state["funnel_deliveries_total"] / state["funnel_prospects_total"], abs=1e-4
            )
        # The funnel actually flows: RFQs and deliveries move off tick 0.
        assert snapshots[1]["state"]["funnel_rfqs"] != tick_zero["funnel_rfqs"]
        assert snapshots[-1]["state"]["funnel_deliveries_total"] > 12.0


def test_satisfaction_feedback_loop_end_to_end(monkeypatch, tmp_path: Path) -> None:
    """Same seed, two runs differing only in starting satisfaction
    (0.4 vs 0.9 via initial_state): the low-satisfaction run gets
    lower RFQ rates from tick 1, fewer RFQs at tick 3 (where the
    gap peaks), and fewer deliveries / prospects by tick 6.
    That is the satisfaction -> next-RFQ loop, observed end to end.
    The RFQ-stock gap is asserted at tick 3, not tick 6: satisfaction
    mean-reverts toward ~0.95, so the gap decays after tick 3 and the
    tick-6 stock gap is marginal (it flipped by 0.01 when the Track 7
    merge added 4 sampled NEV variables and shifted the RNG stream);
    deliveries and prospects still separate clearly at tick 6."""

    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        low = _create_run(client, initial_state={"delivery_satisfaction": 0.4})
        high = _create_run(client, initial_state={"delivery_satisfaction": 0.9})
        low_snaps = _snapshots(client, low["id"])
        high_snaps = _snapshots(client, high["id"])
        assert low_snaps[0]["state"]["delivery_satisfaction"] == 0.4
        assert high_snaps[0]["state"]["delivery_satisfaction"] == 0.9
        # Tick 1: the feedback factor is 0.65 vs 1.15 on the same bases.
        assert (
            low_snaps[1]["state"]["funnel_lead_to_rfq_rate"]
            < high_snaps[1]["state"]["funnel_lead_to_rfq_rate"]
        )
        assert (
            low_snaps[1]["state"]["funnel_rfq_win_rate"]
            < high_snaps[1]["state"]["funnel_rfq_win_rate"]
        )
        # The RFQ-stock gap peaks at tick 3, then washes out as
        # satisfaction mean-reverts (see docstring); deliveries and
        # prospects still separate at tick 6.
        assert low_snaps[3]["state"]["funnel_rfqs"] < high_snaps[3]["state"]["funnel_rfqs"]
        assert (
            low_snaps[6]["state"]["funnel_deliveries_total"]
            < high_snaps[6]["state"]["funnel_deliveries_total"]
        )
        assert (
            low_snaps[6]["state"]["funnel_prospects_total"]
            < high_snaps[6]["state"]["funnel_prospects_total"]
        )


def test_funnel_run_is_deterministic(monkeypatch, tmp_path: Path) -> None:
    """Same seed + same bindings replay the funnel tick for tick."""

    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        first = _create_run(client)
        second = _create_run(client)
        first_states = [s["state"] for s in _snapshots(client, first["id"])]
        second_states = [s["state"] for s in _snapshots(client, second["id"])]
        assert first_states == second_states


def test_delivery_complaint_rule_dips_satisfaction(monkeypatch, tmp_path: Path) -> None:
    """Evidence-triggered rule: a late-delivery / customer-complaint
    claim fires auto.delivery_satisfaction_slip, and the tick-1
    satisfaction lands below the same-seed run without that evidence
    (the dip then decays toward the delivery target)."""

    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        baseline = _create_run(client)
        _accept_claim(
            client,
            "A late delivery caused a customer complaint about delivery "
            "satisfaction after a delivery delay on the last shipment.",
        )
        complaint = _create_run(client)
        assert "auto.delivery_satisfaction_slip" in complaint["summary"].get("matched_rules", [])
        base_snaps = _snapshots(client, baseline["id"])
        complaint_snaps = _snapshots(client, complaint["id"])
        assert (
            complaint_snaps[1]["state"]["delivery_satisfaction"]
            < base_snaps[1]["state"]["delivery_satisfaction"]
        )
        assert complaint_snaps[1]["state"]["delivery_satisfaction"] >= 0


def test_rfq_inflow_rule_adds_open_rfq(monkeypatch, tmp_path: Path) -> None:
    """Evidence-triggered rule: a new-RFQ claim fires
    auto.rfq_momentum, and the tick-1 open-RFQ stock lands above the
    same-seed run without that evidence."""

    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        baseline = _create_run(client)
        _accept_claim(
            client,
            "A new RFQ arrived: the customer issued a request for "
            "quotation with a strong RFQ inflow this month.",
        )
        momentum = _create_run(client)
        assert "auto.rfq_momentum" in momentum["summary"].get("matched_rules", [])
        base_snaps = _snapshots(client, baseline["id"])
        momentum_snaps = _snapshots(client, momentum["id"])
        assert momentum_snaps[1]["state"]["funnel_rfqs"] > base_snaps[1]["state"]["funnel_rfqs"]

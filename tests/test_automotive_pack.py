"""Unit tests for the automotive domain pack and variable template
(Phase 1 automotive pack).

Covers pack registration and state fields/defaults, the action/event/
actor surface, the built-in template synthesis (52 variables, 36
formulas, 33 drivers, assumption data), corporate-template invariance,
assumption-data merging, and ``resolve_assumption_data`` precedence.
"""

from __future__ import annotations

import copy
import random

from planagent.services.distributions import sample_variable_set
from planagent.services.variables import evaluate_tick_drivers, validate_template
from planagent.services.variables.models import (
    DistributionType,
    VariableSet,
)
from planagent.services.variables.presets import (
    builtin_template,
    resolve_assumption_data,
)
from planagent.services.variables.validator import merge_variable_sets
from planagent.simulation.domain_packs import registry as domain_pack_registry
from planagent.simulation.domain_packs.automotive.template_spec import (
    TEMPLATE_ASSUMPTION_DATA,
    TEMPLATE_FORMULAS,
    TEMPLATE_VARIABLES,
)


def test_pack_registered_and_state_fields() -> None:
    pack = domain_pack_registry.get("automotive")
    assert pack.domain_id == "automotive"
    fields = {field.name: float(field.default) for field in pack.state_fields}
    # 25 synthesis C1 fields + cash (MC continuity) + the generation
    # transition index (Ho's generation dimension) + 4 Phase 2
    # dual-track splits (NEV/ICE production + retail) + 14 Track 4
    # funnel/satisfaction fields (7 pipeline stocks + 2 cumulative
    # totals + 5 stage rates + overall conversion + satisfaction)
    # + 3 Track 7 supplier magnitude fields (market_share /
    # revenue / profit, mirroring the corporate pack so cases
    # can score them) + 2 Track 11 order-book fields
    # (order_backlog / order_intake) + 1 Track C1 ADAS penetration
    # field (adas_penetration, MIIT combined-assist 2025: 0.649).
    assert len(fields) == 51
    assert fields["production_volume"] == 287.8
    assert fields["sales_volume_retail"] == 197.9
    assert fields["sales_volume_wholesale"] == 246.3
    assert fields["export_volume"] == 59.2
    assert fields["capacity_utilization"] == 0.662
    assert fields["dealer_inventory_coef"] == 1.35
    assert fields["cash"] == 100.0
    assert fields["generation_transition_index"] == 0.0
    assert fields["dms_mandate"] == 0.0
    assert fields["policy_tax_rate"] == 0.05
    assert fields["tier1_gross_margin"] == 0.25
    assert fields["adas_penetration"] == 0.649
    # Dual-track splits sum exactly to their spine totals.
    assert fields["nev_production_volume"] == 137.86
    assert fields["ice_production_volume"] == 149.94
    assert fields["nev_production_volume"] + fields["ice_production_volume"] == 287.8
    assert fields["nev_retail_volume"] == 94.79
    assert fields["ice_retail_volume"] == 103.11
    assert fields["nev_retail_volume"] + fields["ice_retail_volume"] == 197.9
    # Track 4 funnel/satisfaction defaults: pipeline stocks, cumulative
    # totals consistent with the 0.10 overall default (12 / 120).
    assert fields["funnel_prospects"] == 40.0
    assert fields["funnel_leads"] == 12.0
    assert fields["funnel_rfqs"] == 4.0
    assert fields["funnel_contracts"] == 2.0
    assert fields["funnel_projects"] == 6.0
    assert fields["funnel_deliveries_total"] == 12.0
    assert fields["funnel_prospects_total"] == 120.0
    assert fields["funnel_prospect_to_lead_rate"] == 0.25
    assert fields["funnel_lead_to_rfq_rate"] == 0.30
    assert fields["funnel_rfq_win_rate"] == 0.25
    assert fields["funnel_contract_to_project_rate"] == 0.90
    assert fields["funnel_project_to_delivery_rate"] == 0.92
    assert fields["funnel_overall_conversion"] == 0.10
    assert fields["delivery_satisfaction"] == 0.75
    # Track 7 supplier magnitude fields mirror the corporate pack
    # defaults; no template driver moves them.
    assert fields["market_share"] == 0.05
    assert fields["revenue"] == 100.0
    assert fields["profit"] == 20.0
    # Track 11 order-book fields default to an empty book, so generic
    # runs are exactly unaffected.
    assert fields["order_backlog"] == 0.0
    assert fields["order_intake"] == 0.0


def test_pack_actions_events_actors() -> None:
    pack = domain_pack_registry.get("automotive")
    actions = {action.action_id for action in pack.action_library}
    assert actions == {
        "adjust_price",
        "increase_incentive",
        "cut_production",
        "ramp_production",
        "build_inventory",
        "destock",
        "shift_mix_nev",
        "shift_product_mix",
        "expand_channel",
        "qualify_leads",
        "accelerate_rfq_response",
        "improve_delivery_quality",
        "hold_and_monitor",
    }
    events = {event.event_type for event in pack.event_types}
    assert events == {
        "policy_calendar_event",
        "dms_mandate_switch",
        "chip_supply_shock",
        "price_war_escalation",
        "generation_changeover",
        "dealer_inventory_alert",
        "delivery_satisfaction_feedback",
    }
    templates = {template.actor_type: template for template in pack.actor_templates}
    assert set(templates) == {"oem", "dealer", "tier1_supplier"}
    # Actor templates carry no invented state overrides in Phase 1.
    assert all(template.default_state == {} for template in templates.values())
    entities = {entity.entity_type for entity in pack.entity_types}
    assert entities == {"oem", "dealer", "tier1_supplier", "nameplate"}


def test_template_spec_counts_and_driver_flags() -> None:
    # Merge (2026-11-23): 61 -> 76 variables, 36 -> 43 formulas,
    # 33 -> 40 tick drivers — C1 ADAS chain (+6/+1/+1) plus R&D margin
    # promotion (+8/+6/+6) plus transmission (+1/+0/+0), exact union,
    # no overlap (the six R&D chain drivers append at the end, in
    # chain order: adoption default -> revenue passthrough anchor ->
    # gross_margin -> rd_intensity -> net_margin -> profit; the
    # transmission is a term inside the gross_margin driver, not a
    # new formula). Track A rebase (2026-11-23): +1 formula / +1 tick
    # driver — the order-intake decay merge anchor, first in the
    # chain (43 -> 44, 40 -> 41).
    assert len(TEMPLATE_VARIABLES) == 76
    assert len(TEMPLATE_FORMULAS) == 44
    drivers = [f for f in TEMPLATE_FORMULAS if f.get("tick_driver")]
    assert len(drivers) == 41
    assert [f["output"] for f in drivers] == [
        "pull_forward_stock",
        "price_index",
        "income_index",
        "sales_volume_retail",
        "dealer_inventory_coef",
        "production_volume",
        "nev_penetration",
        "adas_penetration",
        "nev_retail_volume",
        "ice_retail_volume",
        "nev_production_volume",
        "ice_production_volume",
        "tier1_gross_margin",
        "generation_transition_index",
        # Track 4 funnel drivers, in chain order: rates -> flows ->
        # stocks -> satisfaction -> overall conversion.
        "funnel_prospect_to_lead_rate",
        "funnel_lead_to_rfq_rate",
        "funnel_rfq_win_rate",
        "funnel_contract_to_project_rate",
        "funnel_project_to_delivery_rate",
        "funnel_new_prospects",
        "funnel_new_leads",
        "funnel_new_rfqs",
        "funnel_new_contracts",
        "funnel_new_projects",
        "funnel_new_deliveries",
        "funnel_prospects",
        "funnel_leads",
        "funnel_rfqs",
        "funnel_contracts",
        "funnel_projects",
        "funnel_deliveries_total",
        "funnel_prospects_total",
        "delivery_satisfaction",
        "funnel_overall_conversion",
        # R&D decomposition drivers, in chain order: order-intake
        # decay anchor (Track A) -> adoption default -> revenue
        # passthrough anchor -> gross_margin -> rd_intensity ->
        # net_margin -> profit.
        "order_intake",
        "disruptor_adoption",
        "revenue",
        "gross_margin",
        "rd_intensity",
        "net_margin",
        "profit",
    ]
    # Every variable carries a unit and an evidence reference.
    for raw in TEMPLATE_VARIABLES:
        assert raw["unit"], raw["id"]
        assert raw["evidence_ref"], raw["id"]
    # 34 of 76 variable ids match pack state fields (the wiring: sampling
    # applies to id-matched fields). The 42 formula parameters are the 9
    # pre-Track-4 sensitivities/rates plus the 12 Track 4 funnel
    # parameters (7 base rates/inflow/gain + 5 attrition rates) plus
    # the 4 Track 7 NEV-chain variables (the chain's penetration is
    # the pack's nev_penetration state field, reused, not a fifth
    # variable), plus the 3 Track 11 order-book parameters
    # (order_intake_rate / backlog_conversion / order_decay — the
    # backlog stock itself is the pack's order_backlog state field,
    # bound, not a parameter), plus the 5 Track C1 ADAS-chain
    # variables (adas_ceiling / adas_rate / adas_midpoint /
    # adas_coupling / adas_penetration_monthly_drift — the penetration
    # is the pack's adas_penetration state field, reused, not a sixth
    # variable), plus the 8 R&D decomposition variables
    # (the legs themselves are the gross_margin / rd_intensity /
    # net_margin driver outputs, not further variables, and profit is
    # the pack's profit state field, reused), plus the Tier-1
    # transmission coefficient (tier1_pass_through, fixed, not
    # sampled — it is a formula parameter, not a state field).
    fields = {field.name for field in domain_pack_registry.get("automotive").state_fields}
    unbound = {raw["id"] for raw in TEMPLATE_VARIABLES} - fields
    assert unbound == {
        "confidence_sensitivity",
        "income_sensitivity",
        "tax_sensitivity",
        "lpr_sensitivity",
        "material_passthrough",
        "price_sensitivity",
        "margin_material_sensitivity",
        "income_growth_rate_annual",
        "nev_penetration_monthly_drift",
        "prospect_inflow_monthly",
        "funnel_prospect_to_lead_base",
        "funnel_lead_to_rfq_base",
        "funnel_rfq_win_base",
        "funnel_contract_to_project_base",
        "funnel_project_to_delivery_base",
        "satisfaction_feedback_gain",
        "funnel_prospect_attrition",
        "funnel_lead_attrition",
        "funnel_rfq_attrition",
        "funnel_contract_attrition",
        "funnel_project_attrition",
        "nev_ceiling",
        "nev_rate",
        "nev_midpoint",
        "nev_coupling",
        "adas_ceiling",
        "adas_rate",
        "adas_midpoint",
        "adas_coupling",
        "adas_penetration_monthly_drift",
        "order_intake_rate",
        "backlog_conversion",
        "order_decay",
        "gross_base",
        "gross_longrun",
        "gross_reversion",
        "rd_base",
        "rd_longrun",
        "rd_reversion",
        "rd_adoption",
        "other_share",
        "tier1_pass_through",
    }


def test_builtin_automotive_template_validates() -> None:
    template = builtin_template("automotive")
    assert template.id == "builtin:automotive"
    assert template.is_builtin is True
    # Merge (2026-11-23): 61 -> 76 variables, 36 -> 44 formulas
    # (C1 +6/+1, R&D +8/+6, transmission +1/+0, Track A intake
    # anchor +0/+1; the revenue-passthrough merge anchor is one of
    # the seven chain formulas; see the template docstring).
    assert len(template.variables) == 76
    assert len(template.formulas) == 44
    assert validate_template(template).is_valid is True
    # The tax-level factor is an initial formula; the retail driver is a
    # tick driver. Both exist exactly once.
    by_output = {formula.output: formula for formula in template.formulas}
    assert by_output["demand_level_factor"].tick_driver is False
    assert by_output["sales_volume_retail"].tick_driver is True
    # Simulated values are labeled as simulated, never as evidence.
    by_id = {variable.id: variable for variable in template.variables}
    for var_id in ("annual_cut_rate", "payment_terms_months"):
        assert by_id[var_id].evidence_ref.startswith("simulated:industry-average"), var_id
    # tier1_gross_margin is DESAY-EVIDENCE since calibration-simulated-
    # generation-2026-11-20 (audited 2015-2020 decision-time margin,
    # moment-matched) — no longer simulated, so it leaves the loop above.
    assert by_id["tier1_gross_margin"].evidence_ref.startswith("desay-evidence:"), "tier1_gross_margin"


def test_tier1_gross_margin_band_is_calibration_value() -> None:
    """Margin-profit transmission / calibration alignment: the tier1
    band is the calibration DESAY-EVIDENCE value (0.20, 0.25, 0.29) —
    audited 2015-2020 decision-time margins, moment-matched — not the
    A3 widened band (0.167, 0.191, 0.215), whose mode 0.191 is itself
    a post-hoc 2025 value (TRACK-A3 §5.2 admits it), and not the
    mainline (0.188, 0.191, 0.20), whose span was 6.3% of the mode.
    Span/mode 36% clears the red-team 10% overconfidence threshold,
    so the A3 finding stays cleared while the band is also
    firewall-clean.
    """
    by_id = {raw["id"]: raw for raw in TEMPLATE_VARIABLES}
    dist = by_id["tier1_gross_margin"]["distribution"]
    assert dist["type"] == "triangular"
    assert (dist["min"], dist["mode"], dist["max"]) == (0.20, 0.25, 0.29)
    assert abs((dist["max"] - dist["min"]) / dist["mode"] - 0.36) < 1e-9
    assert by_id["tier1_gross_margin"]["evidence_ref"].startswith("desay-evidence:")


def test_gross_margin_transmission_literal_matches_tier1_mode() -> None:
    """Margin-profit transmission: the gross_margin driver carries
    tier1_pass_through x (tier1_gross_margin(t) - MODE), where MODE
    is a literal — the formula language has no 'distribution mode'
    reference. This test pins the literal to the tier1 distribution's
    mode so the two cannot drift apart silently: if the band is ever
    re-anchored, this test fails until the literal is updated too.
    It also pins the coefficient itself: fixed 0.5, labeled simulated.
    """
    by_id = {raw["id"]: raw for raw in TEMPLATE_VARIABLES}
    mode = by_id["tier1_gross_margin"]["distribution"]["mode"]
    kappa = by_id["tier1_pass_through"]
    assert kappa["distribution"] == {"type": "fixed", "value": 0.5}
    assert kappa["evidence_ref"].startswith("simulated:")
    template = builtin_template("automotive")
    by_output = {f.output: f for f in template.formulas}
    expression = by_output["gross_margin"].expression

    def walk(node: object, found: list[object]) -> None:
        if isinstance(node, dict):
            found.append(node)
            for value in node.values():
                walk(value, found)
        elif isinstance(node, list):
            for value in node:
                walk(value, found)

    nodes: list[object] = []
    walk(expression, nodes)
    literal: object = None
    for node in nodes:
        if not isinstance(node, dict) or node.get("op") != "multiply":
            continue
        args = node.get("args", [])
        if {"ref": "tier1_pass_through"} not in args:
            continue
        for arg in args:
            if isinstance(arg, dict) and arg.get("op") == "subtract":
                sub_args = arg.get("args", [])
                assert sub_args[0] == {"ref": "tier1_gross_margin"}
                literal = sub_args[1]
    assert literal is not None, "gross_margin carries no tier1 term"
    assert literal == mode


def test_promoted_rate_variables_resolve_in_drivers() -> None:
    """The two Phase 2 literal rates are template variables whose sampled
    values resolve inside their tick drivers (cap raised 30 -> 100)."""

    def _refs(node: object, found: set[str]) -> None:
        if isinstance(node, dict):
            if set(node) == {"ref"}:
                found.add(str(node["ref"]))
            for value in node.values():
                _refs(value, found)
        elif isinstance(node, list):
            for value in node:
                _refs(value, found)

    template = builtin_template("automotive")
    by_id = {variable.id: variable for variable in template.variables}

    income_rate = by_id["income_growth_rate_annual"]
    assert income_rate.unit == "rate/year"
    assert income_rate.distribution.type == DistributionType.FIXED
    assert income_rate.distribution.value == 0.055
    assert income_rate.evidence_ref.startswith("calibration:v3")

    drift = by_id["nev_penetration_monthly_drift"]
    assert drift.unit == "rate points/month"
    assert drift.distribution.type == DistributionType.FIXED
    assert drift.distribution.value == 0.0068
    assert drift.evidence_ref.startswith("calibration:v3")

    # The drivers reference the promoted variables, not literals.
    by_output = {formula.output: formula for formula in template.formulas}
    income_refs: set[str] = set()
    _refs(by_output["income_index"].expression, income_refs)
    assert income_refs == {"income_index", "income_growth_rate_annual"}
    penetration_refs: set[str] = set()
    _refs(by_output["nev_penetration"].expression, penetration_refs)
    assert penetration_refs == {"nev_penetration", "nev_penetration_monthly_drift"}

    # Sampling the template resolves both rates, and the drivers evaluate
    # to the calibrated behavior (v3: income 5.50%/yr, drift 0.0068/mo).
    sampled = sample_variable_set(
        VariableSet(variables=list(template.variables)), random.Random(7)
    )
    assert sampled["income_growth_rate_annual"] == 0.055
    assert sampled["nev_penetration_monthly_drift"] == 0.0068
    updates = evaluate_tick_drivers(
        [by_output["income_index"], by_output["nev_penetration"]],
        sampled,
        {"income_index": 1.0, "nev_penetration": 0.479},
        1,
    )
    assert updates == {"income_index": 1.0046, "nev_penetration": 0.4858}


def test_builtin_corporate_template_unchanged() -> None:
    # Profit-chain pack (2026-11-20): the corporate template is no
    # longer empty — it now carries the profit chain (4 margin
    # variables + 4 formulas, same as the automotive chain). The
    # assumption data is still empty (the automotive fitment lookup /
    # supply-share data is auto-specific); what this test still pins
    # is that the corporate template ships NOTHING else.
    template = builtin_template("corporate")
    assert [v.id for v in template.variables] == [
        "margin_base",
        "margin_longrun",
        "margin_reversion",
        "margin_adoption",
    ]
    assert [f.output for f in template.formulas] == [
        "disruptor_adoption",
        "revenue",
        "net_margin",
        "profit",
    ]
    assert template.assumption_data == {}


def test_template_assumption_data_lookup_cells() -> None:
    data = copy.deepcopy(TEMPLATE_ASSUMPTION_DATA)
    lookup = data["fitment_lookup"]
    assert lookup["l2_by_price_band"]["<10"] == 0.111
    assert lookup["l2_by_price_band"]["40-60"] == 0.901
    assert lookup["cockpit_domain_controller_by_price_band"][">20"] == 0.864
    assert lookup["city_noa_by_price_band"]["25-30"] == 0.57
    assert lookup["intelligent_cabin_by_energy"]["NEV"] == 0.90
    assert lookup["intelligent_cabin_by_energy"]["ICE"] == 0.633
    assert data["supply_share_simulated"]["value"] == 0.10
    assert "simulated" in data["supply_share_simulated"]["provenance"]
    # The pack returns a fresh copy each time: mutating one call's data
    # must not leak into the next.
    pack = domain_pack_registry.get("automotive")
    first = pack.template_assumption_data()
    first["fitment_lookup"]["l2_by_price_band"]["<10"] = 0.0
    assert pack.template_assumption_data()["fitment_lookup"]["l2_by_price_band"]["<10"] == 0.111


def test_merge_variable_sets_assumption_data() -> None:
    base = VariableSet(
        name="base",
        variables=[],
        assumption_data={"fitment_lookup": {"a": 1}, "kept": "base"},
    )
    override = VariableSet(
        name="override",
        variables=[],
        assumption_data={"fitment_lookup": {"b": 2}, "added": "override"},
    )
    merged = merge_variable_sets(base, override)
    # Top-level keys merge; nested values replace wholesale.
    assert merged.assumption_data == {
        "fitment_lookup": {"b": 2},
        "kept": "base",
        "added": "override",
    }


def test_resolve_assumption_data_bindings_win() -> None:
    configuration = {
        "variables": {
            "bindings": {"assumption_data": {"source": "bindings"}},
            "template": {"assumption_data": {"source": "template"}},
        }
    }
    assert resolve_assumption_data(configuration) == {"source": "bindings"}


def test_resolve_assumption_data_template_snapshot_fallback() -> None:
    configuration = {
        "variables": {
            "template": {
                "id": "builtin:automotive",
                "name": "Built-in automotive preset",
                "domain_id": "automotive",
                "variables": [],
                "formulas": [],
                "assumption_data": {"source": "template"},
            }
        }
    }
    assert resolve_assumption_data(configuration) == {"source": "template"}


def test_resolve_assumption_data_empty_when_absent() -> None:
    assert resolve_assumption_data(None) == {}
    assert resolve_assumption_data({}) == {}
    assert resolve_assumption_data({"variables": {}}) == {}

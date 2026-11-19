"""Unit tests for the automotive domain pack and variable template
(Phase 1 automotive pack).

Covers pack registration and state fields/defaults, the action/event/
actor surface, the built-in template synthesis (32 variables, 16
formulas, 13 drivers, assumption data), corporate-template invariance,
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
    # dual-track splits (NEV/ICE production + retail) + 3 Track 7
    # supplier magnitude fields (market_share / revenue / profit,
    # mirroring the corporate pack so cases can score them).
    assert len(fields) == 34
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
    assert fields["tier1_gross_margin"] == 0.191
    # Dual-track splits sum exactly to their spine totals.
    assert fields["nev_production_volume"] == 137.86
    assert fields["ice_production_volume"] == 149.94
    assert fields["nev_production_volume"] + fields["ice_production_volume"] == 287.8
    assert fields["nev_retail_volume"] == 94.79
    assert fields["ice_retail_volume"] == 103.11
    assert fields["nev_retail_volume"] + fields["ice_retail_volume"] == 197.9
    # Track 7 supplier magnitude fields mirror the corporate pack
    # defaults; no template driver moves them.
    assert fields["market_share"] == 0.05
    assert fields["revenue"] == 100.0
    assert fields["profit"] == 20.0


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
    }
    templates = {template.actor_type: template for template in pack.actor_templates}
    assert set(templates) == {"oem", "dealer", "tier1_supplier"}
    # Actor templates carry no invented state overrides in Phase 1.
    assert all(template.default_state == {} for template in templates.values())
    entities = {entity.entity_type for entity in pack.entity_types}
    assert entities == {"oem", "dealer", "tier1_supplier", "nameplate"}


def test_template_spec_counts_and_driver_flags() -> None:
    assert len(TEMPLATE_VARIABLES) == 36
    assert len(TEMPLATE_FORMULAS) == 16
    drivers = [f for f in TEMPLATE_FORMULAS if f.get("tick_driver")]
    assert len(drivers) == 13
    assert [f["output"] for f in drivers] == [
        "pull_forward_stock",
        "price_index",
        "income_index",
        "sales_volume_retail",
        "dealer_inventory_coef",
        "production_volume",
        "nev_penetration",
        "nev_retail_volume",
        "ice_retail_volume",
        "nev_production_volume",
        "ice_production_volume",
        "tier1_gross_margin",
        "generation_transition_index",
    ]
    # Every variable carries a unit and an evidence reference.
    for raw in TEMPLATE_VARIABLES:
        assert raw["unit"], raw["id"]
        assert raw["evidence_ref"], raw["id"]
    # 23 of 36 variable ids match pack state fields (the wiring: sampling
    # applies to id-matched fields). The 13 formula parameters are the 7
    # sensitivity coefficients plus the 2 rates promoted from Phase 2
    # literals when the cap was raised from 30 to 100, plus the 4 Track 7
    # NEV-chain variables (the chain's penetration is the pack's
    # nev_penetration state field, reused, not a fifth variable).
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
        "nev_ceiling",
        "nev_rate",
        "nev_midpoint",
        "nev_coupling",
    }


def test_builtin_automotive_template_validates() -> None:
    template = builtin_template("automotive")
    assert template.id == "builtin:automotive"
    assert template.is_builtin is True
    assert len(template.variables) == 36
    assert len(template.formulas) == 16
    assert validate_template(template).is_valid is True
    # The tax-level factor is an initial formula; the retail driver is a
    # tick driver. Both exist exactly once.
    by_output = {formula.output: formula for formula in template.formulas}
    assert by_output["demand_level_factor"].tick_driver is False
    assert by_output["sales_volume_retail"].tick_driver is True
    # Simulated values are labeled as simulated, never as evidence.
    by_id = {variable.id: variable for variable in template.variables}
    for var_id in ("annual_cut_rate", "payment_terms_months", "tier1_gross_margin"):
        assert by_id[var_id].evidence_ref.startswith("simulated:industry-average"), var_id


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
    assert income_rate.distribution.value == 0.05
    assert income_rate.evidence_ref.startswith("NBS")

    drift = by_id["nev_penetration_monthly_drift"]
    assert drift.unit == "rate points/month"
    assert drift.distribution.type == DistributionType.FIXED
    assert drift.distribution.value == 0.002
    assert drift.evidence_ref.startswith("assumption:pending-calibration")

    # The drivers reference the promoted variables, not literals.
    by_output = {formula.output: formula for formula in template.formulas}
    income_refs: set[str] = set()
    _refs(by_output["income_index"].expression, income_refs)
    assert income_refs == {"income_index", "income_growth_rate_annual"}
    penetration_refs: set[str] = set()
    _refs(by_output["nev_penetration"].expression, penetration_refs)
    assert penetration_refs == {"nev_penetration", "nev_penetration_monthly_drift"}

    # Sampling the template resolves both rates, and the drivers evaluate
    # to exactly the old literal behavior (fixed values, no drift).
    sampled = sample_variable_set(VariableSet(variables=list(template.variables)), random.Random(7))
    assert sampled["income_growth_rate_annual"] == 0.05
    assert sampled["nev_penetration_monthly_drift"] == 0.002
    updates = evaluate_tick_drivers(
        [by_output["income_index"], by_output["nev_penetration"]],
        sampled,
        {"income_index": 1.0, "nev_penetration": 0.479},
        1,
    )
    assert updates == {"income_index": 1.0042, "nev_penetration": 0.481}


def test_builtin_corporate_template_unchanged() -> None:
    template = builtin_template("corporate")
    assert template.variables == []
    assert template.formulas == []
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

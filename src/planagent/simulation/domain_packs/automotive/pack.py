"""Automotive domain pack (Phase 1, auto-industry track).

China market, tick = 1 month. State fields and defaults follow the v2
table in the synthesis report (``auto-model-synthesis.md`` §C1); each
default cites its synthesis section in the comment above it. Fields the
synthesis marks as assumption parameters carry explicitly-labeled
assumption defaults — never silently invented values.

The VOLUME SPINE is OEM PRODUCTION volume, including Audi (Ho
2026-11-16): if the OEM produces the car it needs the product, so
production counts as a sale and export is irrelevant. Retail and
wholesale are transmission intermediates (retail → inventory →
production), not the spine.

The generation/lifecycle dimension (Ho 2026-11-16) is represented
coarsely in Phase 1 by ``generation_transition_index``: the
representative successor-generation share, ramped by a tick driver.
Per-nameplate generation schedules are Phase 2; the split-gate
structure (``services/splits``) already carries the full
nameplate → generation → trim → product → supplier-share tree.

Phase 2 adds the NEV/ICE dual track: ``nev_*`` / ``ice_*`` splits of
the production spine and retail, derived each tick from the shared
spine x ``nev_penetration`` by tick drivers (the template's dual-track
drivers). The splits always sum back to their spine totals by
construction. Transmission links (income / LPR / materials) live in
the template's tick drivers; the pack only carries the state fields.
"""

from __future__ import annotations

from copy import deepcopy

from planagent.simulation.domain_packs import DomainPack, registry
from planagent.simulation.specs import (
    ActionSpec,
    ActorTemplate,
    EntityTypeSpec,
    EventTypeSpec,
    StateFieldSpec,
)

from .template_spec import (
    TEMPLATE_ASSUMPTION_DATA,
    TEMPLATE_FORMULAS,
    TEMPLATE_VARIABLES,
)


class AutomotiveDomainPack(DomainPack):
    @property
    def domain_id(self) -> str:
        return "automotive"

    @property
    def entity_types(self) -> list[EntityTypeSpec]:
        return [
            EntityTypeSpec("oem", "Vehicle manufacturer (OEM) in the China market."),
            EntityTypeSpec("dealer", "Franchised dealer / distribution channel."),
            EntityTypeSpec(
                "tier1_supplier", "Tier-1 automotive electronics supplier (Ho's position)."
            ),
            EntityTypeSpec("nameplate", "Vehicle nameplate carrying successive generations."),
        ]

    @property
    def state_fields(self) -> list[StateFieldSpec]:
        return [
            # Synthesis C1: 2025 monthly-average derived value (CAAM caliber).
            # The volume spine (Ho 2026-11-16): OEM production incl. Audi.
            StateFieldSpec("production_volume", "Monthly production volume, 10k vehicles.", 287.8),
            # Synthesis C1/B1: 2025 monthly-average derived value, CPCA retail caliber.
            StateFieldSpec("sales_volume_retail", "Monthly retail volume, 10k vehicles.", 197.9),
            # Synthesis C1/B1: 2025 monthly-average derived value, CPCA wholesale caliber.
            StateFieldSpec(
                "sales_volume_wholesale", "Monthly wholesale volume, 10k vehicles.", 246.3
            ),
            # Synthesis C1: 2025 monthly-average derived value (CAAM export caliber).
            StateFieldSpec("export_volume", "Monthly export volume, 10k vehicles.", 59.2),
            # Synthesis C1/B1: NBS, 2026Q3.
            StateFieldSpec(
                "capacity_utilization", "Auto-manufacturing capacity utilization.", 0.662
            ),
            # Synthesis C1/B1: CADA, Sep 2025 (Sep 2026: 1.68 is a scenario reference).
            StateFieldSpec(
                "dealer_inventory_coef",
                "Dealer inventory coefficient (ending inventory / sales).",
                1.35,
            ),
            # Synthesis C1: CADA, Dec 2025.
            StateFieldSpec(
                "inventory_warning", "Inventory warning index (50% is the boom/bust line).", 0.577
            ),
            # Synthesis C1: 1.0 = 2025 average, anchored to CNY 170k average retail price.
            StateFieldSpec("price_index", "Transaction price level, 1.0 = 2025 average.", 1.0),
            # Synthesis C1/B1: point value, Nov/Dec 2025; no continuous public series.
            StateFieldSpec("promo_rate", "Terminal promotion rate.", 0.10),
            # Synthesis C1/B5: wait-and-see buyer share, 2025H1 survey.
            StateFieldSpec(
                "price_cut_expectation", "Share of buyers waiting for price cuts.", 0.45
            ),
            # Synthesis C1/B1: CAAM total-volume caliber, 2025.
            StateFieldSpec("nev_penetration", "NEV share of total vehicle sales.", 0.479),
            # Phase 2 dual track: NEV/ICE splits of the production spine
            # and retail. Initial values are the spine x 0.479, rounded
            # so each pair sums exactly to its spine total; tick
            # drivers re-derive them from the live spine x penetration.
            StateFieldSpec(
                "nev_production_volume", "Monthly NEV production volume, 10k vehicles.", 137.86
            ),
            StateFieldSpec(
                "ice_production_volume", "Monthly ICE production volume, 10k vehicles.", 149.94
            ),
            StateFieldSpec(
                "nev_retail_volume", "Monthly NEV retail volume, 10k vehicles.", 94.79
            ),
            StateFieldSpec(
                "ice_retail_volume", "Monthly ICE retail volume, 10k vehicles.", 103.11
            ),
            # Synthesis C1: 1.0 = 2025, anchored to CNY 43,377 per-capita disposable income.
            StateFieldSpec("income_index", "Disposable-income level, 1.0 = 2025.", 1.0),
            # Synthesis C1/B4: ASSUMPTION PARAMETER (no unified public series).
            # Normalized so 1.0 is the 2024Q4 PBOC survey baseline.
            StateFieldSpec(
                "consumer_confidence_proxy",
                "Consumer-confidence proxy, 1.0 = 2024Q4 baseline.",
                1.0,
            ),
            # Synthesis C1/B4: ASSUMPTION PARAMETER. Normalized index, 1.0 =
            # baseline; the live LPR value is bound per run (Phase 2 data item).
            # No LPR point value is baked into the pack.
            StateFieldSpec("lpr_proxy", "Interest-rate environment proxy, 1.0 = baseline.", 1.0),
            # Synthesis C1/B3: 5% halved rate in 2026-27 (MOF/STA/MIIT 2023 No.10).
            StateFieldSpec("policy_tax_rate", "NEV purchase-tax rate.", 0.05),
            # Synthesis C1/B3: ASSUMPTION PARAMETER. 1.0 = the 2026 proportional-cap scheme.
            StateFieldSpec(
                "trade_in_support", "Trade-in subsidy support strength, 0-1 normalized.", 1.0
            ),
            # Synthesis C1/B3: LOWER-BOUND anchor — 2025 trade-in scale exceeded
            # 11.5M vehicles. The payback rate is an assumption parameter.
            StateFieldSpec(
                "pull_forward_stock", "Subsidy pull-forward stock, 10k vehicles.", 1150.0
            ),
            # Synthesis C1/B3: 0 until 2027-01-01, then 1 (GB 47955-2026, mandatory DMS).
            StateFieldSpec("dms_mandate", "DMS mandate switch (0/1).", 0.0),
            # Synthesis C1/B4: ASSUMPTION PARAMETER. The value is the documented
            # 2022-02 PEAK anchor (Susquehanna 26.2w average, MCU 35.7w), NOT a
            # normal baseline — bind the current lead time per run.
            StateFieldSpec("chip_lead_time_weeks", "Average chip lead time, weeks.", 26.2),
            # Synthesis C1: 1.0 = normal supply.
            StateFieldSpec("chip_supply_index", "Chip supply level, 1.0 = normal.", 1.0),
            # Synthesis C1: 1.0 = baseline (lithium + steel/aluminum proxies composite).
            StateFieldSpec(
                "material_cost_index", "Raw-material cost pressure, 1.0 = baseline.", 1.0
            ),
            # Synthesis C1/B5: midpoint of the conventional 3-5% range; the
            # stressed 10%+ regime is a scenario parameter. SIMULATED
            # industry average (Ho-authorized 2026-11-16).
            StateFieldSpec("annual_cut_rate", "Annual price-cut rate demanded by OEMs.", 0.04),
            # Synthesis C1/B5: 6 months is common (n+3+6 structure). SIMULATED
            # industry average (Ho-authorized 2026-11-16); Ho internal actuals
            # take priority when they arrive.
            StateFieldSpec("payment_terms_months", "Actual payment-terms length, months.", 6.0),
            # Synthesis C1/B2: Desay SV 2025 overall margin (listed benchmark).
            # SIMULATED industry average (Ho-authorized 2026-11-16); Ho's own
            # margin is an internal parameter.
            StateFieldSpec("tier1_gross_margin", "Tier-1 gross margin.", 0.191),
            # Synthesis C1: 1.0 = baseline (anchored to 366M parc, ~8yr average age).
            StateFieldSpec("replacement_demand", "Replacement-demand level, 1.0 = baseline.", 1.0),
            # Synthesis C1: retained ONLY for Monte Carlo metric continuity.
            StateFieldSpec("cash", "Available operating cash.", 100.0),
            # Ho 2026-11-16 generation/lifecycle dimension (NOT in synthesis
            # C1): coarse Phase 1 representation. 0 = outgoing generation
            # fully, 1 = successor fully ramped. Assumption parameter; the
            # tick driver ramps it and per-nameplate schedules are Phase 2.
            StateFieldSpec(
                "generation_transition_index",
                "Representative successor-generation share, 0-1.",
                0.0,
            ),
        ]

    @property
    def action_library(self) -> list[ActionSpec]:
        return [
            ActionSpec("adjust_price", "Adjust transaction pricing."),
            ActionSpec("increase_incentive", "Increase terminal incentives / promotions."),
            ActionSpec("cut_production", "Cut production scheduling (inventory discipline)."),
            ActionSpec("ramp_production", "Ramp production scheduling on strong demand."),
            ActionSpec("build_inventory", "Build channel inventory ahead of demand."),
            ActionSpec("destock", "Destock channel inventory."),
            ActionSpec("shift_mix_nev", "Shift mix toward NEV nameplates."),
            ActionSpec("shift_product_mix", "Shift the electronics product/solution mix."),
            ActionSpec("expand_channel", "Expand channel / export coverage."),
            ActionSpec("hold_and_monitor", "Hold position while collecting more evidence."),
        ]

    @property
    def event_types(self) -> list[EventTypeSpec]:
        return [
            EventTypeSpec(
                "policy_calendar_event",
                "A policy-calendar event took effect (tax, trade-in, dual-credit).",
            ),
            EventTypeSpec("dms_mandate_switch", "The GB 47955-2026 DMS mandate switched on."),
            EventTypeSpec("chip_supply_shock", "Chip supply disruption / lead-time blowout."),
            EventTypeSpec("price_war_escalation", "Terminal price war escalated."),
            EventTypeSpec(
                "generation_changeover", "A nameplate generation changed over (phase-out / ramp)."
            ),
            EventTypeSpec("dealer_inventory_alert", "Dealer inventory crossed the warning line."),
        ]

    @property
    def actor_templates(self) -> list[ActorTemplate]:
        # Phase 1: actor templates carry NO state overrides — the pack
        # defaults apply uniformly. Per-actor differentiation arrives with
        # calibration data; inventing actor-specific values now would be
        # fabrication. The templates exist as the actor vocabulary.
        return [
            ActorTemplate("oem", {}),
            ActorTemplate("dealer", {}),
            ActorTemplate("tier1_supplier", {}),
        ]

    def template_variables(self) -> list[dict]:
        return deepcopy(TEMPLATE_VARIABLES)

    def template_formulas(self) -> list[dict]:
        return deepcopy(TEMPLATE_FORMULAS)

    def template_assumption_data(self) -> dict:
        return deepcopy(TEMPLATE_ASSUMPTION_DATA)


registry.register(AutomotiveDomainPack())

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
            # Track C1 (2026-11-20, ADAS penetration chain): L2 /
            # combined driving-assist fitment share of new-car sales.
            # 2025 caliber 0.649 (MIIT combined driving-assist
            # fitment 64.9% in 2025, published 2026-10 — same
            # MIIT series as the 16.2% 2020 figure; NOT a
            # decision-time input — backtest cases bind their own
            # decision-time starting level and logistic path, which
            # replaces the template's drift driver per-output at
            # merge, exactly like the NEV chain). Generic runs keep
            # the drift driver; only a case that supplies the ADAS
            # logistic + the revenue/share coupling terms moves
            # revenue or share through it.
            StateFieldSpec(
                "adas_penetration",
                "L2 / combined driving-assist fitment share of new-car sales.",
                0.649,
            ),
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
            StateFieldSpec("nev_retail_volume", "Monthly NEV retail volume, 10k vehicles.", 94.79),
            StateFieldSpec("ice_retail_volume", "Monthly ICE retail volume, 10k vehicles.", 103.11),
            # Synthesis C1: 1.0 = 2025, anchored to CNY 43,377 per-capita disposable income.
            StateFieldSpec("income_index", "Disposable-income level, 1.0 = 2025.", 1.0),
            # Synthesis C1/B4: ASSUMPTION PARAMETER (no unified public series).
            # Normalized so 1.0 is the 2024Q4 PBOC survey baseline.
            StateFieldSpec(
                "consumer_confidence_proxy",
                "Consumer-confidence proxy, 1.0 = 2024Q4 baseline.",
                1.0,
            ),
            # Calibration v3: lpr_proxy = 1y LPR / 3.85% (2020-2021 modal
            # 1y LPR, the pre-easing level); 1.0 = 3.85%. The live LPR
            # value is bound per run (Phase 2 data item). No LPR point
            # value is baked into the pack.
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
            # Calibration-simulated-generation-2026-11-20: moment-matched to
            # the audited 2015-2020 decision-time margin trajectory (mean
            # 24.97%); replaces the 2023-25 post-decision window
            # (hindsight-leak fix). Ho's own margin is an internal parameter.
            StateFieldSpec("tier1_gross_margin", "Tier-1 gross margin.", 0.25),
            # Synthesis C1: 1.0 = baseline (anchored to 366M parc, ~8yr average age).
            StateFieldSpec("replacement_demand", "Replacement-demand level, 1.0 = baseline.", 1.0),
            # Synthesis C1: retained ONLY for Monte Carlo metric continuity.
            StateFieldSpec("cash", "Available operating cash.", 100.0),
            # B2B funnel (Track 4, one-click): the 8-stage Tier-1 sales
            # chain — customer development -> lead funnel -> RFQ/contract
            # -> demand/product matching/project management -> manufacturing
            # follow-up -> delivery satisfaction — as modeled pipeline
            # STOCKS (counts), not manual overrides. Stocks flow into each
            # other at the modeled conversion rates below; the rates are
            # tick-driver outputs (template_spec.py), so a run with the
            # built-in template computes the whole funnel end to end.
            # Stock defaults are round placeholder pipeline levels
            # (assumption:pending-calibration — bind the real CRM pipeline
            # per run); the cumulative totals are consistent with the
            # overall conversion default (12 / 120 = 0.10).
            StateFieldSpec(
                "funnel_prospects", "Open prospect accounts in customer development.", 40.0
            ),
            StateFieldSpec("funnel_leads", "Qualified leads in the funnel.", 12.0),
            StateFieldSpec("funnel_rfqs", "Open RFQs (requests for quotation).", 4.0),
            StateFieldSpec("funnel_contracts", "Won contracts awaiting project kickoff.", 2.0),
            StateFieldSpec(
                "funnel_projects",
                "Active projects (demand + product matching + project mgmt + manufacturing).",
                6.0,
            ),
            StateFieldSpec("funnel_deliveries_total", "Cumulative deliveries completed.", 12.0),
            StateFieldSpec(
                "funnel_prospects_total", "Cumulative prospects ever prospected.", 120.0
            ),
            # B2B funnel conversion RATES (Track 4): modeled quantities,
            # recomputed every tick by the template's tick drivers from
            # the sampled base rates + the satisfaction feedback (see
            # template_spec.py). 0-1; the overall rate is cumulative
            # deliveries / cumulative prospects.
            StateFieldSpec(
                "funnel_prospect_to_lead_rate", "Prospect-to-lead conversion rate.", 0.25
            ),
            StateFieldSpec("funnel_lead_to_rfq_rate", "Lead-to-RFQ conversion rate.", 0.30),
            StateFieldSpec("funnel_rfq_win_rate", "RFQ win rate.", 0.25),
            StateFieldSpec(
                "funnel_contract_to_project_rate", "Contract-to-project conversion rate.", 0.90
            ),
            StateFieldSpec(
                "funnel_project_to_delivery_rate", "Project-to-delivery rate per month.", 0.92
            ),
            StateFieldSpec(
                "funnel_overall_conversion",
                "Overall funnel conversion (cumulative deliveries / cumulative prospects).",
                0.10,
            ),
            # Delivery SATISFACTION (Track 4): 0-1 score, driven each tick
            # toward a delivery-performance target by its tick driver.
            # The feedback loop: this score (previous tick's value) lifts
            # or drags the lead-to-RFQ rate, the RFQ win rate, and prospect
            # inflow — satisfaction feeds the NEXT RFQ, modeled, not
            # overridden by hand.
            StateFieldSpec("delivery_satisfaction", "Delivery satisfaction score, 0-1.", 0.75),
            # Track 7 (2026-11-19, NEV transmission chain): company-level
            # magnitude fields for a representative Tier-1 supplier, so a
            # case can express revenue / profit / share trajectories on the
            # automotive domain exactly as corporate cases do (Fix 3 added
            # the same three fields to the corporate pack for the same
            # reason). Defaults mirror the corporate pack (100.0 / 20.0 /
            # 0.05, abstract units on the cash scale); a case declares its
            # own unit convention (e.g. RMB m per tick) through its
            # revenue/profit/market_share variables and tick-driver
            # formulas, exactly as cases already do for `market_share`.
            # No template driver moves these fields: generic automotive
            # runs leave them at their defaults, and only a case that
            # supplies the growth drivers (e.g. the Desay backtest, with
            # the NEV-chain revenue term) moves them. Adding the fields
            # changes no existing field's default or trajectory.
            StateFieldSpec("market_share", "Representative Tier-1 supplier market share.", 0.05),
            StateFieldSpec(
                "revenue",
                "Supplier revenue for the period, same abstract units as cash.",
                100.0,
            ),
            StateFieldSpec(
                "profit",
                "Supplier net profit for the period, same abstract units as cash.",
                20.0,
            ),
            # Track 11 (2026-11-19, order-book / backlog mechanism):
            # the shape term to the NEV chain's level term (Track 7
            # report §7). `order_backlog` is the stock of unfulfilled
            # orders (same units as the case's revenue, e.g. RMB m);
            # `order_intake` is the new-orders flow per tick (same
            # units). Both default to 0.0, so generic automotive runs
            # — which attach no backlog drivers — are exactly
            # unaffected, and only a case that supplies the backlog
            # drivers (the revenue term + the intake-decay and
            # backlog-update drivers, with the opening book/intake
            # bound as case variables) moves them. The opening book
            # is bound as a variable, not an initial formula: merge
            # is per-output, so an initial formula and a tick driver
            # cannot share an output id. The flow
            # decays per tick by (1 - order_decay), and the book
            # depletes on the D2C delivery schedule (2026-11-25:
            # backlog_delivery_fraction of the opening book per tick,
            # 0 in tick 1), so the backlog term shrinks as the order
            # surge passes and per-tick growth FALLS even while
            # penetration and adoption keep rising — the front-loaded
            # shape the monotone channels cannot express
            # (diagnostic-2020 §4).
            StateFieldSpec(
                "order_backlog",
                "Stock of unfulfilled orders, same units as revenue.",
                0.0,
            ),
            StateFieldSpec(
                "order_intake",
                "New orders arriving per tick, same units as revenue.",
                0.0,
            ),
            StateFieldSpec(
                "backlog_delivery_fraction",
                "Fraction of the opening order book delivered this tick (D2C delivery schedule, 0-1).",
                0.0,
            ),
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
            ActionSpec("qualify_leads", "Improve lead qualification in customer development."),
            ActionSpec("accelerate_rfq_response", "Respond to RFQs faster to lift the win rate."),
            ActionSpec(
                "improve_delivery_quality",
                "Improve on-time delivery and quality to lift satisfaction.",
            ),
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
            EventTypeSpec(
                "delivery_satisfaction_feedback",
                "Delivery satisfaction moved the next RFQ rate (satisfaction feedback loop).",
            ),
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

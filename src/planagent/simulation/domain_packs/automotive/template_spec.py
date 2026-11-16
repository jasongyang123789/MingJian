"""Built-in automotive variable template: raw spec dicts (Phase 1).

The spec lives here as plain JSON-shaped dicts so the domain pack stays
free of Pydantic imports; :func:`builtin_template` validates the dicts
into models at synthesis time and refuses to synthesize a broken
built-in. Every value cites the synthesis report
(``~/workspace/research/strategy-engine/auto-model-synthesis.md``) or is
explicitly marked as an assumption / simulated value. Nothing here is
presented as fact when the synthesis marks it unknown:

- ``assumption:pending-calibration`` — the synthesis lists the parameter
  with no initial value (C5); the number is a placeholder whose
  DIRECTION and MECHANISM are the Phase 1 deliverable, and whose
  magnitude is a sensitivity-analysis input.
- ``simulated:industry-average`` — Ho authorized industry-average
  SIMULATED values for supply share, payment terms, gross margin, and
  annual-cut execution (2026-11-16); replaceable via the template
  mechanism when internal data arrives. Do not block on internal data.

Variable ids MATCH state-field names wherever the variable IS a state
quantity: that alignment is what makes sampling move trajectories
(``resolve_run_values`` applies id-matched values to the initial state,
and levers can only target sampled ids — fixed-distribution variables
double as lever handles for the C4 scenario families).

Formula graph (evaluation order matters — drivers chain within a tick):

- ``demand_growth_rate`` (initial): monthly growth from confidence +
  income. The tax term is deliberately NOT here: a tax change is a
  LEVEL shift, and putting it in a monthly growth rate would compound
  it every tick.
- ``demand_level_factor`` (initial): the 2026-cliff event anchor
  (semi-elasticity 1.25, synthesis C2 link 2 — NON-structural, event
  observation only). Applied ONCE, on tick 1, by the retail driver via
  the first-tick indicator ``max(0, min(1, 2 - tick))``.
- ``pull_forward_stock_initial`` (initial): captures the sampled
  pull-forward stock so the retail driver can form the decay ratio
  (a driver self-reference reads the CURRENT state, never the initial
  value — the separate initial formula is the only way to see both).
- Drivers, in order: pull-forward decay → retail → inventory →
  production → generation transition. Each driver is self-referential,
  so rule effects applied earlier in the same tick are PRESERVED (the
  driver transforms the post-rule state, it does not reset it).
"""

from __future__ import annotations

# Fixed-distribution variables double as C4 scenario lever handles: a
# lever can only replace a sampled value, so every C4 lever id must be a
# sampled variable. Fixed values equal the pack defaults, so a run with
# the built-in template starts from the same state as a run without
# bindings, except for the triangular variables below.
TEMPLATE_VARIABLES: list[dict] = [
    # --- Demand drivers (D/V) ---
    {
        "id": "consumer_confidence_proxy",
        "unit": "index (1.0 = 2024Q4 baseline)",
        "distribution": {"type": "triangular", "min": 0.8, "mode": 1.0, "max": 1.2},
        "evidence_ref": "assumption:pending-calibration (synthesis B4: no unified public series; PBOC household-survey willingness proxy, 24.6% in 2024Q4)",
        "description": "Consumer-confidence proxy, normalized so 1.0 is the 2024Q4 survey baseline. Spread is a placeholder assumption (C5 lists no initial value for the transmission coefficient).",
    },
    {
        "id": "income_index",
        "unit": "index (1.0 = 2025)",
        "distribution": {"type": "fixed", "value": 1.0},
        "evidence_ref": "NBS via synthesis B4 (per-capita disposable income CNY 43,377 in 2025, nominal +5.0%)",
        "description": "Disposable-income level, 1.0 = 2025. The +5.0%/year path is an assumption parameter (C1).",
    },
    {
        "id": "policy_tax_rate",
        "unit": "rate",
        "distribution": {"type": "fixed", "value": 0.05},
        "evidence_ref": "MOF/STA/MIIT Announcement 2023 No.10 via synthesis B3 (NEV purchase tax halved to 5% in 2026-27, cap CNY 15k)",
        "description": "NEV purchase-tax rate. Lever to 0.10 for the post-2028 resumption scenario (C4 policy cliff; resumption is 'likely', not committed).",
    },
    {
        "id": "trade_in_support",
        "unit": "index (1.0 = 2026 scheme)",
        "distribution": {"type": "fixed", "value": 1.0},
        "evidence_ref": "assumption:pending-calibration (synthesis B3: 2026 proportional-cap scheme as the baseline)",
        "description": "Trade-in subsidy support strength, normalized so 1.0 is the 2026 proportional-cap scheme.",
    },
    {
        "id": "pull_forward_stock",
        "unit": "10k vehicles",
        "distribution": {"type": "fixed", "value": 1150.0},
        "evidence_ref": "NDRC/MOF via synthesis B3 (2025 trade-in scale exceeded 11.5M vehicles; 1150 is the stated lower bound)",
        "description": "Subsidy pull-forward stock: 2025 demand pulled forward, decaying back over 2026-27 (C2 link 11). The decay rate is an assumption parameter.",
    },
    # --- Supply / upstream drivers (D) ---
    {
        "id": "chip_lead_time_weeks",
        "unit": "weeks",
        "distribution": {"type": "fixed", "value": 26.2},
        "evidence_ref": "Susquehanna via synthesis B4 (2022-02 PEAK anchor, 26.2w average, MCU 35.7w; current value assumption:pending-calibration)",
        "description": "Average chip lead time. The pack/template value is the documented PEAK anchor, NOT a normal baseline — bind the current lead time per run; live values are a Phase 2 data item.",
    },
    {
        "id": "chip_supply_index",
        "unit": "index (1.0 = normal)",
        "distribution": {"type": "fixed", "value": 1.0},
        "evidence_ref": "assumption:pending-calibration (synthesis C2 link 6: 1.0 = normal supply baseline; China scaling factor is an assumption parameter)",
        "description": "Chip supply level. Below 1.0 constrains production through the production driver (C2 link 6).",
    },
    # --- Tier-1 / sales-strategy parameters (S): SIMULATED, Ho-authorized ---
    {
        "id": "annual_cut_rate",
        "unit": "rate/year",
        "distribution": {"type": "triangular", "min": 0.03, "mode": 0.04, "max": 0.05},
        "evidence_ref": "simulated:industry-average (synthesis B5: conventional 3-5%, stressed 10%+; Ho-authorized simulation 2026-11-16, replace with internal execution data)",
        "description": "Annual price-cut (year-down) rate demanded by OEMs. Conventional-range simulation; the stressed 10%+ regime is a C4 scenario lever.",
    },
    {
        "id": "payment_terms_months",
        "unit": "months",
        "distribution": {"type": "triangular", "min": 2.0, "mode": 6.0, "max": 9.0},
        "evidence_ref": "simulated:industry-average (synthesis B5: 6 months common, 60-day commitment floor, tails to 9+ months; Ho-authorized simulation 2026-11-16, replace with internal actuals)",
        "description": "Actual payment-terms length under the n+3+6 structure. Simulated industry average; Ho internal actuals take priority when they arrive.",
    },
    {
        "id": "tier1_gross_margin",
        "unit": "rate",
        "distribution": {"type": "triangular", "min": 0.188, "mode": 0.191, "max": 0.20},
        "evidence_ref": "simulated:industry-average (synthesis B2: Desay SV overall margin trajectory 20%/19.9%/19.1% 2023-25; Ho-authorized simulation 2026-11-16, replace with internal margin)",
        "description": "Tier-1 gross margin. Simulated from the listed-benchmark trajectory; Ho's own margin is an internal parameter.",
    },
    # --- Market structure (V) ---
    {
        "id": "nev_penetration",
        "unit": "rate",
        "distribution": {"type": "fixed", "value": 0.479},
        "evidence_ref": "CAAM via synthesis B1 (2025 total-volume NEV penetration 47.9%; retail caliber is higher and must never be mixed in)",
        "description": "NEV share of total vehicle sales (CAAM total-volume caliber). NEV/ICE dual-track dynamics are Phase 2 (v2).",
    },
    # --- Lever handles: C4 scenario ids, fixed at pack defaults ---
    {
        "id": "promo_rate",
        "unit": "rate",
        "distribution": {"type": "fixed", "value": 0.10},
        "evidence_ref": "CPCA via synthesis B1 (c.10% point value, Nov/Dec 2025, post-anti-involution stabilization; no continuous public series)",
        "description": "Terminal promotion rate. Lever upward for the C4 price-war scenario family.",
    },
    {
        "id": "price_index",
        "unit": "index (1.0 = 2025 avg)",
        "distribution": {"type": "fixed", "value": 1.0},
        "evidence_ref": "CPCA via synthesis C1 (anchored to the 2025 average retail price of CNY 170k)",
        "description": "Transaction price level, 1.0 = 2025 average.",
    },
    {
        "id": "price_cut_expectation",
        "unit": "rate",
        "distribution": {"type": "fixed", "value": 0.45},
        "evidence_ref": "Roland Berger/Autohome via synthesis B5 (wait-and-see buyer share 28% in 2023 to 45% in 2025H1)",
        "description": "Share of buyers waiting for price cuts. A state variable, not a static elasticity (C2 link 12).",
    },
    {
        "id": "dealer_inventory_coef",
        "unit": "coefficient",
        "distribution": {"type": "fixed", "value": 1.35},
        "evidence_ref": "CADA via synthesis B1 (1.35 in Sep 2025; 0.8-1.2 reasonable, above 1.5 is the warning line)",
        "description": "Dealer inventory coefficient (ending inventory / current sales). Evolves per tick from the wholesale-retail gap (C2 link 3).",
    },
    {
        "id": "production_volume",
        "unit": "10k vehicles/month",
        "distribution": {"type": "fixed", "value": 287.8},
        "evidence_ref": "CAAM-derived via synthesis C1 (2025 monthly-average derived value; VOLUME SPINE: OEM production incl. Audi, per Ho 2026-11-16)",
        "description": "Monthly production volume. The volume spine: if the OEM produces the car it needs the product, so production counts as a sale and export is irrelevant (Ho 2026-11-16).",
    },
    {
        "id": "dms_mandate",
        "unit": "0/1 switch",
        "distribution": {"type": "fixed", "value": 0.0},
        "evidence_ref": "GB 47955-2026 via synthesis B3 (mandatory DMS + accident recording from 2027-01-01; 0 until then)",
        "description": "DMS mandate switch. Lever to 1.0 for the C4 electronics-acceleration family (2027+). Phase 1 has no run calendar; the switch is lever-driven.",
    },
    {
        "id": "export_volume",
        "unit": "10k vehicles/month",
        "distribution": {"type": "fixed", "value": 59.2},
        "evidence_ref": "CAAM-derived via synthesis C1 (2025 monthly-average derived value from 7.098M vehicles, +21.1%)",
        "description": "Monthly export volume. A transmission intermediate in Phase 1, not part of the production volume spine.",
    },
    {
        "id": "sales_volume_retail",
        "unit": "10k vehicles/month",
        "distribution": {"type": "fixed", "value": 197.9},
        "evidence_ref": "CPCA-derived via synthesis B1/C1 (2025 MarkLines-CPCA retail 23.744M vehicles; monthly-average derived value, never mixed with CAAM caliber)",
        "description": "Monthly retail (terminal delivery). Transmission intermediate: retail feeds inventory, inventory feeds production (Ho 2026-11-16).",
    },
    {
        "id": "sales_volume_wholesale",
        "unit": "10k vehicles/month",
        "distribution": {"type": "fixed", "value": 246.3},
        "evidence_ref": "CPCA-derived via synthesis B1/C1 (2025 MarkLines-CPCA wholesale 29.554M vehicles; monthly-average derived value)",
        "description": "Monthly wholesale (OEM to dealer). Wholesale minus retail is the channel inventory change (C2 link 3).",
    },
    {
        "id": "capacity_utilization",
        "unit": "rate",
        "distribution": {"type": "fixed", "value": 0.662},
        "evidence_ref": "NBS via synthesis B1 (66.2% in 2026Q3, -7.1pp; 2021-24 range 72.2-74.7%)",
        "description": "Auto-manufacturing capacity utilization (NBS, quarterly). Brand-group splits are assumption parameters (C5).",
    },
    # --- Sensitivity coefficients (C5 assumption parameters) ---
    {
        "id": "confidence_sensitivity",
        "unit": "growth per index point",
        "distribution": {"type": "fixed", "value": 0.05},
        "evidence_ref": "assumption:pending-calibration (synthesis C5: the confidence transmission coefficient has no initial value; placeholder sensitivity for tornado analysis)",
        "description": "Monthly retail growth per point of the confidence proxy above 1.0. Magnitude is a placeholder; direction and mechanism are the Phase 1 deliverable.",
    },
    {
        "id": "income_sensitivity",
        "unit": "growth per index point",
        "distribution": {"type": "fixed", "value": 0.05},
        "evidence_ref": "assumption:pending-calibration (synthesis C5/A9: no public income elasticity exists; placeholder sensitivity for tornado analysis)",
        "description": "Monthly retail growth per point of the income index above 1.0. Magnitude is a placeholder; direction and mechanism are the Phase 1 deliverable.",
    },
    {
        "id": "tax_sensitivity",
        "unit": "level ratio per rate point",
        "distribution": {"type": "fixed", "value": 1.25},
        "evidence_ref": "synthesis C2 link 2 event anchor (2026 cliff: +20% low-band purchase cost, ~-25% volume; NON-structural semi-elasticity, sensitivity analysis only)",
        "description": "Retail LEVEL semi-elasticity to the purchase-tax rate: the 2026 cliff event anchor. Applied once (tick 1), never compounded. High-band behavior differs mechanistically and must not share this elasticity (C2).",
    },
]

TEMPLATE_FORMULAS: list[dict] = [
    {
        "output": "demand_growth_rate",
        "expression": {
            "op": "add",
            "args": [
                {
                    "op": "multiply",
                    "args": [
                        {"ref": "confidence_sensitivity"},
                        {"op": "subtract", "args": [{"ref": "consumer_confidence_proxy"}, 1]},
                    ],
                },
                {
                    "op": "multiply",
                    "args": [
                        {"ref": "income_sensitivity"},
                        {"op": "subtract", "args": [{"ref": "income_index"}, 1]},
                    ],
                },
            ],
        },
        "description": "Initial formula (once per run): monthly retail growth from confidence + income. The tax term is NOT here — a tax change is a level shift (see demand_level_factor).",
    },
    {
        "output": "demand_level_factor",
        "expression": {
            "op": "add",
            "args": [
                1,
                {
                    "op": "multiply",
                    "args": [
                        {"ref": "tax_sensitivity"},
                        {"op": "subtract", "args": [0.05, {"ref": "policy_tax_rate"}]},
                    ],
                },
            ],
        },
        "description": "Initial formula (once per run): retail LEVEL factor from the purchase-tax rate vs the 2026-27 5% baseline. 1.0 at the baseline rate; the retail driver applies it once, on tick 1.",
    },
    {
        "output": "pull_forward_stock_initial",
        "expression": {"ref": "pull_forward_stock"},
        "description": "Initial formula (once per run): captures the sampled pull-forward stock so the retail driver can form the decay ratio. A driver self-reference reads the CURRENT state, so the initial value needs its own id.",
    },
    {
        "output": "pull_forward_stock",
        "tick_driver": True,
        "expression": {
            "op": "multiply",
            "args": [{"ref": "pull_forward_stock"}, 0.98],
        },
        "description": "Tick driver (C2 link 11): pull-forward stock decays 2% per tick. The 2% rate is an assumption parameter (C5: no initial value, calibrate on 2026 actuals); literal in Phase 1, promote to a variable when calibrated.",
    },
    {
        "output": "sales_volume_retail",
        "tick_driver": True,
        "expression": {
            "op": "multiply",
            "args": [
                {
                    "op": "multiply",
                    "args": [
                        {"ref": "sales_volume_retail"},
                        {
                            "op": "subtract",
                            "args": [
                                {"op": "add", "args": [1, {"ref": "demand_growth_rate"}]},
                                {
                                    "op": "multiply",
                                    "args": [
                                        0.01,
                                        {
                                            "op": "divide",
                                            "args": [
                                                {"ref": "pull_forward_stock"},
                                                {
                                                    "op": "max",
                                                    "args": [
                                                        {"ref": "pull_forward_stock_initial"},
                                                        1,
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
                {
                    "op": "add",
                    "args": [
                        1,
                        {
                            "op": "multiply",
                            "args": [
                                {"op": "subtract", "args": [{"ref": "demand_level_factor"}, 1]},
                                {
                                    "op": "max",
                                    "args": [
                                        0,
                                        {
                                            "op": "min",
                                            "args": [
                                                1,
                                                {"op": "subtract", "args": [2, {"ref": "tick"}]},
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
        "description": "Tick driver (C2 links 2+11): retail compounds at (1 + demand growth - pull-forward drag), where the drag is 1% x the remaining pull-forward ratio (assumption parameter, literal in Phase 1). The tax LEVEL factor applies once, on tick 1, via the first-tick indicator max(0, min(1, 2 - tick)).",
    },
    {
        "output": "dealer_inventory_coef",
        "tick_driver": True,
        "expression": {
            "op": "add",
            "args": [
                {"ref": "dealer_inventory_coef"},
                {
                    "op": "multiply",
                    "args": [
                        0.1,
                        {
                            "op": "divide",
                            "args": [
                                {
                                    "op": "subtract",
                                    "args": [
                                        {"ref": "sales_volume_wholesale"},
                                        {"ref": "sales_volume_retail"},
                                    ],
                                },
                                {"op": "max", "args": [{"ref": "sales_volume_retail"}, 1]},
                            ],
                        },
                    ],
                },
            ],
        },
        "description": "Tick driver (C2 link 3): the inventory coefficient rises when wholesale exceeds retail. The 0.1 response coefficient is an assumption parameter (C2: calibratable from CADA series); literal in Phase 1. Reads the same-tick retail value (drivers chain in list order).",
    },
    {
        "output": "production_volume",
        "tick_driver": True,
        "expression": {
            "op": "multiply",
            "args": [
                {
                    "op": "multiply",
                    "args": [
                        {"ref": "production_volume"},
                        {
                            "op": "subtract",
                            "args": [
                                1,
                                {
                                    "op": "multiply",
                                    "args": [
                                        0.05,
                                        {
                                            "op": "subtract",
                                            "args": [{"ref": "dealer_inventory_coef"}, 1.2],
                                        },
                                    ],
                                },
                            ],
                        },
                    ],
                },
                {
                    "op": "add",
                    "args": [
                        1,
                        {
                            "op": "multiply",
                            "args": [
                                0.5,
                                {"op": "subtract", "args": [{"ref": "chip_supply_index"}, 1]},
                            ],
                        },
                    ],
                },
            ],
        },
        "description": "Tick driver (C2 links 5+6): production is cut when the inventory coefficient exceeds the 1.2 reasonable-band ceiling (CADA, B1) and constrained when chip supply falls below normal. The 0.05 inventory response and 0.5 chip response are assumption parameters (C5); literals in Phase 1. Reads the same-tick inventory value.",
    },
    {
        "output": "generation_transition_index",
        "tick_driver": True,
        "expression": {
            "op": "min",
            "args": [
                {"op": "add", "args": [{"ref": "generation_transition_index"}, 0.05]},
                1,
            ],
        },
        "description": "Tick driver (Ho 2026-11-16 generation dimension): the representative successor-generation share ramps 5 points per tick, capped at 1.0. The 5-point rate is an assumption parameter (literal in Phase 1); per-nameplate schedules are Phase 2.",
    },
]

# Assumption data shipped with the built-in template. The fitment lookup
# holds EXACTLY the published B2 cells — sparse series, not an invented
# full matrix. Cells the research does not publish are absent, and the
# consumer fails loudly on a missing cell instead of interpolating.
# Replaceable with Ho's real trim-split file via the template mechanism
# (stored template or inline binding override) with zero code change.
TEMPLATE_ASSUMPTION_DATA: dict = {
    "fitment_lookup": {
        "provenance": "synthesis B2 (agency estimates, calibers locked in B2; NOT Ho customer actuals)",
        "note": "Price bands in CNY 10k. Replace with Ho's trim-split file via the template mechanism.",
        "cell_notes": "NEV intelligent-cabin 0.90 is the stated lower bound ('>90%'); city-NOA '<20' 0.10 is approximate ('about 10%').",
        "l2_by_price_band": {
            "<10": 0.111,
            "10-15": 0.369,
            "15-20": 0.411,
            "20-30": 0.693,
            "30-40": 0.859,
            "40-60": 0.901,
        },
        "cockpit_domain_controller_by_price_band": {
            "<10": 0.093,
            "10-20": 0.417,
            ">20": 0.864,
        },
        "city_noa_by_price_band": {
            "<20": 0.10,
            "20-25": 0.297,
            "25-30": 0.57,
        },
        "intelligent_cabin_by_energy": {
            "NEV": 0.90,
            "ICE": 0.633,
        },
    },
    "supply_share_simulated": {
        "value": 0.10,
        "provenance": "simulated:industry-average — Ho-authorized placeholder (2026-11-16); a round neutral value, NOT an estimate. Replace with internal supply-share data when it arrives. Prospects always get 0, never this value.",
    },
}

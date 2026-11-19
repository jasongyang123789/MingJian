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
- ``calibration:v3`` — the value was fitted by
  ``planagent.services.calibration.transmission`` from decision-time
  public series (cutoff 2025-12-31); the method, window, gates, and
  sources are on the calibration report. Two of the eight
  transmission coefficients are calibrated v3 (income growth,
  NEV drift); the other six keep their placeholder values with the
  failed v3 attempt recorded in their evidence_ref — the report, not
  the label, is what changed for them.

Variable ids MATCH state-field names wherever the variable IS a state
quantity: that alignment is what makes sampling move trajectories
(``resolve_run_values`` applies id-matched values to the initial state,
and levers can only target sampled ids — fixed-distribution variables
double as lever handles for the C4 scenario families).

Formula graph (evaluation order matters — drivers chain within a tick):

- ``demand_growth_rate`` (initial): monthly growth from confidence
  ONLY. The income / LPR / price terms live in the retail driver,
  which reads the CURRENT state each tick (Phase 2): income and price
  evolve per tick, so freezing them into a once-per-run formula would
  double-count the level and miss the dynamics.
- ``demand_level_factor`` (initial): the 2026-cliff event anchor
  (semi-elasticity 1.25, synthesis C2 link 2 — NON-structural, event
  observation only). Applied ONCE, on tick 1, by the retail driver via
  the first-tick indicator ``max(0, min(1, 2 - tick))``.
- ``pull_forward_stock_initial`` (initial): captures the sampled
  pull-forward stock so the retail driver can form the decay ratio
  (a driver self-reference reads the CURRENT state, never the initial
  value — the separate initial formula is the only way to see both).
- Drivers, in order: pull-forward decay → price (partial adjustment
  toward the material-implied level) → income (monthly compounding
  of the annual growth rate) → retail (confidence + income + LPR +
  price + pull-forward drag, tax level factor on tick 1) → inventory
  → production → NEV penetration drift → NEV/ICE retail splits →
  NEV/ICE production splits → Tier-1 margin (unpassed material-cost
  pressure) → generation transition. Each driver is self-referential,
  so rule effects applied earlier in the same tick are PRESERVED (the
  driver transforms the post-rule state, it does not reset it) —
  except the four split drivers, which re-derive their fields from
  the spine x penetration each tick by construction.
"""

from __future__ import annotations

# Calibration v3 (elasticity calibration): the eight transmission
# coefficients below read their values from
# ``planagent.services.calibration.transmission`` (ADOPTED_VALUES) —
# the fitted value where the v3 gates passed, the prior placeholder
# where they did not. The template and the fit cannot drift apart:
# tests assert the template values equal ADOPTED_VALUES exactly. See
# the transmission module for the panel, the methods, the gates, and
# the per-coefficient adoption record.
from planagent.services.calibration.transmission import ADOPTED_VALUES

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
        "description": "Disposable-income level, 1.0 = 2025. Compounds monthly at income_growth_rate_annual/12 via the income tick driver (Phase 2); the retail driver reads the current level each tick (C2 link: income -> demand).",
    },
    {
        "id": "income_growth_rate_annual",
        "unit": "rate/year",
        "distribution": {"type": "fixed", "value": ADOPTED_VALUES["income_growth_rate_annual"]},
        "evidence_ref": "calibration:v3 (transmission.calibrate_transmission_coefficients; ridge location fit, lambda=5, toward prior 0.05 on NBS nominal per-capita disposable-income growth 2020-2025, n=6, mean 5.92%, fitted 5.50%; decision-time cutoff 2025-12-31; replaces the NBS 2025 single-year anchor)",
        "description": "Annual disposable-income growth rate. The income tick driver compounds the income_index monthly at this rate / 12 (C2 link: income -> demand). Promoted from a Phase 2 formula literal when the variable cap was raised from 30 to 100; calibrated v3 (ridge location fit on 2020-2025 NBS growth, 5.50%/year), a lever handle for income-growth scenarios.",
    },
    {
        "id": "lpr_proxy",
        "unit": "index (1.0 = baseline)",
        "distribution": {"type": "fixed", "value": 1.0},
        "evidence_ref": "calibration:v3 baseline definition (transmission.LPR_PROXY_BASELINE_PCT): lpr_proxy = 1y LPR / 3.85% (2020-2021 modal 1y LPR, the pre-easing level); 1.0 = 3.85%. The live LPR value is bound per run — no point value is baked in. (Was: assumption:pending-calibration, baseline undefined.)",
        "description": "Interest-rate environment proxy. Below 1.0 = easier financing, supporting demand through the retail driver (C2 link: LPR -> financing cost -> demand). Lever for the C4 monetary-easing family.",
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
    {
        "id": "material_cost_index",
        "unit": "index (1.0 = baseline)",
        "distribution": {"type": "fixed", "value": 1.0},
        "evidence_ref": "synthesis C1 (lithium + steel/aluminum proxy composite, 1.0 = baseline)",
        "description": "Raw-material cost pressure. Passes into transaction prices via the price driver (partial adjustment toward the material-implied level) and squeezes the Tier-1 margin via the margin driver while unpassed (C2 links 7-8).",
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
        "description": "NEV share of total vehicle sales (CAAM total-volume caliber). Drifts monthly via the penetration driver (Phase 2 dual track); the NEV/ICE split drivers derive each track from the shared spine x this penetration.",
    },
    {
        "id": "nev_penetration_monthly_drift",
        "unit": "rate points/month",
        "distribution": {"type": "fixed", "value": ADOPTED_VALUES["nev_penetration_monthly_drift"]},
        "evidence_ref": "calibration:v3 (transmission.calibrate_transmission_coefficients; OLS trend on CAAM total-caliber annual NEV penetration 2023-2025: 31.6% -> 40.9% -> 47.9%, slope +8.15pp/yr = 0.0068/mo, R2=0.993; cross-checks 2025-only 0.0058, 2025 Jul-Dec monthly anchors 0.0072, logistic recent segment 0.0059; decision-time cutoff 2025-12-31)",
        "description": "Monthly NEV penetration drift applied by the penetration tick driver, capped at 1.0. Promoted from a Phase 2 formula literal when the variable cap was raised from 30 to 100; calibrated v3 (OLS trend on CAAM 2023-2025, 0.0068/mo — the 0.002 placeholder implied +2.4pp/year against an observed +8.15pp/year trend), a lever handle for adoption-speed scenarios.",
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
        "distribution": {"type": "fixed", "value": ADOPTED_VALUES["confidence_sensitivity"]},
        "evidence_ref": "assumption:pending-calibration (synthesis C5: the confidence transmission coefficient has no initial value; placeholder sensitivity for tornado analysis; v3 NOT ESTIMABLE — no verifiable quarterly PBOC willingness series, see transmission.CALIBRATION_REPORT)",
        "description": "Monthly retail growth per point of the confidence proxy above 1.0. Magnitude is a placeholder; direction and mechanism are the Phase 1 deliverable.",
    },
    {
        "id": "income_sensitivity",
        "unit": "growth per index point",
        "distribution": {"type": "fixed", "value": ADOPTED_VALUES["income_sensitivity"]},
        "evidence_ref": "assumption:pending-calibration (synthesis C5/A9: no public income elasticity exists; v3 ATTEMPTED — joint ridge fit on the 2020-2025 annual panel gives beta=1.01 -> 0.153, but LOO RMSE 7.64pp fails the mean baseline 5.14pp and the slope is unstable across windows (OLS 1.18 with 2020, 0.27 without); placeholder RETAINED, see transmission.CALIBRATION_REPORT)",
        "description": "Monthly retail growth per point of the income index above 1.0. Magnitude is a placeholder; direction and mechanism are the Phase 1 deliverable.",
    },
    {
        "id": "tax_sensitivity",
        "unit": "level ratio per rate point",
        "distribution": {"type": "fixed", "value": 1.25},
        "evidence_ref": "synthesis C2 link 2 event anchor (2026 cliff: +20% low-band purchase cost, ~-25% volume; NON-structural semi-elasticity, sensitivity analysis only)",
        "description": "Retail LEVEL semi-elasticity to the purchase-tax rate: the 2026 cliff event anchor. Applied once (tick 1), never compounded. High-band behavior differs mechanistically and must not share this elasticity (C2).",
    },
    # --- Phase 2 transmission-link sensitivities (C5 assumption parameters) ---
    {
        "id": "lpr_sensitivity",
        "unit": "growth per index point",
        "distribution": {"type": "fixed", "value": ADOPTED_VALUES["lpr_sensitivity"]},
        "evidence_ref": "assumption:pending-calibration (synthesis C5: no public rate elasticity exists; v3 ATTEMPTED — joint ridge fit gives beta=-0.35 -> 0.112, but LOO RMSE 7.64pp fails the mean baseline 5.14pp and the bivariate slope flips sign across windows (OLS +13.08 with 2020, -5.97 without); placeholder RETAINED, see transmission.CALIBRATION_REPORT)",
        "description": "Monthly retail growth per point of the LPR proxy BELOW 1.0 (easing supports demand; tightening drags it). Magnitude is a placeholder; direction and mechanism are the Phase 2 deliverable.",
    },
    {
        "id": "material_passthrough",
        "unit": "price ratio per index point",
        "distribution": {"type": "fixed", "value": ADOPTED_VALUES["material_passthrough"]},
        "evidence_ref": "assumption:pending-calibration (synthesis C5: no public passthrough estimate exists; v3 NOT ESTIMABLE — one clean annual pair only (2023->2024: lithium -64.5%, avg price +0.5%), wrong sign, mix-shift dominated; composite weights undefined, see transmission.CALIBRATION_REPORT)",
        "description": "Share of raw-material cost pressure passed into transaction prices: the price driver's target level is 1 + passthrough x (material_cost_index - 1). The unpassed remainder squeezes the Tier-1 margin (C2 links 7-8).",
    },
    {
        "id": "price_sensitivity",
        "unit": "growth per index point",
        "distribution": {"type": "fixed", "value": ADOPTED_VALUES["price_sensitivity"]},
        "evidence_ref": "assumption:pending-calibration (synthesis C5/A9: no public price elasticity exists; v3 ATTEMPTED — joint ridge fit gives beta=-0.46 -> 0.039, but LOO RMSE 7.64pp fails the mean baseline 5.14pp; the joint 95% CI bounds price_sensitivity at [0, 0.159], so the 0.20 placeholder sits ABOVE the bound and is retained only as an upper-end sensitivity input, see transmission.CALIBRATION_REPORT)",
        "description": "Monthly retail growth drag per point of the price index above 1.0. Magnitude is a placeholder; direction and mechanism are the Phase 2 deliverable.",
    },
    {
        "id": "margin_material_sensitivity",
        "unit": "margin points per index point",
        "distribution": {"type": "fixed", "value": ADOPTED_VALUES["margin_material_sensitivity"]},
        "evidence_ref": "assumption:pending-calibration (synthesis C5: no public cost-to-margin transmission estimate exists; v3 NOT ESTIMABLE — wrong-sign episode: Desay margins fell 20% -> 19.1% (2023-25) while lithium collapsed, i.e. unpassed pressure was negative; the margin driver lacks the annual-cut channel, see transmission.CALIBRATION_REPORT)",
        "description": "Tier-1 margin points lost per tick per point of unpassed material-cost pressure (material_cost_index minus the current price index). Price passthrough mitigates the squeeze.",
    },
    # NOTE (cap raised, 2026-11-17): the variable-set limit was 30
    # (Sprint 2 design pin) and this template held exactly 30, so the
    # income growth rate and the penetration drift stayed formula
    # literals in Phase 2. Ho raised the cap to 100; both rates are
    # now template variables (income_growth_rate_annual,
    # nev_penetration_monthly_drift) and the drivers reference them.
    # The income LEVEL (income_index) and penetration LEVEL
    # (nev_penetration) remain sampled lever handles.
]

TEMPLATE_FORMULAS: list[dict] = [
    {
        "output": "demand_growth_rate",
        "expression": {
            "op": "multiply",
            "args": [
                {"ref": "confidence_sensitivity"},
                {"op": "subtract", "args": [{"ref": "consumer_confidence_proxy"}, 1]},
            ],
        },
        "description": "Initial formula (once per run): monthly retail growth from confidence ONLY (Phase 2: the income term moved into the retail driver, which reads the current income level each tick; the LPR and price terms live there too). The tax term is NOT here — a tax change is a level shift (see demand_level_factor).",
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
        "output": "price_index",
        "tick_driver": True,
        "expression": {
            "op": "add",
            "args": [
                {"ref": "price_index"},
                {
                    "op": "multiply",
                    "args": [
                        0.5,
                        {
                            "op": "subtract",
                            "args": [
                                {
                                    "op": "add",
                                    "args": [
                                        1,
                                        {
                                            "op": "multiply",
                                            "args": [
                                                {"ref": "material_passthrough"},
                                                {
                                                    "op": "subtract",
                                                    "args": [{"ref": "material_cost_index"}, 1],
                                                },
                                            ],
                                        },
                                    ],
                                },
                                {"ref": "price_index"},
                            ],
                        },
                    ],
                },
            ],
        },
        "description": "Tick driver (C2 link 7, Phase 2): partial adjustment toward the material-implied price level 1 + passthrough x (material - 1). The 0.5 adjustment speed is an assumption parameter (literal, Phase 2); at the baseline (material = 1) the driver is a no-op. Rule effects on price are preserved in the level but mean-revert toward the cost-implied target.",
    },
    {
        "output": "income_index",
        "tick_driver": True,
        "expression": {
            "op": "multiply",
            "args": [
                {"ref": "income_index"},
                {
                    "op": "add",
                    "args": [
                        1,
                        {"op": "divide", "args": [{"ref": "income_growth_rate_annual"}, 12]},
                    ],
                },
            ],
        },
        "description": "Tick driver (C2 link: income -> demand, Phase 2): disposable income compounds monthly at income_growth_rate_annual / 12 (calibrated v3: ridge location fit on NBS 2020-2025 growth, 5.50%/year; promoted from a Phase 2 literal when the cap was raised to 100). The retail driver reads the current level each tick.",
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
                                {
                                    "op": "subtract",
                                    "args": [
                                        {
                                            "op": "subtract",
                                            "args": [
                                                {
                                                    "op": "add",
                                                    "args": [
                                                        {
                                                            "op": "add",
                                                            "args": [
                                                                1,
                                                                {"ref": "demand_growth_rate"},
                                                            ],
                                                        },
                                                        {
                                                            "op": "multiply",
                                                            "args": [
                                                                {"ref": "income_sensitivity"},
                                                                {
                                                                    "op": "subtract",
                                                                    "args": [
                                                                        {"ref": "income_index"},
                                                                        1,
                                                                    ],
                                                                },
                                                            ],
                                                        },
                                                    ],
                                                },
                                                {
                                                    "op": "multiply",
                                                    "args": [
                                                        {"ref": "lpr_sensitivity"},
                                                        {
                                                            "op": "subtract",
                                                            "args": [{"ref": "lpr_proxy"}, 1],
                                                        },
                                                    ],
                                                },
                                            ],
                                        },
                                        {
                                            "op": "multiply",
                                            "args": [
                                                {"ref": "price_sensitivity"},
                                                {
                                                    "op": "subtract",
                                                    "args": [{"ref": "price_index"}, 1],
                                                },
                                            ],
                                        },
                                    ],
                                },
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
        "description": "Tick driver (C2 links 2+11, Phase 2 transmission links): retail compounds at (1 + demand growth + income term - LPR term - price term - pull-forward drag), where the income term reads the CURRENT income level, the LPR term reads the CURRENT rate proxy (easing supports demand), and the price term reads the CURRENT price level (same-tick drivers chain in list order). The drag is 1% x the remaining pull-forward ratio (assumption parameter, literal). The tax LEVEL factor applies once, on tick 1, via the first-tick indicator max(0, min(1, 2 - tick)).",
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
        "output": "nev_penetration",
        "tick_driver": True,
        "expression": {
            "op": "min",
            "args": [
                {
                    "op": "add",
                    "args": [{"ref": "nev_penetration"}, {"ref": "nev_penetration_monthly_drift"}],
                },
                1,
            ],
        },
        "description": "Tick driver (Phase 2 dual track): NEV penetration drifts nev_penetration_monthly_drift per month (0.0068/mo, calibrated v3: OLS trend on CAAM 2023-2025), capped at 1.0. The drift is a calibrated value (promoted from a Phase 2 literal when the cap was raised to 100); the split drivers below read the same-tick value.",
    },
    {
        "output": "nev_retail_volume",
        "tick_driver": True,
        "expression": {
            "op": "multiply",
            "args": [{"ref": "sales_volume_retail"}, {"ref": "nev_penetration"}],
        },
        "description": "Tick driver (Phase 2 dual track): NEV retail is the shared retail spine x the same-tick NEV penetration. Re-derived each tick; sums with ice_retail_volume to the spine by construction.",
    },
    {
        "output": "ice_retail_volume",
        "tick_driver": True,
        "expression": {
            "op": "multiply",
            "args": [
                {"ref": "sales_volume_retail"},
                {"op": "subtract", "args": [1, {"ref": "nev_penetration"}]},
            ],
        },
        "description": "Tick driver (Phase 2 dual track): ICE retail is the shared retail spine x (1 - NEV penetration).",
    },
    {
        "output": "nev_production_volume",
        "tick_driver": True,
        "expression": {
            "op": "multiply",
            "args": [{"ref": "production_volume"}, {"ref": "nev_penetration"}],
        },
        "description": "Tick driver (Phase 2 dual track): NEV production is the shared production spine x the same-tick NEV penetration. Sums with ice_production_volume to the spine by construction.",
    },
    {
        "output": "ice_production_volume",
        "tick_driver": True,
        "expression": {
            "op": "multiply",
            "args": [
                {"ref": "production_volume"},
                {"op": "subtract", "args": [1, {"ref": "nev_penetration"}]},
            ],
        },
        "description": "Tick driver (Phase 2 dual track): ICE production is the shared production spine x (1 - NEV penetration).",
    },
    {
        "output": "tier1_gross_margin",
        "tick_driver": True,
        "expression": {
            "op": "subtract",
            "args": [
                {"ref": "tier1_gross_margin"},
                {
                    "op": "multiply",
                    "args": [
                        {"ref": "margin_material_sensitivity"},
                        {
                            "op": "subtract",
                            "args": [{"ref": "material_cost_index"}, {"ref": "price_index"}],
                        },
                    ],
                },
            ],
        },
        "description": "Tick driver (C2 link 8, Phase 2): the Tier-1 margin is squeezed by UNPASSED material-cost pressure — the gap between the material cost index and the current (same-tick) price level. Price passthrough mitigates the squeeze; at the baseline (material = price = 1) the driver is a no-op. Coarse dynamics: no floor, horizons are 6-12 ticks.",
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
        "description": "Tick driver (Ho 2026-11-16 generation dimension): the representative successor-generation share ramps 5 points per tick, capped at 1.0. The 5-point rate is an assumption parameter (literal in Phase 1). Per-nameplate schedules (Phase 2) live in the split structure and drive S-layer aggregation; this global index remains the coarse engine-level representative for trajectory display.",
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

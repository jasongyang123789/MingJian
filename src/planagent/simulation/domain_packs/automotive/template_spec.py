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

- ``funnel_*`` drivers (Track 4, one-click funnel + satisfaction
  feedback): rates from the sampled bases + the PREVIOUS tick's
  satisfaction (one-tick feedback lag, by driver order) -> flow
  intermediates (``funnel_new_*``, not state fields) -> pipeline
  stocks -> satisfaction (20% toward the delivery-performance
  target) -> the overall-conversion identity. See the driver
  descriptions at the end of ``TEMPLATE_FORMULAS``.
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
        "description": "Disposable-income level, 1.0 = 2025. Compounds monthly at income_growth_rate_annual/12 via the income tick driver (Phase 2); the retail driver reads the current level each tick (C2 link: income -> demand).",
    },
    {
        "id": "income_growth_rate_annual",
        "unit": "rate/year",
        "distribution": {"type": "fixed", "value": 0.05},
        "evidence_ref": "NBS via synthesis B4 (per-capita disposable income nominal +5.0% in 2025; same anchor as income_index)",
        "description": "Annual disposable-income growth rate. The income tick driver compounds the income_index monthly at this rate / 12 (C2 link: income -> demand). Promoted from a Phase 2 formula literal when the variable cap was raised from 30 to 100; fixed at the NBS 2025 value, a lever handle for income-growth scenarios.",
    },
    {
        "id": "lpr_proxy",
        "unit": "index (1.0 = baseline)",
        "distribution": {"type": "fixed", "value": 1.0},
        "evidence_ref": "assumption:pending-calibration (synthesis C1/B4: normalized index, 1.0 = baseline; the live LPR value is bound per run — no point value is baked in)",
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
        "distribution": {"type": "fixed", "value": 0.002},
        "evidence_ref": "assumption:pending-calibration (synthesis C5: placeholder drift; no public monthly penetration-drift series exists — direction and mechanism are the Phase 2 deliverable, magnitude is a sensitivity-analysis input)",
        "description": "Monthly NEV penetration drift applied by the penetration tick driver, capped at 1.0. Promoted from a Phase 2 formula literal when the variable cap was raised from 30 to 100; placeholder magnitude, a lever handle for adoption-speed scenarios.",
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
    # --- Phase 2 transmission-link sensitivities (C5 assumption parameters) ---
    {
        "id": "lpr_sensitivity",
        "unit": "growth per index point",
        "distribution": {"type": "fixed", "value": 0.10},
        "evidence_ref": "assumption:pending-calibration (synthesis C5: no public rate elasticity exists; placeholder sensitivity for tornado analysis)",
        "description": "Monthly retail growth per point of the LPR proxy BELOW 1.0 (easing supports demand; tightening drags it). Magnitude is a placeholder; direction and mechanism are the Phase 2 deliverable.",
    },
    {
        "id": "material_passthrough",
        "unit": "price ratio per index point",
        "distribution": {"type": "fixed", "value": 0.30},
        "evidence_ref": "assumption:pending-calibration (synthesis C5: no public passthrough estimate exists; placeholder sensitivity for tornado analysis)",
        "description": "Share of raw-material cost pressure passed into transaction prices: the price driver's target level is 1 + passthrough x (material_cost_index - 1). The unpassed remainder squeezes the Tier-1 margin (C2 links 7-8).",
    },
    {
        "id": "price_sensitivity",
        "unit": "growth per index point",
        "distribution": {"type": "fixed", "value": 0.20},
        "evidence_ref": "assumption:pending-calibration (synthesis C5/A9: no public price elasticity exists; placeholder sensitivity for tornado analysis)",
        "description": "Monthly retail growth drag per point of the price index above 1.0. Magnitude is a placeholder; direction and mechanism are the Phase 2 deliverable.",
    },
    {
        "id": "margin_material_sensitivity",
        "unit": "margin points per index point",
        "distribution": {"type": "fixed", "value": 0.02},
        "evidence_ref": "assumption:pending-calibration (synthesis C5: no public cost-to-margin transmission estimate exists; placeholder sensitivity)",
        "description": "Tier-1 margin points lost per tick per point of unpassed material-cost pressure (material_cost_index minus the current price index). Price passthrough mitigates the squeeze.",
    },
    # --- B2B funnel + satisfaction feedback (Track 4, one-click) ---
    # The 8-stage Tier-1 chain (customer development -> lead funnel ->
    # RFQ/contract -> demand/product matching/project mgmt -> manufacturing
    # -> delivery satisfaction) as MODELED quantities: the base rates and
    # the feedback gain are sampled variables, and the tick drivers at the
    # end of TEMPLATE_FORMULAS turn them into per-tick conversion rates,
    # pipeline stocks, and the satisfaction score. No manual variable
    # override is needed to run the funnel — attaching the built-in
    # template is the one click. All magnitudes are
    # assumption:pending-calibration (no public Tier-1 funnel series
    # exists); directions and mechanisms are the deliverable.
    {
        "id": "prospect_inflow_monthly",
        "unit": "accounts/month",
        "distribution": {"type": "fixed", "value": 4.0},
        "evidence_ref": "assumption:pending-calibration (no public Tier-1 prospecting series exists; placeholder inflow for the customer-development stage)",
        "description": "New target accounts prospected per month (customer-development stage). The funnel_new_prospects driver lifts this inflow with delivery satisfaction (referral / reputation), so satisfaction feeds the top of the NEXT funnel.",
    },
    {
        "id": "funnel_prospect_to_lead_base",
        "unit": "rate",
        "distribution": {"type": "triangular", "min": 0.15, "mode": 0.25, "max": 0.35},
        "evidence_ref": "assumption:pending-calibration (no public Tier-1 prospect-to-lead series exists; placeholder spread for sensitivity analysis)",
        "description": "Base prospect-to-lead conversion rate (customer development -> qualified lead).",
    },
    {
        "id": "funnel_lead_to_rfq_base",
        "unit": "rate",
        "distribution": {"type": "triangular", "min": 0.20, "mode": 0.30, "max": 0.45},
        "evidence_ref": "assumption:pending-calibration (no public Tier-1 lead-to-RFQ series exists; placeholder spread for sensitivity analysis)",
        "description": "Base lead-to-RFQ conversion rate. The tick driver scales it by the previous tick's delivery satisfaction (feedback loop).",
    },
    {
        "id": "funnel_rfq_win_base",
        "unit": "rate",
        "distribution": {"type": "triangular", "min": 0.15, "mode": 0.25, "max": 0.35},
        "evidence_ref": "assumption:pending-calibration (no public Tier-1 RFQ win-rate series exists; placeholder spread for sensitivity analysis)",
        "description": "Base RFQ win rate (RFQ -> contract). The tick driver scales it by the previous tick's delivery satisfaction (feedback loop).",
    },
    {
        "id": "funnel_contract_to_project_base",
        "unit": "rate",
        "distribution": {"type": "triangular", "min": 0.80, "mode": 0.90, "max": 0.95},
        "evidence_ref": "assumption:pending-calibration (no public Tier-1 contract-to-project series exists; placeholder spread for sensitivity analysis)",
        "description": "Base contract-to-project conversion rate (won contract -> active project: demand management + product matching + project kickoff).",
    },
    {
        "id": "funnel_project_to_delivery_base",
        "unit": "rate/month",
        "distribution": {"type": "triangular", "min": 0.85, "mode": 0.92, "max": 0.97},
        "evidence_ref": "assumption:pending-calibration (no public Tier-1 project-to-delivery series exists; placeholder spread for sensitivity analysis)",
        "description": "Base share of active projects delivering per month (manufacturing follow-up -> delivery). The tick driver scales it by chip supply (0.7 + 0.3 x chip_supply_index).",
    },
    {
        "id": "satisfaction_feedback_gain",
        "unit": "fraction per satisfaction point",
        "distribution": {"type": "fixed", "value": 1.0},
        "evidence_ref": "assumption:pending-calibration (no measured satisfaction-to-RFQ elasticity exists; placeholder gain — a 0.10 satisfaction gap above/below the 0.75 neutral level moves the RFQ rates and prospect inflow by 10% relative)",
        "description": "Satisfaction feedback gain: each point of delivery satisfaction above the 0.75 neutral level lifts the lead-to-RFQ rate, the RFQ win rate, and prospect inflow by this fraction (relative), and drags them by the same fraction below neutral.",
    },
    # Funnel ATTRITION (Track 4): the monthly share of each pipeline
    # stock that leaves the funnel WITHOUT converting (prospects go cold,
    # leads die, RFQs are lost to competitors / no-decision, contracts
    # are cancelled before kickoff, projects are cancelled before
    # delivery). Without attrition the funnel would be lossless and the
    # overall conversion would drift to 1.0 — every prospect would
    # eventually deliver, which is not a funnel. With these defaults the
    # end-to-end yield tends to the product of the stage yields
    # rate/(rate+attrition) ≈ 0.41. Fixed placeholders, assumption-labeled.
    {
        "id": "funnel_prospect_attrition",
        "unit": "rate/month",
        "distribution": {"type": "fixed", "value": 0.10},
        "evidence_ref": "assumption:pending-calibration (no public Tier-1 prospect-churn series exists; placeholder attrition for the customer-development stage)",
        "description": "Monthly share of open prospects that go cold without becoming leads.",
    },
    {
        "id": "funnel_lead_attrition",
        "unit": "rate/month",
        "distribution": {"type": "fixed", "value": 0.10},
        "evidence_ref": "assumption:pending-calibration (no public Tier-1 lead-decay series exists; placeholder attrition for the lead stage)",
        "description": "Monthly share of qualified leads that die without issuing an RFQ.",
    },
    {
        "id": "funnel_rfq_attrition",
        "unit": "rate/month",
        "distribution": {"type": "fixed", "value": 0.05},
        "evidence_ref": "assumption:pending-calibration (no public Tier-1 RFQ-loss series exists; placeholder attrition for lost / no-decision RFQs)",
        "description": "Monthly share of open RFQs lost to competitors or no-decision without becoming contracts.",
    },
    {
        "id": "funnel_contract_attrition",
        "unit": "rate/month",
        "distribution": {"type": "fixed", "value": 0.05},
        "evidence_ref": "assumption:pending-calibration (no public Tier-1 contract-cancellation series exists; placeholder attrition for the contract stage)",
        "description": "Monthly share of won contracts cancelled before project kickoff.",
    },
    {
        "id": "funnel_project_attrition",
        "unit": "rate/month",
        "distribution": {"type": "fixed", "value": 0.02},
        "evidence_ref": "assumption:pending-calibration (no public Tier-1 project-cancellation series exists; placeholder attrition for the project stage)",
        "description": "Monthly share of active projects cancelled before delivery.",
    },
    # Funnel pipeline stocks + satisfaction as fixed state-matching
    # variables (lever handles, = pack defaults): the initial pipeline is
    # a per-run binding, exactly like production_volume.
    {
        "id": "funnel_prospects",
        "unit": "accounts",
        "distribution": {"type": "fixed", "value": 40.0},
        "evidence_ref": "assumption:pending-calibration (placeholder pipeline stock; bind the real CRM pipeline per run)",
        "description": "Open prospect accounts in customer development at run start.",
    },
    {
        "id": "funnel_leads",
        "unit": "accounts",
        "distribution": {"type": "fixed", "value": 12.0},
        "evidence_ref": "assumption:pending-calibration (placeholder pipeline stock; bind the real CRM pipeline per run)",
        "description": "Qualified leads in the funnel at run start.",
    },
    {
        "id": "funnel_rfqs",
        "unit": "accounts",
        "distribution": {"type": "fixed", "value": 4.0},
        "evidence_ref": "assumption:pending-calibration (placeholder pipeline stock; bind the real CRM pipeline per run)",
        "description": "Open RFQs at run start.",
    },
    {
        "id": "funnel_contracts",
        "unit": "accounts",
        "distribution": {"type": "fixed", "value": 2.0},
        "evidence_ref": "assumption:pending-calibration (placeholder pipeline stock; bind the real CRM pipeline per run)",
        "description": "Won contracts awaiting project kickoff at run start.",
    },
    {
        "id": "funnel_projects",
        "unit": "accounts",
        "distribution": {"type": "fixed", "value": 6.0},
        "evidence_ref": "assumption:pending-calibration (placeholder pipeline stock; bind the real CRM pipeline per run)",
        "description": "Active projects at run start.",
    },
    {
        "id": "funnel_deliveries_total",
        "unit": "accounts",
        "distribution": {"type": "fixed", "value": 12.0},
        "evidence_ref": "assumption:pending-calibration (placeholder cumulative count, consistent with the 0.10 overall-conversion default; bind real delivery history per run)",
        "description": "Cumulative deliveries completed before the run.",
    },
    {
        "id": "funnel_prospects_total",
        "unit": "accounts",
        "distribution": {"type": "fixed", "value": 120.0},
        "evidence_ref": "assumption:pending-calibration (placeholder cumulative count, consistent with the 0.10 overall-conversion default; bind real prospecting history per run)",
        "description": "Cumulative prospects ever prospected before the run.",
    },
    {
        "id": "delivery_satisfaction",
        "unit": "score 0-1",
        "distribution": {"type": "fixed", "value": 0.75},
        "evidence_ref": "assumption:pending-calibration (no public Tier-1 delivery-satisfaction series exists; 0.75 is the neutral level of the feedback loop, not a measured score)",
        "description": "Delivery satisfaction score at run start (0-1). Also the feedback-loop input: the tick-1 RFQ rates read this value, so an initial_state override of satisfaction moves the funnel from tick 1.",
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
        "description": "Tick driver (C2 link: income -> demand, Phase 2): disposable income compounds monthly at income_growth_rate_annual / 12 (NBS 2025 nominal growth, 5.0%/year; promoted from a Phase 2 literal when the cap was raised to 100). The retail driver reads the current level each tick.",
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
        "description": "Tick driver (Phase 2 dual track): NEV penetration drifts nev_penetration_monthly_drift per month (0.002 placeholder), capped at 1.0. The drift is a placeholder assumption parameter (promoted from a Phase 2 literal when the cap was raised to 100); the split drivers below read the same-tick value.",
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
    # --- B2B funnel + satisfaction feedback drivers (Track 4) ---
    # Order matters (drivers chain within a tick): RATES first (from the
    # sampled bases + the PREVIOUS tick's satisfaction — the satisfaction
    # driver runs later in this list, so the RFQ rates read last tick's
    # score: the feedback lag is one tick by construction), then FLOW
    # intermediates (funnel_new_*, not state fields — the engine applies
    # only driver outputs that name a state field, but later drivers in
    # the same tick still see them), then STOCKS (self-referential, so
    # rule effects on a stock persist instead of being overwritten),
    # then SATISFACTION, then the OVERALL conversion identity.
    {
        "output": "funnel_prospect_to_lead_rate",
        "tick_driver": True,
        "expression": {"ref": "funnel_prospect_to_lead_base"},
        "description": "Tick driver (Track 4): prospect-to-lead rate is the sampled base rate. Top of funnel; no satisfaction link — prospecting quality, not reputation.",
    },
    {
        "output": "funnel_lead_to_rfq_rate",
        "tick_driver": True,
        "expression": {
            "op": "min",
            "args": [
                0.95,
                {
                    "op": "max",
                    "args": [
                        0,
                        {
                            "op": "multiply",
                            "args": [
                                {"ref": "funnel_lead_to_rfq_base"},
                                {
                                    "op": "add",
                                    "args": [
                                        1,
                                        {
                                            "op": "multiply",
                                            "args": [
                                                {"ref": "satisfaction_feedback_gain"},
                                                {
                                                    "op": "subtract",
                                                    "args": [
                                                        {"ref": "delivery_satisfaction"},
                                                        0.75,
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
        "description": "Tick driver (Track 4, FEEDBACK LOOP): lead-to-RFQ rate = base x (1 + gain x (satisfaction - 0.75)), clamped to [0, 0.95]. The satisfaction read is the PREVIOUS tick's score (this driver runs before the satisfaction driver), so a delivery delight/disappointment moves next month's RFQ inflow, not the same month's.",
    },
    {
        "output": "funnel_rfq_win_rate",
        "tick_driver": True,
        "expression": {
            "op": "min",
            "args": [
                0.95,
                {
                    "op": "max",
                    "args": [
                        0,
                        {
                            "op": "multiply",
                            "args": [
                                {"ref": "funnel_rfq_win_base"},
                                {
                                    "op": "add",
                                    "args": [
                                        1,
                                        {
                                            "op": "multiply",
                                            "args": [
                                                {"ref": "satisfaction_feedback_gain"},
                                                {
                                                    "op": "subtract",
                                                    "args": [
                                                        {"ref": "delivery_satisfaction"},
                                                        0.75,
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
        "description": "Tick driver (Track 4, FEEDBACK LOOP): RFQ win rate = base x (1 + gain x (satisfaction - 0.75)), clamped to [0, 0.95]. Same one-tick feedback lag as the lead-to-RFQ rate: satisfied customers re-buy and refer, dissatisfied ones do not.",
    },
    {
        "output": "funnel_contract_to_project_rate",
        "tick_driver": True,
        "expression": {"ref": "funnel_contract_to_project_base"},
        "description": "Tick driver (Track 4): contract-to-project rate is the sampled base rate (demand management + product matching + project kickoff).",
    },
    {
        "output": "funnel_project_to_delivery_rate",
        "tick_driver": True,
        "expression": {
            "op": "min",
            "args": [
                0.99,
                {
                    "op": "max",
                    "args": [
                        0,
                        {
                            "op": "multiply",
                            "args": [
                                {"ref": "funnel_project_to_delivery_base"},
                                {
                                    "op": "add",
                                    "args": [
                                        0.7,
                                        {
                                            "op": "multiply",
                                            "args": [0.3, {"ref": "chip_supply_index"}],
                                        },
                                    ],
                                },
                            ],
                        },
                    ],
                },
            ],
        },
        "description": "Tick driver (Track 4): project-to-delivery rate = base x (0.7 + 0.3 x chip_supply_index), clamped to [0, 0.99]. Manufacturing follow-up is chip-constrained (C2 link 6); at normal supply (1.0) the rate is the base. This rate also sets the satisfaction target below, so a supply squeeze drags satisfaction next tick.",
    },
    {
        "output": "funnel_new_prospects",
        "tick_driver": True,
        "expression": {
            "op": "multiply",
            "args": [
                {"ref": "prospect_inflow_monthly"},
                {
                    "op": "add",
                    "args": [
                        1,
                        {
                            "op": "multiply",
                            "args": [
                                {"ref": "satisfaction_feedback_gain"},
                                {
                                    "op": "subtract",
                                    "args": [{"ref": "delivery_satisfaction"}, 0.75],
                                },
                            ],
                        },
                    ],
                },
            ],
        },
        "description": "Tick driver (Track 4, FEEDBACK LOOP, intermediate — not a state field): new prospects this month = inflow x (1 + gain x (satisfaction - 0.75)). Referral/reputation channel: high satisfaction brings more prospects next month. Reads the previous tick's satisfaction, like the RFQ rates.",
    },
    {
        "output": "funnel_new_leads",
        "tick_driver": True,
        "expression": {
            "op": "multiply",
            "args": [{"ref": "funnel_prospects"}, {"ref": "funnel_prospect_to_lead_rate"}],
        },
        "description": "Tick driver (Track 4, intermediate): new qualified leads this month = open prospects x the same-tick prospect-to-lead rate.",
    },
    {
        "output": "funnel_new_rfqs",
        "tick_driver": True,
        "expression": {
            "op": "multiply",
            "args": [{"ref": "funnel_leads"}, {"ref": "funnel_lead_to_rfq_rate"}],
        },
        "description": "Tick driver (Track 4, intermediate): new RFQs this month = qualified leads x the same-tick lead-to-RFQ rate.",
    },
    {
        "output": "funnel_new_contracts",
        "tick_driver": True,
        "expression": {
            "op": "multiply",
            "args": [{"ref": "funnel_rfqs"}, {"ref": "funnel_rfq_win_rate"}],
        },
        "description": "Tick driver (Track 4, intermediate): new contracts this month = open RFQs x the same-tick win rate.",
    },
    {
        "output": "funnel_new_projects",
        "tick_driver": True,
        "expression": {
            "op": "multiply",
            "args": [{"ref": "funnel_contracts"}, {"ref": "funnel_contract_to_project_rate"}],
        },
        "description": "Tick driver (Track 4, intermediate): new projects this month = won contracts x the same-tick contract-to-project rate.",
    },
    {
        "output": "funnel_new_deliveries",
        "tick_driver": True,
        "expression": {
            "op": "multiply",
            "args": [{"ref": "funnel_projects"}, {"ref": "funnel_project_to_delivery_rate"}],
        },
        "description": "Tick driver (Track 4, intermediate): deliveries this month = active projects x the same-tick project-to-delivery rate.",
    },
    {
        "output": "funnel_prospects",
        "tick_driver": True,
        "expression": {
            "op": "max",
            "args": [
                0,
                {
                    "op": "subtract",
                    "args": [
                        {
                            "op": "subtract",
                            "args": [
                                {
                                    "op": "add",
                                    "args": [
                                        {"ref": "funnel_prospects"},
                                        {"ref": "funnel_new_prospects"},
                                    ],
                                },
                                {"ref": "funnel_new_leads"},
                            ],
                        },
                        {
                            "op": "multiply",
                            "args": [
                                {"ref": "funnel_prospects"},
                                {"ref": "funnel_prospect_attrition"},
                            ],
                        },
                    ],
                },
            ],
        },
        "description": "Tick driver (Track 4): open prospects = previous + new prospects - new leads - attrition (prospects going cold), floored at 0. Self-referential, so rule effects on the stock (e.g. a prospecting push) persist.",
    },
    {
        "output": "funnel_leads",
        "tick_driver": True,
        "expression": {
            "op": "max",
            "args": [
                0,
                {
                    "op": "subtract",
                    "args": [
                        {
                            "op": "subtract",
                            "args": [
                                {
                                    "op": "add",
                                    "args": [{"ref": "funnel_leads"}, {"ref": "funnel_new_leads"}],
                                },
                                {"ref": "funnel_new_rfqs"},
                            ],
                        },
                        {
                            "op": "multiply",
                            "args": [{"ref": "funnel_leads"}, {"ref": "funnel_lead_attrition"}],
                        },
                    ],
                },
            ],
        },
        "description": "Tick driver (Track 4): qualified leads = previous + new leads - new RFQs - attrition (leads dying), floored at 0.",
    },
    {
        "output": "funnel_rfqs",
        "tick_driver": True,
        "expression": {
            "op": "max",
            "args": [
                0,
                {
                    "op": "subtract",
                    "args": [
                        {
                            "op": "subtract",
                            "args": [
                                {
                                    "op": "add",
                                    "args": [{"ref": "funnel_rfqs"}, {"ref": "funnel_new_rfqs"}],
                                },
                                {"ref": "funnel_new_contracts"},
                            ],
                        },
                        {
                            "op": "multiply",
                            "args": [{"ref": "funnel_rfqs"}, {"ref": "funnel_rfq_attrition"}],
                        },
                    ],
                },
            ],
        },
        "description": "Tick driver (Track 4): open RFQs = previous + new RFQs - new contracts - attrition (RFQs lost to competitors / no-decision), floored at 0. Self-referential, so the auto.rfq_momentum rule effect (+1 RFQ) persists into the flow.",
    },
    {
        "output": "funnel_contracts",
        "tick_driver": True,
        "expression": {
            "op": "max",
            "args": [
                0,
                {
                    "op": "subtract",
                    "args": [
                        {
                            "op": "subtract",
                            "args": [
                                {
                                    "op": "add",
                                    "args": [
                                        {"ref": "funnel_contracts"},
                                        {"ref": "funnel_new_contracts"},
                                    ],
                                },
                                {"ref": "funnel_new_projects"},
                            ],
                        },
                        {
                            "op": "multiply",
                            "args": [
                                {"ref": "funnel_contracts"},
                                {"ref": "funnel_contract_attrition"},
                            ],
                        },
                    ],
                },
            ],
        },
        "description": "Tick driver (Track 4): won contracts awaiting kickoff = previous + new contracts - new projects - attrition (contracts cancelled), floored at 0.",
    },
    {
        "output": "funnel_projects",
        "tick_driver": True,
        "expression": {
            "op": "max",
            "args": [
                0,
                {
                    "op": "subtract",
                    "args": [
                        {
                            "op": "subtract",
                            "args": [
                                {
                                    "op": "add",
                                    "args": [
                                        {"ref": "funnel_projects"},
                                        {"ref": "funnel_new_projects"},
                                    ],
                                },
                                {"ref": "funnel_new_deliveries"},
                            ],
                        },
                        {
                            "op": "multiply",
                            "args": [
                                {"ref": "funnel_projects"},
                                {"ref": "funnel_project_attrition"},
                            ],
                        },
                    ],
                },
            ],
        },
        "description": "Tick driver (Track 4): active projects = previous + new projects - deliveries - attrition (projects cancelled), floored at 0.",
    },
    {
        "output": "funnel_deliveries_total",
        "tick_driver": True,
        "expression": {
            "op": "add",
            "args": [{"ref": "funnel_deliveries_total"}, {"ref": "funnel_new_deliveries"}],
        },
        "description": "Tick driver (Track 4): cumulative deliveries = previous + this month's deliveries. Monotonic by construction; the numerator of the overall conversion rate.",
    },
    {
        "output": "funnel_prospects_total",
        "tick_driver": True,
        "expression": {
            "op": "add",
            "args": [{"ref": "funnel_prospects_total"}, {"ref": "funnel_new_prospects"}],
        },
        "description": "Tick driver (Track 4): cumulative prospects = previous + this month's new prospects. Monotonic by construction; the denominator of the overall conversion rate.",
    },
    {
        "output": "delivery_satisfaction",
        "tick_driver": True,
        "expression": {
            "op": "min",
            "args": [
                1,
                {
                    "op": "max",
                    "args": [
                        0,
                        {
                            "op": "add",
                            "args": [
                                {"ref": "delivery_satisfaction"},
                                {
                                    "op": "multiply",
                                    "args": [
                                        0.2,
                                        {
                                            "op": "subtract",
                                            "args": [
                                                {
                                                    "op": "add",
                                                    "args": [
                                                        0.4,
                                                        {
                                                            "op": "multiply",
                                                            "args": [
                                                                0.6,
                                                                {
                                                                    "ref": "funnel_project_to_delivery_rate"
                                                                },
                                                            ],
                                                        },
                                                    ],
                                                },
                                                {"ref": "delivery_satisfaction"},
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
        "description": "Tick driver (Track 4): satisfaction moves 20% of the way toward its delivery-performance target (0.4 + 0.6 x project-to-delivery rate), clamped to [0, 1]. The 20% adjustment speed and the 0.4/0.6 target weights are assumption parameters (literals). Because the RFQ-rate drivers run BEFORE this driver, a satisfaction change moves next tick's RFQ rates — the one-tick feedback lag. A rule effect on satisfaction (e.g. a delivery complaint) decays toward the target instead of being overwritten outright.",
    },
    {
        "output": "funnel_overall_conversion",
        "tick_driver": True,
        "expression": {
            "op": "divide",
            "args": [
                {"ref": "funnel_deliveries_total"},
                {"op": "max", "args": [{"ref": "funnel_prospects_total"}, 1]},
            ],
        },
        "description": "Tick driver (Track 4): overall funnel conversion = cumulative deliveries / cumulative prospects (denominator guarded by max(..., 1)). An identity, not a parameter — it is the funnel's end-to-end yield, recomputed every tick from the two cumulative stocks.",
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

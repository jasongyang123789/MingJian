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

NEV transmission chain (Track 7, 2026-11-19; diagnostic build spec
``desay-backtest-2026-11-19/diagnostic-2020/new-parameter.md`` §2):

- Parameters: the four template variables ``nev_ceiling`` /
  ``nev_rate`` / ``nev_midpoint`` / ``nev_coupling`` (distributions
  exactly per the diagnostic spec). The penetration itself is the
  pack's ``nev_penetration`` STATE field, reused — the diagnostic
  spec's intermediate is a within-tick value, while here it is the
  shared state the dual-track split drivers already read, so the
  chain's penetration also drives the NEV/ICE volume splits.
- Attachment (case-level, two formulas; see
  ``docs/causal-chain-pattern.md``): a logistic tick driver with
  output ``nev_penetration`` — ``logistic(nev_rate * (tick -
  nev_midpoint), nev_ceiling)`` — which replaces this template's
  drift driver per-output at variable-set merge time (generic runs
  keep the drift driver), and a revenue tick driver that gains
  exactly one additive term: ``revenue * (1 + revenue_growth +
  revenue_coupling * adoption + nev_coupling * nev_penetration)``.
  No interaction term; share and profit formulas are untouched.
- Planning-path check (diagnostic §5.2): at mode values the logistic
  gives nev_penetration(1..4) = 0.044 / 0.079 / 0.133 / 0.200 — tick 4
  is exactly the 2025 20% plan target. The realized path (ceiling
  0.50, rate 0.90, midpoint 2.0) matches actual 2021-2024 penetration
  within 2pp. The chain changes the LEVEL, not the shape: with any
  constant coupling and non-decreasing penetration, per-tick growth
  is still non-decreasing, so the chain cannot fix the desay-2020
  shape problem (actual growth decelerates) — that needs the separate
  order-book mechanism, built in Track 11 (see the
  ``order_backlog`` / ``order_intake_rate`` / ``backlog_conversion`` /
  ``order_decay`` variables below and docs/causal-chain-pattern.md):
  the backlog term is the SHAPE term to this chain's LEVEL term, and
  the two channels stay separately decomposable (frozen-baseline per
  channel).
- Domain-controller substitution is deliberately NOT a separate
  mechanism here (diagnostic §5.1c: real but secondary; its
  reasonable core is covered by the NEV-chain coupling).

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

- Profit transmission chain (R&D margin promotion, 2026-11-20;
  replaces the profit-chain pack's single-regression net-margin leg
  with the R&D expense-path decomposition, design spec
  ``rd-expense-path-2026-11-20/EVIDENCE.md`` §2):
  ``profit(t) = revenue(t) x net_margin(t)`` with
  ``net_margin(t) = gross_margin(t) - rd_intensity(t) -
  other_share``, clamped to [0.02, 0.25], where
  ``gross_margin(t) = gross_base + gross_reversion x
  (gross_longrun - gross_base) x (tick-1)`` and
  ``rd_intensity(t) = rd_base + rd_reversion x
  (rd_longrun - rd_base) x (tick-1) + rd_adoption x
  disruptor_adoption``. Each leg reverts LINEARLY: each tick closes
  25% of the ORIGINAL gap, so tick 4 closes 75% and leaves 25% —
  NOT geometric (TRACK-B §2's "(0.75)^3 ≈ 42%" was a documentation
  error; the implementation was always linear — see the CORRECTION
  appended to TRACK-B.md). The clamp's upper rail is 0.25, not
  Track B's 0.15: the template's own implied net margin is 0.20
  (revenue 100 / profit 20 state defaults), so a 0.15 rail would
  clip generic runs to 0.15 and break the "generic run unaffected"
  convention; the Desay cases never touch either rail (mode-path
  net margins 2015: 0.083–0.098, 2020: 0.076–0.082; the sampled
  rd_adoption moves either by at most ±0.015). Template defaults
  (gross 0.30 / rd 0.05 / other 0.05) make a generic run's net
  margin sit at 0.20 with zero adoption, so generic runs keep
  profit at its default.
  SCOPE (M3, read before using the chain on a new case): the chain
  assumes each leg reverts MONOTONICALLY and LINEARLY from its
  decision-year level toward its pre-decision mean. It fits cases
  whose starting margin is near its settled level with a flat or
  gently falling realized path (2020-type). KNOWN MISFIT:
  decision-year margin SPIKE cases — decision-year net margin more
  than 2pp above the prior-two-year mean (2015-type: +3.79pp) —
  where the yr3 net margin is systematically HIGH (realized path
  rises first, then cliffs); judge such cases by the profit P50,
  never by a single replay. The R&D expense line is now its OWN
  decomposition leg (rd_intensity above): the profit-chain pack's
  "reduced-form expression of cost behavior" (TRACK-B §8.7) is
  SUPERSEDED for the automotive template — the R&D path is built,
  with decision-time gross / R&D / other evidence per case; the
  corporate template keeps the single-regression leg (no
  decision-time gross/R&D decomposition evidence exists for
  Huawei/Nokia in the research files).
  MERGE-ORDER NOTE (why the template carries a ``revenue``
  passthrough driver): template formulas always evaluate BEFORE
  case-appended formulas, so a template ``profit`` driver would
  otherwise read PRE-tick revenue (one-tick lag vs Track B's
  same-tick form). The passthrough is an identity driver on the
  pack's ``revenue`` state field (self-reference = current state);
  a case revenue driver replaces it IN PLACE at merge time, so it
  evaluates BEFORE ``gross_margin`` / ``rd_intensity`` /
  ``net_margin`` / ``profit`` and profit reads same-tick revenue —
  exactly the Track B semantics. The passthrough also makes
  ``revenue`` a known id for template validation (the formula
  language's known ids are sampled variables + earlier driver
  outputs; ``revenue`` is a state field, not a template variable).
  At runtime it is exactly identity (4-decimal rounding only: the
  state value it reads is already 4-decimal).
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
    # --- NEV transmission chain (Track 7, 2026-11-19) ---
    # Diagnostic build spec: desay-backtest-2026-11-19/diagnostic-2020/
    # new-parameter.md §2 (DIAGNOSTIC-2020.md §5.2). The four variables
    # are the chain's parameters; the penetration itself is NOT a fifth
    # variable — it is the pack's existing `nev_penetration` STATE field,
    # reused rather than duplicated. A case attaches the chain with two
    # formulas (see the module docstring): a logistic tick driver whose
    # output `nev_penetration` replaces this template's drift driver
    # per-output at merge time, and a revenue tick driver that gains the
    # additive term `+ nev_coupling * nev_penetration`. Generic
    # automotive runs keep the drift driver and leave these four
    # variables dormant (sampled, unread — the same standing as the
    # other lever-handle variables in this template).
    {
        "id": "nev_ceiling",
        "unit": "share (0-1)",
        "distribution": {"type": "triangular", "min": 0.30, "mode": 0.40, "max": 0.60},
        "evidence_ref": "State Council NEV plan (2021-2035), released 2020-11-02: NEV ~20% of new-car sales by 2025; saturation 40% is an extrapolation, not the plan text (diagnostic-2020/new-parameter.md §4.1)",
        "description": "Long-run saturation level K of NEV penetration for the chain's logistic path. Mode 0.40: the 2025 plan target is 20%, saturation sits above it with ICE persisting; max 0.60 admits faster electrification, min 0.30 admits the plan falling short.",
    },
    {
        "id": "nev_rate",
        "unit": "per-year",
        "distribution": {"type": "triangular", "min": 0.50, "mode": 0.70, "max": 1.00},
        "evidence_ref": "Fitted slope of the logistic through the plan endpoints (5.4% NEV in 2020 -> 20% in 2025); CAAM Dec-2020 forecast: 2021 NEV 180k units (+40%) (diagnostic-2020/evidence-2020.md §1.1-1.2)",
        "description": "Steepness r of the NEV penetration logistic. Mode 0.70 fits the plan endpoints; same order as the disruptor rate but slower, because powertrain switching is slower than electronics-configuration switching.",
    },
    {
        "id": "nev_midpoint",
        "unit": "years (tick)",
        "distribution": {"type": "triangular", "min": 3.0, "mode": 4.0, "max": 5.0},
        "evidence_ref": "Logistic fit of the plan's linear path (5.4% -> 20%) puts the midpoint at ~2024 (tick 4) (diagnostic-2020/new-parameter.md §4.1)",
        "description": "Tick at which NEV penetration passes K/2. Mode 4.0 is the plan-implied midpoint; deliberately different from the disruptor midpoint — the two diffusion curves have different midpoints, and forcing them to share one was part of the desay-2020 failure mechanism.",
    },
    {
        "id": "nev_coupling",
        "unit": "per-unit-penetration",
        "distribution": {"type": "triangular", "min": 0.10, "mode": 0.25, "max": 0.40},
        "evidence_ref": "estimate: LABELED ASSUMPTION — no 2020 source quantifies the supplier-revenue elasticity to NEV penetration; mode 0.25 matches revenue_coupling's optimistic mode (diagnostic-2020/evidence-2020.md §3(b))",
        "description": "Revenue-growth uplift per unit of NEV penetration: the revenue tick driver gains + nev_coupling * nev_penetration. The post-hoc fitted values that would reach the desay-2020 actuals (2.08 year-5 / 9.69 year-3 on the planning path) are 5-24x this distribution's max and were indefensible at 2020-12-31 — they must never be used as parameters.",
    },
    # --- Order-book (backlog) mechanism (Track 11, 2026-11-19) ---
    # Track 7 report §7 build spec (diagnostic-2020 §5.3 shape problem):
    # the NEV chain is the LEVEL term; the backlog term is the SHAPE
    # term. The four variables are the mechanism's parameters; the
    # stock/flow themselves are the pack's `order_backlog` /
    # `order_intake` STATE fields. A case attaches the mechanism by
    # binding the opening book and flow as variables (both =
    # order_intake_rate * mode revenue — the stock proxy is one year
    # of intake, a LABELED ASSUMPTION: the order stock itself was
    # never disclosed) and three tick drivers: the revenue driver
    # gains exactly one additive term
    # (+ backlog_conversion * order_backlog / revenue), the intake
    # driver decays the flow (order_intake * (1 - order_decay)), and
    # the backlog driver updates the stock
    # (backlog + intake - backlog_conversion * backlog, floored at 0).
    # Driver order within a tick (see docs/causal-chain-pattern.md):
    # revenue reads the PRE-tick backlog, then intake decays, then the
    # backlog updates — so the converted amount in a tick is
    # backlog_conversion * pre-tick backlog, exactly the amount the
    # revenue term adds. Generic automotive runs keep these four
    # variables dormant (sampled, unread — the same standing as the
    # NEV-chain variables in generic runs) and the pack defaults
    # (backlog 0, intake 0) leave them with no effect.
    {
        "id": "order_backlog",
        "unit": "RMB m (same units as the case's revenue)",
        "distribution": {"type": "fixed", "value": 0.0},
        "evidence_ref": "assumption:pending-calibration — the order stock is a case-level quantity (a case binds it directly, e.g. one year of intake at mode revenue); 0.0 is the no-book generic default, never a market estimate",
        "description": "Stock of unfulfilled orders at run start. Lever handle: a case overrides it with its decision-time order book (one year of intake at mode revenue is the labeled stock proxy — the stock itself was never disclosed). The tick driver updates it as backlog + intake - converted, floored at 0.",
    },
    {
        "id": "order_intake",
        "unit": "RMB m per tick (same units as the case's revenue)",
        "distribution": {"type": "fixed", "value": 0.0},
        "evidence_ref": "assumption:pending-calibration — the new-orders flow is a case-level quantity (a case binds it directly, e.g. order_intake_rate * mode revenue); 0.0 is the no-book generic default",
        "description": "New-orders flow per tick at run start. Lever handle: a case overrides it with its decision-time intake flow. The tick driver decays it by (1 - order_decay) per tick. (Bound as a variable — not an initial formula — because merge is per-output: an initial formula and a tick driver cannot share the output id, the driver would replace the formula.)",
    },
    {
        "id": "order_intake_rate",
        "unit": "annualized new orders / current revenue",
        "distribution": {"type": "triangular", "min": 0.50, "mode": 1.00, "max": 1.50},
        "evidence_ref": "assumption:pending-calibration — generic range around 1.0x revenue (one year of intake ≈ one year of revenue); a case overrides it from its decision-time order announcements (Desay 2020: ~70亿 annualised orders / 67.99亿 revenue ≈ 1.03, triangular(0.80, 1.00, 1.20))",
        "description": "Annualized new orders as a multiple of current revenue. Sets both the intake flow and (via the initial formula) the opening backlog stock. The 2021-2023 realized order path is scoring evidence only, never an input (hindsight firewall).",
    },
    {
        "id": "backlog_conversion",
        "unit": "fraction of backlog converted per tick",
        "distribution": {"type": "triangular", "min": 0.30, "mode": 0.40, "max": 0.60},
        "evidence_ref": "estimate: LABELED ASSUMPTION — fraction of the order backlog converted to revenue per tick, calibratable from the historical order-to-revenue lag (design-in to start-of-production ~1-2 years for auto electronics, so ~0.40/yr turns the book over in ~2.5 years); no 2020 source states a conversion rate",
        "description": "Fraction of the pre-tick backlog converted to revenue each tick: the revenue driver gains + backlog_conversion * (order_backlog / revenue), and the same amount leaves the backlog. Mode 0.40.",
    },
    {
        "id": "order_decay",
        "unit": "fraction of the order flow lost per tick",
        "distribution": {"type": "triangular", "min": 0.10, "mode": 0.25, "max": 0.40},
        "evidence_ref": "estimate: LABELED ASSUMPTION — per-tick decay of the new-orders flow (mean-reversion of order growth after a surge year; the flow cannot sustain surge growth without continuous wins). No 2020 source states a decay rate; mode 0.25 is the planning assumption.",
        "description": "Per-tick decay of the new-orders flow: order_intake(t) = order_intake(t-1) * (1 - order_decay). The decay is the point of the mechanism: as the surge passes, the backlog term shrinks and per-tick growth falls even while penetration and adoption keep rising.",
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
    # --- Profit transmission chain, R&D decomposition (rd-margin
    # promotion, 2026-11-20) ---
    # The profit-chain pack's single-regression net-margin leg
    # (margin_base / margin_longrun / margin_reversion /
    # margin_adoption) is REPLACED here by the R&D expense-path
    # decomposition (rd-expense-path-2026-11-20/EVIDENCE.md §2): the
    # net margin is an accounting identity over three legs — gross
    # margin, R&D intensity, and a fixed residual ("other") — each
    # leg mean-reverting linearly toward its own long-run level, and
    # the adoption coupling now sits on the R&D leg (rd_adoption)
    # instead of on the net margin. The eight variables are the
    # chain's parameters; the margin itself is the template's
    # `net_margin` tick-driver output (intermediate, not a state
    # field) and profit is the pack's `profit` STATE field, reused.
    # A case attaches the chain by binding the eight values to its
    # decision-time figures (Desay 2015: gross 0.2696/0.255 WEAK, rd
    # 0.076/0.076 WEAK, other 0.0958; Desay 2020: gross 0.2339/0.2307,
    # rd 0.1202/0.1117, other 0.0375; reversions 0.25). The template
    # defaults below make a generic run's net margin sit at the
    # template's own implied net margin (0.30 - 0.05 - 0.05 = 0.20),
    # so generic runs keep profit at its default. No dead margin
    # variables are left behind: the four B-pack margin ids are gone
    # from this template (the corporate template keeps them — no
    # decision-time gross/R&D decomposition evidence exists for
    # Huawei/Nokia in the research files).
    {
        "id": "gross_base",
        "unit": "rate",
        "distribution": {"type": "fixed", "value": 0.30},
        "evidence_ref": "assumption:pending-calibration — template default 0.30 IS a placeholder gross margin (template default, not evidence: the template's own implied net margin is gross 0.30 - rd 0.05 - other 0.05 = 0.20, matching profit 20.0 / revenue 100.0 state defaults); a case binds its decision-year gross margin (Desay 2015: 0.2696; Desay 2020: 0.2339)",
        "description": "Starting gross margin at the decision year: the level the gross leg mean-reverts FROM (template default 0.30, a placeholder — bind the case's decision-year gross margin).",
    },
    {
        "id": "gross_longrun",
        "unit": "rate",
        "distribution": {"type": "fixed", "value": 0.30},
        "evidence_ref": "assumption:pending-calibration — template default 0.30 = no gross reversion in a generic run (equals gross_base); a case binds its long-run gross margin (Desay 2015: 0.255 WEAK, band midpoint; Desay 2020: 0.2307, two-year mean). LABELED ASSUMPTION: the anchor definition is the chain's, the value is case-bound.",
        "description": "Long-run gross margin the gross leg mean-reverts TOWARD (template default 0.30 = no reversion in a generic run, since it equals gross_base).",
    },
    {
        "id": "gross_reversion",
        "unit": "per-tick",
        "distribution": {"type": "fixed", "value": 0.25},
        "evidence_ref": "estimate: LABELED ASSUMPTION — a quarter of the gross-margin gap to the long-run level closes per tick (round number, fixed before the run; carried over from the B-pack margin_reversion — the R&D harness reuses the same 0.25/tick for both legs, no independent evidence)",
        "description": "Gross-margin mean-reversion speed: each tick closes 25% of the ORIGINAL gap to gross_longrun (LINEAR reversion — tick 4 closes 75%, leaving 25% — not geometric).",
    },
    {
        "id": "rd_base",
        "unit": "rate",
        "distribution": {"type": "fixed", "value": 0.05},
        "evidence_ref": "assumption:pending-calibration — template default 0.05 IS a placeholder R&D intensity (template default, not evidence; with gross 0.30 and other 0.05 it yields the template's implied net margin 0.20); a case binds its decision-year R&D intensity (Desay 2015: 0.076 WEAK, 2014 anchor; Desay 2020: 0.1202)",
        "description": "Starting R&D intensity (R&D expense / revenue) at the decision year: the level the R&D leg mean-reverts FROM (template default 0.05, a placeholder — bind the case's decision-year R&D intensity).",
    },
    {
        "id": "rd_longrun",
        "unit": "rate",
        "distribution": {"type": "fixed", "value": 0.05},
        "evidence_ref": "assumption:pending-calibration — template default 0.05 = no R&D reversion in a generic run (equals rd_base); a case binds its long-run R&D intensity (Desay 2015: 0.076 WEAK, same as base — single-point anchor, no reversion drift; Desay 2020: 0.1117, two-year mean). LABELED ASSUMPTION: the anchor definition is the chain's, the value is case-bound.",
        "description": "Long-run R&D intensity the R&D leg mean-reverts TOWARD (template default 0.05 = no reversion in a generic run, since it equals rd_base).",
    },
    {
        "id": "rd_reversion",
        "unit": "per-tick",
        "distribution": {"type": "fixed", "value": 0.25},
        "evidence_ref": "estimate: LABELED ASSUMPTION — a quarter of the R&D-intensity gap to the long-run level closes per tick (round number, fixed before the run; carried over from the B-pack margin_reversion — the R&D harness reuses the same 0.25/tick for both legs, no independent evidence)",
        "description": "R&D-intensity mean-reversion speed: each tick closes 25% of the ORIGINAL gap to rd_longrun (LINEAR reversion — tick 4 closes 75%, leaving 25% — not geometric).",
    },
    {
        "id": "rd_adoption",
        "unit": "margin points per unit adoption",
        "distribution": {"type": "triangular", "min": -0.02, "mode": 0.0, "max": 0.02},
        "evidence_ref": "estimate: LABELED ASSUMPTION — net effect of adoption on R&D intensity (scale/learning vs price pressure passes through R&D spend); mode 0 (no signed decision-time evidence; same width as the B-pack margin_adoption it replaces, so the adoption uncertainty is carried once, not twice)",
        "description": "Net effect of disruptor adoption on R&D intensity per unit of adoption (mode 0: no signed decision-time evidence). The only sampled variable of the eight (the other seven are fixed).",
    },
    {
        "id": "other_share",
        "unit": "rate",
        "distribution": {"type": "fixed", "value": 0.05},
        "evidence_ref": "assumption:pending-calibration — template default 0.05 IS a placeholder residual share (template default, not evidence); a case binds its t=1 residual gross - rd - net (Desay 2015: 0.0958; Desay 2020: 0.0375). The residual absorbs taxes, selling/general expenses, investment income and non-recurring items — it is FIXED by construction, not measured; see the R&D report §7.1 for its time-variation limits.",
        "description": "Fixed residual share (gross margin - R&D intensity - net margin): everything the two modeled legs do not explain, frozen at its t=1 value (template default 0.05, a placeholder).",
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
    # --- Profit transmission chain, R&D decomposition (rd-margin
    # promotion, 2026-11-20) ---
    # The B-pack single-regression net-margin leg is REPLACED by the
    # R&D expense-path decomposition (EVIDENCE.md §2): net_margin =
    # gross_margin - rd_intensity - other_share, each leg reverting
    # linearly toward its own long-run level, the adoption coupling
    # on the R&D leg (rd_adoption). Order inside this block is
    # load-bearing: disruptor_adoption first (rd_intensity reads it;
    # a case adoption curve replaces it in place), then the revenue
    # passthrough (a case revenue driver replaces it in place, so it
    # evaluates BEFORE gross_margin / rd_intensity / net_margin and
    # profit), then gross_margin, rd_intensity, net_margin, then
    # profit — profit reads SAME-TICK revenue, exactly the Track B
    # semantics. The formula language has no `clamp` operator (eight
    # ops only: add/subtract/multiply/divide/min/max/pow/logistic),
    # so the clamp is min(max(...)) nesting, as in the Track B
    # harness.
    {
        "output": "disruptor_adoption",
        "tick_driver": True,
        "expression": 0.0,
        "description": "Tick driver (profit-chain pack): default zero disruptor-adoption intermediate (a bare-number expression is a legal formula). A case with an adoption curve replaces this driver per-output (NEV drift driver precedent); without it, Huawei/generic runs would leave rd_intensity referencing an undefined quantity. Mode 0: no signed decision-time evidence for adoption moving the R&D leg.",
    },
    {
        "output": "revenue",
        "tick_driver": True,
        "expression": {"ref": "revenue"},
        "description": "Tick driver (profit-chain pack): identity passthrough on the pack's revenue state field (a driver self-reference reads the field's current state value). MERGE ANCHOR, not a model: (1) it makes `revenue` a known id for template validation — the formula language's known ids are sampled variables + earlier driver outputs, and `revenue` is a state field, not a template variable — so the profit driver below can reference it; (2) a case revenue driver replaces this driver IN PLACE at merge time, so the case revenue evaluates BEFORE net_margin/profit and profit reads same-tick revenue (Track B semantics) instead of pre-tick revenue (one-tick lag). At runtime it is exactly identity (4-decimal rounding only: the state value it reads is already 4-decimal).",
    },
    {
        "output": "gross_margin",
        "tick_driver": True,
        "expression": {
            "op": "add",
            "args": [
                {"ref": "gross_base"},
                {
                    "op": "multiply",
                    "args": [
                        {
                            "op": "multiply",
                            "args": [
                                {"ref": "gross_reversion"},
                                {
                                    "op": "subtract",
                                    "args": [{"ref": "gross_longrun"}, {"ref": "gross_base"}],
                                },
                            ],
                        },
                        {"op": "subtract", "args": [{"ref": "tick"}, 1]},
                    ],
                },
            ],
        },
        "description": "Tick driver (R&D decomposition): gross margin, the first leg — mean-reverts LINEARLY toward gross_longrun at gross_reversion per tick (each tick closes 25% of the ORIGINAL gap; tick 4 closes 75%, leaving 25%). Intermediate, not a state field. Feeds net_margin; the case binds gross_base/gross_longrun only.",
    },
    {
        "output": "rd_intensity",
        "tick_driver": True,
        "expression": {
            "op": "add",
            "args": [
                {
                    "op": "add",
                    "args": [
                        {"ref": "rd_base"},
                        {
                            "op": "multiply",
                            "args": [
                                {
                                    "op": "multiply",
                                    "args": [
                                        {"ref": "rd_reversion"},
                                        {
                                            "op": "subtract",
                                            "args": [{"ref": "rd_longrun"}, {"ref": "rd_base"}],
                                        },
                                    ],
                                },
                                {"op": "subtract", "args": [{"ref": "tick"}, 1]},
                            ],
                        },
                    ],
                },
                {"op": "multiply", "args": [{"ref": "rd_adoption"}, {"ref": "disruptor_adoption"}]},
            ],
        },
        "description": "Tick driver (R&D decomposition): R&D intensity (R&D expense / revenue), the second leg — mean-reverts LINEARLY toward rd_longrun at rd_reversion per tick, plus rd_adoption x adoption (mode 0: no signed decision-time evidence). Intermediate, not a state field. Feeds net_margin; the case binds rd_base/rd_longrun only.",
    },
    {
        "output": "net_margin",
        "tick_driver": True,
        "expression": {
            "op": "min",
            "args": [
                0.25,
                {
                    "op": "max",
                    "args": [
                        0.02,
                        {
                            "op": "subtract",
                            "args": [
                                {"op": "subtract", "args": [{"ref": "gross_margin"}, {"ref": "rd_intensity"}]},
                                {"ref": "other_share"},
                            ],
                        },
                    ],
                },
            ],
        },
        "description": "Tick driver (R&D decomposition): net margin, the decomposition identity — gross margin minus R&D intensity minus the fixed residual other_share, clamped to [0.02, 0.25]. The 0.25 upper rail (not Track B's 0.15) is the pack-level rail: the template's own implied net margin is 0.20, so a 0.15 rail would clip generic runs. No net-margin variable is sampled anymore — the margin is computed, not drawn. Intermediate, not a state field. SCOPE: assumes monotone linear reversion of each leg from the decision-year level toward its pre-decision mean; known misfit on decision-year margin-spike cases (>2pp above the prior-two-year mean, 2015-type: yr3 margin systematically high — judge by P50, not a single replay).",
    },
    {
        "output": "profit",
        "tick_driver": True,
        "expression": {
            "op": "max",
            "args": [
                0,
                {"op": "multiply", "args": [{"ref": "revenue"}, {"ref": "net_margin"}]},
            ],
        },
        "description": "Tick driver (profit-chain pack): profit = same-tick revenue x net_margin — inherits the NEV term, the backlog term and revenue growth in full; replaces the decoupled profit_growth driver. Evaluates AFTER the (case) revenue driver via the revenue-passthrough merge anchor, so it reads same-tick revenue exactly as the Track B harness did.",
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

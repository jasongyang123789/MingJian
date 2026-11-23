"""Machine-readable registry of every SIMULATED / labeled-assumption
calibration value in the strategy engine (Item 7, 2026-11-20).

Purpose: the calibration upgrade path needs ONE inventory before any
value can be replaced. Each entry names the value as it ships today,
where it lives, what evidence (if any) supports it, and what internal
datum would replace it. Nothing here invents evidence: entries whose
public basis is thin say so in ``evidence`` and carry status
``simulated`` (or ``kept_prior`` for the v3 transmission coefficients
whose fit failed the quality gates).

Status vocabulary
-----------------
* ``simulated`` — Ho-authorized industry-average simulation
  (2026-11-16) or a harness-level labeled assumption; replaceable
  with internal data through the pipeline in
  :mod:`planagent.services.calibration.internal_pipeline`.
* ``evidence`` — decision-time public or internal evidence supports
  the value; kept for the before/after record, not replaced by the
  pipeline (it is already the datum, not the assumption).
* ``calibrated_v3`` — fitted by
  :func:`planagent.services.calibration.transmission.calibrate_transmission_coefficients`
  from the decision-time public panel; replaced by extending the
  public panel, NOT by internal data.
* ``kept_prior`` — the v3 fit was attempted and failed a quality
  gate (or was unidentifiable); the placeholder survives WITH the
  failed attempt recorded. Internal data cannot replace these
  directly either — the replacement path is a better public series
  (see each entry's ``replacement_path``).

Live cross-checks: entries whose value lives in code are checked
against the live value at import-test time (see
``tests/test_calibration_registry.py``); the registry must never drift
from the code it inventories. Entries whose value lives only in an
unmerged branch or a research harness say so in ``location`` — the
registry is honest about provenance, including unmerged work.
"""

from __future__ import annotations

from typing import Any

#: Registry schema version. Bump when an entry gains a field.
REGISTRY_VERSION = "item7/v1"

#: Statuses (see module docstring).
STATUS_SIMULATED = "simulated"
STATUS_EVIDENCE = "evidence"
STATUS_CALIBRATED_V3 = "calibrated_v3"
STATUS_KEPT_PRIOR = "kept_prior"


def _entry(
    entry_id: str,
    group: str,
    location: str,
    current: Any,
    status: str,
    evidence: str,
    replacement_path: str,
    internal_field: str | None = None,
    channel: str = "live",
    notes: str = "",
) -> dict[str, Any]:
    return {
        "id": entry_id,
        "group": group,
        "location": location,
        "current": current,
        "status": status,
        "evidence": evidence,
        "replacement_path": replacement_path,
        "internal_field": internal_field,
        "channel": channel,
        "notes": notes,
    }


# --- Group 1: order book (Desay harness, Track 11 / e047f50 re-run) ---
# The case-level restatements live in the research harness
# (backtest-rerun-2026-11-19-e047f50/run_desay_e047f50.py::
# _orderbook_wiring_variables); the template generics live in
# template_spec.py. Both are inventoried: the harness values are what
# the backtest scores actually run on.
ORDER_BOOK_ENTRIES: list[dict[str, Any]] = [
    _entry(
        "order_intake_rate/desay-2020",
        "order_book",
        "research harness run_desay_e047f50.py::_orderbook_wiring_variables (2020 call)",
        {"type": "triangular", "min": 0.80, "mode": 1.00, "max": 1.30},
        STATUS_SIMULATED,
        "GENERATED (calibration-simulated-generation-2026-11-20): mode 1.00 from ~RMB 7.0bn annualised new orders (2020 annual-report summary, announcement 2021-010) / FY2020 revenue RMB 6,799.06m = 1.03; max 1.30 from 2019 ~RMB 7.0bn / FY2019 revenue RMB 5,337.24m = 1.31; min 0.80 retained (no lower observation).",
        "internal: order_intake_rate (annualised new orders / revenue, "
        "decision year, per case)",
        internal_field="order_intake_rate",
    ),
    _entry(
        "order_intake_rate/desay-2015",
        "order_book",
        "research harness run_desay_e047f50.py::_orderbook_wiring_variables (2015 call)",
        {"type": "triangular", "min": 0.15, "mode": 0.25, "max": 0.40},
        STATUS_SIMULATED,
        "GENERATED (calibration-simulated-generation-2026-11-20): no order-surge disclosure at end-2015 (small-book labeled assumption); width CV-matched (triangular CV 0.193 vs observed cross-year CV 0.170 of the annual intake ratio). Mode 0.25 retained: no evidence to change it, and raising it trips the 2015 headroom red line.",
        "internal: order_intake_rate (2015 decision year)",
        internal_field="order_intake_rate",
    ),
    _entry(
        "order_backlog_opening/desay-2020",
        "order_book",
        "research harness run_desay_e047f50.py::_orderbook_wiring_variables (2020 call)",
        {"type": "fixed", "value": 6800},
        STATUS_SIMULATED,
        "GENERATED (calibration-simulated-generation-2026-11-20): opening order stock was NEVER disclosed. Proxy = one year of intake at the intake-rate mode (1.00 x 6,799.06), rounded to 2 significant figures (6800) to remove false precision.",
        "internal: order_backlog_opening (RMB m, unfulfilled order "
        "stock at the decision date)",
        internal_field="order_backlog_opening",
    ),
    _entry(
        "order_backlog_opening/desay-2015",
        "order_book",
        "research harness run_desay_e047f50.py::_orderbook_wiring_variables (2015 call)",
        {"type": "fixed", "value": 920},
        STATUS_SIMULATED,
        "GENERATED (calibration-simulated-generation-2026-11-20): opening order stock was NEVER disclosed. Proxy = 0.25 x 3,668.25 (one year of intake at the small-book mode), rounded to 2 significant figures (920).",
        "internal: order_backlog_opening (RMB m)",
        internal_field="order_backlog_opening",
    ),
    _entry(
        "order_intake_flow_opening/desay-2020",
        "order_book",
        "research harness run_desay_e047f50.py::_orderbook_wiring_variables (2020 call)",
        {"type": "fixed", "value": 6800},
        STATUS_SIMULATED,
        "GENERATED (calibration-simulated-generation-2026-11-20): opening new-orders flow = one year of intake at the intake-rate mode (1.00 x 6,799.06), rounded to 2 significant figures (6800); same proxy as the stock.",
        "internal: order_intake_flow (RMB m per tick)",
        internal_field="order_intake_flow",
    ),
    _entry(
        "order_intake_flow_opening/desay-2015",
        "order_book",
        "research harness run_desay_e047f50.py::_orderbook_wiring_variables (2015 call)",
        {"type": "fixed", "value": 920},
        STATUS_SIMULATED,
        "GENERATED (calibration-simulated-generation-2026-11-20): opening new-orders flow = 0.25 x 3,668.25, rounded to 2 significant figures (920); same proxy as the stock.",
        "internal: order_intake_flow (RMB m per tick)",
        internal_field="order_intake_flow",
    ),
    _entry(
        "backlog_conversion",
        "order_book",
        "template_spec.py (generic) + research harness case restatement (identical distribution)",
        {"type": "triangular", "min": 0.30, "mode": 0.40, "max": 0.60},
        STATUS_SIMULATED,
        "GENERATED (calibration-simulated-generation-2026-11-20): lag-implied range check — design-in to start-of-production ~1-2 years (IPU04 2020 cooperation -> 2022 SOP target) implies conversion 0.33-1.00; current (0.30, 0.40, 0.60) implies lags 3.33/2.5/1.67y, i.e. conservative. Upward revision (mode 0.50) held by the 2015 headroom red line.",
        "internal: backlog_conversion (fraction/tick, from realised "
        "order-to-revenue lag: project design-in→SOP durations or a "
        "realised conversion series)",
        internal_field="backlog_conversion",
    ),
    _entry(
        "order_decay",
        "order_book",
        "template_spec.py (generic) + research harness case restatement (identical distribution)",
        {"type": "triangular", "min": 0.10, "mode": 0.25, "max": 0.40},
        STATUS_SIMULATED,
        "GENERATED (calibration-simulated-generation-2026-11-20): fit attempted and failed — only two disclosed new-orders points (2019/2020 ~7.0bn, flat); revenue-growth decay unstable (0.894 / 2.721). Mode 0.25 is the centre of the plausible range; low sensitivity (kf7 probe: mode +/-0.15 -> anchor P50 -3.6%/+4.8%).",
        "internal: order_decay (fraction/tick, from the realised "
        "new-orders flow path after surge years)",
        internal_field="order_decay",
    ),
    _entry(
        "order_intake_rate/template-generic",
        "order_book",
        "template_spec.py::TEMPLATE_VARIABLES order_intake_rate",
        {"type": "triangular", "min": 0.50, "mode": 1.00, "max": 1.50},
        STATUS_SIMULATED,
        "GENERATED (calibration-simulated-generation-2026-11-20): cross-case envelope — mode 1.00 = the most recent (2020) observed ratio 1.03 rounded; width 0.50-1.50 covers the observed 1.03-1.31 range plus a planning margin; never directly scored (cases override it).",
        "internal: order_intake_rate (per case; the generic is replaced "
        "by case-level internal values, not by a single global number)",
        internal_field="order_intake_rate",
    ),
]

# --- Group 2: Tier-1 commercial terms (template S-layer) -------------
TIER1_ENTRIES: list[dict[str, Any]] = [
    _entry(
        "annual_cut_rate",
        "tier1_terms",
        "template_spec.py::TEMPLATE_VARIABLES annual_cut_rate",
        {"type": "triangular", "min": 0.03, "mode": 0.04, "max": 0.05},
        STATUS_SIMULATED,
        "NOT GENERATED (dormant): no formula reads this variable on e047f50 (gap-audit A2); replacing the value changes no score until the annual-cut -> price/margin channel is built. Generation deferred (calibration-simulated-generation-2026-11-20).",
        "internal: annual_cut_rate (rate/year, executed annual cuts — "
        "contract schedule by OEM/product, or realised price realisation)",
        internal_field="annual_cut_rate",
        channel="DORMANT — no formula reads this variable on e047f50 "
        "(gap-audit A2). Replacing the value changes NO score until "
        "the annual-cut → price/margin channel is built.",
    ),
    _entry(
        "payment_terms_months",
        "tier1_terms",
        "template_spec.py::TEMPLATE_VARIABLES payment_terms_months",
        {"type": "triangular", "min": 2.0, "mode": 6.0, "max": 9.0},
        STATUS_SIMULATED,
        "NOT GENERATED (dormant): no formula reads this variable on e047f50 (gap-audit A2); replacing the value changes no score until the terms -> cash-occupancy channel is built. Generation deferred (calibration-simulated-generation-2026-11-20).",
        "internal: payment_terms_months (months, actual payment terms "
        "by OEM — contract terms or realised DSO)",
        internal_field="payment_terms_months",
        channel="DORMANT — no formula reads this variable on e047f50 "
        "(gap-audit A2). Replacing the value changes NO score until "
        "the terms → cash-occupancy channel is built.",
    ),
    _entry(
        "tier1_gross_margin",
        "tier1_terms",
        "template_spec.py::TEMPLATE_VARIABLES tier1_gross_margin",
        {"type": "triangular", "min": 0.20, "mode": 0.25, "max": 0.29},
        STATUS_SIMULATED,
        "DESAY-EVIDENCE (calibration-simulated-generation-2026-11-20): audited overall gross margin 2015-2020 (26.96/26.95/25.78/24.0/22.75/23.39%; mean 24.97%, sd 1.84pp); moment-matched triangular (mean 24.67%, sd 1.84pp, CV 0.075 vs observed 0.074). Replaces the 2023-25 post-decision window (hindsight leak fix) and the too-tight span (old CV 0.013).",
        "internal: tier1_gross_margin (rate, audited overall gross "
        "margin; product-line split optional)",
        internal_field="tier1_gross_margin",
        channel="live — the margin tick driver reads and updates this "
        "field each tick (self-referential; at baseline material = "
        "price = 1 it is a no-op, so the sampled value IS the path).",
    ),
    _entry(
        "supply_share_simulated",
        "tier1_terms",
        "template_spec.py::TEMPLATE_ASSUMPTION_DATA supply_share_simulated",
        {"type": "fixed", "value": 0.10},
        STATUS_SIMULATED,
        "GENERATED (calibration-simulated-generation-2026-11-20): Ho-authorized neutral placeholder (2026-11-16), kept by design; a round neutral value, NOT an estimate. Replace with internal supply-share data when it arrives. Prospects always get 0, never this value.",
        "internal: supply_share records (share per OEM × model × trim "
        "× product; must sum to 1 per slot — enforced by the pipeline "
        "validator)",
        internal_field="supply_share",
        channel="live — S-layer attribution (sales = capacity × share); "
        "prospects always get 0, never the default.",
    ),
]

# --- Group 3: profit transmission chain (Track B harness, UNMERGED) ---
# Lives only in the Track B harness copy
# (desay-gap-full-2026-11-20/track-b/run_desay_gapb.py); no product
# code yet. Values are inventoried here so the pipeline knows them
# the day the chain is promoted to the pack.
PROFIT_CHAIN_ENTRIES: list[dict[str, Any]] = [
    _entry(
        "margin_longrun/desay-2020",
        "profit_chain",
        "Track B harness run_desay_gapb.py (UNMERGED branch fix/desay-gap-profit)",
        {"type": "fixed", "value": 0.0658},
        STATUS_SIMULATED,
        "DESAY-EVIDENCE (calibration-simulated-generation-2026-11-20): two-year-mean rule on the audited net-margin history: (7.6935% + 5.4738%) / 2 = 6.5836% (2018-2019). Exact arithmetic confirms the registry value.",
        "internal: margin_longrun (computed from the audited net-margin "
        "history by the documented two-year-mean rule — the rule "
        "itself, not the number, is what internal data would confirm)",
        internal_field="margin_longrun",
    ),
    _entry(
        "margin_longrun/desay-2015",
        "profit_chain",
        "Track B harness run_desay_gapb.py (UNMERGED branch fix/desay-gap-profit)",
        {"type": "fixed", "value": 0.0598},
        STATUS_SIMULATED,
        "DESAY-EVIDENCE (calibration-simulated-generation-2026-11-20): two-year-mean rule on the audited net-margin history: (5.6742% + 6.2779%) / 2 = 5.9761% (2013-2014). Exact arithmetic (registry 0.0599 used rounded inputs 5.7+6.28); a 0.0001 rounding correction.",
        "internal: margin_longrun (same rule, 2015 decision year)",
        internal_field="margin_longrun",
    ),
    _entry(
        "margin_reversion",
        "profit_chain",
        "Track B harness run_desay_gapb.py (UNMERGED branch fix/desay-gap-profit)",
        {"type": "fixed", "value": 0.16},
        STATUS_SIMULATED,
        "GENERATED (calibration-simulated-generation-2026-11-20): DECIDED 0.16 by Ho 2026-11-20 — strict-firewall median of implied one-year reversion rates, 2013-2019 only (median 0.162). Full-window fit 2013-2020 (median 0.2718) NOT applied: the 2019->2020 transition uses the 2020 realised net margin, unknowable at the 2020-12-31 decision point. Cross-check OLS AR(1) r=0.59 R2=0.21 (weak); identification weak (implied r range -10.96 to +2.17).",
        "internal: margin_reversion (NOT directly observable — "
        "estimable only by fitting the reversion rule to a realised "
        "net-margin trajectory; the pipeline accepts a fitted value "
        "with its fit record, never a raw internal number)",
        internal_field="margin_reversion",
    ),
    _entry(
        "margin_adoption",
        "profit_chain",
        "Track B harness run_desay_gapb.py (UNMERGED branch fix/desay-gap-profit)",
        {"type": "triangular", "min": -0.02, "mode": 0.0, "max": 0.02},
        STATUS_SIMULATED,
        "GENERATED (calibration-simulated-generation-2026-11-20): NEV-penetration vs net-margin panel (2015-2020, n=6) fitted and REJECTED as confounded by the 2018-19 down-cycle (slope -0.95 pp/pp, R2=0.68, corr=-0.82); mode 0 retained (no signed decision-time evidence).",
        "internal: margin_adoption (NOT directly observable — "
        "estimable only from a realised adoption-vs-margin panel; "
        "same fitted-value rule as margin_reversion)",
        internal_field="margin_adoption",
    ),
    _entry(
        "margin_clamp",
        "profit_chain",
        "Track B harness run_desay_gapb.py (UNMERGED branch fix/desay-gap-profit)",
        {"type": "fixed", "value": [0.02, 0.15]},
        STATUS_SIMULATED,
        "Clamp [0.02, 0.15]: realised net-margin band 2013–2020 was "
        "5.5%–9.8%; the upper bound is widened deliberately. A guard "
        "rail, not a measurement.",
        "internal: none — a guard rail is set by judgment, not by a "
        "data field. Internal data can only justify widening or "
        "narrowing it (record the realised band).",
        internal_field=None,
    ),
    _entry(
        "margin_base/desay-2020",
        "profit_chain",
        "Track B harness run_desay_gapb.py (UNMERGED branch fix/desay-gap-profit)",
        {"type": "formula", "value": "profit / revenue"},
        STATUS_EVIDENCE,
        "Derived from the case's own decision-time profit and revenue "
        "(2020: 518.15 / 6,799.06 = 7.62% at modes; 2015: 358.87 / "
        "3,668.25 = 9.78%). Decision-time internal figures — the "
        "datum, not the assumption. NOT replaced by the pipeline.",
        "internal: none (already the internal datum)",
        internal_field=None,
    ),
    _entry(
        "margin_base/desay-2015",
        "profit_chain",
        "Track B harness run_desay_gapb.py (UNMERGED branch fix/desay-gap-profit)",
        {"type": "formula", "value": "profit / revenue"},
        STATUS_EVIDENCE,
        "Same derivation as the 2020 entry (2015 modes: 9.78%).",
        "internal: none (already the internal datum)",
        internal_field=None,
    ),
]

# --- Group 4: downside default parameter set (Track C, UNMERGED) ----
# On e047f50 the downside mechanism is OPT-IN, default OFF, with NO
# canonical default set in code (per-case ON observations bind their
# own variables). The unified default set below exists only on the
# Track C branch (fix/desay-gap-downside-on, 2026-11-20). It is
# inventoried here so the pipeline covers it the day it lands.
DOWNSIDE_ENTRIES: list[dict[str, Any]] = [
    _entry(
        "downturn_occurs/default",
        "downside_default",
        "Track C branch downside.py::DOWNSIDE_DEFAULT_* (UNMERGED branch fix/desay-gap-downside-on)",
        {"type": "bernoulli", "p": 0.5},
        STATUS_SIMULATED,
        "No independent estimate. Anchored, where possible, on the "
        "observed 2018–19 episode (revenue −10.0% then −1.3% against "
        "a ~+15% trend, i.e. a ~25pp swing) — the episode bounds the "
        "DEPTH, not the occurrence probability.",
        "internal: NONE — no internal series exists for the probability "
        "of a future downturn. Replacement path is an episode catalog "
        "(dated downturn episodes + frequencies) or an expert panel, "
        "recorded as judgment, never as a measured rate.",
        internal_field=None,
    ),
    _entry(
        "downturn_depth/default",
        "downside_default",
        "Track C branch downside.py::DOWNSIDE_DEFAULT_* (UNMERGED branch fix/desay-gap-downside-on)",
        {"type": "triangular", "min": 0.05, "mode": 0.20, "max": 0.35},
        STATUS_SIMULATED,
        "Mode 0.20: the 2018–19 ~25pp swing, discounted for a single-"
        "tick peak hit. Max 0.35 is the largest single-tick hit the "
        "mechanism can express before the 2020 growth rate (~1.5×/tick) "
        "swallows it (a tick-over-tick decline needs depth > 0.33). "
        "No independent estimate of the depth distribution.",
        "internal: NONE (same as downturn_occurs — episode catalog / "
        "expert panel only).",
        internal_field=None,
    ),
    _entry(
        "downturn_start/default",
        "downside_default",
        "Track C branch downside.py::DOWNSIDE_DEFAULT_* (UNMERGED branch fix/desay-gap-downside-on)",
        {"type": "triangular", "min": 2, "mode": 3, "max": 4},
        STATUS_SIMULATED,
        "Uniform ignorance over the middle of a 5-tick horizon, "
        "stated as a triangular. The 2020 per-case ON observation "
        "used (1, 2, 4) instead — the unified default takes the "
        "majority value (2015 + Huawei).",
        "internal: NONE (episode catalog only).",
        internal_field=None,
    ),
    _entry(
        "downturn_duration/default",
        "downside_default",
        "Track C branch downside.py::DOWNSIDE_DEFAULT_* (UNMERGED branch fix/desay-gap-downside-on)",
        {"type": "triangular", "min": 1, "mode": 2, "max": 3},
        STATUS_SIMULATED,
        "1–3 ticks: the 2018–19 episode lasted two annual prints. "
        "No distribution estimate exists.",
        "internal: NONE (episode catalog only).",
        internal_field=None,
    ),
    _entry(
        "downturn_persistent/default",
        "downside_default",
        "Track C branch downside.py::DOWNSIDE_DEFAULT_* (UNMERGED branch fix/desay-gap-downside-on)",
        {"type": "bernoulli", "p": 0.15},
        STATUS_SIMULATED,
        "15%: a low-probability reversal regime (the downturn never "
        "recovers). No base rate exists — 0.15 is a judgment weight, "
        "taken as the majority value (2015 + Huawei; the 2020 per-case "
        "observation used 0.10).",
        "internal: NONE (episode catalog only).",
        internal_field=None,
    ),
]

# --- Group 5: transmission calibration v3 (live, from the module) ----
# Values are read from CALIBRATION_REPORT at registry build time so
# the registry cannot drift from the fit. The two adopted values are
# fitted; the six kept priors are placeholders WITH a recorded failed
# identification — the report, not the label, is what changed for them.
TRANSMISSION_ENTRIES: list[dict[str, Any]] = [
    _entry(
        "nev_penetration_monthly_drift",
        "transmission_v3",
        "services/calibration/transmission.py::ADOPTED_VALUES",
        {"type": "fixed", "value": 0.0068},
        STATUS_CALIBRATED_V3,
        "OLS trend on CAAM total-caliber annual NEV penetration "
        "2023–2025 (31.6% → 40.9% → 47.9%), slope +8.15pp/yr = "
        "0.0068/mo, R²=0.993; cross-checks 2025-only 0.0058, Jul–Dec "
        "monthly anchors 0.0072, logistic recent segment 0.0059. "
        "Gates passed. The 0.002 placeholder implied +2.4pp/yr "
        "against an observed +8.15pp/yr trend.",
        "public panel: extend the CAAM annual series past 2025 and "
        "re-run calibrate_transmission_coefficients (new decision "
        "time). NOT internal data.",
        internal_field=None,
    ),
    _entry(
        "income_growth_rate_annual",
        "transmission_v3",
        "services/calibration/transmission.py::ADOPTED_VALUES",
        {"type": "fixed", "value": 0.055},
        STATUS_CALIBRATED_V3,
        "Ridge-shrunk location fit (λ=5) of NBS nominal per-capita "
        "disposable-income growth 2020–2025 (mean 5.92%) toward the "
        "0.05 NBS-2025 anchor → fitted 5.50%. The prior gate passes "
        "NARROWLY (LOO 1.74pp vs prior-only 1.78pp) — a shrunk central "
        "estimate, not a precise one.",
        "public panel: extend the NBS series and re-run the fit. NOT "
        "internal data.",
        internal_field=None,
    ),
    _entry(
        "income_sensitivity",
        "transmission_v3",
        "services/calibration/transmission.py::ADOPTED_VALUES",
        {"type": "fixed", "value": 0.05},
        STATUS_KEPT_PRIOR,
        "v3 ATTEMPTED: joint ridge fit gives β=1.01 → 0.153, but LOO "
        "RMSE 7.64pp FAILS the mean baseline 5.14pp and the bivariate "
        "slope is unstable across windows (OLS 1.18 with 2020, 0.27 "
        "without). Placeholder RETAINED; the 95% CI spans zero.",
        "public panel: a quarterly panel with a mix-adjusted price "
        "index is the follow-up; a longer annual panel alone will "
        "not identify this (subsidy/NEV-mix confounding).",
        internal_field=None,
    ),
    _entry(
        "lpr_sensitivity",
        "transmission_v3",
        "services/calibration/transmission.py::ADOPTED_VALUES",
        {"type": "fixed", "value": 0.10},
        STATUS_KEPT_PRIOR,
        "v3 ATTEMPTED: joint ridge fit gives β=−0.35 → 0.112, but LOO "
        "RMSE 7.64pp fails the mean baseline; the bivariate slope "
        "FLIPS SIGN across windows (OLS +13.08 with 2020, −5.97 "
        "without) — 2024 subsidy-driven growth loads onto the LPR "
        "cut. All in-window LPR moves are cuts, so identification "
        "rests on cut-size variation alone.",
        "public panel: needs a hiking episode or a quarterly panel; "
        "not identifiable from the 2020–2025 annual cuts alone.",
        internal_field=None,
    ),
    _entry(
        "price_sensitivity",
        "transmission_v3",
        "services/calibration/transmission.py::ADOPTED_VALUES",
        {"type": "fixed", "value": 0.20},
        STATUS_KEPT_PRIOR,
        "v3 ATTEMPTED: joint ridge fit gives β=−0.46 → 0.039, LOO "
        "RMSE fails the mean baseline — BUT the joint 95% CI bounds "
        "price_sensitivity at [0, 0.159]: the 0.20 placeholder sits "
        "ABOVE the bound and is retained only as an upper-end "
        "sensitivity input. Average transaction price is mix-driven, "
        "not a clean price level.",
        "public panel: quarterly panel with a mix-adjusted price "
        "index. Until then the honest statement is '≤0.159', not "
        "'0.20'.",
        internal_field=None,
    ),
    _entry(
        "confidence_sensitivity",
        "transmission_v3",
        "services/calibration/transmission.py::ADOPTED_VALUES",
        {"type": "fixed", "value": 0.05},
        STATUS_KEPT_PRIOR,
        "v3 NOT ESTIMABLE: no verifiable quarterly PBOC willingness "
        "series (scattered points only: 2021Q2 25.1%, 2023Q1 23.2%, "
        "2024Q4 24.9%; band 23–25%). The annual panel cannot identify "
        "a quarterly-moving proxy.",
        "public panel: collect the full quarterly PBOC survey series "
        "and fit a quarterly panel.",
        internal_field=None,
    ),
    _entry(
        "material_passthrough",
        "transmission_v3",
        "services/calibration/transmission.py::ADOPTED_VALUES",
        {"type": "fixed", "value": 0.30},
        STATUS_KEPT_PRIOR,
        "v3 NOT ESTIMABLE: one clean annual pair only (2023→2024: "
        "lithium −64.5%, avg price +0.5%) — WRONG-SIGNED for "
        "passthrough, mix-shift dominated; and the template's "
        "material_cost_index is a lithium+steel/aluminum COMPOSITE "
        "whose weights are undefined, so even a lithium-only slope "
        "would not map to the coefficient.",
        "public panel: monthly Mysteel lithium + steel/aluminum "
        "series, composite weights defined, monthly price regression.",
        internal_field=None,
    ),
    _entry(
        "margin_material_sensitivity",
        "transmission_v3",
        "services/calibration/transmission.py::ADOPTED_VALUES",
        {"type": "fixed", "value": 0.02},
        STATUS_KEPT_PRIOR,
        "v3 NOT ESTIMABLE: wrong-sign episode — Desay margins FELL "
        "20% → 19.1% (2023–25) while lithium collapsed, i.e. while "
        "the driver would EXPAND margins. The decline was driven by "
        "the price-war / annual-cut channel, which the margin driver "
        "does not model (the same missing channel as gap-audit A2).",
        "public panel: add the annual-cut channel to the margin driver "
        "FIRST, then calibrate on a margin-vs-material panel.",
        internal_field=None,
    ),
]

#: Hand-curated entries (groups 1–5). Group 6 (other template labeled
#: assumptions) is derived live from TEMPLATE_VARIABLES — see
#: :func:`registry_entries`.
CURATED_ENTRIES: list[dict[str, Any]] = (
    ORDER_BOOK_ENTRIES
    + TIER1_ENTRIES
    + PROFIT_CHAIN_ENTRIES
    + DOWNSIDE_ENTRIES
    + TRANSMISSION_ENTRIES
)


def _template_derived_entries() -> list[dict[str, Any]]:
    """Other labeled assumptions, derived live from the template.

    Every TEMPLATE_VARIABLES entry whose evidence_ref is an assumption
    / labeled-assumption / pending-calibration marker and which is not
    already covered by a curated entry becomes a registry entry. The
    derivation is live so the inventory cannot go stale when the
    template changes; curated entries win on id collision.
    """

    from planagent.simulation.domain_packs.automotive.template_spec import (
        TEMPLATE_VARIABLES,
    )

    curated_ids = {entry["id"] for entry in CURATED_ENTRIES}
    # Template ids covered by curated entries under a scoped id.
    covered_bases = {
        "order_intake_rate",
        "backlog_conversion",
        "order_decay",
        "annual_cut_rate",
        "payment_terms_months",
        "tier1_gross_margin",
    }
    derived: list[dict[str, Any]] = []
    for var in TEMPLATE_VARIABLES:
        vid = var["id"]
        if vid in curated_ids or vid in covered_bases:
            continue
        ref = str(var.get("evidence_ref", ""))
        markers = ("assumption", "LABELED ASSUMPTION", "pending-calibration", "estimate:")
        if not any(marker in ref for marker in markers):
            continue
        derived.append(
            _entry(
                f"template/{vid}",
                "template_other",
                "template_spec.py::TEMPLATE_VARIABLES " + vid,
                var.get("distribution"),
                STATUS_SIMULATED,
                ref,
                "internal: per-variable — see the template evidence_ref; "
                "most are lever handles / planning parameters with no "
                "single internal series. Replacement is case-by-case "
                "through the same pipeline (parameter must first be "
                "added to INTERNAL_PARAMETER_SPECS).",
                internal_field=None,
                notes="Auto-derived from the live template; the "
                "evidence_ref IS the evidence record.",
            )
        )
    return derived


def _transmission_entries_live() -> list[dict[str, Any]]:
    """Transmission entries with ``current`` read from the live fit.

    The evidence text is curated; the VALUE is never hand-copied —
    it comes from ADOPTED_VALUES so the registry cannot drift from
    the calibration module.
    """

    import copy

    from planagent.services.calibration.transmission import ADOPTED_VALUES

    live = copy.deepcopy(TRANSMISSION_ENTRIES)
    for entry in live:
        entry["current"] = {"type": "fixed", "value": ADOPTED_VALUES[entry["id"]]}
    return live


def registry_entries() -> list[dict[str, Any]]:
    """All registry entries: curated (groups 1–5) + template-derived."""

    entries = [entry for entry in CURATED_ENTRIES if entry["group"] != "transmission_v3"]
    entries.extend(_transmission_entries_live())
    return entries + _template_derived_entries()


def entries_by_status(status: str) -> list[dict[str, Any]]:
    """Entries with the given status."""

    return [entry for entry in registry_entries() if entry["status"] == status]


def replaceable_entries() -> list[dict[str, Any]]:
    """Entries with an internal-data field: the pipeline's scope."""

    return [entry for entry in registry_entries() if entry.get("internal_field")]


__all__ = [
    "CURATED_ENTRIES",
    "DOWNSIDE_ENTRIES",
    "ORDER_BOOK_ENTRIES",
    "PROFIT_CHAIN_ENTRIES",
    "REGISTRY_VERSION",
    "STATUS_CALIBRATED_V3",
    "STATUS_EVIDENCE",
    "STATUS_KEPT_PRIOR",
    "STATUS_SIMULATED",
    "TIER1_ENTRIES",
    "TRANSMISSION_ENTRIES",
    "entries_by_status",
    "registry_entries",
    "replaceable_entries",
]

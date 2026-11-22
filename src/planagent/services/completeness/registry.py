"""Domain driver registry + general guided checklist (Phase 4, Track 10).

The registry is built from the auto pack's known transmission links
(Phase 1 pack state fields + Phase 2 template drivers/rules,
``simulation/domain_packs/automotive/``): every entry names the model
elements that count as "the driver is in the model" — a variable id, a
formula/driver output, or a rule id — and the state fields a tick
driver must carry it to (``link_outputs``), so the check can tell a
missing driver from a present-but-unlinked one.

A registry can only flag KNOWN drivers. That is the honest limit of
this check (see the Track 10 report): unknown unknowns are the LLM
red team's job, and the general checklist below is the fallback for
domains with no registry — it asks the builder the questions a
reviewer would ask, instead of pretending to know the domain.

Registry entries are plain data, no imports from the pack: the pack
is the authority for the links, this file is the snapshot of them
used by the check. ``test_phase4_completeness.py`` pins the snapshot
against the live pack (every primary element must exist as a template
variable, formula output, or rule id) so registry drift fails loudly.
"""

from __future__ import annotations

from dataclasses import dataclass

from .findings import BoundaryClass


@dataclass(frozen=True)
class DriverRegistryEntry:
    """One known external driver for a domain.

    ``model_elements``: any one of these present in the case counts as
    the driver being IN the model (variable id, formula output, driver
    output, or rule id — all compared lowercased, exact match).
    ``link_outputs``: state fields a formula/driver must produce for
    the driver to actually REACH a key variable. A driver that is
    present but reaches none of its link outputs is a ``missing_link``,
    not a pass. Entries whose carrier is NOT a formula — the split
    structure (domain-controller fitment) or a rule (DMS mandate) —
    carry an empty list: presence alone passes, and the wiring is the
    prompt/rule layer's job, not this check's. Link outputs must be
    real formula/driver outputs of the pack's template, never bare
    state fields no formula produces (``revenue`` is not one).
    ``drives``: key variables the driver moves, most-affected first.
    ``weight``: expected impact, 0-1; breaks ties inside a severity.
    ``boundary_class`` / ``boundary_basis``: the §6 verdict for a
    finding about this driver. Every registry entry is
    ``fixable_defect`` by admission: a driver enters the registry only
    when decision-time public evidence exists to encode it as a
    distribution. The ``acceptable_limit`` side of §6 is therefore
    never a registry finding — it is carried by residual-gap findings
    (see check.py), which is exactly where the unknowable magnitude
    lives.
    """

    id: str
    name: str
    description: str
    weight: float
    severity: str  # "high" | "medium" | "low"
    drives: list[str]
    model_elements: list[str]
    link_outputs: list[str]
    evidence: list[str]
    suggested_fix: str
    boundary_class: BoundaryClass
    boundary_basis: str


@dataclass(frozen=True)
class ChecklistItem:
    """One guided question for domains WITHOUT a registry.

    ``keywords`` are matched (lowercased substring) against the case's
    variable ids AND descriptions. A match means "the builder thought
    about this"; no match means the question is still open. Deliberately
    coarse: the checklist cannot know the domain, so it asks instead of
    asserting.
    """

    id: str
    question: str
    keywords: list[str]
    drives: list[str]
    suggested_fix: str


# ---------------------------------------------------------------------------
# Automotive registry — from the Phase 1/2 auto pack transmission links.
# Order is definition order (used for stable coverage lists); ranking is
# by (severity, weight) in check.py, never by this order.
# ---------------------------------------------------------------------------

AUTOMOTIVE_DRIVER_REGISTRY: list[DriverRegistryEntry] = [
    DriverRegistryEntry(
        id="nev_penetration",
        name="NEV penetration chain",
        description=(
            "NEV share of vehicle sales and its drift, splitting the "
            "production/retail spine into NEV and ICE tracks."
        ),
        weight=1.00,
        severity="high",
        boundary_class=BoundaryClass.FIXABLE_DEFECT,
        boundary_basis="§6 fixable defect: 2020-12-31 public evidence — NEV penetration 5.4%, State Council 20%-by-2025 target, NEV in the decision topic itself — could be encoded into a distribution.",
        drives=["revenue", "market_share", "production_volume"],
        model_elements=[
            "nev_penetration",
            "nev_penetration_monthly_drift",
            "nev_production_volume",
            "nev_retail_volume",
            "nev_share",
            "nev_adoption_rate",
            "auto.nev_momentum",
        ],
        link_outputs=[
            "nev_production_volume",
            "nev_retail_volume",
            "ice_production_volume",
            "ice_retail_volume",
        ],
        evidence=[
            "NEV volume 1.367M (2020) -> 16.49M (2025), 65% CAGR (desay backtest 2026-11-19)",
            "NEV penetration 5.4% (2020) -> 47.9% (2025, CAAM total-volume caliber)",
            "desay-2020 B-arm revenue P50 underestimated actual by 52.3% with no NEV variable in the model (desay backtest 2026-11-19)",
        ],
        suggested_fix=(
            "Add `nev_penetration` (+ `nev_penetration_monthly_drift`) as variables "
            "with a tick driver splitting revenue/production into NEV/ICE tracks, "
            "or bind the automotive template's NEV chain."
        ),
    ),
    DriverRegistryEntry(
        id="adas_penetration",
        name="ADAS / L2 penetration chain",
        description=(
            "L2 / combined driving-assist fitment share of new-car sales "
            "and its diffusion, carrying the intelligent-driving "
            "grade effect into supplier revenue and share. The grade "
            "channel (L2 within new cars) is distinct from the broad "
            "adoption channel (any smart function): the two price "
            "different hardware, so the chain must be built on that "
            "division of labor (TRACK-C1.md §1), not as a second "
            "adoption curve."
        ),
        weight=0.85,
        severity="medium",
        boundary_class=BoundaryClass.FIXABLE_DEFECT,
        boundary_basis="§6 fixable defect: 2020-12-31 public evidence — L2 fitment ~12% (Canalys Q4-2020; decision-time-knowable range 11-16%), NEV L2 premium 25.3% vs ICE 14.3%, intelligent-driving revenue +94.78% in 2020 off RMB 712m (10.48% of revenue) — could be encoded into a distribution.",
        drives=["revenue", "market_share"],
        model_elements=[
            "adas_penetration",
            "adas_penetration_monthly_drift",
            "adas_ceiling",
            "adas_rate",
            "adas_midpoint",
            "adas_coupling",
        ],
        link_outputs=[
            "adas_penetration",
        ],
        evidence=[
            "L2 share of new-car sales, China, Q4 2020: 12% (Canalys, published 2021-03-25/26; decision-time-knowable range 11-16% per diagnostic-2020/evidence-2020.md §1.4)",
            "MIIT combined driving-assist fitment 16.2% (2020) -> 64.9% (2025) (diagnostic-2020/evidence-2020.md §2.5)",
            "Desay intelligent-driving revenue 7.12亿 (2020) -> 97.00亿 (2025), 13.6x (DIAGNOSTIC-2020.md §5.1c: the real growth engine)",
        ],
        suggested_fix=(
            "Add `adas_penetration` (+ `adas_ceiling` / `adas_rate` / "
            "`adas_midpoint` / `adas_coupling`) as variables with a "
            "logistic tick driver, and gain exactly one additive term "
            "in the revenue driver (`+ adas_coupling * adas_penetration`) "
            "and one in the share driver — or bind the automotive "
            "template's ADAS chain. Keep the division of labor with "
            "`disruptor_adoption` / `revenue_coupling`: grade (L2 "
            "premium stack) vs breadth (average smart content)."
        ),
    ),
    DriverRegistryEntry(
        id="domain_controller_substitution",
        name="domain-controller substitution",
        description=(
            "Cockpit / driving domain controllers displacing discrete ECUs and "
            "screens, changing product mix, camera counts, and ASPs."
        ),
        weight=0.90,
        severity="high",
        boundary_class=BoundaryClass.FIXABLE_DEFECT,
        boundary_basis="§6 fixable defect: 2020-12-31 public evidence — IPU03 in mass production on XPeng P7, IPU04/Orin cooperation announced, DC fitment by price band published — could be encoded into a distribution.",
        drives=["revenue", "market_share", "tier1_gross_margin"],
        model_elements=[
            "cockpit_domain_controller_fitment",
            "domain_controller_penetration",
            "domain_controller_substitution",
            "cockpit_domain_controller",
            "scdc_penetration",
            "domain_controller_share",
            # The pack carries DC substitution in assumption data, not
            # in a variable: the fitment lookup (cockpit domain
            # controller by price band, synthesis B2) is the model
            # element. A case binding the full automotive template
            # carries it via `fitment_lookup`.
            "fitment_lookup",
            "cockpit_domain_controller_by_price_band",
        ],
        link_outputs=[],
        evidence=[
            "Desay smart-driving revenue 7.12亿 (2020) -> 97.00亿 (2025), 13.6x (desay backtest 2026-11-19)",
            "Cockpit domain-controller fitment by price band: 9.3% (<10万) -> 41.7% (10-20万) -> 86.4% (>20万) (synthesis B2)",
            "Co-occurrence rule R1: domain controller => cameras (Phase 2 prompts)",
        ],
        suggested_fix=(
            "Add a `domain_controller_penetration` / "
            "`cockpit_domain_controller_fitment` variable (fitment by price band, "
            "synthesis B2) linked to revenue and camera demand, or bind the "
            "automotive template + split structure."
        ),
    ),
    DriverRegistryEntry(
        id="income",
        name="disposable-income transmission",
        description="Disposable-income level and growth feeding vehicle demand.",
        weight=0.70,
        severity="high",
        boundary_class=BoundaryClass.FIXABLE_DEFECT,
        boundary_basis="§6 fixable defect: NBS per-capita disposable income is published statistics, encodable into a distribution at decision time.",
        drives=["sales_volume_retail", "revenue", "production_volume"],
        model_elements=[
            "income_index",
            "income_growth_rate_annual",
            "income_sensitivity",
            "disposable_income",
        ],
        link_outputs=["income_index", "sales_volume_retail"],
        evidence=[
            "NBS per-capita disposable income CNY 43,377 in 2025, nominal +5.0% (synthesis B4)",
            "C2 link: income -> demand (Phase 2 retail driver)",
        ],
        suggested_fix=(
            "Add `income_index` + `income_growth_rate_annual` as variables and "
            "let the retail driver read the current income level each tick."
        ),
    ),
    DriverRegistryEntry(
        id="lpr_financing",
        name="LPR / financing-cost transmission",
        description="Interest-rate environment (LPR proxy) feeding demand via financing cost.",
        weight=0.65,
        severity="high",
        boundary_class=BoundaryClass.FIXABLE_DEFECT,
        boundary_basis="§6 fixable defect: the LPR is published by the PBOC; the financing-cost channel could be encoded into a distribution at decision time.",
        drives=["sales_volume_retail", "revenue"],
        model_elements=[
            "lpr_proxy",
            "lpr_sensitivity",
            "financing_cost",
            "interest_rate",
            "auto.rate_cut",
        ],
        link_outputs=["sales_volume_retail"],
        evidence=[
            "C2 link: LPR -> financing cost -> demand (Phase 2 retail driver)",
            "No public rate elasticity exists; the pack sensitivity is a labeled assumption (synthesis C5)",
        ],
        suggested_fix=(
            "Add `lpr_proxy` + `lpr_sensitivity` as variables and let the retail "
            "driver read the current rate proxy each tick."
        ),
    ),
    DriverRegistryEntry(
        id="raw_materials",
        name="raw-material cost transmission",
        description="Raw-material cost pressure passing into prices and squeezing margin.",
        weight=0.65,
        severity="high",
        boundary_class=BoundaryClass.FIXABLE_DEFECT,
        boundary_basis="§6 fixable defect: lithium/steel/aluminum prices are public market data, encodable into a distribution at decision time.",
        drives=["tier1_gross_margin", "price_index", "revenue"],
        model_elements=[
            "material_cost_index",
            "material_passthrough",
            "margin_material_sensitivity",
            "raw_material_cost",
            "lithium_price",
            "auto.material_cost_shock",
        ],
        link_outputs=["price_index", "tier1_gross_margin"],
        evidence=[
            "C2 links 7-8: materials -> price passthrough -> margin squeeze (Phase 2 drivers)",
            "Material cost index is a lithium + steel/aluminum proxy composite, 1.0 = baseline (synthesis C1)",
        ],
        suggested_fix=(
            "Add `material_cost_index` + `material_passthrough` as variables with "
            "the price driver (partial adjustment) and the margin driver "
            "(unpassed pressure squeezes margin)."
        ),
    ),
    DriverRegistryEntry(
        id="consumer_confidence",
        name="consumer-confidence transmission",
        description="Consumer-confidence proxy feeding demand growth.",
        weight=0.55,
        severity="medium",
        boundary_class=BoundaryClass.FIXABLE_DEFECT,
        boundary_basis="§6 fixable defect: the PBOC household survey is published, encodable into a distribution at decision time.",
        drives=["sales_volume_retail", "revenue"],
        model_elements=["consumer_confidence_proxy", "confidence_sensitivity"],
        link_outputs=["demand_growth_rate", "sales_volume_retail"],
        evidence=[
            "PBOC household-survey willingness proxy, 24.6% in 2024Q4 (synthesis B4)",
            "C2 link: confidence -> demand growth (Phase 1 formula)",
        ],
        suggested_fix=(
            "Add `consumer_confidence_proxy` + `confidence_sensitivity` as "
            "variables feeding `demand_growth_rate`."
        ),
    ),
    DriverRegistryEntry(
        id="policy_tax",
        name="purchase-tax / subsidy policy",
        description="Purchase-tax rate, trade-in support, and subsidy payback shaping demand level.",
        weight=0.60,
        severity="medium",
        boundary_class=BoundaryClass.FIXABLE_DEFECT,
        boundary_basis="§6 fixable defect: purchase-tax and subsidy policy are public at decision time; the tax-rate lever could be encoded into a distribution.",
        drives=["sales_volume_retail", "revenue"],
        model_elements=[
            "policy_tax_rate",
            "tax_sensitivity",
            "trade_in_support",
            "purchase_tax_rate",
            "subsidy_support",
            "auto.policy_tax_hike",
            "auto.subsidy_payback",
        ],
        link_outputs=["demand_level_factor", "sales_volume_retail"],
        evidence=[
            "MOF/STA/MIIT Announcement 2023 No.10: NEV purchase tax halved to 5% in 2026-27 (synthesis B3)",
            "2026 cliff event anchor: +20% low-band purchase cost, ~-25% volume (synthesis C2 link 2)",
        ],
        suggested_fix=(
            "Add `policy_tax_rate` + `tax_sensitivity` as variables with the "
            "demand-level factor applied once, on tick 1."
        ),
    ),
    DriverRegistryEntry(
        id="chip_supply",
        name="chip-supply constraint",
        description="Chip supply level and lead times constraining production.",
        weight=0.55,
        severity="medium",
        boundary_class=BoundaryClass.FIXABLE_DEFECT,
        boundary_basis="§6 fixable defect: chip lead times are published (Susquehanna); a supply-level distribution could be encoded at decision time.",
        drives=["production_volume", "revenue"],
        model_elements=[
            "chip_supply_index",
            "chip_lead_time_weeks",
            "semiconductor_supply",
            "auto.chip_shortage",
        ],
        link_outputs=["production_volume"],
        evidence=[
            "Susquehanna 2022-02 peak anchor: 26.2w average lead time, MCU 35.7w (synthesis B4)",
            "C2 link 6: chip supply -> production (Phase 1 driver)",
        ],
        suggested_fix=(
            "Add `chip_supply_index` (+ `chip_lead_time_weeks`) as variables "
            "with the production driver constraining output when supply is below normal."
        ),
    ),
    DriverRegistryEntry(
        id="price_competition",
        name="price / promotion competition",
        description="Transaction prices, promotion rates, and wait-and-see buyers dragging demand.",
        weight=0.55,
        severity="medium",
        boundary_class=BoundaryClass.FIXABLE_DEFECT,
        boundary_basis="§6 fixable defect: terminal promotion rates and wait-and-see shares are published (CPCA, Roland Berger/Autohome), encodable at decision time.",
        drives=["sales_volume_retail", "revenue", "tier1_gross_margin"],
        model_elements=[
            "price_index",
            "price_sensitivity",
            "promo_rate",
            "price_cut_expectation",
            "auto.price_war",
        ],
        link_outputs=["price_index", "sales_volume_retail"],
        evidence=[
            "CPCA terminal promotion rate c.10%, Nov/Dec 2025 (synthesis B1)",
            "Wait-and-see buyer share 28% (2023) -> 45% (2025H1) (Roland Berger/Autohome, synthesis B5)",
        ],
        suggested_fix=(
            "Add `price_index` + `price_sensitivity` as variables and let the "
            "retail driver read the current price level each tick."
        ),
    ),
    DriverRegistryEntry(
        id="generation_transition",
        name="model-generation transition",
        description="Nameplate generation changeover (outgoing phase-out, successor ramp).",
        weight=0.50,
        severity="medium",
        boundary_class=BoundaryClass.FIXABLE_DEFECT,
        boundary_basis="§6 fixable defect: nameplate changeovers are public OEM announcements; the transition schedule could be encoded at decision time.",
        drives=["market_share", "revenue", "production_volume"],
        model_elements=[
            "generation_transition_index",
            "generation_mix",
            "model_generation_share",
            "auto.generation_changeover",
        ],
        link_outputs=["generation_transition_index"],
        evidence=[
            "Generation/lifecycle dimension (Ho 2026-11-16); per-nameplate schedules in Phase 2",
            "T-Roc rows are a generation transition, not a data error (Ho Part D follow-up)",
        ],
        suggested_fix=(
            "Add `generation_transition_index` as a variable with the tick driver "
            "ramping the successor share, or per-nameplate transition schedules "
            "in the split structure."
        ),
    ),
    DriverRegistryEntry(
        id="pull_forward",
        name="subsidy pull-forward drag",
        description="Demand pulled forward by subsidies, decaying back over following years.",
        weight=0.45,
        severity="medium",
        boundary_class=BoundaryClass.FIXABLE_DEFECT,
        boundary_basis="§6 fixable defect: the 2025 trade-in scale is published (NDRC/MOF); a pull-forward stock could be encoded at decision time.",
        drives=["sales_volume_retail"],
        model_elements=[
            "pull_forward_stock",
            "pull_forward_stock_initial",
            "subsidy_pull_forward",
        ],
        link_outputs=["pull_forward_stock", "sales_volume_retail"],
        evidence=[
            "2025 trade-in scale exceeded 11.5M vehicles (NDRC/MOF, synthesis B3)",
            "C2 link 11: pull-forward stock decay drags retail (Phase 1 driver)",
        ],
        suggested_fix=(
            "Add `pull_forward_stock` as a variable with the 2%-per-tick decay "
            "driver dragging retail."
        ),
    ),
    DriverRegistryEntry(
        id="tier1_economics",
        name="Tier-1 commercial terms",
        description="OEM annual price cuts, payment terms, and Tier-1 gross margin.",
        weight=0.45,
        severity="medium",
        boundary_class=BoundaryClass.FIXABLE_DEFECT,
        boundary_basis="§6 fixable defect: OEM annual-cut ranges and payment terms are industry-known and Ho-authorized as simulated averages, encodable at decision time.",
        drives=["tier1_gross_margin", "revenue"],
        model_elements=[
            "annual_cut_rate",
            "payment_terms_months",
            "tier1_gross_margin",
        ],
        link_outputs=["tier1_gross_margin"],
        evidence=[
            "OEM annual price-cut 3-5% conventional, 10%+ stressed (synthesis B5)",
            "Payment terms 6 months common under the n+3+6 structure (synthesis B5)",
        ],
        suggested_fix=(
            "Add `annual_cut_rate`, `payment_terms_months`, and "
            "`tier1_gross_margin` as variables (simulated industry averages, "
            "Ho-authorized 2026-11-16, replaceable with internal actuals)."
        ),
    ),
    DriverRegistryEntry(
        id="dealer_inventory",
        name="dealer-inventory channel",
        description="Dealer inventory coefficient and warning index feeding production discipline.",
        weight=0.50,
        severity="medium",
        boundary_class=BoundaryClass.FIXABLE_DEFECT,
        boundary_basis="§6 fixable defect: the CADA dealer inventory coefficient is published, encodable at decision time.",
        drives=["production_volume"],
        model_elements=[
            "dealer_inventory_coef",
            "inventory_warning",
            "dealer_inventory",
            "auto.inventory_overhang",
        ],
        link_outputs=["dealer_inventory_coef", "production_volume"],
        evidence=[
            "CADA Sep 2025: dealer inventory coefficient 1.35; 0.8-1.2 reasonable, above 1.5 is the warning line (synthesis B1)",
            "C2 link 3: wholesale-retail gap -> inventory -> production (Phase 1 drivers)",
        ],
        suggested_fix=(
            "Add `dealer_inventory_coef` as a variable with the inventory driver "
            "(wholesale minus retail) feeding the production driver."
        ),
    ),
    DriverRegistryEntry(
        id="dms_mandate",
        name="DMS regulation mandate",
        description="Mandatory driver-monitoring (GB 47955-2026) switching on from 2027.",
        weight=0.40,
        severity="medium",
        boundary_class=BoundaryClass.FIXABLE_DEFECT,
        boundary_basis="§6 fixable defect: GB 47955-2026 was published before its 2027-01-01 effective date; the mandate switch could be encoded at decision time.",
        drives=["revenue", "market_share"],
        model_elements=["dms_mandate", "dms_penetration", "auto.dms_mandate"],
        link_outputs=[],
        evidence=[
            "GB 47955-2026: mandatory DMS + accident recording from 2027-01-01 (synthesis B3)",
        ],
        suggested_fix=(
            "Add `dms_mandate` as a 0/1 switch variable, levered to 1.0 for the "
            "2027+ electronics-acceleration family."
        ),
    ),
    DriverRegistryEntry(
        id="export_demand",
        name="export demand",
        description="Export volume as a transmission intermediate (not part of the production spine).",
        weight=0.30,
        severity="low",
        boundary_class=BoundaryClass.FIXABLE_DEFECT,
        boundary_basis="§6 fixable defect: CAAM export volumes are published statistics, encodable at decision time.",
        drives=["production_volume", "revenue"],
        model_elements=["export_volume", "auto.export_hedge"],
        link_outputs=[],
        evidence=[
            "CAAM 2025 exports 7.098M vehicles, +21.1% (synthesis C1)",
        ],
        suggested_fix="Add `export_volume` as a variable if export exposure moves the decision.",
    ),
    DriverRegistryEntry(
        id="capacity_utilization",
        name="capacity utilization",
        description="Auto-manufacturing capacity utilization bounding production.",
        weight=0.30,
        severity="low",
        boundary_class=BoundaryClass.FIXABLE_DEFECT,
        boundary_basis="§6 fixable defect: NBS capacity utilization is published quarterly, encodable at decision time.",
        drives=["production_volume"],
        model_elements=["capacity_utilization"],
        link_outputs=[],
        evidence=[
            "NBS 66.2% in 2026Q3, -7.1pp; 2021-24 range 72.2-74.7% (synthesis B1)",
        ],
        suggested_fix="Add `capacity_utilization` as a variable if capacity constraints bind the decision.",
    ),
]

#: Domains with a registry, by domain id.
REGISTRIES: dict[str, list[DriverRegistryEntry]] = {
    "automotive": AUTOMOTIVE_DRIVER_REGISTRY,
}

# ---------------------------------------------------------------------------
# General guided checklist — for every domain WITHOUT a registry.
# ---------------------------------------------------------------------------

GENERAL_DRIVER_CHECKLIST: list[ChecklistItem] = [
    ChecklistItem(
        id="external_demand",
        question="What external demand driver moves the outcome (market growth, adoption, penetration)?",
        keywords=[
            "demand",
            "adoption",
            "penetration",
            "market_growth",
            "sales_growth",
            "consumption",
        ],
        drives=["revenue", "market_share"],
        suggested_fix=(
            "Name the single biggest external demand driver in the decision topic "
            "and add it as a variable with an evidence ref."
        ),
    ),
    ChecklistItem(
        id="input_cost",
        question="What input-cost driver moves price or margin?",
        keywords=["cost", "material", "input", "commodity", "wage", "energy_price"],
        drives=["revenue", "profit"],
        suggested_fix=(
            "Add a variable for the largest input-cost driver (materials, labour, "
            "energy) and link it to price or margin."
        ),
    ),
    ChecklistItem(
        id="substitution",
        question="What substitutes for, or displaces, the current product?",
        keywords=["substitution", "displacement", "disruptor", "replacement", "cannibal"],
        drives=["market_share", "revenue"],
        suggested_fix=(
            "Add a variable for the displacing technology or substitute and link "
            "it to share or revenue."
        ),
    ),
    ChecklistItem(
        id="policy",
        question="What policy, tax, or regulation moves the outcome?",
        keywords=["policy", "tax", "regulation", "subsidy", "tariff", "mandate"],
        drives=["revenue", "market_share"],
        suggested_fix=(
            "Add a variable for the binding policy lever (tax rate, subsidy, "
            "mandate switch) and link it to demand or cost."
        ),
    ),
    ChecklistItem(
        id="supply",
        question="What supply constraint can bind (capacity, lead time, inventory)?",
        keywords=["supply", "capacity", "lead_time", "inventory", "bottleneck", "shortage"],
        drives=["revenue"],
        suggested_fix=(
            "Add a variable for the binding supply constraint and link it to "
            "production or delivery."
        ),
    ),
    ChecklistItem(
        id="competition",
        question="What competitive move changes share or price?",
        keywords=["competit", "rival", "share", "price_war"],
        drives=["market_share", "revenue"],
        suggested_fix=(
            "Add a variable for the competitive pressure (rival share, price war) "
            "and link it to share or price."
        ),
    ),
    ChecklistItem(
        id="macro",
        question="What macro driver (rates, income, FX, inflation) moves the outcome?",
        keywords=["rate", "interest", "income", "inflation", "fx", "exchange", "gdp"],
        drives=["revenue"],
        suggested_fix=(
            "Add a variable for the macro driver named in the decision topic "
            "(rate, income, FX) and link it to demand."
        ),
    ),
    ChecklistItem(
        id="technology",
        question="What technology shift changes the product or the cost curve?",
        keywords=["technolog", "innovation", "platform", "generation", "digital"],
        drives=["market_share", "revenue"],
        suggested_fix=(
            "Add a variable for the technology shift (platform, generation, "
            "process) and link it to share or cost."
        ),
    ),
]

__all__ = [
    "AUTOMOTIVE_DRIVER_REGISTRY",
    "GENERAL_DRIVER_CHECKLIST",
    "REGISTRIES",
    "ChecklistItem",
    "DriverRegistryEntry",
]

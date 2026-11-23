"""Built-in corporate variable template: raw spec dicts (profit-chain pack).

The spec lives here as plain JSON-shaped dicts so the domain pack stays
free of Pydantic imports; :func:`builtin_template` validates the dicts
into models at synthesis time and refuses to synthesize a broken
built-in. The corporate template was EMPTY before the profit-chain
pack (0 variables / 0 formulas: the corporate pack's state defaults
alone were the preset); it now carries exactly the profit transmission
chain — the same four variables and four formulas as the automotive
template, with the same distributions and the same template defaults
(mode net margin 0.20 = the pack's own implied margin, profit 20.0 /
revenue 100.0 state defaults; actor overlays 120/24 and 60/12 keep
the same 20% implied margin).

Profit transmission chain (profit-chain pack, 2026-11-20; Track B
harness form promoted, diagnosis
``profit-chain-pack-2026-11-20/diagnosis/DIAGNOSIS-2015.md`` §4):
``profit(t) = revenue(t) x net_margin(t)`` with
``net_margin(t) = margin_base + 0.25 x (margin_longrun -
margin_base) x (tick-1) + margin_adoption x disruptor_adoption``,
clamped to [0.02, 0.25]. The reversion is LINEAR: each tick closes
25% of the ORIGINAL gap, so tick 4 closes 75% and leaves 25% —
NOT geometric (TRACK-B §2's "(0.75)^3 ≈ 42%" was a documentation
error; the implementation was always linear — see the CORRECTION
appended to TRACK-B.md). The clamp's upper rail is 0.25, not
Track B's 0.15: the template's own implied net margin is 0.20,
so a 0.15 rail would clip generic runs to 0.15 and break the
"generic run unaffected" convention.

SCOPE (M3, read before using the chain on a new case): the chain
assumes the net margin reverts MONOTONICALLY and LINEARLY from its
decision-year level toward its pre-decision two-year mean. It fits
cases whose starting margin is near its settled level with a flat
or gently falling realized path (2020-type). KNOWN MISFIT:
decision-year margin SPIKE cases — decision-year net margin more
than 2pp above the prior-two-year mean (2015-type: +3.79pp) — where
the yr3 net margin is systematically HIGH (realized path rises
first, then cliffs); judge such cases by the profit P50, never by
a single replay. The chain is a reduced-form expression of cost
behavior, NOT a separate R&D-expense line: TRACK-B §8.7 —
decision-time evidence does not support an R&D-intensity trend
assumption, so no R&D line is built here.

MERGE-ORDER NOTE (why the template carries a ``revenue``
passthrough driver): template formulas always evaluate BEFORE
case-appended formulas, so a template ``profit`` driver would
otherwise read PRE-tick revenue (one-tick lag vs Track B's
same-tick form). The passthrough is an identity driver on the
pack's ``revenue`` state field (self-reference = current state);
a case revenue driver replaces it IN PLACE at merge time, so it
evaluates BEFORE ``net_margin`` / ``profit`` and profit reads
same-tick revenue — exactly the Track B semantics. The passthrough
also makes ``revenue`` a known id for template validation (the
formula language's known ids are sampled variables + earlier
driver outputs; ``revenue`` is a state field, not a template
variable). At runtime it is exactly identity (4-decimal rounding
only: the state value it reads is already 4-decimal).

M2 (diagnosis §4): margin_base is sampled DIRECTLY —
triangular(mode-0.02, mode, mode+0.02) — instead of the Track B
ratio of two independently sampled profit/revenue draws (same SD
order, no ratio-construction tail; the replay trajectory changes,
so the baseline is rebuilt by the pack rerun).

NOTE on margin caliber: the template's margin is a NET margin.
A case whose ``profit`` state field is an OPERATING profit (Nokia:
the evidence_ref says operating profit) must anchor margin_base /
margin_longrun on the SAME operating-profit caliber — the chain
is then an operating-margin chain, not a net-margin chain, and
the case must say so in its evidence_ref. The template itself
cannot know a case's profit caliber.
"""

from __future__ import annotations

# Profit transmission chain (profit-chain pack, 2026-11-20): the
# chain's four parameters. The margin itself is the template's
# `net_margin` tick-driver output (intermediate, not a state field)
# and profit is the pack's `profit` STATE field, reused. A case
# attaches the chain by binding margin_base / margin_longrun to its
# decision-time figures; the template defaults below make a generic
# run's margin sit at the template's own implied net margin (0.20),
# so generic runs keep profit at its default (revenue x 0.20).
CORPORATE_TEMPLATE_VARIABLES: list[dict] = [
    {
        "id": "margin_base",
        "unit": "rate",
        "distribution": {"type": "triangular", "min": 0.18, "mode": 0.20, "max": 0.22},
        "evidence_ref": "assumption:pending-calibration — template default mode 0.20 IS the template's own implied net margin (profit 20.0 / revenue 100.0 state defaults; actor overlays 120/24 and 60/12 keep the same 20%); a case binds its decision-year profit/revenue as the mode. The +-0.02 spread is a LABELED ASSUMPTION, same width as margin_adoption (M2: direct sampling replaces the Track B profit/revenue ratio; SD ~0.82pp, same order as the ratio construction's 0.84pp/0.53pp)",
        "description": "Starting net margin at the decision year: the level the chain mean-reverts FROM. Directly sampled triangular(mode-0.02, mode, mode+0.02); the mode is the case's decision-year profit/revenue (template default 0.20 = the pack's own implied margin).",
    },
    {
        "id": "margin_longrun",
        "unit": "rate",
        "distribution": {"type": "fixed", "value": 0.20},
        "evidence_ref": "assumption:pending-calibration — template default 0.20 IS the template's own implied net margin (profit 20.0 / revenue 100.0); a case binds the mean net margin of the two years BEFORE its decision year (Nokia: 0.1346 on the OPERATING-profit caliber; Huawei: 0.1318 fallback = decision-year mode, no verifiable two-year profit history). LABELED ASSUMPTION: the anchor definition (pre-decision two-year mean) is the chain's, the value is case-bound.",
        "description": "Long-run net margin the chain mean-reverts TOWARD: the mean of the two years before the decision year (anchor definition fixed, value case-bound; template default 0.20 = no reversion in a generic run, since margin_base mode equals it).",
    },
    {
        "id": "margin_reversion",
        "unit": "per-tick",
        "distribution": {"type": "fixed", "value": 0.25},
        "evidence_ref": "estimate: LABELED ASSUMPTION — a quarter of the gap to the long-run mean closes per tick (round number, fixed before the run; Track B §4 sensitivity: no globally optimal value exists, 0.25 is the a priori choice, not a fit)",
        "description": "Net-margin mean-reversion speed: each tick closes 25% of the ORIGINAL gap to margin_longrun (LINEAR reversion — tick 4 closes 75%, leaving 25% — not geometric; see the module docstring).",
    },
    {
        "id": "margin_adoption",
        "unit": "margin points per unit adoption",
        "distribution": {"type": "triangular", "min": -0.02, "mode": 0.0, "max": 0.02},
        "evidence_ref": "estimate: LABELED ASSUMPTION — net effect of adoption on the net margin; mode 0 (no signed decision-time evidence: scale/learning vs annual-cut price pressure; gross margin fell 2017-19 while R&D intensity rose)",
        "description": "Net effect of disruptor adoption on the net margin per unit of adoption (mode 0: no signed decision-time evidence).",
    },
]

# Order inside this list is load-bearing: disruptor_adoption first
# (net_margin reads it; a case adoption curve replaces it in place),
# then the revenue passthrough (a case revenue driver replaces it in
# place, so it evaluates BEFORE net_margin and profit), then
# net_margin, then profit — profit reads SAME-TICK revenue, exactly
# the Track B semantics. The formula language has no `clamp`
# operator (eight ops only: add/subtract/multiply/divide/min/max/
# pow/logistic), so the clamp is min(max(...)) nesting, as in the
# Track B harness.
CORPORATE_TEMPLATE_FORMULAS: list[dict] = [
    {
        "output": "disruptor_adoption",
        "tick_driver": True,
        "expression": 0.0,
        "description": "Tick driver (profit-chain pack): default zero disruptor-adoption intermediate (a bare-number expression is a legal formula). A case with an adoption curve replaces this driver per-output (NEV drift driver precedent); without it, Huawei/generic runs would leave net_margin referencing an undefined quantity. Mode 0: no signed decision-time evidence for adoption moving the margin.",
    },
    {
        "output": "revenue",
        "tick_driver": True,
        "expression": {"ref": "revenue"},
        "description": "Tick driver (profit-chain pack): identity passthrough on the pack's revenue state field (a driver self-reference reads the field's current state value). MERGE ANCHOR, not a model: (1) it makes `revenue` a known id for template validation — the formula language's known ids are sampled variables + earlier driver outputs, and `revenue` is a state field, not a template variable — so the profit driver below can reference it; (2) a case revenue driver replaces this driver IN PLACE at merge time, so the case revenue evaluates BEFORE net_margin/profit and profit reads same-tick revenue (Track B semantics) instead of pre-tick revenue (one-tick lag). At runtime it is exactly identity (4-decimal rounding only: the state value it reads is already 4-decimal).",
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
                            "op": "add",
                            "args": [
                                {
                                    "op": "add",
                                    "args": [
                                        {"ref": "margin_base"},
                                        {
                                            "op": "multiply",
                                            "args": [
                                                {
                                                    "op": "multiply",
                                                    "args": [
                                                        {"ref": "margin_reversion"},
                                                        {
                                                            "op": "subtract",
                                                            "args": [{"ref": "margin_longrun"}, {"ref": "margin_base"}],
                                                        },
                                                    ],
                                                },
                                                {"op": "subtract", "args": [{"ref": "tick"}, 1]},
                                            ],
                                        },
                                    ],
                                },
                                {"op": "multiply", "args": [{"ref": "margin_adoption"}, {"ref": "disruptor_adoption"}]},
                            ],
                        },
                    ],
                },
            ],
        },
        "description": "Tick driver (profit-chain pack): net margin mean-reverts LINEARLY toward margin_longrun at margin_reversion per tick — each tick closes 25% of the ORIGINAL gap (tick 4 closes 75%, leaving 25%), plus margin_adoption x adoption (mode 0: no signed decision-time evidence); clamped to [0.02, 0.25]. The 0.25 upper rail (not Track B's 0.15) is the pack-level rail: the template's own implied net margin is 0.20, so a 0.15 rail would clip generic runs. Intermediate, not a state field. SCOPE: assumes monotone linear reversion from the decision-year level toward the pre-decision two-year mean; known misfit on decision-year margin-spike cases (>2pp above the prior-two-year mean, 2015-type: yr3 margin systematically high — judge by P50, not a single replay).",
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
        "description": "Tick driver (profit-chain pack): profit = same-tick revenue x net_margin — inherits the revenue drivers in full; replaces the decoupled profit_growth driver. Evaluates AFTER the (case) revenue driver via the revenue-passthrough merge anchor, so it reads same-tick revenue exactly as the Track B harness did.",
    },
]

# No assumption data ships with the corporate template (the automotive
# template's fitment lookup / supply-share data is auto-specific).
CORPORATE_TEMPLATE_ASSUMPTION_DATA: dict = {}

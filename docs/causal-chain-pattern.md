# Causal-chain pattern: driver variable + link formulas

- Date: 2026-11-19 (Track 7, Phase 4; Track 11 adds §5, the order-book
  worked example, 2026-11-19; Track C1 adds §6, the ADAS penetration
  chain, 2026-11-20)
- Status: pattern + three worked examples (NEV transmission chain, level
  term; order-book mechanism, shape term; ADAS penetration chain, grade
  term). The shape fix is now BUILT (Track 11), not just designed.
- Authority: desay-backtest-2026-11-19/diagnostic-2020/DIAGNOSTIC-2020.md
  §5.2 + new-parameter.md §2 (the NEV-chain build spec); the Desay
  re-run harness under
  research/strategy-engine/desay-backtest-2026-11-19/autopack-rerun/.

## 1. The pattern

A causal chain is **a driver variable + link formulas**. It replaces the
older practice of expressing adoption as a closed-form time curve
(`logistic(rate * (tick - midpoint), ceiling)` as a free-standing
intermediate) with a chain of state-reading links:

```
external driver (sampled variable, decision-time evidence)
  → intermediate state (pack state field, driven per tick)
    → demand / value / share links (tick-driver formulas)
      → revenue / profit (tick-driver formulas, scored metrics)
```

Rules:

1. **Links read state, never `tick` alone.** A link formula's inputs
   are sampled variables and current state fields. The one exception
   is the driver itself when the diagnostic spec parameterizes it as
   a logistic in `tick` (the NEV chain below): the logistic is still
   driven by sampled variables (`nev_ceiling` / `nev_rate` /
   `nev_midpoint`), never by a hardcoded time series — and it writes
   to a shared state field so downstream links and the dual track see
   the same value.
2. **The driver variable is a first-class template variable** with a
   decision-time evidence anchor and a distribution (triangular for
   the NEV chain). Arms pin it (levers) or leave it sampled; they
   never rewrite the link.
3. **One additive term per channel.** Each channel adds exactly one
   term to the downstream formula (the NEV chain adds
   `+ nev_coupling * nev_penetration` to revenue). No interaction
   terms unless evidence quantifies one. Channels stay decomposable:
   any run's uplift splits exactly into per-channel contributions.
4. **Share and profit formulas are untouched by a revenue channel**
   unless their own transmission is separately evidenced.
5. **Initial-state calibration is explicit.** When a link's t=0
   identity has a free parameter (e.g. value-per-vehicle), its mode is
   set so the chain reproduces the decision-time known starting level
   at mode inputs, and the calibration arithmetic is written down.
   Calibrating t=0 to known inputs is not tuning to outcomes.

## 2. Worked example: the NEV transmission chain

Build spec: diagnostic-2020/new-parameter.md §2. Template variables
(`simulation/domain_packs/automotive/template_spec.py`):

| Variable | Distribution | Decision-time anchor |
|---|---|---|
| `nev_ceiling` | triangular(0.30, 0.40, 0.60) | State Council NEV plan 2020-11-02: 20% by 2025; saturation is an extrapolation |
| `nev_rate` | triangular(0.50, 0.70, 1.00) | Logistic slope fitting the plan endpoints (5.4% → 20%) |
| `nev_midpoint` | triangular(3.0, 4.0, 5.0) | Plan linear path's logistic midpoint ≈ 2024 (tick 4) |
| `nev_coupling` | triangular(0.10, 0.25, 0.40) | Labeled assumption; mode matches `revenue_coupling`'s optimistic mode |

The penetration is the pack's existing `nev_penetration` STATE field,
reused rather than duplicated. Difference from the diagnostic spec:
the diagnostic's `nev_penetration` is a within-tick intermediate,
while here it is the shared state the dual-track split drivers
already read — so the chain's penetration also drives the NEV/ICE
volume splits, and it is visible in snapshots and the trajectory
endpoint. The dynamics are identical: at mode values the logistic
gives nev_penetration(1..4) = 0.044 / 0.079 / 0.133 / 0.200 (tick 4
is exactly the 2025 20% plan target).

A case attaches the chain with two formulas (the Desay harness shows
the full form):

```python
# 1. Logistic tick driver, output `nev_penetration`. At merge time it
#    replaces the template's drift driver per-output (generic runs keep
#    the drift driver).
{"output": "nev_penetration",
 "expression": {"op": "logistic", "args": [
     {"op": "multiply", "args": [
         {"ref": "nev_rate"},
         {"op": "subtract", "args": [{"ref": "tick"}, {"ref": "nev_midpoint"}]}]},
     {"ref": "nev_ceiling"}]},
 "tick_driver": True}

# 2. Revenue tick driver gains exactly one term.
revenue = max(0, revenue * (1 + revenue_growth
                            + revenue_coupling * disruptor_adoption
                            + nev_coupling * nev_penetration))
```

The revenue/profit/market_share state fields the case drives are
pack fields (Track 7 added them to the automotive pack mirroring the
corporate pack: defaults 100.0 / 20.0 / 0.05 on the cash scale; a case
declares its unit convention, e.g. RMB m per tick). No template driver
moves them; only a case that supplies the growth drivers does.

## 3. What the chain does and does not do

- It fixes the **missing channel**: a publicly planned demand variable
  (NEV penetration) now has a path into supplier revenue, with
  distributions set from the plan document, not from outcomes.
- It does **not** fix the **shape problem** (DIAGNOSTIC-2020.md §4):
  with any constant coupling and non-decreasing penetration, per-tick
  growth is still non-decreasing, while the desay-2020 actuals
  decelerate (47.7%/yr in the first three years, 21.9%/yr in the last
  two). Fitting year-3 overshoots year-5 by 1.3–4.2×; fitting year-5
  undershoots year-3 by 36–44%. The chain changes the level, not the
  shape. The shape fix is the order-book mechanism in §5 below
  (Track 11) — a second channel, decomposable separately from this one.
- Post-hoc fitted couplings that would reach the desay-2020 actuals
  (planning path: 9.69 year-3 / 2.08 year-5; realized path: 3.01 /
  0.79) are 5–24× the distribution max 0.40 and were indefensible at
  2020-12-31. They must never be used as parameters. A run that comes
  out far above the expected validation values (B year-3 ~10201,
  year-5 ~18212 at defensible values) should first be suspected of
  post-hoc widened distributions.

## 4. Controlled comparisons: the frozen-baseline method

(Diagnostic Appendix A.) The sampler draws variables in table order;
pinning a variable consumes no draw, so pinning a NEW variable shifts
the resampled values of every variable drawn after it. A one-lever
comparison that pins a new variable is therefore contaminated: the
row differs in the pinned lever AND in the resampled base.

For controlled comparisons, freeze the baseline: pin ALL variables at
the baseline run's sampled values (read from its replay package,
`determinism.sampled_values`) plus the one lever changed. A control
run that pins all variables at the baseline's sampled values must
reproduce the baseline replay exactly. Note that a fully frozen
variant has a degenerate Monte Carlo ensemble (P50 = P10 = P90 =
replay value) because nothing is left to resample — take genuine P50s
from single-lever-pinned variants, and use the frozen variant for
replay comparisons only.

The NEV-chain test `test_nev_chain_frozen_baseline_k_zero_is_no_chain`
demonstrates the method: with every variable fixed, `nev_coupling`
0.0 reproduces the no-chain revenue exactly, and 0.25 lifts it by the
NEV term alone, with share and profit bit-identical.

## 5. Worked example 2: the order-book (backlog) mechanism — the shape term

Build spec: Track 7 report §7 (diagnostic-2020 §5.3 shape problem).
Template variables (`template_spec.py`):

| Variable | Distribution | Decision-time anchor |
|---|---|---|
| `order_backlog` | fixed 0.0 | Case-level stock; a case binds it (one year of intake at mode revenue is the labeled stock proxy — the stock itself was never disclosed) |
| `order_intake` | fixed 0.0 | Case-level flow; a case binds it the same way |
| `order_intake_rate` | triangular(0.50, 1.00, 1.50) | Generic range around 1.0× revenue; a case overrides it from its decision-time order announcements (Desay 2020: ~70亿 annualised orders / 67.99亿 revenue ≈ 1.03) |
| `backlog_conversion` | triangular(0.30, 0.40, 0.60) | Labeled assumption; mode 0.40 turns the book over in ~2.5 years (design-in to start-of-production ~1–2 years) |
| `order_decay` | triangular(0.10, 0.25, 0.40) | Labeled assumption; mode 0.25 is the planning assumption for mean-reversion of order growth after a surge year |

The stock and flow are the pack's `order_backlog` / `order_intake`
STATE fields (defaults 0.0; generic runs keep them dormant). A case
attaches the mechanism by binding the opening book/flow as variables
and adding TWO tick drivers — intake decay and the revenue term — in
list order (intake must run before revenue). The stock update is the
TEMPLATE's `order_backlog` tick driver (`TEMPLATE_FORMULAS`, right
after the revenue passthrough — a merge anchor): a case must NOT
supply its own backlog-update driver, because one on the same output
replaces the anchor in place and silently reintroduces its own form
(that is how the Track 11 stock form survived untested — see the
history note below).

```python
# 1. Intake driver decays the flow (diagnostic only under this form:
#    the flow enters neither the revenue term nor the stock update).
order_intake = order_intake * (1 - order_decay)

# 2. Revenue driver gains exactly one term (after the NEV term):
#    conversion on the PRE-TICK book only. The converted amount is
#    exactly backlog_conversion * book, so the revenue term still
#    equals the converted amount.
revenue = max(0, revenue * (1 + revenue_growth
                            + revenue_coupling * disruptor_adoption
                            + nev_coupling * nev_penetration
                            + backlog_conversion * order_backlog / revenue))

# 3. TEMPLATE backlog driver (merge anchor, not a case driver):
#    the finite decision-time book depletes geometrically at the
#    conversion rate, floored at 0. The intake flow does NOT
#    replenish the book.
order_backlog = max(0, order_backlog * (1 - backlog_conversion))
```

FINITE-BOOK DEPLETION (step 1, 2026-11-24 — replaces both the Track
11 stock form and the Track A pool form). History: the Track 11
stock form (term `c*B/R`, update `B + intake - c*B`) made the term
a perpetual growth premium — the intake flow (≈1× revenue) re-filled
the book every tick, so the term added ~+10pp/+38pp per tick forever,
horizon-unbounded. Track A revised it to a POOL form (term on the
pre-tick book + decayed intake, pool lapsing with adoption) — but
that form was NEVER run by any backtest harness: the tests pinned
it while every rerun harness (e047f50 → A/C → trials50) kept its own
stock driver, and Track A's own rerun made the 2015 yr-3 replay
error WORSE (−4.1% → +15.2%). Step 1 unifies template, tests and
harness on one form, chosen by offline screening on the trials50
replay paths (the old form is reproduced exactly by the screen;
FBOOK yr-3 replay errors +3.4%/+8.8%/−11.7%/−9.0% vs OLD
+19.9%/+20.2%/+20.0%/+13.2%; the pool form screened HOTTER,
+24.9%/+21.2% on the anchor paths) and confirmed by a full four-case
rerun (downside ON, seed 42, trials 50). The mechanism's evidence
basis is unchanged: the opening book is a finite decision-time stock
(mean delivery lag 1/c, ~2.5y at mode 0.40, inside the SOP-lag
evidence 1.67–3.33y); later orders' delivery is carried by
`revenue_growth`, which is calibrated on TOTAL historical growth and
already includes normal order conversion — replenishing the stock on
top of it double-counts. Under depletion the total backlog uplift is
finite and front-loaded, and the book is 1/16 of its opening level
by tick 4 at mode 0.40.

Why variables, not initial formulas, for the opening book: merge is
per-output, so an initial formula and a tick driver cannot share an
output id — the driver replaces the formula (caught by test during
Track 11: the initial-formula version silently left the tick-0 book
at 0.0). The opening book is therefore bound as a variable, exactly
like `nev_penetration`'s opening level. `order_intake_rate` is
sampled but unread by any driver; backtest cases pin it FIXED at its
mode (Track A task 2, option (ii)) — the ensemble does not propagate
intake-rate uncertainty until real order-book calibration data
exists (see the Track A report for the assessed engine-level
alternative and why it was not taken).

RESTATED CRITERION (Track A, 2026-11-20 — replaces Track 7 §7 as
literally written): **per-tick growth becomes decreasing AND both
absolute errors shrink** (yr-3 replay and yr-5 P50, each vs its
actual). The old wording ("yr-3 and yr-5 signed errors moving toward
each other") is unachievable by any positive additive term (Track 11
proof; measured 22.0→33.2pp on 2015 and 37.4→43.6pp on 2020 at
e047f50) and is kept only in the historical reports. STEP-1
REFINEMENT (2026-11-24): the mechanism-level pin is the BACKLOG
TERM falling every tick (the book depletes geometrically, so the
term — the mechanism's own output — shrinks monotonically) plus the
opening fall of total growth (the anti-hump guard: under Track 11
total factors ROSE from tick 1, [1.2316, 1.2614, 1.2613, 1.2622] at
e047f50). Total-factor monotonicity through the whole horizon is NOT
pinned at synthetic mode values: the adoption/NEV couplings are
monotone RISING channels, and once the term has burned off (tick
3–4 at mode values) they take over and total growth rises again —
that handover is the mechanism working as designed (the opportunity
leg is front-loaded; after it burns off, base + coupling growth takes
over). Unit tests lock the term's fall, the geometric depletion and
the opening fall at 2020 AND 2015 mode values; total-factor falling
through the horizon is verified on the REAL cases (step-1 rerun,
below), not the synthetic controls.

What it does and does not do (measured on the step-1 four-case
re-run, downside ON, seed 42, trials 50): the B-replay growth
factors FALL tick by tick on both real cases (2015 [1.2599, 1.1796,
1.0694, 0.9763]; 2020 [1.7271, 1.3917, 1.2342, 1.1253]) while
adoption and penetration keep rising — the shape property the
monotone channels cannot express — and the anchor yr-3 bands now
COVER both actuals (2015 band [5222, 6488, 7793] vs actual 5408.74;
2020 band [17510, 22354, 26385] vs actual 21908), where trials50 had
both actuals below P10. B year-4 P50 errors move to −7.0% (2015)
and −23.9% (2020), from +10.6%/+7.1%; the tripwire stays CLEAR
(2015 B P50 6325.42 vs the 9178.73 line). What it does NOT do: make
the two SIGNED errors converge (they move from 2.7pp apart to 37.4pp
apart under Track 11, because yr-5 crosses zero), or raise the
yr-3/yr-5 level ratio (0.583 → 0.422 vs actual 0.673 under Track 11).
That is structural, not a parameter choice: a positive additive term
compounds into year 5, so it can fix the growth-rate shape but cannot
raise the level ratio — hence the restated criterion above (Track A):
per-tick growth becomes decreasing AND both absolute errors shrink.
The signed-gap wording is retired; do not reintroduce it as a gate.
It also does NOT bring band width under the W0 cap: widths are
1.98×/1.77× W0 (was 2.10×/2.13×), so both Desay milestones still
FAIL under the §2 width rule — now on width alone, not coverage.
That is a rule question for Ho (whether the W0 cap, frozen from the
downside-OFF run, should be re-baselined for downside-ON bands), not
a model fix.
The mechanism no longer over-lifts a non-surging case without
bound: the 2015 control book (0.25× revenue) lifted B's year-5 P50
by +44% under the stock form because the decaying intake flow kept
replenishing the stock; under depletion the uplift is bounded by
the finite book (2015 B year-4 P50 now sits −7.0% vs actual). The
intake-rate assumption still needs real calibration data (the
internal order book) before the mechanism is used for planning —
see the Track 11 report §"Limits".

## 6. Worked example 3: the ADAS penetration chain — the grade term

Build spec: gap audit §3 C1 (gap-audit-2026-11-20/REPORT.md); full
design, division of labor, and labeled assumptions in
research/strategy-engine/audit-fixes-2026-11-20/TRACK-C1.md.
Template variables (`template_spec.py`):

| Variable | Distribution | Decision-time anchor |
|---|---|---|
| `adas_penetration` | fixed 0.649 | MIIT combined driving-assist fitment 64.9% in 2025 (published 2026-10); template-caliber, not a decision-time input |
| `adas_penetration_monthly_drift` | fixed 0.0081 | Endpoint average (0.649−0.162)/60 on MIIT 16.2% (2020) → 64.9% (2025); NOT a fitted trend |
| `adas_ceiling` | triangular(0.50, 0.65, 0.80) | Labeled assumption; mode 0.65 below the disruptor ceiling 0.85 — L2 is a grade within smart features |
| `adas_rate` | triangular(0.50, 0.70, 1.00) | Labeled assumption; same order as `nev_rate` 0.70 |
| `adas_midpoint` | triangular(2.0, 3.0, 4.0) | Labeled assumption; mode 3.0 tracks the 2020 disruptor midpoint |
| `adas_coupling` | triangular(0.10, 0.25, 0.40) | Labeled assumption; mode 0.25 by analogy to `nev_coupling` — NEVER from the segment's revenue share |

The penetration is the pack's `adas_penetration` STATE field, reused
rather than duplicated — the same pattern as the NEV chain. A case
attaches the chain with a logistic tick driver (output
`adas_penetration`, replacing the template drift driver per-output at
merge) plus exactly one additive term in the revenue driver
(`+ adas_coupling * adas_penetration`) and exactly one in the share
driver (`+ adas_share_coupling * adas_penetration` — case-level only,
like `share_coupling`). Profit is untouched.

Division of labor (the design precondition — the chain is built on
it, not beside it): `disruptor_adoption` is BREADTH (any
smart-cockpit/ADAS function, L0–L2 combined, ~34% in 2020);
`adas_penetration` is GRADE (L2 within new cars, ~12% in 2020). The
couplings price different hardware — average smart content vs the
incremental L2 premium stack (cameras + radar + domain-controller
IPU) — so the two channels do not double-count. The guard is the
coupling's basis: its mode is set by analogy, never derived from the
intelligent-driving segment's 10.48% revenue share, which includes
L0/L1 content already priced by `revenue_coupling`. The tests pin
the separability both ways: zeroing the ADAS couplings reproduces
the pure-adoption path exactly, and zeroing adoption leaves the ADAS
term carrying revenue on its own.

Planning-path check (2020 case, modes): adas_penetration(1..5) =
0.1286 / 0.2157 / 0.325 / 0.4343 / 0.5214 — tick 1 sits on the 12%
anchor. What it does and does not do: it fixes the missing GRADE
channel (the diagnostic's real growth engine, 13.6×), and it lifts
the level, not the shape — same as the NEV chain. It does NOT close
the desay-2020 residual gap: the post-hoc fitted coupling would be
several times the 0.40 max, and the chain's tick-5 revenue term at
mode (0.25 × 0.5214 ≈ 0.13) is an order below what the realized
13.6× segment growth would need. That gap stays an accepted
prediction limit, not a reason to widen the coupling.

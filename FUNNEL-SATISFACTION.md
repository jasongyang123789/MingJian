# Track 4 — Funnel conversion + satisfaction feedback as one-click features

Branch: `fix/funnel-satisfaction-one-click`, from `83bb09f` (tip of
`fix/backtest-improvements`). Not merged, not pushed.

## What was built

The B2B 8-stage Tier-1 chain — customer development → lead funnel →
RFQ / contract → demand management → product matching → project
management → manufacturing follow-up → delivery satisfaction — is now
**modeled, not manually overridden**. One click = an automotive run
with the built-in template (`variable_template_id:
"builtin:automotive"`); the funnel computes itself from sampled base
rates and tick drivers.

### Funnel conversion rates as modeled quantities

14 new automotive pack state fields (`pack.py`): 7 pipeline stocks
(`funnel_prospects/leads/rfqs/contracts/projects`, counts),
2 cumulative totals (`funnel_deliveries_total`,
`funnel_prospects_total`), 6 rates
(`funnel_prospect_to_lead_rate`, `funnel_lead_to_rfq_rate`,
`funnel_rfq_win_rate`, `funnel_contract_to_project_rate`,
`funnel_project_to_delivery_rate`, `funnel_overall_conversion`),
and `delivery_satisfaction` (0–1).

20 new tick drivers (`template_spec.py`, appended after the
generation-transition driver; 52 variables / 36 formulas / 33 drivers
total, under the 40-formula cap), chained in list order within a tick:

1. **Rates** from sampled bases: prospect→lead and contract→project
   are their base rates; lead→RFQ and RFQ-win are
   `base × (1 + satisfaction_feedback_gain × (satisfaction − 0.75))`,
   clamped to [0, 0.95]; project→delivery is
   `base × (0.7 + 0.3 × chip_supply_index)`, clamped to [0, 0.99]
   (manufacturing follow-up is chip-constrained, C2 link 6).
2. **Flows** (`funnel_new_*`, intermediates, not state fields):
   stocks × same-tick rates; new prospects = inflow × the same
   satisfaction factor (referral channel).
3. **Stocks**: previous + inflow − outflow − **attrition**
   (prospects 10%/mo go cold, leads 10%/mo die, RFQs 5%/mo lost to
   competitors/no-decision, contracts 5%/mo cancelled, projects 2%/mo
   cancelled), floored at 0. Attrition is load-bearing: without it the
   funnel is lossless and the overall conversion drifts to 1.0. With
   it, the end-to-end yield tends to the product of the stage yields
   `rate/(rate+attrition)` ≈ 0.41.
4. **Satisfaction**: moves 20% per tick toward its delivery target
   `0.4 + 0.6 × project_to_delivery_rate`, clamped to [0, 1].
5. **Overall conversion**: the identity `deliveries_total /
   max(prospects_total, 1)`, recomputed every tick.

12 new template variables are formula parameters (6 base rates +
inflow + feedback gain + 5 attrition rates, all
`assumption:pending-calibration` — no public Tier-1 funnel series
exists); 8 are fixed state-matching lever handles (initial pipeline
stocks, cumulative totals, satisfaction). The 8-stage mapping is
documented in the pack/template comments; stages 4–6 (demand,
product matching, project mgmt) share the project stock, and stage 7
(manufacturing) is the project→delivery rate.

### Satisfaction → next-RFQ feedback loop (first-class, one-tick lag)

The RFQ-rate and inflow drivers run **before** the satisfaction
driver in the tick-driver order, so they read the **previous tick's**
satisfaction. A delivery delight/disappointment moves *next* month's
RFQ inflow, win rate, and prospect inflow — never the same month's.
The lag is by construction, not by a flag. A rule effect on
satisfaction decays toward the delivery target (20%/tick) instead of
being overwritten outright; a rule effect on a stock persists through
the self-referential stock drivers.

### Rules, actions, policies

- 3 new actions (`qualify_leads`, `accelerate_rfq_response`,
  `improve_delivery_quality`), 1 new event type
  (`delivery_satisfaction_feedback`).
- 2 new rules (`rules/automotive/default_rules.yaml`, 13 → 15 rules):
  `auto.delivery_satisfaction_slip` (late-delivery / complaint
  evidence → satisfaction −0.05) and `auto.rfq_momentum` (new-RFQ
  evidence → +1 open RFQ). Neither sets a rate by hand — rates stay
  model-determined; the rules move stocks/satisfaction, which the
  drivers carry through the funnel.
- 3 new automotive metric policies (`delivery_satisfaction`,
  `funnel_overall_conversion`, `funnel_rfq_win_rate`) for
  direction/branch scoring, anchored to the pack defaults.

## Verification

- Targeted: `tests/test_funnel_satisfaction.py` (10 tests: driver
  math at fixed scope — exact feedback factors 0.65/1.15, clamps,
  hand-computed one-tick conservation with attrition, 36-tick
  stabilization, rule shapes; API — end-to-end funnel run, feedback
  loop via `initial_state` satisfaction 0.4 vs 0.9, determinism,
  complaint + RFQ rules) + updated `test_automotive_pack.py` +
  `test_rule_effect_scaling.py`: **31 passed**.
- Demo: `scripts/demo_funnel_satisfaction.py` (throwaway SQLite DB,
  never the standing deployment). Observed output: baseline 6-tick
  trajectory (RFQs 4.00 → 16.19, deliveries 12.00 → 25.45, overall
  0.100 → 0.175, satisfaction 0.750 → 0.876); feedback loop —
  low-satisfaction run tick-1 lead→RFQ 0.192 / win 0.120 vs high
  0.340 / 0.212, tick-6 RFQs 15.90 vs 16.22, deliveries 23.61 vs
  26.28; complaint rule fires (`auto.delivery_satisfaction_slip`),
  tick-1 satisfaction 0.7841 → 0.7441 (exactly −0.05 × 0.8, the
  driver pulling 20% back toward target).
- Full suite: **2105 passed in 740.32s (0:12:20), 0 failed** —
  single-process run under `~/workspace/scripts/full-run-lock.sh`
  with `TMPDIR=/dev/shm/pytest-tmp-funnel` (792M free at start, gate
  passed), `env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest
  -q`, tip `a05df51`. (Two earlier attempts never ran: the first
  waited 60 min in the lock queue behind other tracks' suites and
  timed out; the second was killed by a runtime restart while still
  queued. The third attempt acquired the lock immediately after the
  restart and ran clean.)
- Lint: `ruff check` clean, `ruff format` applied to touched files.

## Limits (honest)

- **All funnel magnitudes are assumption-labeled placeholders**
  (bases, inflow, gain, attrition, satisfaction target/speed). No
  public Tier-1 funnel series exists; direction and mechanism are the
  deliverable, magnitudes are sensitivity-analysis inputs. Bind the
  real CRM pipeline (initial stocks) and delivery history per run.
- **The feedback gap decays**: satisfaction mean-reverts toward its
  delivery-performance target (~0.95 at default delivery rates), so
  the low-vs-high satisfaction gap is largest in ticks 1–3 and mostly
  washed out by tick 6 (tick-6 RFQs 15.90 vs 16.22). The loop is
  strongest as a near-term signal, not a permanent wedge — unless the
  delivery rate itself stays depressed (e.g. chip squeeze), which
  holds satisfaction down and keeps the loop open.
- **No per-OEM / per-nameplate funnel**: one global Tier-1 pipeline.
  Per-OEM pipelines would live in the split structure (S-layer), not
  in this track.
- **No UI**: the funnel is visible in run snapshots / replay
  packages and the demo script. No cockpit funnel panel was built.
- **Tick-0 rates are pack defaults** (0.30/0.25): sampled triangular
  bases first apply at tick 1, consistent with the other drivers.
- Stages 4–6 share one project stock (no separate demand / product-
  matching / project-mgmt stocks); splitting them is a follow-up if
  Ho wants stage-level visibility there.

# Downside mechanism for growth cases (fix/downside-mechanism)

Branch: `fix/downside-mechanism`, from `83bb09f` (tip of
`fix/backtest-improvements`). Status: built + unit/API-tested; Desay
verification in
`~/workspace/research/strategy-engine/desay-backtest-2026-11-19/`
(`run_desay_downside.py`, `DOWNSIDE-REPORT.md` — see there for the real
numbers).

## Problem

Growth-coupled diffusion only computes "how fast it grows". Both Desay
anchors report `p_loss 0.0`, so the 2018–19 downturn and the 2020 growth
shortfall had no advance warning: no trajectory can ever fall.

## Mechanism (default ON since Track C, 2026-11-20)

Ho ordered the default flipped from OFF to ON on 2026-11-20 08:42
(Desay-gap "全做"), explicitly reversing his 2026-11-19 14:31 decision
("下行风险机制，默认关闭保向后兼容"). A run that omits `downside`
now gets the default config (enabled, fields revenue + profit, the
canonical labeled-assumption variables below, auto-bound by the engine
where they apply); pass `downside: null` or `{"enabled": false}` to opt
out. An explicitly supplied fragment keeps the loud-failure contract
(named variables must be bound, or run creation fails).

Default scope — the mechanism attaches only where it can run:

- the run must carry a variable set (template and/or inline). A run
  with no bindings has no sampling to bind the shock to, so the
  default fragment is omitted and the run behaves exactly as before.
- the run's domain pack must carry at least one of the default fields
  (`revenue`, `profit`). The military pack carries neither, so military
  runs are unaffected by the default.
- the fill must fit the 100-variable cap; otherwise the fragment is
  omitted rather than failing creation.

Pre-existing runs are untouched: the default only affects runs created
after the change. Replays, Monte Carlo trials, and scenario branches
copy the stored configuration, so they reproduce exactly what the base
run ran with; the living-loop re-simulation carries the baseline's
stored downside fragment verbatim (and re-simulates a fragment-less
pre-Track-C baseline explicitly OFF).

A cyclical downturn shock, plus an optional persistent reversal, as
ordinary sampled variables + a `downside` configuration fragment on the
run. All parameters are LABELED ASSUMPTIONS — no independent estimate
is claimed anywhere.

## Canonical default parameter set (Track C, unified across cases)

| Variable | Distribution | Meaning |
|---|---|---|
| `downturn_occurs` | Bernoulli(0.5) | Does a downturn hit inside the horizon at all |
| `downturn_depth` | triangular(0.05, 0.20, 0.35) | Peak per-tick fractional level hit (0–1) |
| `downturn_start` | triangular(2, 3, 4) | First tick of the downturn window |
| `downturn_duration` | triangular(1, 2, 3) | Window length in ticks |
| `downturn_persistent` | Bernoulli(0.15) | The downturn never recovers (thesis reverses) |

The set is UNIFIED: the per-case ON observations differed (2020 used
start (1, 2, 4) / persistent 0.10; 2015 and Huawei used start (2, 3, 4)
/ persistent 0.15) and the unified default takes the majority values.
A case that needs its own start / persistence still binds its own
variables and passes an explicit fragment — those win over the default
(the engine only fills missing ids, and only for the default config).
The engine appends the missing canonical variables at the END of the
run's variable set, so pre-existing draws are untouched (the sampler
draws in set order, one draw per variable — verified: pre-existing
sampled values are byte-identical with the default on vs explicitly
off). The canonical variables carry no `scope_tags`, so they can never
trip the decomposition scope cross-check.

Per-case variables (appended to the variable set, so pre-existing draws
are untouched):

| Variable | Distribution | Meaning |
|---|---|---|
| `downturn_occurs` | Bernoulli(p) | Does a downturn hit inside the horizon at all |
| `downturn_depth` | triangular | Peak per-tick fractional level hit (0–1) |
| `downturn_start` | triangular | First tick of the downturn window |
| `downturn_duration` | triangular | Window length in ticks |
| `downturn_persistent` | Bernoulli(p), optional | The downturn never recovers (thesis reverses) |

Config fragment (`SimulationRunCreate.downside`, stored in the run
configuration, hence in the Sprint 3 input hash, and inherited by Monte
Carlo trials, scenario branches, and replays):

```json
{"enabled": true, "fields": ["revenue", "profit"],
 "occurs_variable": "downturn_occurs", "depth_variable": "downturn_depth",
 "start_variable": "downturn_start", "duration_variable": "downturn_duration",
 "persistent_variable": "downturn_persistent",
 "label": "LABELED ASSUMPTION — ..."}
```

## Semantics

- Pure module `src/planagent/services/simulation/downside.py`:
  `resolve_downside(configuration, sampled_values, state_fields)` →
  `DownsideState | None`. Returns `None` when the fragment is absent or
  disabled. Raises `DownsideError` when enabled but misconfigured
  (unknown field, unbound variable, out-of-range parameter) — before
  any tick executes, same loud failure as a broken tick driver.
- The engine applies the shock AFTER the tick drivers, as a level
  multiplier on the configured fields:
  `field *= 1 - depth * occurs * window(tick)`. Because drivers
  recompute from the current state each tick, the level hit persists as
  a scar — growth resumes from the lower base, it does not snap back.
- Window: smooth bump, difference of two logistics (steepness 2.0 per
  tick), normalised by its own peak so `depth` is the peak of the
  continuous window; the realised per-tick peak is at most depth and
  depends on alignment with integer ticks. Persistent mode drops the
  second logistic: the window rises and stays down.
- The resolved parameters + per-tick multipliers are recorded on the
  run summary under `"downside"` (only when enabled).

## New statistic: decline probability

`DistributionSummary.decline_probability` — fraction of Monte Carlo
trials whose metric trajectory falls in at least one tick, read from
the trial snapshots (never re-executed). This is the statistic that
stays meaningful for growth cases: `p_loss` (final value below the
loss threshold) is structurally near-zero for a 5-year growth case
even with a severe shock — five ticks of ~25% growth need a >55%
cumulative hit to end below the starting value — so a dip that
recovers still leaves `p_loss` at 0. A persistent reversal is the only
regime that can push a final value below its starting value, which is
why it exists as a separate, low-probability draw. ES needs no change:
the fatter lower tail flows into it automatically.

## Backward compatibility — and the deliberate comparability break

- No `downside` fragment (explicit opt-out via `downside: null`, or
  `enabled: false`): `resolve_downside` returns `None`; executor, run
  summary, and Monte Carlo statistics are exactly as before. Verified
  by `tests/test_downside_mechanism.py`: off/disabled/never-occurring
  runs produce byte-identical trajectories to the no-fragment control.
- `DistributionSummary.decline_probability` defaults to 0.0, so
  ensembles stored before this change still validate.
- **The break is deliberate and quantified, not hidden.** A run created
  after Track C without an explicit opt-out carries the default shock,
  so its scores are NOT comparable with pre-change scores for the same
  case. Measured (Track C report
  `~/workspace/research/strategy-engine/desay-gap-full-2026-11-20/TRACK-C.md`):
  the Acme anchor P50 (cash, trials 5, seed 42) is UNCHANGED at
  99.8143 — cash sits outside the shocked fields (revenue, profit) and
  no rule feeds revenue/profit back into cash over 2 ticks — while the
  same probe's revenue P50 moves 100.0 → 95.2326 with decline
  probability 0.0 → 0.6. The four backtest cases re-run under the new
  default keep their direction verdicts (highest_p50 → B in all four)
  and their magnitude verdicts, but BOTH Desay milestones flip FAIL →
  PASS by the band rule — NOT because the point forecasts improved
  (both yr3 replay nodes moved further from actual) but because the
  shock fattens the anchor bands' lower tails (2015 tick-3 P10
  6798.11 → 5157.40; 2020 tick-3 P10 24538.31 → 19892.84), so the
  actuals now fall inside. The milestone rule as written rewards wider
  bands; that interaction is flagged in the Track C report, not hidden.
  The 2020 headline statistics stay 0.0 (p_loss and decline_p) — the
  auto-pack ~1.5×/tick growth still swamps the modal 0.20 shock.
  To reproduce a pre-change score exactly, re-run with an explicit
  opt-out (`downside: null`); the living-loop re-simulation does this
  automatically for fragment-less baselines.

## Calibration gap (stated plainly)

The shock parameters have NO independent estimate. They are labelled
assumptions anchored, where possible, on the observed 2018–19 episode
(revenue −10.0% then −1.3% against a ~+15% trend, i.e. a ~25pp swing),
but a different equally reasonable depth / probability moves every
score the mechanism produces. Scores with the mechanism on are
assumption-conditional, never parameter-free conclusions. In
particular, `p_loss` for desay-2020 at the standard (starting-value)
threshold stays near zero by construction — see the verification
report for the actual value and for what the meaningful statistics
(decline probability, ES tail, shortfall vs base-case P10) actually
say.

## Files changed (Track C, 2026-11-20 — default ON)

- `src/planagent/services/simulation/downside.py` (canonical default
  parameter set + `default_downside_variables()`; docstrings OFF → ON)
- `src/planagent/domain/api.py` (`DownsideConfig.enabled` default False
  → True; `SimulationRunCreate.downside` default `None` →
  `default_factory=_default_downside_config` — omitted means default ON,
  explicit `null` still means OFF)
- `src/planagent/services/simulation/engine.py` (default-only variable
  auto-bind in `_resolve_variable_bindings`; `_downside_configuration_fragment`
  now takes the variables fragment and attaches the default only where
  it can run; explicit fragments stored verbatim with the loud-failure
  contract kept)
- `src/planagent/services/simulation/living_loop.py` (re-simulation
  carries the baseline's stored downside fragment verbatim; a
  fragment-less baseline is re-simulated explicitly OFF)
- `tests/test_downside_mechanism.py` (controls that asserted the old
  default-OFF behaviour now opt out explicitly; new tests pin the
  default-ON behaviour — see TRACK-C.md for the per-test reasons)
- `tests/test_distributions_api.py` (`test_sampling_applies...` now
  expects the canonical downside draws appended after the BOUND_SET
  draws — pre-existing draws byte-identical)

## Files changed (original fix/downside-mechanism)

- NEW `src/planagent/services/simulation/downside.py` (pure mechanism)
- `src/planagent/domain/api.py` (`DownsideConfig` + `SimulationRunCreate.downside`)
- `src/planagent/services/simulation/engine.py` (fragment helper, three
  run creators, tick-loop hook, summary fragment)
- `src/planagent/services/distributions/models.py`
  (`DistributionSummary.decline_probability`)
- `src/planagent/services/simulation/distributions.py`
  (`_trial_decline_probability`, wired into `run_monte_carlo`)
- NEW `tests/test_downside_mechanism.py` (11 tests: pure window/resolution,
  dip shape + off control, off-identical, MC decline probability,
  loud misconfiguration failure)

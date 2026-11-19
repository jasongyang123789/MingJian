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

## Mechanism (opt-in, default OFF)

A cyclical downturn shock, plus an optional persistent reversal, as
ordinary sampled variables + a `downside` configuration fragment on the
run. All parameters are LABELED ASSUMPTIONS — no independent estimate
is claimed anywhere.

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

## Backward compatibility

- No `downside` fragment (or `enabled: false`): `resolve_downside`
  returns `None`; executor, run summary, and Monte Carlo statistics are
  exactly as before. Verified by `tests/test_downside_mechanism.py`:
  off/disabled/never-occurring runs produce byte-identical
  trajectories to the no-fragment control, and the Acme baseline P50
  99.8143 is unchanged (see the Desay verification report).
- `DistributionSummary.decline_probability` defaults to 0.0, so
  ensembles stored before this change still validate.

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

## Files changed

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

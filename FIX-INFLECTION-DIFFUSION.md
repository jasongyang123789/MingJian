# Fix 2 — Inflection/diffusion dynamics (logistic S-curve drivers)

Branch: `fix/inflection-diffusion`, from tip `35dbf21`.
Status: implemented + tested (targeted files only; full suite is the
coordinator's integration gate).

## Problem

The first backtest run (report
`~/workspace/research/strategy-engine/backtest-runs-2026-11-19/REPORT.md`,
"跨案例发现" §3) showed the system flags downside risk (anchor p_loss
0.55 Nokia / 0.50 Blockbuster) but cannot compute collapse speed or
depth: the constant-growth drivers (`market_share * (1 + share_growth)`,
one rate sampled once) produce bands that never contain Nokia's
40% → 27% → 6.4% fall or Blockbuster's bankruptcy. Reproducing collapse
needs inflection/diffusion dynamics.

## Design (minimal, inside the existing formula graph)

No new subsystem, no arbitrary-code path, no new state field, no
migration. Two binary operators join the formula vocabulary (still
arity 2, still validated by the same gate, still failing loudly):

- `pow(base, exponent)` — `math.pow` semantics. A negative base with a
  non-integer exponent, `0` to a negative power, and overflow all raise
  `FormulaEvaluationError` (never silently skipped).
- `logistic(z, ceiling)` — `ceiling / (1 + exp(-z))`, evaluated in the
  numerically stable form (``exp()`` is only ever taken of a
  non-positive argument, so no `|z|` can overflow). First argument is
  the logit, usually `rate * (tick - midpoint)` built from the other
  operators; second argument is the saturation ceiling (an ordinary
  sampled variable or literal). For a positive ceiling the result lies
  in `[0, ceiling]`; `logistic(0, K) = K/2`.

The S-curve is a **closed form in `tick`**, not a persistent state
variable: the adoption driver is a within-tick intermediate (its output
is not a pack state field, so it is recomputed from `tick` every tick
and never persisted — driver chaining within a tick already supports
this). That is why no pack change was needed: the adoption curve is a
pure function of tick + sampled parameters, so ensembles over the
parameters give non-degenerate bands and replay stays deterministic.

### Canonical recipe (usage contract for the re-run agent)

Variables — all ordinary variables (sampled from distributions or
fixed); the values below are SYNTHETIC test parameters, not fitted to
any historical case:

| Variable | Meaning | Example value |
|---|---|---|
| `market_share` | incumbent share; seeds the initial state | fixed 0.40 |
| `disruptor_ceiling` | adoption saturation level K | fixed 0.9 (ensemble: triangular 0.7 / 0.9 / 0.95) |
| `disruptor_rate` | logistic steepness per tick r | fixed 1.2 (ensemble: triangular 0.8 / 1.2 / 1.6) |
| `disruptor_midpoint` | tick at which adoption passes K/2 | fixed 3.0 (ensemble: triangular 2.0 / 3.0 / 4.0) |
| `disruptor_coupling` | incumbent share lost per tick per unit of adoption | fixed 0.55 |
| `base_growth` | incumbent's underlying growth absent disruption | fixed 0.01 |

Tick drivers, in this list order:

```json
[
  {
    "output": "disruptor_adoption",
    "tick_driver": true,
    "expression": {
      "op": "logistic",
      "args": [
        {
          "op": "multiply",
          "args": [
            {"ref": "disruptor_rate"},
            {"op": "subtract", "args": [{"ref": "tick"}, {"ref": "disruptor_midpoint"}]}
          ]
        },
        {"ref": "disruptor_ceiling"}
      ]
    }
  },
  {
    "output": "market_share",
    "tick_driver": true,
    "expression": {
      "op": "max",
      "args": [
        0,
        {
          "op": "multiply",
          "args": [
            {"ref": "market_share"},
            {
              "op": "add",
              "args": [
                1,
                {
                  "op": "subtract",
                  "args": [
                    {"ref": "base_growth"},
                    {
                      "op": "multiply",
                      "args": [{"ref": "disruptor_coupling"}, {"ref": "disruptor_adoption"}]
                    }
                  ]
                }
              ]
            }
          ]
        }
      ]
    }
  }
]
```

Semantics: past the midpoint the incumbent's per-tick growth
(`base_growth - coupling * adoption`) flips negative and accelerates
toward `1 + g - c*K` per tick — the collapse. With the example values
the share trajectory is 0.40 → 0.3875 → 0.3470 → 0.2646 → 0.1666 →
**0.0927 at tick 5** → 0.0035 at tick 10. Adoption at ticks 1/3/5/10 is
0.0749 / 0.45 / 0.8251 / 0.8998. A later midpoint delays the collapse
and a steeper rate brings it forward (both covered by tests); every
sampled corner of the ensemble ranges above still collapses below 0.10
by tick 10 (slowest corner ≈ 0.023).

### No-behaviour-change proof

With `disruptor_ceiling = 0` (or `disruptor_coupling = 0`) the recipe
reproduces the backtest's legacy constant-growth driver **tick for
tick, including the per-tick 4-decimal rounding** (pinned by test).
Sets without the new operators evaluate exactly as before — the change
is purely additive to the operator vocabulary. Verified: Acme smoke
baseline P50 is still **99.8143** (probe below), and the Sprint 0 smoke
script passes.

## Files changed

- `src/planagent/services/variables/models.py` — `FormulaOperator`
  gains `POW = "pow"`, `LOGISTIC = "logistic"` (+ docstring).
- `src/planagent/services/variables/formulas.py` — `_FORMULA_OPERATORS`
  gains both operators; `_evaluate_expression` gains the `pow` and
  `logistic` branches (+ module docstring).
- `frontend-v2/src/api/engineTypes.ts`, `frontend-v2/src/components/cockpit/templateDraft.ts`
  — `FormulaOperator` union / `FORMULA_OPERATORS` list synced so the
  template authoring UI can offer the new operators.
- `tests/test_inflection_diffusion.py` — 13 new tests (see below).
- This file.

## Verification (targeted files only, per task; full suite is the coordinator's gate)

- `tests/test_inflection_diffusion.py`: **13 passed** — `pow` values +
  loud domain failures; `logistic` values, monotonicity, ceiling bound,
  `|z| = 1000` overflow safety; validation (new ops accepted, unknown
  op / wrong arity still rejected); adoption S-shape (midpoint = K/2);
  collapse 0.40 → < 0.10 by tick 5 and < 0.01 by tick 10; midpoint/rate
  sensitivity; zero-ceiling and zero-coupling exact equivalence with
  the legacy driver; engine run collapses (real trajectory 0.40 → 0.0927
  tick 5 → 0.0035 tick 10) while the zero-ceiling control grows to
  0.4418; ensemble over sampled diffusion params (20 trials, seed 42,
  metric `market_share`) is non-degenerate (P10 0.0037 < P90 0.0096)
  with the whole band collapsed (min 0.0032, max 0.0102, P50 0.0058).
- `tests/unit/test_formulas.py` + `test_formula_golden.py` +
  `tests/test_tick_drivers.py` + `tests/unit/test_sampler.py`:
  **57 passed**.
- `tests/test_distributions_api.py` + `tests/test_robustness_api.py` +
  `tests/test_rule_effect_scaling.py` +
  `tests/unit/test_simulation_engine.py` +
  `tests/unit/test_simulation_service.py`: **109 passed**.
- `docs/sprint0/smoke_e2e.py`: **SMOKE: PASS** (evidence file reverted).
- Acme baseline probe (BOUND_SET run, seed 7, tick 2; monte-carlo
  trials 5, seed 42, metric cash): baseline **P50 99.8143** — unchanged.
- `ruff check` + `ruff format --check` on all changed Python files:
  clean. `mypy` on the two changed source files: clean.

## Limits / notes for the re-run agent

- The recipe expresses collapse **speed and depth**; it does not by
  itself pick the parameters — `ceiling` / `rate` / `midpoint` /
  `coupling` must be set from decision-time evidence or labeled
  assumptions, exactly as `share_growth` was in the first run. Do not
  tune them to the known historical outcomes (hindsight firewall).
- The adoption curve is a function of `tick` only: it cannot react to
  within-run state (e.g. a price cut slowing adoption) — that would
  need a persistent adoption state field, deliberately not built here.
- `pow` is a general primitive (also enables Hill-type curves and
  compounding); `logistic` is the diffusion primitive. Both are usable
  in initial (once-per-run) formulas too, not only in tick drivers.
- Frontend vitest suite not run (same standing limit as Sprint 4).

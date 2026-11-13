# Sprint 3 — Distribution layer + determinism hardening (PRD deltas D4/D5)

Date: 2026-11-13. Branch: `strategy-engine/sprint3-distributions` (local
only, never pushed), branched from `strategy-engine/sprint2-variables`
(`5646204`). Baseline: `SPRINT0.md`, `SPRINT1.md`, `SPRINT2.md`,
`docs/as-is-architecture.md`.

## 1. What was built

Three workstreams, per `SPRINT2.md` §7 items 1–3:

- **Determinism hardening (approved enrichment, closes gap G6)** —
  canonical JSON + SHA-256 input hashes at run creation, per-tick state
  hashes during execution, the run seed threaded into the sampler's RNG,
  and a hash-verified replay path. Reference: the adadsws deterministic
  market-game engine (`market/protocols.py`, `market/replay.py`).
- **Seeded paired Monte Carlo (the distribution layer)** — a sampler
  over exactly the five distributions the Sprint 2 validator accepts,
  wired into execution so sampled variable values drive the initial
  state, plus baseline-vs-strategy paired ensembles on shared seeds
  with P10/P50/P90 + loss-probability aggregation. Reference:
  agilhaykal/strategic-simulation (`backend/engine.py`); aggregation
  shape follows scenario-lab's ensemble statistics and the v0.1
  prototype's percentile/loss-probability semantics.
- **Branch-level bindings** — per-branch variable overrides in
  `create_scenario_run`, validated with the same gate, with
  decomposition-branch scope ownership (variable tags checked against
  one MECE branch's scope instead of the root scope).

### New module: `src/planagent/services/distributions/`

Dependency-free pure modules, mirroring the MECE/variables pattern:

- `canonical.py` — canonical JSON (sorted keys, compact separators,
  UTF-8, non-finite floats rejected), `sha256:`-prefixed hashes,
  `state_hash` (excludes a stored `state_hash` key), `derive_sub_seed`
  (SHA-256 seed-material derivation, masked to 63 bits so trial seeds
  fit a signed `INTEGER` column), and `compute_input_hash` /
  `determinism_input_fragment` (hash of domain, actor template, tick
  count, seed, subject, tenant, preset, and full configuration minus
  any stored determinism fragment).
- `sampler.py` — `sample_variable_set` over the validator's vocabulary
  (`fixed` / `normal` / `triangular` / `beta_pert` / `bernoulli`) with
  stdlib `random.Random`; re-validates the set and raises on anything
  the validator rejects. Levers replace drawn values *after* the draw
  is consumed, so paired runs on shared seeds keep identical streams
  for non-levered variables. `resolve_run_samples` reads a run's
  bindings + trial levers from its configuration and returns the
  sampled vector plus the subset matching state fields.
- `aggregation.py` — linear-interpolation percentiles (prototype
  semantics), per-arm summaries (n/mean/min/max/p10/p50/p90/stddev/
  p_loss vs an explicit threshold), and paired delta statistics.
- `models.py` — `MonteCarloRequest` / `MonteCarloResult` /
  `DistributionSummary` / `PairedDeltaSummary` / `ReplayResult` /
  `DeterminismRead`. `MonteCarloResult` is both the API response and
  the stored audit fragment, so stored and served shapes cannot drift.

### Service wiring

- **Input hash at creation** — `_create_corporate_run`,
  `_create_military_run`, `create_scenario_run`, Monte Carlo trial
  creation, and replay creation all store a `determinism` fragment
  (`protocol` + `input_hash`) in the run's configuration JSON. No
  migration: existing JSON columns carry everything.
- **Sampling in execution** — `_execute_run` samples the run's bound
  variables once from `random.Random(run.seed)` and applies values
  whose variable id matches a state field to the initial state, after
  template/pack defaults and before the actor-template and
  `initial_state` overlays (explicit overrides keep precedence). Runs
  without bindings sample nothing and behave exactly as before.
- **State hashes in execution** — every snapshot's state is hashed as
  it is written; the summary carries a `determinism` fragment with the
  input hash, per-tick state hashes, all sampled values, and the
  applied subset.
- **Monte Carlo + replay mixin** —
  `services/simulation/distributions.py` (`SimulationDistributionsMixin`,
  added to `SimulationService`): `run_monte_carlo` (N paired trials as
  real `SimulationRun` rows executed by the same `_execute_run`, trial
  seeds derived from the requested seed, results stored on the base
  run's summary), `get_monte_carlo`, `replay_simulation_run`
  (re-executes from stored inputs as a fresh run row, compares per-tick
  hashes, reports the first diverging tick), `get_determinism`
  (prefers stored fragments, recomputes live for pre-Sprint-3 runs).
  Trial and replay runs skip report generation (ensemble/verification
  members, not decision artifacts); military trials/replays clone geo
  assets from the source run, as scenario branches do.
- **Branch bindings** — `ScenarioRunCreate` gains
  `variable_template_id` / `variable_set` / `decomposition_branch`.
  `_resolve_scenario_variable_bindings` resolves a branch template
  (replacing the parent's template snapshot and base set), merges an
  inline set over the inherited bindings (inline wins per id),
  validates with the same gate, and cross-checks scope tags against
  the named branch's scope (`find_branch_by_path` in the MECE module)
  or the parent root scope. Refusals raise before any row is written;
  the scenario route returns the structured variable-gate error shape.
  With no binding fields, children inherit the parent's fragment
  unchanged (Sprint 2 behavior).
- **Endpoints** — `POST /runs/{run_id}/monte-carlo` (201),
  `GET /runs/{run_id}/monte-carlo`,
  `POST /runs/{run_id}/replay` (201),
  `GET /runs/{run_id}/determinism`, in `api/routes/distributions.py`,
  served bare and under `/api` like all routers.

## 2. Design decisions

**Sampling wiring: per-trial sampled initial state.** The alternative
(per-tick sampled drivers) needs a mapping from variables to tick
dynamics that does not exist without a formula graph (explicitly
deferred, Sprint 2 §6.5). Per-run sampling is the honest minimal
wiring: a variable named `cash` with a triangular distribution samples
the starting cash; every other variable is sampled, recorded in the
audit trail, and available to Sprint 4 formula-graph work. Sampling
happens inside `_execute_run` (not only on the Monte Carlo path), so
single runs with bindings also close the Sprint 2 validated-but-
unsampled gap, and replay reproduces the same samples from the same
seed automatically.

**Seed contract.** Same seed + same inputs → byte-identical snapshots.
The contract rests on three facts, all verified: (1) the sampler is
the ONLY stochastic behavior in the simulation path — a grep audit
found zero `random.*`/`numpy` usage in `services/simulation/`,
`simulation/`, `simulation_branching.py`, `simulation_military.py`,
and `prediction.py`; the `fallback_random` decision method is a
misnomer, `_fallback_effect` is fully deterministic; (2) the tick loop
is a pure function of initial state + claims + rule registry; (3) the
sampler draws in set order from `random.Random(seed)`. Known
non-reproducible inputs, documented as replay assumptions: the
LLM-assisted decision level (no key in this environment, so never
hit), new evidence arriving between original and replay, and rule
registry calibration weights changing between runs
(`effective_priority` reads in-memory weights).

**Canonical JSON with floats.** The adadsws reference avoids floats
(fixed-point integers); this engine's state is floats, so floats are
supported via Python's `repr` formatting — stable within a Python
version/platform. Cross-language hash stability is NOT claimed.
Non-finite floats are rejected. Trial sub-seeds are masked to 63 bits
after an `OverflowError` showed 64-bit unsigned seeds overflow SQLite's
signed `INTEGER` column.

**Paired trials as real run rows.** Trials execute the real engine
(instead of a simplified in-memory loop), so ensemble members are
inspectable through every existing endpoint and the replay machinery
covers them. Cost: 2N full executions per ensemble; trials are capped
at 200 per request. No queue/worker path yet — ensembles run inline.

**No Sprint 4 items.** Aggregation stops at P10/P50/P90 + loss
probability + paired deltas. Expected shortfall, tornado sensitivity,
threshold search, pre-registered gates, and bootstrap intervals are
Sprint 4, grafted onto the trial values this sprint persists (trial
run ids + final states are all stored).

## 3. Integration points

| Change | File |
|---|---|
| Pure modules: canonical, sampler, aggregation, models | `src/planagent/services/distributions/` |
| Input-hash fragment at creation; sampling + state hashes in `_execute_run` | `src/planagent/services/simulation/engine.py` |
| Input-hash fragment for child runs; branch bindings resolver | `src/planagent/services/simulation/scenarios.py` |
| Monte Carlo runner, replay, determinism reads | `src/planagent/services/simulation/distributions.py` (new mixin) |
| Mixin wired into the service | `src/planagent/services/simulation/__init__.py` |
| Branch binding fields on the payload | `src/planagent/domain/api.py` (`ScenarioRunCreate`) |
| Branch-path lookup | `src/planagent/services/mece/validator.py`, `__init__.py` |
| Structured variable-gate errors on the scenario route | `src/planagent/api/routes/simulation.py` |
| New router + registration | `src/planagent/api/routes/distributions.py`, `src/planagent/api/routes/__init__.py` |
| Return annotation `dict[str, Any]` (was `dict[str, object]`) so callers can extend the fragment | `src/planagent/services/variables/presets.py` |

No Alembic migration: input hashes, state hashes, sampled values,
Monte Carlo results, and replay verifications all live in the existing
`configuration` / `summary` JSON columns.

## 4. Verification

Environment quirks from Sprint 0 apply unchanged: run pytest with
`env -u NO_PROXY -u no_proxy`; `.venv` (Python 3.12.3); SQLite +
in-memory event bus; no Docker, no LLM keys.

<!-- FINAL NUMBERS: filled in from the clean re-run on the finished branch. -->
Full suite (CI command `python -m pytest -q`, sanitized env):
**850 passed, 0 failed, 226.52s** (clean re-run on the finished
branch) — the 801 Sprint-2 baseline tests plus 49 new tests. Log:
`docs/sprint3/test-full.log`.

New-test breakdown:

- `tests/unit/test_canonical_hash.py` — byte-stability, unicode/float
  handling, rejection of non-JSON/non-finite values, `sha256:` prefix,
  state-hash self-exclusion, sub-seed determinism/label-sensitivity/
  63-bit range, input-hash stability/sensitivity/fragment-exclusion.
- `tests/unit/test_sampler.py` — each distribution's sampling behavior
  (bounds, centering, bernoulli edges, fixed exactness), pinned golden
  draws for seeds 42 and 7, seed reproducibility, lever replacement
  with shared-stream preservation (including variables drawn after a
  levered one), validator-contract rejection (8 invalid shapes), draw
  order dependence, run-level sample resolution (no bindings, state
  -field filtering, trial levers).
- `tests/unit/test_aggregation.py` — percentile interpolation (prototype
  semantics), summary shape + explicit loss threshold, empty/single
  inputs, paired delta pairing/count-mismatch/empty.
- `tests/unit/test_mece_branch_path.py` — root/nested paths, unknown
  paths, root-anchored exact matching.
- `tests/unit/test_replay_comparison.py` — match, first diverging tick
  (mid-run and tick 0), missing/extra ticks, numeric (not
  lexicographic) tick order.
- `tests/test_distributions_api.py` — sampling applies to tick-0 state
  with `initial_state` precedence; golden-run byte-identity (snapshots
  + input hash + state hashes); determinism endpoint with/without
  bindings; replay match + input-hash match + identical snapshots;
  replay/MC refusals (queued run, no bindings, unknown metric/lever,
  trials bounds, 404s); MC distributions + pairing (shared non-levered
  draws per index, lever values on the strategy arm) + stored-result
  retrieval + `/api` prefix; MC seed reproducibility (identical
  distributions across ensembles); branch override merge; branch
  refusal with zero branches created; decomposition-branch scope
  ownership (valid template-scoped branch, tag-outside-branch refusal,
  unknown path, no parent decomposition).

Regression notes:

- The first focused run on this branch showed 2 failures in
  `tests/test_variable_templates_api.py` when run in isolation
  (template-listing order). Verified pre-existing: the same tests fail
  in isolation on the Sprint 2 branch (pack-registry discovery
  order-dependence — the military pack is registered only after some
  other test imports it). The full suite is the gate, as before.
- `derive_sub_seed` initially returned 64-bit unsigned values; the
  first Monte Carlo API run failed with `OverflowError` on SQLite's
  signed `INTEGER` seed column. Fixed by masking to 63 bits.
- `docs/sprint0/smoke_e2e.py` re-run on this branch: PASS (unchanged
  no-bindings flow; the smoke evidence file was reverted after the run
  so it does not pollute the diff).
- `ruff format --check` tree-wide: same single pre-existing unformatted
  file as the Sprint 1/2 baseline (`docs/sprint0/smoke_e2e.py`); all
  new and touched files are formatted. `ruff check` on the new/touched
  files: zero findings except 4× B008 on the new route module, the
  `Depends()`-default pattern every existing route module uses (same
  treatment as Sprints 1–2). Two UP035 + one I001 + one TRY004 found
  during this sprint were fixed in the new code.
- `mypy src/planagent/` is clean: no issues in 166 source files (159
  Sprint-2 files + 7 new: 5 in `services/distributions/` + 1 mixin + 1
  route module).

Worked example (scratch DB, no evidence ingested, 50 trials, seed 42,
metric `cash`, loss threshold 90): baseline cash sampled from
triangular(60, 100, 140) gives final-cash P10 79.4 / P50 98.9 / P90
118.4 with p_loss 0.30; the strategy arm (cash levered to fixed 140)
collapses to 140.0 with p_loss 0.0; paired mean delta +40.6,
p_strategy_better 1.0. The strategy arm is degenerate because, with no
claims in the store, every tick takes the `monitor` fallback (no cash
effect), so final cash equals starting cash exactly — the numbers are
an honest demonstration of the pairing machinery, not a forecast.
Replay of the same run: match=true, first_diverging_tick=null,
input_hash_match=true.

## 5. How to run / verify

```bash
git checkout strategy-engine/sprint3-distributions
env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest -q tests/unit/test_canonical_hash.py tests/unit/test_sampler.py tests/unit/test_aggregation.py tests/unit/test_mece_branch_path.py tests/unit/test_replay_comparison.py tests/test_distributions_api.py
env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest -q   # full suite
.venv/bin/python docs/sprint0/smoke_e2e.py                  # Sprint 0 smoke
```

Example: bind variables, run an ensemble, replay the run:

```bash
curl -s -X POST localhost:8000/simulation/runs -d '{...,
  "variable_set": {"variables": [
    {"id": "cash", "unit": "k", "distribution": {"type": "triangular",
      "min": 60, "mode": 100, "max": 140}, "evidence_ref": "estimate: x"},
    {"id": "pipeline", "unit": "x", "distribution": {"type": "normal",
      "mean": 1.0, "std": 0.1}, "evidence_ref": "estimate: x"}]}}'
# -> 201 {"id": "<run_id>", ...}

curl -s -X POST localhost:8000/runs/<run_id>/monte-carlo -d '{
  "trials": 50, "seed": 11, "metric": "cash",
  "strategy_levers": {"pipeline": 1.0}}'
# -> 201 {"ensemble_id": ..., "baseline": {"p10": ..., "p50": ..., "p90": ...,
#      "p_loss": ...}, "strategy": {...}, "paired": {"mean_delta": ...}}

curl -s -X POST localhost:8000/runs/<run_id>/replay
# -> 201 {"match": true, "first_diverging_tick": null, "input_hash_match": true, ...}

curl -s localhost:8000/runs/<run_id>/determinism
# -> 200 {"input_hash": "sha256:...", "state_hashes": {"0": ..., ...},
#      "sampled_values": {"cash": ..., "pipeline": ...}, ...}
```

## 6. Known limits

1. **Variables affect dynamics only through state-field names.** A
   sampled variable applies to the initial state only when its id
   matches a state field; other variables are sampled and recorded but
   do not move the tick loop. The prototype's example variables
   (R&D 投入, CAC, uplift, churn) need the formula graph to affect
   outcomes — that is Sprint 4 work, not built here.
2. **No correlation between variables.** Kept honestly from the
   reference and Sprint 2: independent sampling only.
3. **Branch bindings merge, never remove.** An inline set overrides or
   adds variables; it cannot drop an inherited binding. A branch that
   narrows scope should attach a fresh template (which replaces the
   base set) — the scope-ownership test exercises exactly this.
4. **Replay assumes unchanged execution inputs.** New evidence, rule
   calibration weight changes, or LLM-level decisions between the
   original and the replay can diverge the trajectories; divergence is
   reported honestly (first diverging tick), not hidden. Replay
   compares state trajectories only, not decision-record text.
5. **Ensembles run inline, capped at 200 trials.** 2N full executions
   per request; no queued/worker path yet. Trial runs skip report
   generation.
6. **Hashes are runtime-stable, not cross-language.** Float formatting
   follows Python `repr`; stability is claimed for this runtime only.
7. **Bindings remain opt-in**, as in Sprint 2. Runs without bindings
   are unaffected except for the (content-neutral) input-hash fragment.
8. **Docker stack / LLM paths** remain unverified, as in Sprints 0–2
   (no container runtime, no keys on this VM). The seed contract is
   verified on the SQLite + in-memory-bus dev path only; LLM-assisted
   ticks are inherently non-reproducible.

## 7. Sprint 4 entry points

1. **Robustness evaluation (approved enrichment)** — expected
   shortfall, tornado sensitivity, threshold/critical-point search,
   and pre-registered decision gates (per taylanakgn) + bootstrap
   intervals (per jasonrkeen), grafted onto the trial values this
   sprint persists: every trial run id + final state is stored on the
   ensemble result, and `summarize_samples` / `paired_delta_stats` are
   the aggregation seam.
2. **Formula graph (Sprint 2 §6.5 / BACKLOG.md)** — derived variables
   computed from sampled variables with the reference's no-arbitrary-
   code expression vocabulary (`add/subtract/multiply/divide/min/max`
   + `ref`), evaluated per trial before the tick loop; lets
   non-state-field variables (CAC, uplift) drive dynamics.
3. **Queued ensembles** — move `run_monte_carlo` behind the simulation
   worker for large trial counts; the trial-row design already fits
   the queued path (`process_queued_runs` executes PENDING runs).
4. **Calibration (Sprint 5, approved enrichment)** — hindsight
   firewall (per saisrikolanu) + ridge-to-prior calibration (per
   jasonrkeen), using the stored validation results, sampled values,
   and run outcomes.
5. **Decision-record comparison in replay** — extend
   `compare_snapshot_hashes` with action-sequence comparison for
   stronger replay verification.

## 8. Commits on this branch

- `8479cec` — distribution layer pure modules (canonical hash, sampler,
  aggregation, models)
- `1bad86f` — input hashes at run creation, seeded sampling + per-tick
  state hashes in execution
- `7fd764a` — Monte Carlo + replay service mixin
- `61c4c20` — branch-level variable bindings + decomposition-branch
  scope ownership
- `f9c06f5` — distribution-layer API routes
- `54c7603` — tests + 63-bit sub-seed fix
- (this doc) — Sprint 3 report + backlog update + full-suite log

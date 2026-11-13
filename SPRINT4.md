# Sprint 4 — Robustness evaluation + formula graph (PRD deltas D6/D7)

Branch: `strategy-engine/sprint4-robustness`, from
`strategy-engine/sprint3-distributions` (`ad5f98e`). Nothing pushed.

This sprint closes gap G4 (no robustness evaluation) and the Sprint 3
§6 limit "variables affect dynamics only via state-field-name match":
five robustness analyses grafted onto the Sprint 3 persisted ensembles,
and a no-arbitrary-code formula graph that lets non-state-field
variables (the prototype's CAC, uplift, churn) drive tick dynamics.
Both workstreams are pure/deterministic, exposed through service
functions and API endpoints, and stored in the run audit trail.

References (read-only, code-verified in the research record):

- Robustness methods: taylanakgn/monte-carlo-strategic-decision-simulator
  (seeded MC, expected shortfall, tornado, threshold search,
  pre-registered decision gates, full tests).
- Bootstrap intervals: jasonrkeen US–Middle East withdrawal model
  (`backtesting.py`: seeded resampling + percentile intervals).
- Formula graph: agilhaykal/strategic-simulation ("SimplifySimulation")
  `backend/engine.py` (validated variable tables + formula graph, no
  arbitrary code, seeded paired MC).

## 1. What was built

### Formula graph

- `src/planagent/services/variables/models.py`: `FormulaOperator`
  (`add`, `subtract`, `multiply`, `divide`, `min`, `max`),
  `FormulaDefinition` (`output`, `expression`, `description`),
  `MAX_FORMULAS = 40`, `MAX_FORMULA_DEPTH = 15`. `VariableSet`,
  `VariableTemplate`, `VariableTemplateCreate`, and
  `VariableTemplateUpdate` gain a `formulas` field (default `[]`).
  `expression` is held as raw JSON at the Pydantic layer and validated
  by the pure validator, so malformed expressions become structured
  gate issues instead of 422s.
- `src/planagent/services/variables/formulas.py` (new, pure): 
  `validate_formulas` and `evaluate_formulas` plus
  `FormulaEvaluationError`. Evaluation is list-order: a formula may
  only reference sampled variables and the outputs of *earlier*
  formulas. Forward references are refused, which makes cycles
  impossible (every cycle contains a forward reference; self-reference
  is refused the same way). Issue kinds: `too_many_formulas`,
  `duplicate_formula_output`, `formula_output_collides_with_variable`,
  `formula_invalid_expression`, `formula_nonfinite_literal`,
  `formula_unknown_ref`, `formula_unknown_operator`,
  `formula_wrong_arity`, `formula_too_deep`,
  `formula_division_by_zero`. The `formulas` validation check only
  appears when the set carries formulas, so formula-free sets
  serialize exactly as in Sprint 3.
- `src/planagent/services/variables/validator.py`: formula validation
  integrated into `validate_variable_set`; `merge_variable_sets`
  merges formulas with override-by-output precedence.
- Gate discipline: the run-creation gates in `engine.py` and
  `scenarios.py` carry template formulas into the base set. A template
  binding with formulas but no variables is validated as formulas-only
  (the empty-set rule does not apply) and its bindings are stored.
  `POST /variables/validate` and template CRUD cover formulas through
  the same validator.
- Persistence: `VariableTemplateRecord.formulas` JSON column, Alembic
  migration `0030_variable_template_formulas` (upgrade + downgrade
  verified on scratch SQLite, §4). Template create/update/read carry
  formulas through `store.py`.
- Execution wiring: `resolve_run_values` in
  `services/distributions/sampler.py` returns
  `(sampled, derived, applied)` — formulas evaluate after sampling and
  after lever replacement, so Monte Carlo levers propagate through
  derived values. `_execute_run` applies derived values that match
  state fields to the initial state with the same precedence as
  sampled values (explicit `initial_state` still wins). Derived values
  that do not match state fields are recorded, not applied.
- Audit: `GET /runs/{id}/determinism` gains `derived_values` and
  `derived_applied` alongside `sampled_values` / `sampled_applied`.

### Robustness evaluation

- `src/planagent/services/distributions/quantiles.py` (new, pure):
  distribution quantiles for the tornado probes. Analytic for
  fixed / normal (`statistics.NormalDist.inv_cdf`) / triangular
  (closed-form inverse CDF) / bernoulli (step at `1 - p`). Beta-PERT
  uses seeded empirical quantiles (8192 draws, seed derived from
  `derive_sub_seed(seed, "tornado-quantiles")`) because the standard
  library has no beta inverse CDF; this is declared in the module
  docstring.
- `src/planagent/services/robustness/` (new package, pure):
  - `methods.py`: `expected_shortfall`, `bootstrap_intervals`,
    `bisect_threshold_search` (generator-form bisection) +
    `bisect_threshold` (synchronous driver), `gate_observed_value`.
    All statistics are full precision — no rounding anywhere in the
    robustness path, because a gate must see the unrounded statistic
    (the 4-decimal rounding in `paired_delta_stats` can flip a
    boundary gate).
  - `models.py`: request/response models for all five analyses,
    `GateDefinition` (metric + operator + threshold + arm + alpha),
    gate registration/evaluation records. Model-level validation:
    paired metrics (`mean_delta`, `p_strategy_better`) require the
    `paired` arm; ES gates carry `alpha`; `p_loss` threshold search
    requires a target in (0, 1); `arm_flip` requires target 0.
- `src/planagent/services/simulation/robustness.py` (new):
  `SimulationRobustnessMixin` + `RobustnessError`, mixed into
  `SimulationService`. All five analyses require a stored ensemble on
  the run (uniform precondition, `robustness_requires_ensemble`).
  Trial values are re-read from the trial run rows' summaries via the
  ensemble's stored `trial_run_ids` — nothing is re-executed. Every
  result carries `trial_values_hash` (SHA-256 of the canonical JSON of
  the trial values) and a `protocol` string naming the method. Results
  are stored on the run summary under `robustness` (per-analysis-key
  overwrite); gates under `decision_gates` (registrations +
  evaluations).
- `src/planagent/api/routes/robustness.py` (new, 8 endpoints, mounted
  on both the bare and `/api` routers like the Sprint 1–3 routes):
  `POST /runs/{id}/robustness/expected-shortfall`,
  `POST /runs/{id}/robustness/tornado`,
  `POST /runs/{id}/robustness/threshold-search`,
  `POST /runs/{id}/robustness/bootstrap` (201),
  `GET /runs/{id}/robustness`,
  `POST /runs/{id}/decision-gates` (201),
  `GET /runs/{id}/decision-gates`,
  `POST /runs/{id}/decision-gates/evaluate` (201).
  `RobustnessError` → 400 with a `{"code", "message"}` detail,
  `LookupError` → 404, `ValueError` → 400.

## 2. Design decisions

### Expected shortfall

Ported from the taylanakgn reference: ES is the mean of the worst
`alpha` fraction of the trial outcomes. `tail_count = max(1,
floor(alpha * n))`, so small ensembles still yield a defined tail (at
n = 10, alpha = 0.1, ES is the single worst outcome); `threshold` is
the cutoff value (VaR) at the tail boundary. Both tails are supported
(`lower` = worst outcomes, `upper` = best outcomes); per arm plus a
paired variant over per-trial deltas. Empty input raises; non-finite
values raise.

### Bootstrap intervals

Ported from the jasonrkeen reference: ordinary nonparametric
bootstrap, percentile method. `random.Random(seed)` resamples with
replacement; each arm's seed is derived via
`derive_sub_seed(seed, "bootstrap", arm)` so arms differ but runs are
reproducible; the default seed is the ensemble's seed. Statistics:
mean, median, p_loss (p_loss needs the ensemble's loss threshold).
The interval is `[percentile((1-level)/2), percentile(1-(1-level)/2)]`
of the resampled statistics, using the same linear-interpolation
percentile as the Sprint 3 aggregation. BCa was not built: the
reference uses percentile intervals, and BCa's acceleration estimate
needs a jackknife pass over the same stored values — a possible
Sprint 5+ refinement, not a correctness gap for the headline
statistics.

### Tornado sensitivity

Following the reference's ranges-not-percentages principle: each
bound variable is swung between its own P10 and P90 quantiles while
all other variables sit at their medians; the base probe has every
variable at its median. Rows are ranked by swing (high − low outcome),
descending, ties in binding order. Each probe is a real
`SimulationRun` row through the same `_execute_run`, with a fixed
replacement binding and a `robustness_probe` configuration fragment,
so probe outcomes are audit-trailed like trials. Probe count is
`2n + 1` for n variables. Probes share the ensemble seed's derivation
scheme, so the only difference between probes is the frozen variable.
Fixed variables are refused for threshold search but allowed in
tornado (their swing is honestly 0); bernoulli variables swing
between their P10/P90 values (0 and/or 1, depending on p). A subset of variables may be requested; an unknown
variable is refused (`robustness_unknown_variable`).

### Threshold / critical-point search

The search is a generator (`bisect_threshold_search`): the pure
function owns the bisection logic and yields probe points; the caller
supplies each statistic via `send()`. This split exists because probe
evaluation is an async service call — the pure function never touches
I/O. `bisect_threshold` drives it synchronously for tests and
callers with a callable statistic.

Probes use **fixed replacement bindings** (the frozen variable
becomes a fixed distribution; the rest sample normally), matching the
reference's freeze-input semantics, and every evaluation reuses the
same per-trial seeds (`derive_sub_seed(seed, "threshold-search",
trial_index)`, independent of evaluation order), so differences
between evaluations come only from the frozen variable. Two modes:
`p_loss` (find where the loss probability crosses the target) and
`arm_flip` (find where the paired mean delta crosses 0; strategy-arm
levers exclude the frozen variable — freeze wins over levers).
Direction (`increasing`/`decreasing`) orients the statistic so the
bisection is monotone in the oriented value. Default bounds come from
the variable's distribution (triangular/beta_pert: [min, max];
normal: mean ± 3 std); explicit bounds are honored. Fixed variables
(no interval) and bernoulli variables (no continuum) are refused. If
the target is not bracketed by the endpoint statistics, the search
reports `reachable: false`, `threshold: null`, honestly — with the two
endpoint evaluations retained. A final evaluation at the returned
threshold is always included in the evaluation list.

### Pre-registered decision gates

Ported from the reference's gate discipline: a gate is a metric +
operator + threshold (+ arm + alpha for ES), evaluated against the
stored ensemble's unrounded statistics. Unknown metrics fail loudly
(the reference rule) rather than defaulting. Registrations are
append-only: a new registration may `supersede` an old one, but the
old one is retained with status `superseded`; evaluation defaults to
the active registration or takes an explicit id. Pre-registration is
*evidenced, not asserted*: at registration time the service records
`ensemble_existed_at_registration` and the then-current ensemble id.
An evaluation is `pre_registered` iff the registration's ensemble id
differs from the evaluated ensemble's id, or no ensemble existed at
registration. A gate registered after the ensemble exists is honestly
marked not pre-registered. Gates are evaluated with the unrounded
`_raw_arm_summary` / `_raw_paired_summary` statistics, not the
rounded ensemble summaries.

### Formula graph

Expression vocabulary is exactly the reference's: numeric literals,
`{"ref": id}`, and `{"op": ..., "args": [exactly 2]}` with the six
binary operators. No strings, no function calls, no arbitrary code —
the evaluator is a small recursive interpreter over validated JSON.
Evaluation order is list order (a legal topological order by
construction); referencing a later formula is a validation issue, so
no separate cycle check is needed. Division by zero splits into two
cases, as in the reference: statically provable zero denominators
(literal 0, or a reference to a fixed-0 variable) are validation
issues (`formula_division_by_zero`); data-dependent zeros raise
`FormulaEvaluationError` at evaluation time — the reference's own
examples guard with `max(denominator, epsilon)`, and the same guard
works here. Non-finite literals and non-finite results are refused.
A formula output may not collide with a sampled variable id.
Formulas evaluate once per run, before the tick loop, on the sampled
(+ lever-replaced) values — they do not re-evaluate per tick.

### Correction to the task statement

The Sprint 4 task said "every trial run id + final state is stored on
the ensemble result". In the Sprint 3 implementation only the trial
run ids are stored on the ensemble; the final states live on the
trial run rows' summaries. The robustness service therefore re-reads
trial values from the trial rows via the stored ids (and records a
`trial_values_hash` so the exact input set is pinned). Nothing is
re-executed, and the hash makes any later drift detectable.

## 3. Integration points

- Sampling seam: `resolve_run_values` extends `resolve_run_samples`
  (kept with its original semantics for the determinism audit and
  existing callers). Formula evaluation sits between sampling and
  state application, after lever replacement.
- Gate seam: formula validation rides the existing
  `validate_variable_set` gate in run creation and scenario branching;
  template formulas flow through the same merge path as template
  variables. No bypass exists: a run with an invalid formula graph is
  refused before any row is written, with the same 400 shape as the
  Sprint 2 variable gate.
- Ensemble seam: robustness reads the Sprint 3 ensemble fragment
  (`trial_run_ids`, `metric`, `loss_threshold`, `strategy_levers`,
  `seed`) and reuses `derive_sub_seed` for probe/bootstrap seeds.
  Probe runs are created through the same `_create_run_record` +
  `_execute_run` path as MC trials (including military geo-asset
  cloning), with report generation skipped.
- Storage seam: robustness results and gate records live in the run
  summary JSON (`robustness`, `decision_gates` keys), following the
  Sprint 1–3 fragment pattern — no new tables except the template
  `formulas` column. The determinism fragment gains the two derived
  fields with no migration.

## 4. Verification

- Full suite: **912 passed, 0 failed** (Sprint 3 baseline 850; +62:
  45 new unit tests + 17 API tests), same command as Sprints 0–3
  (`env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest -q`, log
  at `docs/sprint4/test-full.log`, 254 s). No existing test was
  modified except the Sprint 2 golden fixture, whose diff is exactly
  one line (`"formulas": []`); the validation section is unchanged.
- Sprint 0 smoke re-run on this branch: PASS (evidence reverted, not
  committed).
- Migration `0030_variable_template_formulas` verified by hand on
  scratch SQLite: `alembic upgrade head` adds the `formulas` column
  and stamps `0030_variable_template_formulas`; `alembic downgrade
  0029_variable_templates` drops it and stamps `0029`.
- `mypy src/planagent/`: clean. `ruff check`: 495 findings vs the
  Sprint 3 baseline of 487 — the +8 are all B008 `Depends()` in the
  new routes module, the repo-wide pattern used by every other route
  module. `ruff format --check`: only the pre-existing
  `docs/sprint0/smoke_e2e.py` remains unformatted.
- The known Sprint 3 ordering quirk stands: `test_variable_templates_api`
  shows 2 failures when run in isolation (pack-registry discovery
  order); the full suite is the gate and it is green.

### Behavior evidence (real ensemble, scratch DB, demo script)

Setup: cash triangular(60, 100, 140), pipeline normal(1.0, 0.1), cac
triangular(8000, 12000, 20000); 50 trials, seed 42, metric cash, loss
threshold 90, strategy levers `{cash: 140}`. Honest note, as in
Sprint 3: with no evidence ingested, every tick takes the `monitor`
fallback, so final cash equals starting cash exactly — these numbers
verify the robustness machinery, not a forecast.

- Ensemble: baseline mean 99.39, P10 79.38 / P50 98.90 / P90 118.40,
  p_loss 0.30; strategy degenerate at 140.0; paired mean_delta 40.61,
  p_strategy_better 1.0.
- ES(0.05, lower): baseline 74.23 (tail_count 2, threshold 74.32);
  strategy 140.0. `trial_values_hash` stable across recomputation.
- Bootstrap (500 draws, percentile, level 0.95): mean 99.39
  [95.30, 103.52]; median 98.90 [93.17, 103.77]; p_loss 0.30
  [0.18, 0.44]. Same seed reproduces byte-identical intervals.
- Tornado: cash swing 44.22 (P10 77.89 → P90 122.11, outcomes equal
  the frozen values); pipeline and cac swing 0.0 (they do not move
  cash in the evidence-free setup). 7 probe runs.
- Threshold search (p_loss, target 0.5, decreasing, 10 trials per
  evaluation, 8 iterations, tolerance 0.5): threshold 89.84 — the
  true step is at the loss threshold 90; 11 evaluations, bounds
  [60, 140]. An unreachable search (bounds [100, 140]) honestly
  reports `reachable: false`, `threshold: null`, 0 iterations.
- Gates (registered before the ensemble): `pre_registered: true`,
  all 4 pass — mean 99.39 > 0; ES(0.05) 74.23 > 70; p_loss 0.30 ≤ 0.5;
  mean_delta 40.61 > 0. A gate registered after the ensemble is
  marked not pre-registered; supersession retains the old
  registration as `superseded`.

### Formula golden case (prototype variables)

`tests/fixtures/variable_formula_golden_case.json` ports the MVP
prototype's four variables (R&D person-months, CAC, uplift, churn)
plus four formulas: `获客成本(千元)` = CAC/1000; `cash` =
140 − (获客成本(千元) + 研发投入); `净留存信号` = uplift − churn;
`pipeline` = max(0.5, 净留存信号/20). At mode values the graph
evaluates to 12.0, 92.0, 23.0, 1.15. The golden test pins the
byte-stable serialization of the validated set + validation result,
and the API test shows a live run's tick-0 state equals the
independently computed derived values, with the determinism audit
recording `derived_values` / `derived_applied`. Through Monte Carlo
with levers `{CAC: 20000, 研发投入: 36}`, the strategy arm is exactly
84.0 on every trial (140 − (20 + 36)) — prototype-style variables now
move outcomes through the graph.

### Coverage note: arm_flip convergence

The `arm_flip` threshold mode's convergence is covered at the pure
level (`bisect_threshold` over synthetic monotone statistics,
including a step function and an unreachable case). The API test
covers only the honest-unreachable path: in the evidence-free setup
the paired delta cannot flip, so no engine-level flip exists to
converge to. Once evidence-driven dynamics move outcomes, an
end-to-end converging arm_flip test becomes possible; it is recorded
in §6 rather than faked here.

## 5. How to run / verify

```bash
env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest -q
env -u NO_PROXY -u no_proxy .venv/bin/python docs/sprint0/smoke_e2e.py
```

```bash
# Bound run + ensemble (Sprint 2/3 endpoints), then:
curl -X POST /runs/<id>/robustness/expected-shortfall \
  -d '{"alpha": 0.05, "tail": "lower"}'
# -> 201 {"ensemble_id": ..., "baseline": {"value": ..., "threshold": ...,
#      "tail_count": ..., "n": ...}, "strategy": {...}, "paired": {...},
#      "trial_values_hash": "sha256:..."}
curl -X POST /runs/<id>/robustness/bootstrap \
  -d '{"draws": 500, "level": 0.95}'
# -> 201 {"baseline": [{"statistic": "mean", "estimate": ..., "low": ...,
#      "high": ..., "draws": 500, "seed": ..., "method": "percentile"} ...]}
curl -X POST /runs/<id>/robustness/tornado -d '{}'
# -> 201 {"rows": [{"variable": "cash", "low_value": ..., "high_value": ...,
#      "outcome_low": ..., "outcome_high": ..., "swing": ...} ...],
#      "probe_run_ids": [...]}
curl -X POST /runs/<id>/robustness/threshold-search \
  -d '{"variable": "cash", "mode": "p_loss", "target": 0.5,
       "direction": "decreasing"}'
# -> 201 {"threshold": 89.84, "reachable": true, "iterations": 8, ...}
curl -X POST /runs/<id>/decision-gates \
  -d '{"gates": [{"name": "g", "metric": "mean", "operator": ">",
                  "threshold": 0}]}'
# -> 201 {"id": ..., "ensemble_existed_at_registration": false, ...}
curl -X POST /runs/<id>/decision-gates/evaluate -d '{}'
# -> 201 {"pre_registered": true, "outcomes": [...], "all_passed": true}
curl /runs/<id>/robustness
# -> 200 {"expected_shortfall": {...}, "tornado": {...}, ...}
```

## 6. Known limits

- Formulas evaluate once per run, before the tick loop. A formula
  cannot reference tick-evolving state or another tick's outcome.
  Per-tick derived quantities are a later-sprint design question.
- No correlation between variables (same limit as the reference,
  which explicitly refuses correlation). Tornado is one-at-a-time:
  it cannot surface interactions between variables.
- Beta-PERT tornado quantiles are seeded empirical quantiles (8192
  draws), not analytic — declared in `quantiles.py`. All other
  distributions use analytic quantiles.
- Threshold search assumes the oriented statistic is monotone in the
  frozen variable over the search bounds. Non-monotone statistics
  may converge to a crossing that is not the decision-relevant one;
  the returned evaluation list lets a reviewer see the shape.
- Bootstrap is percentile-method only (no BCa). ES at small n has a
  coarse tail (`tail_count` floor of 1) — the tail count is always
  reported so the coarseness is visible.
- Probe runs are real run rows: a tornado over n variables adds
  2n+1 rows; a threshold search adds
  (2 + iterations + 1) × trials_per_evaluation × (1 or 2 arms) rows.
  Ensembles stay inline (Sprint 3 cap: 200 trials per request).
- Gate registrations and robustness results live in run summary
  JSON, not dedicated tables — consistent with the Sprint 1–3
  fragment pattern, and sufficient for audit, but a future UI may
  want queryable gate history.
- Hashes are runtime-stable only (Python float repr), as in Sprint 3.
- No authoring UI for formulas, gates, or robustness requests;
  decomposition and bindings remain opt-in; scope tags remain exact
  strings (carried limits from Sprints 1–2).
- The `arm_flip` end-to-end convergence path is untested at the API
  level for the reason in §4 (evidence-free dynamics cannot flip);
  pure-level coverage stands.
- Unverified, as in Sprints 0–3: Docker Compose stack (no container
  runtime on this VM), LLM-backed paths (no key; no LLM call was
  added in this sprint), frontend vitest suite (Node 24 vs 22).

## 7. Sprint 5 entry points

Sprint 5 (approved enrichment): hindsight firewall (per saisrikolanu)
+ ridge-to-prior calibration (per jasonrkeen), targeting gap G5
(uncalibrated heuristic constants).

1. **Hindsight firewall.** The seam is the evidence store: claims
   carry ingestion timestamps, and `_execute_run` reads all claims
   for a run regardless of when the decision was "made". The
   firewall is a decision-time cutoff: runs record a
   `decision_time`, and evidence/claim reads filter to
   `ingested_at <= decision_time`. The determinism fragment
   (`input_hash`) should gain the cutoff so a replay with the same
   cutoff reproduces the same evidence set. The saisrikolanu
   reference's deliberation split (decide-time vs outcome-time
   information) is the design model.
2. **Ridge-to-prior calibration.** The constants to calibrate are
   the `_STATE_POLICIES` thresholds/weights (now stored as editable
   templates since Sprint 2) and the rule-registry calibration
   weights. The calibration seam is `calibration_records` (migration
   0013) plus the stored run outcomes: fit a ridge regression of
   observed outcomes on the policy features, shrinking toward the
   template priors, per the jasonrkeen reference's
   `_bootstrap_coefficients` pattern (seeded resampling already
   exists in this sprint's bootstrap module — reuse it, do not
   re-implement). A calibrated template should be stored as a new
   template version with its provenance (source runs, shrinkage
   parameter), never by overwriting the prior.
3. **Robustness consumers.** The Sprint 4 gate/ES/tornado outputs
   are the natural inputs to the deferred decision-direction
   narrative (pre-mortems, 48-hour first steps): each direction's
   distribution, key drivers (tornado rows), and flip signals
   (thresholds) are already computed and stored. The narrative layer
   is a presentation sprint, not a methods sprint.

## 8. Deferred (out of scope, recorded deliberately)

- **Decision-direction narrative output** (pre-mortems, 48-hour
  first steps, LLM narrative/red-team layer): deferred to a later
  sprint. The robustness outputs it consumes now exist and are
  stored; the narrative layer needs LLM access (no key on this VM)
  and a presentation design, neither of which belongs in a methods
  sprint.
- **Sprint 5 items** (hindsight firewall, ridge-to-prior
  calibration): not built; see §7.
- **Queued ensembles**: not needed — inline execution sufficed for
  all robustness probes. If probe volume grows (larger ensembles,
  wider tornado sweeps), queueing becomes the scaling answer.

## 9. Commits on this branch

- `f085bf7` — formula graph models, pure validator/evaluator,
  template persistence (migration 0030).
- `e5b47d5` — wire formula evaluation into execution + determinism
  audit (golden fixture regenerated: one-line diff).
- `9fa8c72` — pure robustness methods, gate models, distribution
  quantiles.
- `f8bffae` — robustness service mixin + API routes.
- `5f56eb7` — tests: 45 unit + 17 API + formula golden fixture.
- `863445f` — lint/format polish.
- (this report + `BACKLOG.md` update + `docs/sprint4/test-full.log` —
  final commit below)

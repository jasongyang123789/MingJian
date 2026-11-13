# Sprint 5 — Calibration loop + hindsight firewall (PRD delta D8)

Branch: `strategy-engine/sprint5-calibration`, from
`strategy-engine/sprint4-robustness` (`cc2fd58`). Nothing pushed.

This sprint closes gap G5 (uncalibrated heuristic constants) and adds
the deliberation-integrity half of the approved Sprint 5 enrichment:
a hindsight firewall that keeps post-decision evidence out of
simulation runs, and a ridge-to-prior calibration loop that fits the
`_STATE_POLICIES` thresholds and the rule-registry weights from stored
run outcomes. Both workstreams are pure/deterministic, exposed through
service functions and API endpoints, and stored in the audit trail.
No LLM call was added anywhere in this sprint.

References (read-only, code-verified in the research record):

- Hindsight firewall: saisrikolanu multi-agent decision simulator
  (`crew/deliberation.py`: `ground_truth` is never passed to agents;
  briefings are built only from `agent_visible` data plus a knowledge
  cutoff; `crew/evaluator.py` alone reads ground truth). The
  decide-time vs outcome-time split is the design model.
- Ridge-to-prior calibration: jasonrkeen US–Middle East withdrawal
  model (`src/backtesting.py`: `fit_ridge_to_prior` normal equations
  with the penalty centered on a prior, non-negative clipping,
  `_bootstrap_coefficients` seeded resampling, LOO predictions).
  The Sprint 4 bootstrap module is reused for seeded resampling, not
  re-implemented.
- Existing machinery built on, not duplicated: the calibration worker
  and `calibration_records` table (migration 0013, hypothesis
  verification aggregates), the rule-registry calibration weights,
  and the Sprint 2 template system (built-in presets + stored
  templates + validation). The Global-Affairs Brier-score code is
  context only; this sprint's method is ridge-to-prior, not Brier.

## 1. What was built

### Hindsight firewall

- `src/planagent/services/calibration/firewall.py` (new, pure):
  `normalize_cutoff` (aware → naive UTC; naive assumed UTC — SQLite
  stores naive datetimes), `format_cutoff` (canonical
  `YYYY-MM-DDTHH:MM:SS.ffffffZ`), `parse_cutoff` (accepts the
  canonical form, `+00:00` offsets, and naive ISO strings; raises on
  garbage), `firewall_configuration_fragment`, and
  `firewall_cutoff_from_configuration`. The cutoff lives in the run's
  `configuration` JSON under `hindsight_firewall` with protocol
  `sprint5-v1`, the canonical decision-time string, and a
  `cutoff_source` (`explicit` or `creation_time`).
- `src/planagent/domain/api.py`: `SimulationRunCreate` gains optional
  `decision_time: datetime | None`.
- `src/planagent/services/simulation/engine.py`: both run-creation
  paths store the firewall fragment in the run configuration before
  the determinism fragment is computed, so the Sprint 3 input hash
  covers the cutoff. `_execute_run` resolves the cutoff and passes it
  to `_fetch_relevant_claims`, which applies `Claim.created_at <=
  cutoff` inside `scoped()` — the helper all four claim queries pass
  through, so no fallback fetch can bypass the firewall. The summary
  `determinism` fragment gains `decision_time`, `cutoff_source`, and
  `firewall_active`. MC trials, replays, scenario children, and
  robustness probes all copy the configuration, so they inherit the
  cutoff automatically; replay therefore reproduces the same evidence
  set even when new claims arrived after the original run.
- `GET /runs/{run_id}/firewall`: recomputes the claim fetch with and
  without the cutoff and reports the diff — `included_claim_ids`,
  `excluded_claim_ids` (exactly the claims the firewall kept out),
  plus the stored `decision_time`/`cutoff_source`/`firewall_active`
  and the execution-time `stored_evidence_ids` (evidence-item ids
  from the run summary, a different id space from claim ids — the
  distinction is documented on the model).

### Ridge-to-prior calibration

- `src/planagent/services/calibration/estimator.py` (new, pure,
  stdlib-only): `fit_ridge_to_prior` solves `(X'X + λI)β = X'y +
  λ·prior` by Gaussian elimination with partial pivoting (no
  numpy/pandas — this codebase's new modules are stdlib-only),
  optional non-negative clipping (default on, matching the
  reference); `ridge_location_fit` routes the single-threshold fit
  through the same solver with a ones-column design (closed form
  `(Σy + λ·prior)/(n + λ)`; n ≥ 1 accepted); `leave_one_out_rmse`
  (None below 3 observations); `bootstrap_coefficient_intervals`
  (resample via the shared Sprint 4 primitive, refit, percentile
  intervals via the Sprint 3 percentile); `calibrate_policy_thresholds`
  and `calibrate_rule_weights` (see §2). Defaults match the reference:
  ridge strength 5.0, seed 20260727; bootstrap draws default 200
  (reference: 1000 — a latency choice for the pure-Python solver,
  documented on the constant).
- `src/planagent/services/robustness/methods.py`:
  `bootstrap_index_draws(count, draws, seed)` extracted as the single
  seeded-resampling primitive; `bootstrap_intervals` refactored onto
  it with identical RNG consumption (23 existing tests pass
  unchanged, including the seed-reproducibility test).
- `src/planagent/simulation/rules.py`: `RuleRegistry.apply_fitted_weights`
  validates finite weights, clips to [0.0, 2.0] (the worker's
  `weight_multiplier` range), replaces the current weights outright,
  and returns the applied mapping. Unlike `apply_calibration` (the
  worker's periodic accuracy blend), this is an explicit, audited
  override; the durable record is the calibration fit row, not the
  registry (weights are in-memory only; `reload()` resets them).
- `src/planagent/services/simulation/calibration.py` (new mixin,
  `SimulationCalibrationMixin`, wired into `SimulationService`):
  `get_firewall_audit`, `fit_policy_thresholds`, `fit_rule_weights`,
  `apply_rule_weights`, `get_calibration_fit`, `list_calibration_fits`,
  plus `CalibrationError(ValueError)` with stable codes, mapped like
  `MonteCarloError`/`RobustnessError`. Eligible runs are completed
  primary runs only — MC trials, robustness probes, and replays are
  excluded (derived artifacts would double-count the same evidence);
  scenario children are included (documented correlation caveat in
  §6). Runs are ordered by `(created_at, id)` for determinism.
  Explicit `source_run_ids` are validated uniformly (existence,
  completed, domain match, exclusions) with 400s; an unknown or
  ineligible id refuses the fit rather than being silently skipped.
- `src/planagent/domain/models.py` + migration
  `0031_calibration_fits`: new `calibration_fits` table (model
  `CalibrationFitRecord`), one row per fit, append-only: kind,
  domain, source/calibrated template ids, metric, ridge strength,
  seed, draws, level, source run ids, observation count, changes JSON,
  `inputs_hash` (SHA-256 of the canonical fit inputs), LOO RMSE,
  application events JSON, created_at. Distinct from
  `CalibrationRecord` (migration 0013, the worker's verification
  aggregates). Upgrade + downgrade verified on scratch SQLite (see
  §4). The only post-creation mutation is appending application
  events; fit inputs and results are immutable.
- Policy fits store a NEW template version through the existing
  validated create path (same state fields, variables, formulas,
  internal entries; fitted policies; name suffixed ` (calibrated)`;
  provenance in the description). The source template row is never
  touched. Rule-weight fits do NOT write `RuleAccuracy.weight_multiplier`
  (the calibration worker recomputes and overwrites it); fitted
  weights live on the fit record and take effect only through the
  explicit apply endpoint.
- API routes (`src/planagent/api/routes/calibration.py`, registered
  in `routes/__init__.py`, dual bare + `/api` mounting automatic):
  `POST /calibration/policy-fit` (201), `POST
  /calibration/rule-weight-fit` (201), `GET /calibration/fits`,
  `GET /calibration/fits/{fit_id}`, `POST
  /calibration/fits/{fit_id}/apply-rule-weights` (201),
  `GET /runs/{run_id}/firewall`. `CalibrationError` → 400 dict
  detail, `LookupError` → 404, `ValueError` → 400.

## 2. Design decisions

### Back-compat default for decision_time

Runs without an explicit `decision_time` get a cutoff equal to the
run's creation time (`cutoff_source: creation_time`) — evidence
available when the decision was made. This is the only default that
preserves the meaning of the firewall for ordinary runs: a run
created now should not see evidence ingested later, and replaying it
later must reproduce the same evidence set. The alternative (no
cutoff, legacy behavior) would have made the firewall opt-in and left
replays silently hindsight-contaminated. Runs that predate Sprint 5
(no fragment, e.g. rows built outside the run-creation path) keep the
legacy unfiltered reads — `(None, None)` from the resolver — so old
rows never change behavior. A present-but-malformed fragment raises
`ValueError` and fails loudly: silently ignoring a corrupt cutoff
would leak hindsight. The boundary is inclusive (`created_at <=
decision_time`): a claim ingested exactly at the decision time was
available when the decision was made.

The calibration worker's verification path is deliberately NOT
firewalled: it is the evaluator side of the saisrikolanu split, and
verification legitimately uses post-decision evidence. The same
applies to `_build_calibration_context` and the debate/report LLM
paths — out of scope for this sprint, recorded as a limit in §6.

### The exact ridge estimator

Both fit kinds solve the same normal equations,
`β = (X'X + λI)⁻¹(X'y + λ·prior)`, ported from the reference:

- **Policy thresholds.** Per metric, two location fits through the
  ones-column design. The alert threshold is fit over all observed
  final values with the current alert threshold as prior; the
  critical threshold is fit over the worst-side tail (below the
  alert line for `increase` metrics, above it for `decrease`) with
  the current critical threshold as prior. When no observation
  crossed the alert line, the worst quartile stands in as the tail
  (recorded via the tail count, not hidden). Metrics with fewer
  than 3 observations keep their priors
  (`unchanged_reason: insufficient_observations`). A fitted pair
  that would break the direction's threshold ordering is rejected
  wholesale for that metric (both priors kept, reason
  `ordering_guard`, rejected fit recorded) rather than silently
  clamped. With valid priors the fitted pair provably preserves
  ordering, so the guard fires only against inverted priors — it
  converts what would be a template-validator refusal into a
  keep-priors outcome. A one-observation tail yields no bootstrap
  interval for the critical threshold (no resampling variability to
  report); the fitted value is still recorded. Clipping is off for
  thresholds (they may legitimately be negative).
- **Rule weights.** One observation per completed run: features are
  per-rule match counts from decision records
  (`policy_rule_ids`), the target is the run's final value of the
  caller-specified metric (must be a pack state field), and the
  prior is the registry's current weight per rule (default 1.0).
  Coefficients are clipped at zero (weights are non-negative
  multipliers). Rules that never matched keep their prior exactly —
  an all-zero column contributes nothing to `X'y`, so the penalty
  term alone decides, and it decides for the prior. At least 2
  observations are required (the reference's floor for the general
  fit). LOO RMSE is reported as a fit-quality signal. Fitted weights
  are an association signal (rule activation vs outcome), not a
  causal estimate — stated on the fit record via `association_note`.

### What the firewall does not cover

The cutoff filters claim reads in `_execute_run` only. Evidence
ingested through other paths (debate context, report generation,
`_build_calibration_context`) is untouched: those are presentation
and verification surfaces, not the simulation's evidence set. The
firewall also does not version the rule registry or the domain packs:
replay assumes unchanged evidence/registry/LLM configuration, as in
Sprint 3 — a changed registry between run and replay still diverges
state hashes, and the firewall does not claim otherwise.

### Correction to the task statement

The task named `calibration_records` as "the calibration seam".
That table aggregates hypothesis-verification outcomes for the
calibration worker; it does not store the per-run outcomes a ridge
fit needs. The actual seam is the stored run outcomes themselves
(`summary.final_state` + decision records), which is what the fits
read. The new `calibration_fits` table records the fits; the worker
and its table are untouched, and the interaction is documented: the
worker's periodic `apply_calibration` blends from whatever weights
are current, including previously applied fitted weights.

## 3. Integration points

- Run creation: `decision_time` is accepted on
  `POST /simulation/runs` (and scenario/branch creation inherits the
  parent's configuration fragment). The firewall fragment is written
  before the determinism fragment in both `_create_corporate_run`
  and `_create_military_run`.
- Determinism: the cutoff enters the Sprint 3 input hash because
  `compute_input_hash` hashes the full configuration minus the
  `determinism` key; no hash-protocol change was needed. The
  `DeterminismRead` model is untouched; the summary fragment carries
  the new keys.
- Templates: policy fits read through `builtin_template` /
  `get_variable_template` and write through `create_variable_template`,
  so fitted versions pass the same validator as hand-authored ones.
  Builtin sources are eligible for fitting: runs with no variables
  fragment, a fragment naming the builtin id, or a bindings-only
  fragment all execute against the pack defaults the builtin
  synthesizes.
- Registry: `apply_fitted_weights` is the only new registry method;
  `effective_priority`, `apply_calibration`, and `reload` are
  unchanged.
- No changes to the worker, debate, report, or evidence services.

## 4. Verification

- Full suite: 912 → 963 passed, 0 failed (same pytest command as
  Sprints 0–4, with the `NO_PROXY` workaround; log:
  `docs/sprint5/test-full.log`, 278.95s). 51 new tests: 36 unit
  (`test_firewall.py`, `test_ridge_estimator.py`,
  `test_rule_registry_fitted_weights.py`) + 15 API
  (`test_calibration_api.py`).
- One existing test updated (not a test double): Sprint 3's
  `test_golden_run_same_seed_same_inputs_byte_identical` asserted
  two identical runs get identical input hashes. The task requires
  the cutoff to enter the input hash, and the creation-time default
  is wall-clock-dependent, so two runs created at different instants
  now legitimately hash differently — the evidence set genuinely is
  a function of the cutoff. The test now pins the same explicit
  `decision_time` on both runs, restoring the literal "same inputs"
  premise; snapshots and state hashes were already identical, only
  the input hash differed. This is the only existing-test change in
  the sprint, and it is documented here rather than buried.
- Migration 0031: `alembic upgrade head` then `downgrade
  0030_variable_template_formulas` then `upgrade head` on scratch
  SQLite — table created with all 17 columns, dropped on downgrade,
  recreated on re-upgrade.
- `mypy src/planagent/`: clean (179 source files). `ruff check`:
  only the repo-wide B008 `Depends()` findings on the new route
  module. `ruff format --check`: clean on all Sprint 5 files (the
  only pre-existing unformatted file remains
  `docs/sprint0/smoke_e2e.py`).
- Sprint 0 smoke re-run on this branch: PASS (exit 0; health →
  ingest → 4-tick simulation → decision trace → workbench →
  options). The smoke evidence file was reverted after the run, as
  in previous sprints.
- Bootstrap refactor check: `tests/unit/test_robustness_methods.py`
  (23 tests) passes unchanged after extracting
  `bootstrap_index_draws`, confirming RNG-consumption identity.

### Behavior evidence (firewall)

From `tests/test_calibration_api.py::test_firewall_excludes_post_decision_claims`
(scratch DB, claims seeded with explicit ingestion timestamps):

- 4 ACCEPTED claims: 2 ingested 2026-01-10 / 2026-02-10, 2 ingested
  2026-04-10 / 2026-05-10. Run created with
  `decision_time: 2026-03-01T00:00:00Z`.
- The run's evidence set contains exactly the 2 pre-cutoff claims
  (`evidence_count: 2`, statements match); the summary determinism
  fragment records `decision_time: 2026-03-01T00:00:00.000000Z`,
  `cutoff_source: explicit`, `firewall_active: true`.
- `GET /runs/{id}/firewall` reports `included_claim_ids` =
  the 2 early claims, `excluded_claim_ids` = the 2 late claims.
- A claim ingested exactly at the decision time is included
  (inclusive boundary, tested separately).
- Replay after the late claims exist: `match: true`,
  `first_diverging_tick: null`, `input_hash_match: true`; the replay
  row's audit shows the inherited cutoff and the same exclusion.
- Two runs identical except for `decision_time` get different input
  hashes; two runs identical including `decision_time` get the same
  input hash.

### Behavior evidence (calibration)

From the policy-fit API test (evidence-free runs bound to a template
with cash policy increase 50.0/25.0; final cash equals starting cash
exactly, so the fit is exactly predictable):

- Observations 80/90/100/110, λ = 1.0, seed 7: fitted alert
  `(380 + 50)/5 = 86.0`, fitted critical `(80 + 25)/2 = 52.5` (tail:
  worst quartile, no value below the alert line). New template
  version carries 86.0/52.5; the source template still reads 50.0/25.0.
- Shrinkage: λ = 1e6 → fitted alert 50.0003 (stays at the prior);
  λ = 1e-6 → fitted alert 95.0 (the data mean). Two identical fits
  produce identical `changes` and `inputs_hash`.
- A template with 1 carrying run fits with
  `unchanged_reason: insufficient_observations` and priors kept; a
  template with 0 carrying runs refuses with 400
  `insufficient_observations`.
- Rule-weight fit (3 runs, claims triggering `corp.cost_pressure`
  and `corp.ship_momentum`, metric `cash`, λ = 5.0, seed 7):
  `corp.cost_pressure` fitted 32.70 (5 matches),
  `corp.ship_momentum` fitted 21.44 (3 matches), the other six
  corporate rules fitted exactly 1.0 (0 matches, priors kept);
  LOO RMSE 45.31; `inputs_hash`
  `sha256:0c5fd00c…`. The large fitted values are the no-intercept
  estimator absorbing the cash level (~100–120) into the weights —
  see the no-intercept limit in §6. The apply endpoint records
  previous weights (all 1.0) and applied weights (clipped to
  [0, 2]) as an application event, and a second apply appends a
  second event. Two identical fits produce identical `changes` and
  `inputs_hash`.

## 5. How to run / verify

Same environment as Sprints 0–4: `.venv` (Python 3.12.3, editable
install), SQLite + `PLANAGENT_EVENT_BUS_BACKEND=memory`, no LLM keys,
pytest with `env -u NO_PROXY -u no_proxy`. New endpoints:

- `GET /runs/{run_id}/firewall`
- `POST /calibration/policy-fit` — `{"template_id", "ridge_strength"?,
  "seed"?, "bootstrap_draws"?, "level"?, "source_run_ids"?}`
- `POST /calibration/rule-weight-fit` — `{"domain_id", "metric",
  "ridge_strength"?, "seed"?, "bootstrap_draws"?, "level"?,
  "source_run_ids"?}`
- `GET /calibration/fits[?kind&domain_id&limit&offset]`,
  `GET /calibration/fits/{fit_id}`
- `POST /calibration/fits/{fit_id}/apply-rule-weights`

To fit thresholds by hand: create runs bound to a template (or
unbound runs for `builtin:<domain>`), then POST a policy fit; the
response names the new template version. To apply rule weights: POST
a rule-weight fit, then POST the apply endpoint; the fit record's
`application.events` shows what changed.

## 6. Known limits

- The firewall covers claim reads in `_execute_run` only. Debate
  context, report generation, and `_build_calibration_context` can
  still surface post-decision evidence; the calibration worker's
  verification path does so deliberately (evaluator side).
- No correlation modeling: threshold fits are per-metric
  independent location fits; the rule-weight fit is a single linear
  model over match counts with no interaction terms.
- Scenario children are included as observations; they share their
  parent's evidence and configuration, so their outcomes are
  correlated with the parent's. The fit treats them as independent
  observations (documented, not corrected).
- Fitted rule weights are associative, not causal. A rule that fires
  often in high-cash runs gets a higher weight whether or not it
  caused the cash. The fit record says so; the apply step is manual
  and audited for exactly this reason.
- No intercept term: the estimator is the reference's plain ridge
  through the origin, so for a level-dominated target (final cash
  ~100) the fitted weights absorb the target's level (demo fit:
  32.70 / 21.44 for the two matching rules) and the apply-time clip
  to [0, 2] bounds the effect. The fit is best read relatively
  (which rules associate with the outcome, and in which direction)
  or on centered/rate-like targets. Adding an intercept or target
  centering — with careful prior semantics for the intercept — is a
  recorded Sprint 6+ hardening item (§7.5), not a silent change to
  the reference estimator in this sprint.
- Rule-weight application is in-memory only: a process restart or
  `registry.reload()` resets weights to 1.0, and the calibration
  worker's next blend starts from the applied values. Re-applying a
  stored fit restores them; there is no persistent "current weights"
  record beyond the fit rows' application events.
- Formulas evaluate once per run (Sprint 4 limit, unchanged); the
  calibration fits read final states only and do not model
  within-run dynamics.
- Bootstrap intervals are percentile-only (Sprint 4 limit,
  unchanged). A one-observation tail yields no critical-threshold
  interval.
- Threshold fits use final states only: a metric that moved during
  the run but ended at the same value leaves no trace in the fit.
- Still unverified (as in all sprints): Docker Compose stack (no
  container runtime on this VM), LLM-backed paths (no key, none
  invented), frontend vitest suite (Node 24 vs required 22).

## 7. Sprint 6+ entry points

Sprint 6+ (per BACKLOG.md): skill grafts + cockpit UI, with the
decision-direction narrative still deferred.

1. **Calibration consumers.** The cockpit UI's natural first
   calibration surface is the fit history (`GET /calibration/fits`)
   plus a "new version available" affordance on templates: a
   calibrated template is an ordinary stored template, so the UI
   needs no new template machinery — only a way to show provenance
   (source template, source runs, shrinkage) from the fit record.
   The apply endpoint is the manual gate; an "auto-apply on
   schedule" policy would be a worker change, not an API change.
2. **Firewall-aware presentation.** The firewall audit endpoint
   returns exactly the claims a run could not see; the cockpit's
   run view can show the excluded set as "evidence that arrived
   after the decision" — the honest counterpart to the evidence
   list. No new backend work is needed for that view.
3. **Skill grafts.** The verified strategy skills (per the research
   record) graft as prompt templates / pipeline stages. The
   calibration fits give the debate/advisory stages something new
   to argue about: fitted-vs-prior threshold deltas and rule-weight
   deltas are structured inputs a deliberation stage can consume
   without touching the numeric core.
4. **Decision-direction narrative (still deferred).** The Sprint 4
   robustness outputs plus the Sprint 5 fitted templates are the
   inputs: each direction's distribution, drivers, flip signals, and
   now calibrated thresholds. The narrative layer still needs LLM
   access + presentation design.
5. **Calibration hardening (if wanted).** Persistent current-weights
   record; excluding scenario children or weighting them; per-metric
   correlation in threshold fits; an intercept term or target
   centering for the rule-weight fit (see the no-intercept limit in
   §6 — the intercept needs its own prior semantics, which is why it
   was not improvised into the reference estimator); a fit-quality
   gate (e.g. refuse to create a version when LOO RMSE is worse than
   the prior-only baseline). None of these is needed for the loop to
   function; each is a small, well-scoped follow-up.

## 8. Deferred (out of scope, recorded deliberately)

- **Decision-direction narrative output**: still deferred (needs LLM
  access + presentation design).
- **Sprint 6+ items** (skill grafts, cockpit UI, queued ensembles):
  not built; see §7.
- **Brier-score calibration**: context only; the method is
  ridge-to-prior per the approved enrichment.
- **Firewalling debate/report/verification paths**: deliberately out
  of scope; verification must see outcomes.

## 9. Commits on this branch

- `c65ee08` — pure calibration package (firewall cutoff, ridge-to-prior
  estimator), shared bootstrap primitive, registry fitted-weights apply
- `4ec4fe6` — `calibration_fits` table (model + migration 0031,
  upgrade/downgrade verified on scratch SQLite)
- `3efc28f` — hindsight firewall in engine (decision_time on run
  creation, cutoff in claim reads, audit keys in summary determinism
  fragment)
- `ab9e6c6` — calibration service mixin + API routes (firewall audit,
  policy/rule-weight fits, apply, fit reads)
- `95ba4da` — tests (firewall/estimator/registry unit tests +
  calibration API tests); fix single-observation tail bootstrap
- `0f95e51` — pin decision_time in golden byte-identity test (cutoff
  enters input hash by design)
- (this report + `BACKLOG.md` update + `docs/sprint5/test-full.log` —
  final commit below)

Environment note: one full-suite run during this sprint failed 33
tests with `sqlite3.OperationalError: database or disk is full` —
`/tmp` (a 512M tmpfs) had filled with accumulated pytest scratch dirs
from prior runs. After removing the ephemeral `/tmp/pytest-of-root`
scratch dirs, the suite passed 963/963. No code change was involved;
the committed log is from the clean re-run.

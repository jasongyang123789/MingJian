# Sprint 10 — Calibration hardening (PRD delta D8, hardening)

Branch: `strategy-engine/sprint10-calibration-hardening`, from
`strategy-engine/sprint9-living-loop` (`32b93b8`). Nothing pushed.

This sprint implements the five hardening items from SPRINT5.md §7.5
item 5 and §6 limits, on top of the Sprint 5 calibration loop. The
headline fix is target centering for rule-weight fits: Sprint 5's
ridge-through-the-origin estimator let fitted weights absorb the
target level (the demo fit produced 32.70 / 21.44, then clipped to
[0, 2] at apply time). Centering moves the level into an unpenalized
intercept, so the weights carry deviations only. The other four items
are a durable current-weights record with explicit restore, scenario
children handling (include / exclude / family weighting), a
fit-quality gate against the prior-only baseline for both fit kinds,
and per-metric correlation diagnostics for policy fits. All five are
pure/deterministic, stdlib-only in the estimator, and exposed through
the existing calibration endpoints plus three new ones. No LLM call
was added anywhere in this sprint, and no behavior changed outside
the calibration package, the calibration mixin/models/routes, one new
table, and tests.

References (read-only, code-verified in the research record):

- Ridge-to-prior calibration: jasonrkeen US–Middle East withdrawal
  model (`src/backtesting.py`), the Sprint 5 reference. The
  centering, row-weight, and gate additions are new code in the same
  estimator module, verified against hand-computed closed forms.
- Existing machinery built on, not duplicated: the Sprint 5
  `calibration_fits` table and inputs-hash discipline, the rule
  registry's `calibration_weights` / `apply_fitted_weights`, the
  Sprint 2 template system, and the Sprint 4 bootstrap module
  (seeded resampling is reused, not re-implemented).

## 1. What was built

### 1. Intercept / target centering for rule-weight fits

`fit_ridge_to_prior` gained a sibling, `fit_centered_ridge_to_prior`
(`services/calibration/estimator.py`). Features and target are
centered on their (weighted) means, weights are fit on centered data
with ridge-to-prior on the weights, and the intercept is derived as
`y_mean - x_mean·β`. Centering is the DEFAULT for new rule-weight
fits; `center_target: false` on the request reproduces exact Sprint 5
behavior (see §4). Every fit records the centering mode, the
intercept value, and the means used (`centering.mode`,
`centering.target_mean`, `centering.feature_means`); the mode enters
the inputs hash.

LOO RMSE stays on the ORIGINAL scale: each held-out prediction is
re-centered through the refit's intercept, so it remains comparable
with the prior-only baseline and with Sprint 5 numbers. Bootstrap
refits re-center WITHIN each resample — centering is part of the fit,
not one-time preprocessing — via a shared `_fit_coefficients` path
used by both LOO and bootstrap. Rules that never matched still keep
their prior exactly: an all-zero column is still all-zero after
centering, and a constant non-zero column is absorbed by the
intercept and keeps its prior; both properties are tested.

Policy (location) fits are untouched by this item: the coefficient IS
the location there, so there is nothing to center. The report says
so, and no policy code path calls the centered estimator.

### 2. Persistent current-weights record

New table `calibration_weight_applications` (migration 0033, revises
0032): one row per rule-weight application — domain, weights JSON,
source fit id, `previous_weights` JSON, `supersedes_id` (self-FK to
the previous application for the same domain), `applied_at`.
Append-only, consistent with `calibration_fits` discipline. The
existing apply endpoint writes the record in the same transaction as
the fit-row application event. New endpoints:

- `GET /calibration/current-weights?domain_id=` — latest application
  for the domain (404 when none; 400 `unknown_domain`).
- `GET /calibration/weight-applications?domain_id=&limit&offset` —
  history, newest first.
- `POST /calibration/restore-weights` (200 — it writes zero rows) —
  EXPLICIT re-application of the latest persisted weights to the
  in-memory registry. Restore is never automatic: startup and
  registry `reload()` do not restore, so a restart still resets to
  1.0 until someone explicitly restores. The calibration worker is
  untouched; its periodic blend starts from whatever weights are
  current, including restored ones, exactly as it did with applied
  ones (Sprint 5 interaction, unchanged).

### 3. Scenario-children handling

Verified from the code before relying on it: scenario children are
the only runs that carry `parent_run_id` (`scenarios.py` sets
`parent_run_id=parent_run.id` at branch creation), while Monte Carlo
trials, robustness probes, and replays explicitly set it to `None`
(`distributions.py`) and are already excluded via `_is_derived_run`.
Nested branches (a branch of a branch) exist, so `family` is defined
by ROOT ancestor, found by walking the `parent_run_id` chain (a
dangling parent or a cycle stops the walk at the current run, which
then counts as its own root).

Request parameter `scenario_children` on BOTH fit kinds, three modes:

- `include` (DEFAULT — preserves Sprint 5 behavior): every eligible
  run, weight 1.0.
- `exclude`: runs with a `parent_run_id` are dropped; the excluded
  ids are recorded on the fit.
- `family`: each root-ancestor family contributes total weight 1,
  implemented as row weights (1 / family size, family size counted
  within the observation set) in weighted normal equations
  `(X'WX + λI)β = X'Wy + λ·prior`. Weights are derived from family
  sizes, deterministic ordering is preserved, and the mode, the
  excluded ids, and the per-run observation weights are recorded on
  the fit and enter the inputs hash.

Unknown modes are rejected loudly (422 via the `Literal` request
model). Scenario selection runs AFTER the eligible-run and
available-value filters, so family sizes count only runs that
actually contribute observations.

### 4. Fit-quality gate vs the prior-only baseline

The prior-only baseline is defined precisely: predictions made with
prior coefficients and NO fitting — rule weights: `ŷ = X·prior`;
policy thresholds: the prior threshold constant for every
observation. Because the baseline is not fitted, its LOO error equals
its in-sample error, so the gate compares fitted LOO RMSE against the
baseline RMSE on the same observations with no adjustment needed
(`prior_only_rmse` in the estimator). Gate verdicts and both RMSE
numbers are recorded on every fit, including passing ones, and gate
settings enter the inputs hash.

- Rule-weight fits: WHOLE-FIT gate, ON by default
  (`quality_gate: true`). If fitted LOO RMSE is worse than the
  prior-only RMSE, the request is refused with 400 and stable code
  `fit_quality_gate_failed`, the message carrying both numbers to 4
  decimals, and NOTHING is written (no fit row — the house gate
  discipline). Explicit opt-out (`quality_gate: false`) is recorded
  on the fit. The gate is not evaluated when LOO is undefined
  (fewer than 3 observations); that is recorded as
  `quality_gate.reason: loo_undefined_below_3_observations`.
- Policy fits: PER-METRIC gate (metrics have different scales;
  averaging RMSEs across metrics is meaningless). Per metric, fitted
  LOO RMSE vs prior-only RMSE; a metric whose fitted LOO is worse
  keeps its priors with `unchanged_reason: quality_gate`, the
  rejected fit AND both RMSE numbers recorded on the change — the
  same pattern as the existing `ordering_guard`. `unchanged_reason`
  priority is ordering_guard > quality_gate (defensive code; in
  practice the two triggers conflict, and the priority itself is
  untested — see §6). A fit in which the gate leaves ZERO metrics
  changed does NOT create a misleading "(calibrated)" template
  version: the fit is recorded with `calibrated_template_id` null,
  `version_created: false`, and
  `version_created_reason: quality_gate_left_no_metric_changed`.
  Metrics with insufficient observations keep Sprint 5 behavior (the
  version is still created); the suppression condition is exactly:
  gate enabled AND at least one metric evaluated AND all evaluated
  metrics failed AND no metric changed.

The Sprint 5 demo fixture PASSES the new gate under centering
(fitted LOO 11.50 vs prior-only 107.61), so no default was flipped
and no demo fixture had to be replaced. The one existing estimator
test whose fixture genuinely trips the policy gate was updated to
opt out explicitly; see §4.

### 5. Per-metric correlation diagnostics for policy fits

`pairwise_metric_correlations` computes pairwise Pearson r over
per-metric observation vectors (same runs, pairwise-complete
observations), recorded on the policy fit record with `n` per pair
and a deterministic metric ordering. `r` is null when n < 2 or a
vector has zero variance — never a fabricated 0. A
`correlation_warning` flag is set when |r| >= 0.8 with n >= 5; the
threshold is a documented choice, not a universal constant. Warnings
are recorded, never refusing — warnings don't refuse; gates refuse.
Diagnostics NEVER change fitted values: a joint multivariate fit is
a different estimator and is explicitly out of scope (see §2).

## 2. Design decisions

### Intercept prior semantics (read this before touching the code)

The intercept has NO prior and NO shrinkage. It is not a registry
quantity: the rule registry holds weights only, and the apply step
still applies weights only. The intercept carries the target level;
the weights carry deviations from it. Two consequences are
deliberate and tested:

- The intercept is DERIVED, not fitted: `intercept = y_mean -
  x_mean·β` after the weights are fit. It is recomputed in the
  mixin from the FINAL (clipped to [0, 2]) coefficients, so the
  recorded intercept and the recorded weights are mutually
  consistent: predictions `intercept + x·β_recorded` use the same
  coefficients the registry will hold. The estimator-level intercept
  (from unclipped coefficients) is superseded by the mixin-level
  one whenever clipping binds; when clipping does not bind, the two
  agree exactly.
- A constant non-zero column (a rule matching the same number of
  times on every run) is absorbed by the intercept and keeps its
  prior exactly, just as an all-zero column does. The Sprint 5 demo
  shows this: `corp.ship_momentum` matches once on every run, and
  its centered fitted weight is exactly 1.0.

### Gate semantics

The gate compares LOO RMSE (fitted) against RMSE (prior-only) on the
same observations. "Worse" is strict: fitted LOO > prior-only RMSE
refuses; equal passes. For rule-weight fits the gate is whole-fit
because the weights are one joint fit; for policy fits it is
per-metric because each metric is an independent location fit and
the scales differ. A refused rule-weight fit writes no fit row at
all, so a refused fit leaves no audit residue beyond the 400
response; a gate-failed policy metric leaves its full record
(rejected fit + both RMSEs) on the stored fit, because the fit
itself is still a legitimate audit record. The asymmetry is
intentional: the rule-weight gate guards an applicable weight set,
the policy gate guards individual threshold changes.

### Scenario-mode semantics

`family` weighting is row weighting, not family aggregation: the
observations stay individual rows, each weighted 1 / family size.
The penalty term is deliberately NOT scaled by total weight, so
uniform weights reproduce the unweighted fit exactly (tested). The
family definition uses the root ancestor because nested branches
exist; a lone run is a family of one. Scenario selection happens
after value availability filtering, so a child with no usable value
does not dilute its family's weight.

### Why correlation is diagnostic-only

Sprint 5's threshold fits are per-metric independent location fits.
Modeling correlation would mean a joint multivariate estimator with
its own priors, shrinkage, and failure modes — a different sprint's
worth of design, and it would change fitted values in ways the
existing per-metric gates could not audit. The diagnostic records
the information a human needs to decide whether the independence
assumption is safe, without pretending the fits account for it.

### Correction to the task statement

The brief said "the Sprint 5 demo test asserts 32.70/21.44". No
existing test asserted those numbers: they appear only in the
SPRINT5.md report. The through-origin reproduction contract is now
pinned by a new test,
`test_rule_weight_fit_through_origin_reproduces_sprint5`, asserting
32.7011 / 21.4368 and LOO 45.3072 with `center_target: false`. The
correction is recorded here rather than silently absorbed.

### Registry singleton leak (found while testing)

The rule registry is a module-global singleton, so weights applied
by one test leak into later tests' fit priors in the same process.
The pre-existing apply test was already order-fragile in principle;
Sprint 10's value-pinning tests exposed it. The fix is test-side
only: a `_reset_registry_weights` helper posts
`/admin/rules/reload` at the start of each test that pins exact
fitted values, establishing the all-1.0 premise instead of relying
on file order. No production code changed for this. The full suite
passes in both default and reversed order for the affected tests.

## 3. Integration points

- Estimator (`services/calibration/estimator.py`): `sample_weights`
  on `fit_ridge_to_prior` / `ridge_location_fit` / LOO / bootstrap;
  `fit_centered_ridge_to_prior`; `prior_only_rmse`;
  `pairwise_metric_correlations` (+ `CORRELATION_WARNING_THRESHOLD`,
  `CORRELATION_WARNING_MIN_N`); `quality_gate` on
  `calibrate_policy_thresholds`; `center_target` / `sample_weights`
  on `calibrate_rule_weights`. `_worst_tail` was refactored to
  position-based `_worst_tail_positions` so weights stay aligned
  with tail positions; behavior is unchanged, including the
  worst-quartile fallback. Pure, stdlib-only, no I/O — unchanged
  discipline.
- Models (`services/calibration/models.py`): `ScenarioChildrenMode`
  literal; new request fields with Sprint 5 defaults preserved
  (`center_target=True`, `scenario_children="include"`,
  `quality_gate=True`); gate numbers on `ThresholdChange`;
  `PersistedWeightsRead` / `RestoreWeightsRequest`. All models
  `extra="forbid"`.
- Mixin (`services/simulation/calibration.py`): `_family_root_id` /
  `_scenario_selection`; scenario selection + weighted estimator
  calls + gate handling in both fit methods; `version_created`
  suppression; `apply_rule_weights` writes the durable record;
  `get_current_weights` / `list_weight_applications` /
  `restore_weights`. No `rules.py` change was needed: persistence
  and restore reuse `apply_fitted_weights` and the registry seam
  Sprint 5 already had.
- Routes (`api/routes/calibration.py`): three new endpoints with
  the Sprint 5 error mapping (CalibrationError → 400 dict detail,
  LookupError → 404). `POST /calibration/restore-weights` returns
  200 because it writes zero rows.
- Domain models + migration 0033: `CalibrationWeightApplicationRecord`
  / `calibration_weight_applications` (7 columns). No other table
  changed; fit records carry the new data in the existing `changes`
  JSON, so no `calibration_fits` migration was needed.
- inputs_hash coverage: centering mode, scenario mode, observation
  weights, excluded run ids, and gate setting are all folded into
  the hash for both fit kinds (verified by determinism tests: same
  inputs → same hash; the new parameters are part of the hashed
  payload).
- Cockpit: no change. See §7.

## 4. Verification

Test counts: backend 1125 → 1163 (38 new: 28 pure-estimator unit
tests in `tests/unit/test_calibration_hardening.py`, 10 API tests
in `tests/test_calibration_api.py`), 0 failed. Full log:
`docs/sprint10/test-full.log` (1163 passed in 331.32s). Frontend
untouched: 163 tests, lint, and build not re-run (no frontend file
changed).

Existing-test changes (2, both documented Sprint 5 style):

1. `test_policy_fit_decrease_direction_uses_upper_tail`
   (`test_ridge_estimator.py`): the fixture genuinely trips the new
   policy gate (fitted LOO 0.185 > prior-only 0.15), so the test now
   passes `quality_gate=False` explicitly — it tests tail selection,
   not the gate. The refusal itself is asserted by the new test
   `test_policy_gate_refuses_worse_than_prior`, including both
   numbers. The test was not weakened; its scope was narrowed to
   what it measures.
2. `test_rule_weight_fit_and_apply` (`test_calibration_api.py`):
   now resets the module-global registry at the start (see §2). No
   assertion changed.

`ruff format` was applied to `tests/test_calibration_api.py`, which
was already unformatted on the base branch; the reformat touches 6
pre-existing regions plus the new code. No other existing test was
modified.

Migration check: 0033 verified on scratch SQLite —
upgrade → downgrade to 0032 → re-upgrade, table present with 7
columns, revision chain correct.

Type/lint: `mypy src/planagent/` clean (194 files, no issues).
`ruff check` clean on all Sprint 10 files except the pre-approved
B008 `Depends()` pattern on the routes module. `ruff format --check`
clean on all new/changed files. Pre-existing findings left
untouched, verified present on the base branch: 35 findings in
`domain/models.py` (all before line 1500; the new model code is
after it, zero overlap), 2 C408 in `test_ridge_estimator.py`, 2
FURB162 in `test_calibration_api.py`.

Smoke: Sprint 0 smoke re-run PASS; the smoke evidence file was
reverted afterward, per Sprints 2–9 convention.

### Behavior evidence (centering)

Demo fixture (3 runs, 2 claims, cash 100/110/120; decision records
verified deterministic): design matrix X = [[1,1],[2,1],[2,1]]
(cost_pressure column [1,2,2], ship_momentum [1,1,1]), λ=5, priors
1.0. Hand-computed closed forms, asserted in
`test_rule_weight_fit_centered_values_hand_verified`:

- Centered (default): cost_pressure 45/17 ≈ 2.6471, ship_momentum
  exactly 1.0 (constant column absorbed by the intercept), intercept
  1778/17 ≈ 104.5882, centering mode `centered`, target_mean 110,
  feature_means [5/3, 1], LOO RMSE 11.4951, prior-only RMSE 107.6135,
  gate passed. The six never-matched rules are exactly 1.0.
- Through-origin (`center_target: false`): 32.7011 / 21.4368, LOO
  45.3072 — exact Sprint 5 reproduction. Centering cut the demo LOO
  from 45.31 to 11.50 and moved the level out of the weights.

### Behavior evidence (gate)

- Rule-weight refusal: an all-zero design (no claim matches) fits
  LOO 4.0825 against a prior-only RMSE of 0.0, so the default gate
  refuses with 400 `fit_quality_gate_failed`, the message carrying
  both numbers, and the fits list stays empty (zero rows). With
  `quality_gate: false` the same fit stores, recording
  `quality_gate.enabled: false` and reason `quality_gate_disabled`.
- Policy gate: a 3-metric fixture (cash / pipeline / sentiment)
  passes cash (fitted LOO 4.0825 < prior-only 45.8258) and refuses
  pipeline and sentiment (fitted 17.9412 > prior 0.15) with
  `unchanged_reason: quality_gate`, rejected fits, and both RMSEs
  recorded; the version is created because cash changed. A
  single-metric all-fail fixture records `calibrated_template_id:
  null`, `version_created: false`, reason
  `quality_gate_left_no_metric_changed`, and no new template row.

### Behavior evidence (scenario children)

Family fixture: parent (cash 80) + 2 children (90, 100) + lone run
(120), λ=1, prior 50. Hand-computed closed forms, asserted in
`test_policy_fit_scenario_children_modes` and the matching
rule-weight test:

- `include`: cash alert 100.0 (all four runs weight 1).
- `exclude`: cash alert 103.3333 (parent + lone only).
- `family`: cash alert exactly 100.0 — parent family weight 1/3 +
  1/3 + 1/3, lone weight 1; the family contributes total weight 1,
  as specified. The fit records all four source run ids and the
  per-run weights [1/3, 1/3, 1/3, 1]. (The include/family equality
  here is arithmetic coincidence: (80+90+100+120+50)/5 = 100 and
  ((80+90+100)/3 + 120 + 50)/3 = 100. The exclude value
  distinguishes the modes.)
- Rule-weight `family` mode on the same structure passes its gate
  and records the mode; `exclude` with a single remaining
  observation is refused with a message naming the mode and the
  exclusion count.

### Behavior evidence (correlations)

5-run fixture where pipeline finals are exactly cash/10 + 0.01:
cash/pipeline r = 1.0, n = 5, `correlation_warning: true`, and the
fitted thresholds are unchanged by the diagnostics (cash alert
550/6 ≈ 91.6667, pipeline alert 9.175 — the same values the fits
produce without the diagnostic code path). A single-metric fit
records `correlations.pairs: []`, warning false. The Pearson
implementation is verified against hand-computed r = 1, r = -1, and
r = 0 fixtures in the pure tests, including the n < 2 and
zero-variance null cases.

### Behavior evidence (persistence round-trip)

`test_apply_persists_weights_and_restore_round_trip`: apply →
current read shows the fit id, weights (cost_pressure 2.0, clipped),
previous weights all 1.0, `supersedes_id` null → second apply
supersedes (previous cost_pressure 2.0, history holds 2 rows,
newest first) → `reload()` resets priors to 1.0 → explicit restore
returns the latest record and priors show 2.0 again → history still
holds exactly 2 rows (restore wrote zero rows). Missing-domain
reads/restores 404; unknown domain 400 `unknown_domain`.

## 5. How to run / verify

New/changed request parameters (all validated; unknown modes/values
rejected loudly — note Pydantic coerces "yes"/"no"/"on"/"off" to
bool, so the validation tests use unparseable strings):

- `POST /calibration/rule-weight-fit`: `center_target` (default
  true), `scenario_children` (`include` | `exclude` | `family`,
  default `include`), `quality_gate` (default true).
- `POST /calibration/policy-fit`: `scenario_children` (default
  `include`), `quality_gate` (default true).
- `GET /calibration/current-weights?domain_id=`,
  `GET /calibration/weight-applications?domain_id=&limit&offset`,
  `POST /calibration/restore-weights` (`{domain_id}`).
- Fit records (`GET /calibration/fits[/{id}]`) now carry `centering`
  + `intercept` + `quality_gate` + `scenario_children` on
  rule-weight fits, and `version_created` +
  `version_created_reason` + `correlations` + `scenario_children`
  plus per-metric gate numbers on policy fits.

Reproduce the numbers: run the calibration suites with the
NO_PROXY workaround —
`env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest
tests/unit/test_ridge_estimator.py
tests/unit/test_calibration_hardening.py
tests/unit/test_rule_registry_fitted_weights.py
tests/test_calibration_api.py -q` (76 tests). Full suite:
`env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest -q`.

## 6. Known limits

- The intercept is recorded and reported, but it is NOT applied
  anywhere: the registry holds weights only, so a centered fit's
  level information does not change simulation behavior. The
  weights are the only applied quantity, as in Sprint 5.
- Fitted weights remain associative, not causal (Sprint 5 limit,
  unchanged). Centering removes the level confound but not others.
- The gate is not evaluated when LOO is undefined (fewer than 3
  observations); such fits store with the gate recorded as
  unevaluated, not as passed.
- `unchanged_reason` priority ordering_guard > quality_gate is
  defensive code; the priority itself has no test because the two
  triggers conflict in practice (the ordering guard fires when the
  fitted ordering inverts the prior ordering; the gate fires when
  the fit is worse than the prior — a fit can in principle trigger
  both, and the code prefers the ordering reason).
- Version suppression covers the gate only: a fit whose zero
  changes come from the ordering guard alone still creates a
  "(calibrated)" version, as in Sprint 5. Extending suppression to
  the ordering guard was out of scope.
- Family weighting models shared evidence as row weights only; it
  does not model within-family correlation beyond the total-weight-1
  allocation, and family sizes count only runs with usable values.
- Correlation diagnostics are pairwise and descriptive; no joint
  multivariate fit exists, and no threshold fit uses the
  correlations.
- The firewall still covers `_execute_run` claim reads only
  (Sprint 5 limit, unchanged). Restore is explicit only; there is
  no automatic restore on startup or reload, by design.
- The `quality_gate` opt-out on a rule-weight fit stores a fit that
  the gate would have refused; the opt-out is recorded on the fit,
  but nothing stops a later apply of such a fit. That is the
  explicit-override semantics, not an oversight.

## 7. Cockpit check

Verified, no UI change needed. The existing calibration surfaces
were checked against the new fit shapes:

- `CalibrationFitsView` (Cockpit) renders `unchanged_reason`
  verbatim when set, so a `quality_gate` reason displays as an
  explicit "unchanged: quality_gate" line rather than a successful
  calibration; it renders the calibrated-version line only when
  `calibrated_template_id` is non-null, so gate-suppressed fits
  show no version line. New `changes` keys (centering, gate,
  correlations, scenario_children, version_created) are not
  rendered — absent, not misleading.
- `VariableTemplates` provenance flags require
  `calibrated_template_id !== null` (`isCalibratedFit`), so a
  gate-suppressed fit can never flag a template as calibrated.
- No other cockpit surface reads calibration fits (verified by
  grep: only Cockpit and VariableTemplates reference the
  calibration API).

One drift note for a future sprint: the frontend `ThresholdChange`
type mirror does not declare the three new optional gate fields
(`fitted_loo_rmse`, `prior_only_rmse`, `quality_gate_passed`).
Harmless today — the view never accesses them — but a future
cockpit change that surfaces gate numbers should extend the type
first.

## 8. Deferred (out of scope, recorded deliberately)

- Joint multivariate threshold fitting (the correlation diagnostic
  is deliberately not a fit).
- Surfacing gate / intercept / correlation data in the cockpit
  (the check in §7 concluded the current UI does not mislead;
  richer display is a future enhancement, not a correction).
- Automatic restore of persisted weights on startup (rejected by
  design: silent behavior change).
- Ordering-guard version suppression (see §6).
- Everything still deferred from Sprints 5–9: decision-direction
  narrative output, template deletion, ensemble/analysis launch
  buttons, monitoring worker / scheduled evaluation (Sprint 9
  automation boundary unchanged: evaluate + record only).

## 9. Commits on this branch

- `791b254` — Sprint 10: centered ridge estimator, row weights,
  gate inputs, correlation diagnostics
- `0f8911f` — Sprint 10: persistent weights table, migration 0033,
  hardening request models
- `039ae44` — Sprint 10: wire hardening into calibration service +
  routes
- `4b0117e` — Sprint 10: API tests for centering, gate, scenario
  modes, correlations, persistence
- (this commit) — Sprint 10 report, backlog update, full-suite log

## 10. What was NOT verified

- Docker Compose stack (no container runtime on this VM) — as in
  all previous sprints.
- Live-LLM deliberation quality (Sprint 6 central open item) and
  real backend integration — untouched by this sprint, still
  unverified.
- The new endpoints against a real browser / the deployed cockpit:
  the cockpit check in §7 is a code-level verification of the
  existing components, not a live rendering test.

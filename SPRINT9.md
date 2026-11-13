# Sprint 9 — Living-strategy loop (monitor → re-simulate)

Branch: `strategy-engine/sprint9-living-loop` (from
`strategy-engine/sprint8-templates-charts` @ 57c4e46). Nothing pushed.

The loop closes the PwC "living strategy" circle on top of Sprints
1–5: monitor actuals → evaluate pre-registered triggers → re-simulate
with fresh evidence → compare distributions → record the review
decision. The loop record is the audit trail for a decision kept alive
over time. Nothing in the loop runs on a schedule: every evaluation,
re-simulation, comparison, and decision is an explicit API/UI action,
and a refused re-simulation writes zero rows.

## 1. What the existing code contributed vs what is new

The existing monitoring machinery turned out to be a *different*
loop: `WatchRule` / `SourceChangeRecord` / `PredictionVersion` plus
the prediction-revision worker form an LLM-driven prediction-revision
cycle (new source material → revised predictions), and the review
worker / strategic-watch worker serve the review queue and strategic
sessions. None of it re-runs a simulation, and none of it carries
numeric actuals. The loop therefore borrows *patterns* from the
existing code and builds its own entities — it does not reuse the
monitoring tables, and no worker was hooked:

- **Borrowed, not rebuilt:** the Sprint 4 gate discipline
  (pre-registration, append-only + explicit supersede,
  `gate_observed_value` / `apply_gate_operator` for gate statistics);
  the Sprint 5 firewall mechanics (`normalize_cutoff` /
  `format_cutoff`, `firewall_cutoff_from_configuration`, the rule
  that the cutoff enters the Sprint 3 input hash); the Sprint 3/4
  stored-fragment readers (`get_monte_carlo`,
  `_trial_values_for_ensemble`, `get_robustness`,
  `get_decision_gates`, `get_firewall_audit`); the Sprint 5 derived-run
  exclusion rule (MC trials, robustness probes, replays are not
  eligible baselines); the Sprint 2/4/5 migration discipline.
- **New:** three tables + migration 0032, a pure trigger-evaluation
  module, a pure comparison module, a service mixin, 11 API
  endpoints, and the `/cockpit/loops` UI.
- **Observation seam (a finding, not an assumption):** there is no
  numeric actuals-ingestion path anywhere in the codebase — `Claim`
  is textual (`subject`/`predicate`/`object_text`) and
  `UserDecision.outcome` is text. Observations are therefore recorded
  explicitly through the loop API (`field` + `value` + `observed_at`
  + optional claim link / note). No new ingestion path was invented,
  and no claim text is parsed into numbers.

## 2. Loop model + state machine

Three tables (`migrations/versions/0032_living_loop.py`, revises
0031; upgrade/downgrade verified on scratch SQLite — see §7):

- `strategy_loops`: id, name, baseline run id (FK), domain id,
  status, `triggers` JSON (the append-only registration list).
- `loop_observations`: id, loop id (FK), field, value, observed_at,
  optional source claim id (FK), source note. Append-only; there is
  no update or delete path.
- `loop_iterations`: id, loop id (FK), index (unique per loop),
  state, decision_time, previous_cutoff, window / trigger_evaluations
  / resimulation / comparison / decision JSON columns.

Iteration state machine, strictly forward:

```
open -> evaluated -> resimulated -> compared -> decided
          \___________________________^
```

A quiet round may be decided directly from `evaluated` (no
re-simulation needed); `decided` is terminal, and corrections happen
via a new iteration, never by editing a decided one. Only one
non-decided iteration may exist per loop. Every refusal names the
current state and the missing prerequisite (`loop_invalid_state`,
`loop_no_triggers`, `loop_iteration_in_progress`, ...).

`decision_time` must strictly advance past the previous evidence
cutoff (`loop_cutoff_must_advance`): iteration 0's previous cutoff is
the baseline run's firewall cutoff (None for pre-Sprint-5 runs, i.e.
unbounded below); later iterations inherit the previous iteration's
decision_time. The evaluation window is `(previous_cutoff,
decision_time]` on `observed_at` (lower exclusive, upper inclusive),
ordered by `observed_at` then id.

Loop creation requires a **completed primary run**: unknown runs 404,
non-completed runs refuse, and derived runs (MC trials, robustness
probes, replays) are excluded by the Sprint 5 rule.

## 3. Trigger semantics

Three trigger kinds, discriminated by `kind` (`services/living_loop/triggers.py`,
pure, deterministic, no I/O, no LLM):

- **threshold**: the latest observed value in the window breaches
  `field operator threshold`.
- **gate**: a Sprint 4 `GateDefinition` evaluated against the
  window's observed values via the same `gate_observed_value`
  statistic used on trial values. Paired metrics (`mean_delta`,
  `p_strategy_better`) are refused and the arm must be `baseline` —
  observations have no arms; `p_loss` requires `loss_threshold`.
- **deviation**: fires only when `consecutive` successive
  observations each deviate from the reference by more than
  `tolerance`. The reference defaults to the baseline run's
  final-state value for the field (missing → the whole evaluation
  fails loudly, `loop_trigger_evaluation_failed`); an explicit
  `reference_value` overrides it and is recorded as such. A single
  stray reading never fires it.

Outcomes carry `status`: `fired` / `quiet` / `no_data` (no
observations for the field in the window). Quiet and no-data rounds
are recorded, not skipped — they are evidence about the monitoring
itself (cf. Sprint 6's two-quiet-rounds stop).

Trigger registration is append-only with explicit supersede,
mirroring Sprint 4 gates. Each registration records
`observation_count_at_registration` as checkable pre-registration
evidence: a registration made before any observations existed is
genuinely pre-registered; one made later says so in the count.
Evaluation uses the latest `active` registration (else the latest
overall). Trigger fields must be state fields of the loop's domain;
unknown fields refuse at registration and at observation time.

## 4. Re-simulation + firewall-cutoff advancement

`POST .../resimulate` rebuilds the baseline's creation payload from
its stored configuration fragments (MECE decomposition, variable
template id + bindings, company/force identity from the profile rows,
initial state, market/theater, tick count, seed, tenant, preset) and
creates the new run through `create_simulation_run` — the same path
as a hand-created run, in `INLINE` mode. Consequences, all verified
by test:

- The MECE gate, variable gate, and firewall fragment engage
  exactly as for hand-created runs. A refused re-simulation (invalid
  bindings, unknown template id) returns the same codes
  (`mece_validation_failed` / `variable_validation_failed` /
  `variable_template_not_found`) and writes **zero rows**: creation
  happens before any iteration mutation, so the iteration stays
  `evaluated` and retryable.
- `decision_time` is the review time, so the firewall cutoff
  advances honestly. The input hash differs by design (the cutoff is
  part of the hashed inputs, per the Sprint 5 precedent) — the
  resimulation record stores **both** cutoffs and **both** input
  hashes, plus the claims-visible / claims-excluded counts from the
  new run's firewall audit, so the advancement is auditable rather
  than hidden.
- Explicit overrides (`variable_template_id`, `variable_set`, `seed`,
  `tick_count`, `note`) are the only way anything changes; every
  override is recorded in `changes`. A template override is resolved
  by id at re-simulation time (current template content), and the
  record stores both the baseline template snapshot hash and the
  resolved snapshot hash, so template drift between reviews is
  detectable. A malformed stored fragment fails loudly
  (`loop_corrupt_baseline_fragment`) rather than silently dropping a
  decomposition or bindings.
- The ensemble is run separately via the existing
  `POST /runs/{id}/monte-carlo` — the loop never runs ensembles
  implicitly, so the comparison step can honestly refuse when either
  side has no stored ensemble.

## 5. Comparison (stored vs stored)

`services/living_loop/comparison.py` is pure: it reads the two stored
ensembles and the stored Sprint 4 fragments, never recomputes or
overwrites the baseline's results.

- `compare_ensembles` requires the same metric and loss threshold on
  both sides. Per arm: P10/P50/P90/mean/loss-probability old vs new
  with deltas; paired mean-delta and p(strategy better) old vs new
  with changes. `seeds_paired` is true only with the same seed *and*
  trial count; when the cutoffs differ (the normal case — the review
  time is later than the baseline cutoff), the evidence caveat is
  attached: identical seeds pair the sampling draws but do not make
  the comparison a pure sampling comparison, because the evidence
  sets differ.
- Gate re-evaluation (`reevaluate_gates`) applies the baseline run's
  latest decision-gate registration to the new ensemble's trial
  values, purely — the new run's own audit trail is not mutated.
  `pre_registered` uses the Sprint 4 formula (registration predates
  the evaluated ensemble). Absent gates → `null`, not an empty claim.
- Threshold drift matches stored threshold-search results on both
  runs by (variable, mode) and reports old/new reachability and
  thresholds; unmatched searches are simply absent from the rows.

## 6. API + route map

`api/routes/loops.py` (router tag "Living Loop"), following the
Sprint 4/5 route patterns. `LoopError` → 400 `{"code", "message"}`;
unknown loop/run/iteration → 404; gate refusals from re-simulation
use the simulation route's dict-detail shapes (including the full
`validation` payload for MECE/variable failures):

| Method + path | Purpose |
|---|---|
| `POST /loops` | Create a loop from a completed primary run (optional initial triggers) |
| `GET /loops` | List loops (limit/offset) |
| `GET /loops/{id}` | Read one loop with its registrations |
| `GET /loops/{id}/timeline` | Full audit trail: loop + observations + iterations |
| `POST /loops/{id}/observations` | Record an observation (append-only) |
| `POST /loops/{id}/triggers` | Register a trigger set (append-only + supersede) |
| `POST /loops/{id}/iterations` | Open a review iteration (cutoff must advance) |
| `GET /loops/{id}/iterations/{iid}` | Read one iteration |
| `POST /loops/{id}/iterations/{iid}/evaluate` | Evaluate triggers against the window |
| `POST /loops/{id}/iterations/{iid}/resimulate` | Re-simulate through the creation path |
| `POST /loops/{id}/iterations/{iid}/compare` | Compare the two stored ensembles |
| `POST /loops/{id}/iterations/{iid}/decide` | Record the review decision (terminal) |

## 7. Cockpit UI

`/cockpit/loops` (new `CockpitNav` tab "活战略循环"), following the
Sprint 7/8 conventions: typed clients (`loopsApi` in `engine.ts`,
field-for-field mirrors in `engineTypes.ts`), `useApi`, `Card` /
`StatusBadge` / `EmptyState` / `ErrorBanner`, Chinese chrome,
Tailwind + lucide, `?loop=` URL sync.

- **Loop list + creation**: name + baseline-run picker
  (`RunPicker`) + optional initial triggers via `TriggerBuilder`.
- **Timeline**: trigger registrations (status + pre-registration
  evidence counts), trigger-set registration with an explicit
  supersede checkbox (default: supersede the active registration),
  observation recording + list, iterations.
- **Iteration cards**: state badge, window, trigger outcomes
  (fired/quiet/no-data), resimulation record (both cutoffs, both
  hashes, explicit changes, template-drift flag), comparison view
  (arm delta tables, paired stats, evidence caveat, gate
  re-evaluation, threshold drift), decision record. Actions match
  the state machine: evaluate → re-simulate (optional seed / tick
  count / note) → compare → decide (decision + required rationale);
  a quiet round can be decided from `evaluated`. Refusals surface
  the backend's structured code (e.g. `variable_validation_failed`).
- **Comparison histograms** reuse the Sprint 8 `EnsembleHistograms`
  components, with one discipline added: a histogram renders only
  when the run's *current* stored ensemble is the one the comparison
  references — a newer ensemble run later must not silently stand in
  for the compared one. Missing trial values render the honest empty
  state, never a synthesized distribution.
- **Start-iteration form** appears only when no iteration is open;
  otherwise the UI names the open iteration and the state it is in.

## 8. Verification

Backend: full suite **1125 passed, 0 failed** in 305.33s
(`env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest -q`;
concluding lines in `docs/sprint9/test-full.log`) — 1088 from
Sprint 8 plus the 37 new loop tests. Sprint 0 smoke re-run:
**PASS** (health → ingest → 4-tick simulation → decision trace →
workbench → options; the refreshed `smoke-evidence.json` was
reverted per the Sprint 2–6 precedent, keeping this branch's diff
to Sprint 9 work). `mypy` clean on the touched backend files and
`ruff` shows only the pre-existing B008 `Depends()` pattern in the
new route (same handling as Sprints 1–5); the new files are `ruff
format`-clean.

Frontend: 132 → 163 tests, all passing; `npm run lint` exits 0 with
zero errors/warnings; `npm run build` (`tsc -b && vite build`)
passes with only the pre-existing informational chunk-size warning.
New tests, all mocked fetch:

- `LoopViews.test.tsx` (23): trigger summaries, registration
  rendering incl. superseded status, observation list, fired/quiet/
  no-data outcomes, resimulation record incl. template-drift flag,
  comparison tables + caveat + ensemble-match discipline + gate
  re-evaluation / threshold drift, `TriggerBuilder` (three kinds,
  p_loss loss-threshold requirement, duplicate names, tolerance
  validation, supersede default/opt-out), `IterationCard` (decided
  has no actions, evaluate, re-simulate with overrides, decide with
  rationale, refused re-simulation surfacing its code, compare).
- `LivingLoop.test.tsx` (8): empty states, list + timeline
  selection, `?loop=` direct load, open-iteration blocking, loop
  creation, iteration start, trigger-set registration with
  supersede, observation recording.

Migration: upgrade to 0032, downgrade to 0031 (tables dropped),
re-upgrade — all on scratch SQLite, no errors.

Behavior evidence (from the backend API tests, stored data, no live
backend): the full walkthrough test runs baseline (cash triangular
60/100/140, cutoff 2026-01-01) → 3 observations (95/65/60) → all
three triggers fire (threshold latest 60 < 70; gate mean 73.33 < 90;
deviation 2 consecutive breaches of 20 from reference 100) →
re-simulation with new cutoff 2026-02-01, differing input hashes,
and the new run's firewall audit agreeing (cutoff source explicit)
→ paired comparison (same seed + trials, evidence caveat attached,
all deltas exactly 0 — same bindings, same seed, no new evidence,
which is the honest result) → recorded `continue` decision. The
quiet-round test decides from `evaluated` with no resimulation. The
refusal test proves an invalid-bindings re-simulation and an unknown
template id each return 400, write zero run rows, leave the iteration
`evaluated`, and leave it retryable.

## 9. Known limits

- Observations are recorded explicitly through the loop API; there
  is no automatic feed from ingested evidence (no numeric actuals
  path exists in the codebase — see §1). An observation's
  `source_claim_id` links it to a claim, but the value itself is
  supplied by the recorder, not extracted.
- The loop never runs ensembles itself: comparison requires both
  ensembles to exist already (the UI has no ensemble-launch button;
  that gap predates Sprint 9 and is still deferred).
- Re-simulation inherits the baseline's bindings verbatim unless the
  review names overrides; there is no UI for editing bindings at
  review time (the Sprint 8 template editor covers templates, not
  per-run binding overrides — `variable_set` override is API-only).
- Comparison is between the baseline run and the latest
  re-simulation of one iteration; multi-iteration trend views are not
  built. Gate re-evaluation covers only the baseline run's gates.
- Deviation triggers with the default reference need the baseline
  run's final-state value for the field; runs whose summary lacks it
  fail the whole evaluation loudly rather than partially.
- The UI's comparison histograms fetch the runs' *current* stored
  ensembles and refuse mismatches; if either ensemble was replaced,
  the histograms stay empty even though the comparison table (stored
  at compare time) still renders.
- No scheduled or worker-driven evaluation: reviews happen only
  when someone opens one. This is the designed automation boundary,
  not an oversight — see §10.

## 10. Automation boundary (designed, not deferred)

No background scheduler and no worker hook were added. The existing
workers (watch, prediction, review, calibration) were read first:
none fits "evaluate loop triggers and re-simulate" without inventing
silent run creation, and the task's boundary forbids exactly that.
If scheduled monitoring is wanted later, the honest shape is a
worker that only evaluates + records (never creates runs without a
recorded trigger firing and an explicit review) — that worker does
not exist yet, and adding it needs Ho's decision.

## 11. Unverified (stated plainly)

- Real scheduled monitoring: no scheduler exists (see §10), so
  there is nothing to verify; any future worker needs its own
  verification without the Docker stack.
- Live backend integration: no view has talked to a running backend
  (the `/api` proxy, auth refresh, and slow-deliberation timeouts
  remain unexercised, as in Sprints 7–8).
- Live-LLM paths: unchanged from Sprints 0–8 — no key on this VM,
  no real deliberation output ever seen. The loop itself adds no LLM
  calls, so this does not block loop verification.
- Docker Compose stack: no container runtime on this VM.
- The `window.confirm` / `beforeunload` dirty guard from Sprint 8
  remains unverified in a real browser (unchanged).

## 12. Deferred (not built)

- Calibration hardening (intercept/centering, weight persistence,
  scenario-run weighting, fit-quality gates) — still deferred, per
  the Sprint 9 task scope.
- Decision-direction narrative output (needs LLM key + presentation
  design).
- Template deletion, ensemble/analysis launch buttons in the
  cockpit.
- A monitoring worker / scheduled evaluation (see §10).

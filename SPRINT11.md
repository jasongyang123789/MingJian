# Sprint 11 — Monitoring worker (evaluate + record only)

Branch: `strategy-engine/sprint11-monitoring-worker`, from
`strategy-engine/sprint10-calibration-hardening` (`a1c22e7`).
Nothing pushed.

This sprint builds the worker SPRINT9.md §10 left as the honest
shape for scheduled monitoring — authorized by Ho on 2026-11-15
("监测 worker 继续都做好不用问我"). §10's boundary, quoted
verbatim:

> If scheduled monitoring is wanted later, the honest shape is a
> worker that only evaluates + records (never creates runs without
> a recorded trigger firing and an explicit review) — that worker
> does not exist yet, and adding it needs Ho's decision.

The worker now exists, and the boundary is enforced by
construction: a monitoring cycle's only writes are INSERTs into
one new table, `loop_evaluations`. It never creates simulation
runs or loop iterations, never transitions iteration state, and
never mutates loop or observation rows. A recorded trigger firing
plus an explicit review is still what starts a re-simulation.

## 1. What was built

### 1. The monitoring cycle

`SimulationLivingLoopMixin.run_monitoring_cycle` (the same code
path serves the scheduled worker and the on-demand endpoint, so
the two cannot drift): for every loop in deterministic order
(created_at, then id), it evaluates the loop's active trigger
registration against ALL recorded observations — the cumulative
monitor view, not a review window (see §2) — using the Sprint 9
pure `evaluate_triggers`, and records one `LoopEvaluationRecord`
row: cycle id, evaluated time, observation fingerprint,
registration id, observation ids, per-trigger outcomes (the Sprint
9 outcome shape, so monitoring results and review results read the
same way), and a loop-level summary (`fired` / `quiet` / `no_data`
/ `error`).

### 2. Fingerprint dedup

A cycle writes no new row for a loop whose latest evaluation
already carries the current fingerprint: the SHA-256 (Sprint 3
canonical JSON) of the sorted observation ids, the selected
registration id, and the canonical trigger definitions. A new
observation, a new registration, or a changed trigger set all
change the fingerprint; anything else leaves it alone. The cycle
result reports skipped loops with the existing row's id and
summary, so a skip is visible, not silent. Error rows dedup the
same way: the same inputs would fail the same way.

### 3. Recorded errors + per-loop isolation

A loop whose evaluation fails gets an error row, not silence:
missing deviation reference → `loop_trigger_evaluation_failed`
(the Sprint 9 failure, recorded instead of raised); unparseable
stored registrations → `loop_corrupt_registration`; missing
baseline run → `loop_baseline_missing`. Error rows carry the code
and message. One loop's failure never aborts the cycle: known
failures are recorded, unexpected exceptions are logged, reported
as public worker errors (no exception details), and skipped, and
the cycle commits the other loops' rows.

### 4. Endpoints

Two endpoints on the loops router, following the Sprint 9 route
patterns (`LoopError` → 400, unknown loop → 404):

- `POST /loops/monitoring/evaluate` — run one cycle on demand
  (200; returns the `MonitoringCycleResult`: counts, per-loop
  results, cycle errors). The same entry the worker uses, exposed
  for tests and manual runs.
- `GET /loops/{loop_id}/evaluations` — evaluation history for one
  loop, newest first (limit/offset, capped at 100).

### 5. The worker + schedule

`MonitoringWorker` (`workers/monitoring.py`) follows the
CalibrationWorker pattern: a thin `run_once()` over a database
session that calls the shared cycle method and returns a summary
dict. It is registered in `worker_cli` (`monitoring-worker`, the
11th worker in `list`) and gets a compose service
(`worker-monitoring`, `profiles: ["advanced"]`, following the
calibration worker). Scheduling is the existing `--loop`
mechanism; the interval default comes from a new setting,
`monitoring_worker_interval_seconds` (default 3600 — one hour,
deliberately conservative), overridable via
`PLANAGENT_MONITORING_WORKER_INTERVAL_SECONDS` or
`--interval-seconds`. `worker_cli` resolves an omitted
`--interval-seconds` to the worker's own default (5 seconds for
every existing worker, unchanged).

### 6. Cockpit display

The worker's output is visible in the cockpit instead of
API-only: a "监测评估" card on the loop timeline shows the
evaluation history (summary badge, evaluated time, observation
count, fingerprint, per-trigger outcomes via the existing
`TriggerOutcomes`, error code/message on failed rows) and a
"运行一次监测（全部循环）" button that runs one on-demand cycle
and shows its counts. Typed clients (`listEvaluations`,
`runMonitoringCycle`) and field-for-field type mirrors follow
the Sprint 7/8/9 conventions.

## 2. Design decisions

### Cumulative window, not a review window

A review iteration evaluates a bounded window
`(previous_cutoff, decision_time]` because a review owns one
slice of history. The worker reports the loop's *current* trigger
status, so it sees everything recorded so far: threshold triggers
read the latest observation overall, gate statistics see all
values, and deviation triggers see the full history their
consecutive-run semantics need. Observation order is
`observed_at` then id, the same deterministic order as Sprint 9
window selection. Consequence, stated plainly: gate statistics
over all history dilute recent movement — old values weigh
forever. The monitor reports cumulative status, not "what changed
since the last review"; change-since-last-review is the review
iteration's job.

### Fingerprint contents

Observation ids alone identify the set because observations are
append-only and immutable. The registration id plus the canonical
trigger definitions cover registration changes, including the
corrupt-registration case (the fingerprint covers the raw stored
JSON, so the error row still dedups). The baseline run id is not
in the fingerprint: a loop's baseline never changes.

### Summary rule

`fired` when any trigger fired; `no_data` when the loop has no
triggers, or when every trigger evaluated to `no_data` (nothing
was actually evaluated — observations for other fields do not
make a trigger quiet); `quiet` otherwise, i.e. at least one
trigger was evaluated and none fired. Error verdicts are set by
the caller: a failed evaluation has no outcomes to summarize.
The rule is a pure function, unit-tested without a database.

### One implementation for worker and endpoint

The worker constructs `SimulationService` (the same wiring
`_deps` uses) and calls the mixin method; the endpoint calls the
same method through the request's service. No duplicated cycle
logic, so the scheduled and on-demand paths cannot disagree
about the boundary.

### Loops with open iterations are still evaluated

Monitoring is independent of reviews: the cycle does not check
iteration state, because its output (trigger state) is input to
a review, not part of one. It also never touches the iteration.

## 3. Integration points

- Domain model + migration 0034 (`LoopEvaluationRecord` /
  `loop_evaluations`, 12 columns, revises 0033): id, loop id
  (FK), cycle id, evaluated_at, fingerprint, registration id,
  observation ids, outcomes, summary, error code/message,
  created_at. Indexes on loop id, cycle id, registration id,
  summary.
- Pure module `services/living_loop/monitoring.py`:
  `evaluation_fingerprint`, `select_registration` (same rule as
  the Sprint 9 iteration evaluation: latest active, else latest
  overall), `summarize_outcomes`. No I/O, no LLM.
- Models (`services/living_loop/models.py`): `LoopEvaluationRead`,
  `MonitoringCycleLoopResult`, `MonitoringCycleResult` (all
  `extra="forbid"`). Stored evaluation rows validate back into
  `LoopEvaluationRead`, so stored and served shapes cannot drift.
- Mixin (`services/simulation/living_loop.py`):
  `run_monitoring_cycle` (cycle id / evaluated time pinnable for
  deterministic tests), `list_loop_evaluations`,
  `_evaluate_loop_for_monitoring`. The cycle commits once; per-loop
  rows are flushed as evaluated.
- Routes (`api/routes/loops.py`): the two endpoints above. The
  module docstring's "no scheduler and no worker hook" line was
  updated: review actions remain explicit; monitoring evaluates +
  records on schedule.
- Worker (`workers/monitoring.py` + `worker_cli.py` registration
  + `config/base.py` setting + `docker-compose.yml` service).
- Cockpit: `EvaluationHistory` (`LoopViews.tsx`), monitoring card
  (`LivingLoop.tsx`), `loopsApi` additions (`engine.ts`), type
  mirrors (`engineTypes.ts`).
- No changes to the simulation engine, firewall, robustness,
  distributions, skills, or calibration packages. The Sprint 9
  iteration path is untouched: the worker reuses
  `evaluate_triggers` but never calls the iteration methods.

## 4. Verification

Test counts: backend 1163 → **1192 passed, 0 failed** in
342.35s (1163 from Sprint 10
plus 29 new: 12 pure-estimator unit tests in
`tests/unit/test_monitoring_evaluation.py`, 17 API/worker tests
in `tests/test_monitoring_api.py`). Full log:
`docs/sprint11/test-full.log`. Frontend: 163 → 169 tests (4
`EvaluationHistory` + 2 page tests), all passing; `npm run lint`
exits 0; `npm run build` passes with only the pre-existing
chunk-size warning.

Migration: 0034 verified on scratch SQLite — upgrade to head
(table present, 12 columns, 4 indexes), downgrade to 0033 (table
dropped), re-upgrade (table present, 12 columns), revision chain
correct.

Type/lint: `mypy` clean on the touched backend files. `ruff
check` clean except the pre-approved B008 `Depends()` pattern in
the routes module (14×, including the 2 new endpoints) and one
pre-existing BLE001 in `worker_cli.py` (untouched `except
Exception` in `run_worker`). `ruff format --check` clean on all
new/changed files. Pre-existing findings left untouched, verified
present on the base branch: 35 findings in `domain/models.py`
(all before line 1500; the new model code is after it).

Smoke: Sprint 0 smoke re-run PASS (health → ingest → 4-tick
simulation → decision trace → workbench → options; the refreshed
`smoke-evidence.json` was reverted per the Sprint 2–10 precedent,
keeping this branch's diff to Sprint 11 work).

Worker scheduling path: exercised end-to-end on scratch SQLite
(the tests cover `run_once`; this covers the `--loop` mechanism).
A scratch DB was seeded with one loop (threshold trigger cash <
70) and one observation (60.0); `python -m
planagent.worker_cli monitoring-worker --loop --interval-seconds
1` ran for ~5 seconds and printed 5 cycle lines: the first
`loops_evaluated` 1 / `loops_fired` 1, the next four
`loops_skipped` 1 / `loops_fired` 1. Afterward the DB held
exactly 1 evaluation row (summary `fired`), 1 run (the seeded
baseline), and 0 iterations — the boundary holds under the real
scheduler, and dedup holds across cycles.

### Behavior evidence (all asserted test values, with test names)

- Fired cycle (`test_cycle_evaluates_and_records_fired`):
  observations 95/65/60 → `loops_evaluated` 1, `loops_skipped` 0,
  `loops_fired` 1, `loops_errored` 0, `errors` []; the row's
  outcomes are cash-floor fired (latest 60.0), cash-mean fired
  (mean 220/3), cash-drift fired (max deviation 40.0, reference
  100.0, 2 consecutive breaches); observation ids in recorded
  order; fingerprint `sha256:`-prefixed; row cycle id equals the
  cycle result's.
- Dedup (`test_cycle_dedups_unchanged_inputs`): the second cycle
  reports `loops_evaluated` 0, `loops_skipped` 1, the same
  evaluation id, a different cycle id; history still holds 1 row.
- New inputs write new rows: a new observation
  (`test_cycle_records_a_new_row_when_observations_change`) and
  a new registration
  (`test_cycle_records_a_new_row_when_registration_changes`,
  cash-ceiling fired on 95 > 90) each produce a second row with
  the new registration id.
- Quiet/no-data
  (`test_cycle_records_quiet`,
  `test_cycle_records_no_data_without_triggers`,
  `test_cycle_records_no_data_without_observations`,
  `test_cycle_on_an_empty_fleet_writes_nothing`): 95/100/105
  stays quiet; no triggers → `no_data` with empty outcomes and
  null registration id; no observations → `no_data` with all 3
  outcomes `no_data`; an empty fleet cycles to all-zero counts
  with no rows.
- Errors + isolation
  (`test_cycle_records_error_and_isolates_loops`,
  `test_cycle_records_corrupt_registration_as_error`): a loop
  whose deviation trigger has no reference and whose baseline
  final state lacks the field records `error_code
  loop_trigger_evaluation_failed` (message naming `cash`) while
  the healthy loop in the same cycle records `fired`;
  `loops_evaluated` 2, `loops_fired` 1, `loops_errored` 1,
  `errors` []; the next cycle skips both. A corrupt stored
  registration records `loop_corrupt_registration` and dedups.
- Boundary
  (`test_cycle_creates_no_runs_or_iterations_and_mutates_nothing`):
  run count unchanged, the open iteration stays `open` with
  empty trigger evaluations and null resimulation, and the
  loop's triggers and `updated_at` are byte-identical after the
  cycle.
- History
  (`test_evaluation_history_paginates_newest_first`,
  `test_evaluation_history_404_for_unknown_loop`): 3 rows
  newest-first with observation counts [3, 2, 1] and 3 distinct
  cycle ids; limit/offset page correctly; unknown loop 404s.
- Worker (`test_worker_run_once_records_evaluations`,
  `test_worker_interval_comes_from_settings`,
  `test_monitoring_worker_is_listed`,
  `test_cycle_accepts_pinned_cycle_id_and_time`):
  `run_once` returns `loops_evaluated` 1 / `loops_fired` 1 and
  writes the row, then dedups on the second run;
  `default_interval_seconds` is 3600.0 by default and 60.0 with
  `PLANAGENT_MONITORING_WORKER_INTERVAL_SECONDS=60`; the worker
  is listed with empty consumes/produces; a pinned cycle id and
  evaluated time land on the result and the row.
- Pure rules (`tests/unit/test_monitoring_evaluation.py`):
  fingerprint stability, order-insensitivity, and sensitivity
  to the observation set / registration id / trigger
  definitions; registration selection (latest active, else
  latest overall, else none); the summary rule including the
  all-`no_data` case.

## 5. How to run / verify

- On demand: `POST /loops/monitoring/evaluate` (no body);
  history: `GET /loops/{loop_id}/evaluations?limit=&offset=`.
- Scheduled: `python -m planagent.worker_cli monitoring-worker
  --loop` (interval from
  `PLANAGENT_MONITORING_WORKER_INTERVAL_SECONDS`, default 3600;
  `--interval-seconds` overrides per run). One-shot:
  `python -m planagent.worker_cli monitoring-worker`.
  Compose: `worker-monitoring` service (`advanced` profile).
- Reproduce the numbers: run the monitoring suites with the
  NO_PROXY workaround —
  `env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest
  tests/unit/test_monitoring_evaluation.py
  tests/test_monitoring_api.py tests/test_loops_api.py -q`
  (41 tests). Full suite:
  `env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest -q`.

## 6. Known limits

- Observations are still recorded explicitly through the loop
  API; there is no automatic feed from ingested evidence (the
  Sprint 9 finding is unchanged). A loop with no observations
  can only ever report `no_data`.
- No alerting: a fired trigger is recorded in the database and
  shown in the cockpit, but nothing notifies anyone. The worker
  records; a human still has to look, or open a review.
- Poll-based scheduling: the worker re-scans on its interval
  (default one hour); a trigger firing is visible only at the
  next cycle, not the moment an observation lands. There is no
  event-driven evaluation on observation recording.
- Cumulative gate statistics dilute recent movement (see §2):
  the monitor reports status over all history, not change since
  the last review.
- A deviation trigger with a missing reference fails the whole
  loop's evaluation (all-or-nothing, the Sprint 9 rule) — the
  other triggers on that loop get no outcomes in that row.
- Evaluation rows are append-only with no retention policy;
  dedup bounds growth to input changes (one row per distinct
  observation-set + registration state), but a busy loop's
  history grows without bound.
- The cycle evaluates loops one by one in a single transaction;
  there is no batching or concurrency limit, and no per-cycle
  loop cap. Fleet sizes in the hundreds were not exercised.
- The `--loop` scheduling path was exercised on scratch SQLite
  (see §4), not under the Docker stack or against Postgres/Redis.

## 7. Cockpit check

Display was warranted: without UI work the worker's entire
output would have been API-only, invisible in the cockpit that
is the loop's audit surface. What was added (see §1.6): the
monitoring card with evaluation history and the on-demand
cycle button. What was checked and left alone:

- `IterationCard` and the review flow are untouched: monitoring
  evaluations render in their own card, never inside iteration
  cards, so a monitoring outcome cannot be mistaken for a review
  evaluation.
- `TriggerOutcomes` is reused verbatim for evaluation outcomes,
  so the two verdict displays cannot drift in wording.
- No other cockpit surface reads loop evaluations (verified by
  grep: only the loops page references the new API).

Frontend verification: 163 → 169 tests (mocked fetch), lint 0,
build passes. The new views were not rendered against a live
backend (see §10).

## 8. Deferred (out of scope, recorded deliberately)

- Alerting / notifications on fired triggers (the worker
  records; nothing pushes).
- Event-driven evaluation when an observation is recorded
  (the worker polls on its interval).
- Change-since-last-review evaluation windows for the worker
  (the cumulative window is the documented semantic; bounded
  windows belong to review iterations).
- Retention / pruning policy for evaluation rows.
- Everything still deferred from Sprints 5–10: decision-direction
  narrative output, template deletion, ensemble/analysis launch
  buttons, ordering-guard version suppression, joint multivariate
  threshold fitting, automatic weight restore.

## 9. Commits on this branch

- `4b8026c` — Sprint 11: loop_evaluations table + migration 0034
- `d3b8f0a` — Sprint 11: evaluation models + pure monitoring helpers
- `ca47145` — Sprint 11: monitoring cycle service + endpoints
- `3be5657` — Sprint 11: monitoring worker + CLI registration + schedule config
- `1816493` — Sprint 11: monitoring unit + API + worker tests
- `73dcad6` — Sprint 11: lint + format fixes on monitoring code
- `db093eb` — Sprint 11: cockpit monitoring evaluations + run-cycle action
- (this commit) — Sprint 11 report, backlog update, full-suite log

## 10. What was NOT verified

- Docker Compose stack (no container runtime on this VM) — as in
  all previous sprints. The `worker-monitoring` compose service
  is YAML-validated and pattern-identical to `worker-calibration`,
  but never started.
- Live-LLM deliberation quality (Sprint 6 central open item) and
  real backend integration — untouched by this sprint, still
  unverified.
- The new cockpit views against a real browser / the deployed
  cockpit: the frontend tests use mocked fetch, and the views
  were not rendered against a live backend.
- Postgres/Redis behavior of the worker: all worker verification
  ran on scratch SQLite + the in-memory event bus.

# Option B hardening — post-commit orphan cleanup + concurrent same-name handling

Closes the two runtime gaps left open in `OPTION-B.md` §6:

1. **Post-commit runner failure can orphan a branch.** If the
   branch runner failed AFTER its internal commit but before
   returning, the branch row survived while the outcome reported
   `failed`.
2. **Concurrent same-name requests were untested/unhandled.** Two
   simultaneous override calls naming the same direction could
   both pass the name check; the second insert then hit the
   unique constraint (a 500).

Branch: `strategy-engine/option-b-hardening`, base `4669016`.
Backend only. No behavior change to
grounding/validation/derivation/proposals/generation. No new
endpoints. No scheduler/worker hook (Sprint 9 boundary). No
schema change (no migration).

## 1. What was built

### The cleanup mechanism (`services/simulation/scenarios.py`)

No delete/remove path for runs or branches existed anywhere in
the simulation services, and no `ON DELETE` cascades exist in
`domain/models.py` — so the smallest safe cleanup had to be
built, with exact scope:

- `SimulationScenariosMixin.delete_scenario_branch(session,
  scenario_id) -> bool` deletes ONLY the named branch: its child
  run plus every row branch execution created for that child,
  in foreign-key order (the order is what keeps this valid on
  Postgres): `PredictionVersion` (via the run's series ids) →
  `PredictionSeries` → `Hypothesis` → `DecisionOption` →
  `PredictionCalibrationContext` → `GeneratedReport` →
  `StateSnapshotRecord` → `DecisionRecordRecord` →
  `ExternalShockRecord` → `GeoAssetRecord` → the
  `ScenarioBranchRecord` → the child `SimulationRun`. It then
  drops the branch id from the parent run's
  `scenario_branch_ids` summary list. The parent run itself is
  otherwise untouched. Returns `True` when a branch was
  deleted, `False` when no such branch exists (idempotent).
  The deletion commits, so it survives the caller's rollback.
- A refresh guard in `create_scenario_run`: the post-commit
  `session.refresh(branch)` is wrapped so a refresh failure
  best-effort deletes the committed branch (via
  `delete_scenario_branch`, using the local `scenario_id`) and
  then re-raises the original error. The guard's own failure
  never masks the refresh error.

Scope is exactly what `create_scenario_run` writes for a fresh
branch. Rows other flows may attach later (evidence links,
replay packages) are NOT deleted: if one blocks the deletion,
the failure surfaces and the branch survives for explicit human
cleanup. `EventArchive` rows and event-bus emissions are
append-only audit side effects and are deliberately left in
place.

### The port (`services/narratives/overrides.py`)

- `BranchCreationFailed` exception, carrying optional
  `branch_id`/`run_id`: raised by a runner when the branch may
  have committed but the creation could not be reported
  normally. `None` identities mean the runner could not
  determine them, and there is nothing safe to discard. Plain
  exceptions keep their existing meaning: nothing committed,
  the caller's rollback covers the failure.
- `BranchRunner.discard_branch(session, branch_id) -> bool`
  added to the port: the inverse of `create_branch`, for a
  post-commit failure or a direction that loses a same-name
  race. `_NoBranchRunner.discard_branch` returns `False`
  (nothing was ever created through it).

### The adapter (`api/routes/_deps.py`)

- `SimulationBranchRunner.create_branch` wraps result-building
  from the committed branch: any failure raises
  `BranchCreationFailed` with the committed identities,
  captured defensively via `_safe_branch_attr` (attribute
  access on a detached object can raise again; a missing
  identity is reported as `None`, never a new failure).
- `SimulationBranchRunner.discard_branch` delegates to
  `delete_scenario_branch`.

### The service (`services/narratives/service.py`)

- `override()` catches `BranchCreationFailed` before the
  generic handler: roll back, then best-effort discard the
  committed branch. The outcome is `failed` with a reason that
  states what happened: branch discarded; branch could not be
  discarded (names the id for explicit cleanup); or no identity
  reported (nothing could be discarded). A discard failure
  never masks the original error
  (`_discard_branch_best_effort` never raises).
- The store phase is now `_store_override_records`: a bounded
  retry loop (attempts ≤ staged directions + 1). Each pass
  re-reads the anchor's mappings, converts any direction whose
  name appeared meanwhile to `skipped` — discarding the branch
  created for it, before any `session.add`, so the discard's
  commit cannot prematurely commit a pending record — and
  stores the survivors. If flush/commit itself hits the
  mapping unique constraint, only that clash retries; any
  other integrity error is re-raised. Outcomes are built after
  the successful commit from re-read rows (with a fallback to
  the committed record's id if a concurrent delete removes the
  row between commit and re-read) and emitted in request
  order. The race-`skipped` reason names the concurrent
  creation and the discard result.
- `_is_mapping_unique_violation` matches only the
  direction-mapping name clash: the Postgres constraint name
  `uq_direction_mappings_anchor_name`, or (`direction_mappings`
  + `unique`) for the SQLite column message. It reads the
  driver error (`exc.orig`) when present, else the wrapped
  message.
- `DirectionOverrideOutcome` docstring updated
  (`services/narratives/models.py`, doc-only) for the
  race-`skipped` and post-commit-`failed` semantics.

### Tests

- New file `tests/test_direction_overrides_hardening.py`: 14
  tests (§4).
- The existing `ScriptedBranchRunner` double in
  `tests/test_direction_overrides_api.py` implements
  `discard_branch` (recording), and the existing partial-failure
  test now asserts `runner.discards == []`: a plain pre-commit
  failure discards nothing.

## 2. Design decisions

### A real cleanup, not record-only

The task required a real cleanup, and none existed: no
delete/remove path in the simulation services, no cascades.
Deleting only the `ScenarioBranchRecord` is impossible on
Postgres (`GeneratedReport.scenario_id` points at it), so the
cleanup removes the full fresh-branch row set in FK order.
Deleting by ORM `delete()` statements scoped to the child run
id (never raw SQL against unrelated rows) keeps the blast
radius to the one failed branch.

### The discard lives on the port, not behind a new import

The narratives service never imports the simulation service
(the port boundary from option B). `discard_branch` on
`BranchRunner` preserves that: the service asks the runner to
discard, the adapter delegates to the simulation service.

### `BranchCreationFailed` vs plain exceptions

The distinction is the commit boundary. A runner that raises
plainly promises nothing committed; a runner that raises
`BranchCreationFailed` reports a branch that may have
committed, with identities when known. The service treats the
two differently (rollback-only vs rollback + discard) and the
test double in the existing API tests proves the plain path
still discards nothing.

### Concurrency: check-then-insert, no locking — with evidence

The decision is to keep check-then-insert and let the unique
constraint arbitrate, with a bounded retry converting the
loser to `skipped`. Evidence it suffices:

- The choreographed concurrency test (§4, T7) fires two
  override calls with the same name through one gate so both
  pass the name check with no mapping visible, then both
  create real branches and race the store phase: exactly one
  `stored` + one `skipped`, 201, one mapping, one child run,
  one discard. No locking, no 500, no duplicates.
- The retry bound is airtight, not heuristic: names are unique
  within one request (the request model rejects duplicates),
  so a unique clash can only come from a concurrent commit,
  which the next pass's re-read sees — each retry settles at
  least one direction, so `len(staged) + 1` attempts always
  suffice. The exhausted-retries branch is unreachable and
  marked `pragma: no cover`.
- The matcher is narrow: only the mapping name clash retries.
  A foreign-key, not-null, or other-constraint integrity
  error surfaces unchanged (unit-tested with both driver
  message shapes, §4 T9).

Locking (advisory locks, `SELECT ... FOR UPDATE`) was not
needed and was not built. The propose/derive flows keep their
existing check-then-insert shape untouched.

### Discard ordering inside the store loop

Race discards run during the re-read pass, before any record
is added: `delete_scenario_branch` commits, and committing
while records are pending would prematurely commit them. The
loop structure guarantees nothing is pending at discard time.

### What was deliberately NOT built

- No locking (above).
- No new endpoint, no new response field: race losers reuse
  `skipped`, post-commit failures reuse `failed`; only reason
  text is extended.
- No background reaper for orphans: every discard is
  synchronous inside the failing/losing request. The only
  surviving orphans are the defined fallbacks (unknown
  identity, discard failure), each named in its outcome reason
  for explicit human cleanup.

## 3. Integration points

- `override()` staging loop: unchanged except the new
  `BranchCreationFailed` handler ahead of the generic handler.
- `override()` store phase: replaced by
  `_store_override_records` (same record shape, same
  `override_record` pins, same positions, same outcome shapes
  for the non-race cases — the 17 pre-existing API tests pass
  unchanged apart from the one added assertion).
- `create_scenario_run`: unchanged on the success path except
  the refresh guard; `delete_scenario_branch` is a new public
  method on the mixin, used only by the adapter (and the
  refresh guard) today.
- No migration, no config, no frontend change. The cockpit
  override-creation UI is a sibling track; nothing here
  depends on it.

## 4. Verification

### New tests: 14 passed

`tests/test_direction_overrides_hardening.py`, all green
(14 passed, 14.61s final re-run; 31 passed with the overrides
API file, 85.33s):

| # | Test | Behavior asserted |
|---|------|-------------------|
| T1 | `test_commit_then_raise_discards_branch_and_keeps_others` | Scripted runner commits a real INLINE branch then raises `BranchCreationFailed`: outcome `failed` with "after commit" + "was discarded" + branch id; the other direction `stored`; zero rows for the failed child across all 12 dependent tables; one branch row, 2 runs, parent summary scrubbed to the stored branch; discard called once |
| T2 | `test_commit_then_raise_without_identity_discards_nothing` | `BranchCreationFailed` with no identities: `failed`, reason states no identity was reported, zero discards, zero branches/mappings |
| T3 | `test_delete_scenario_branch_removes_branch_dependents_and_scrubs_parent` | Direct `delete_scenario_branch` on a real INLINE branch: all dependent counts 0, parent summary scrubbed, parent row + parent snapshots untouched; second delete `False`, missing id `False` |
| T4 | `test_adapter_converts_result_building_failure_with_identities` | Adapter converts a result-building failure to `BranchCreationFailed` with both identities captured |
| T5 | `test_adapter_reports_unknown_identities_when_branch_unreadable` | Fully unreadable branch object: `BranchCreationFailed` with `None` identities, no masking error |
| T6 | `test_adapter_discard_delegates_to_simulation_service` | `discard_branch` delegates and passes the boolean through |
| T7 | `test_create_scenario_run_refresh_failure_cleans_up` | Mocked `AsyncSession.refresh` raising only for `ScenarioBranchRecord`: the original error surfaces, zero branches, 1 run, parent summary clean |
| T8 | `test_concurrent_same_name_override_stores_once_and_skips_loser` | Choreographed concurrent same-name calls (WAL mode, shared gate): exactly one `stored` + one `skipped`, reason names the concurrent creation, one mapping, 2 runs, 1 branch, exactly one discard |
| T9 | `test_is_mapping_unique_violation` (5 params) | SQLite message → True; Postgres constraint message → True; FK / NOT NULL / other-constraint messages → False |
| T10 | `test_is_mapping_unique_violation_without_driver_error` | No `orig`: falls back to the wrapped message |

(T9 counts as 5 tests via parametrize; T1–T8 + T10 are 9
single tests: 14 total.)

Existing-test change: `test_override_partial_branch_failure_leaves_others_stored`
now also asserts `runner.discards == []` (plain failure
discards nothing). All 17 tests in
`test_direction_overrides_api.py` pass.

### Neighbor regression: 122 collected, all green after re-proof

Eight files, run with `TMPDIR=/dev/shm/pytest-tmp-optb-harden`
and the ≥200M pre-check:

| File | Tests |
|---|---|
| `test_direction_overrides_api.py` | 17 |
| `test_direction_overrides_hardening.py` | 14 |
| `test_direction_derivation_api.py` | 31 |
| `test_direction_proposals_api.py` | 25 |
| `test_narratives_api.py` | 15 |
| `test_distributions_api.py` | 12 |
| `test_phase2_simulation_api.py` | 6 |
| `test_phase3_military_api.py` | 2 |
| **Total** | **122** |

The first combined run reported 116 passed + 6 failed, all 6
in the phase2/phase3 files. Those 6 were environmental, not
regressions: the write-denial gate was flapping in the same
window (immediately afterward, fresh pytest invocations died
at startup with `No usable temporary directory found` across
all temp dirs, then recovered). Re-proof: the 5 named failures
re-ran 5/5 green, and both phase files re-ran fully green
(8/8). The 122-test union is therefore green; no test was
left failing. The full suite was NOT run (per task: neighbor
subsets only).

### Type + lint

- mypy on the 5 touched source files: `Success: no issues
  found`. Identical at base `4669016` (stash comparison).
- ruff on the 7 touched files: exactly 3 findings, all
  pre-existing in `src/planagent/api/routes/_deps.py` on
  untouched lines (1× `I001` import order, 2× `UP017`
  `datetime.UTC`), byte-identical multiset at base
  `4669016`. Zero new findings. (An intermediate mypy error
  from a reused variable name in the new code was fixed by
  renaming; the final state is clean.)

### Sprint 0 smoke: PASS

`.venv/bin/python docs/sprint0/smoke_e2e.py` → `SMOKE: PASS`
(exit 0; health 200, ingest 201, simulation 201, decision-trace
200, workbench 200, options 200). `docs/sprint0/smoke-evidence.json`
was reverted afterward (`git checkout`); the tree shows no
smoke residue.

## 5. How to run / verify

```bash
# New tests for this track
TMPDIR=/dev/shm/pytest-tmp-optb-harden env -u NO_PROXY -u no_proxy \
  .venv/bin/python -m pytest tests/test_direction_overrides_hardening.py -q

# Neighbor regression (8 files, 122 tests)
TMPDIR=/dev/shm/pytest-tmp-optb-harden env -u NO_PROXY -u no_proxy \
  .venv/bin/python -m pytest tests/test_direction_overrides_api.py \
  tests/test_direction_overrides_hardening.py \
  tests/test_direction_derivation_api.py tests/test_direction_proposals_api.py \
  tests/test_narratives_api.py tests/test_distributions_api.py \
  tests/test_phase2_simulation_api.py tests/test_phase3_military_api.py -q

# Type + lint (touched files)
.venv/bin/python -m mypy src/planagent/services/narratives/overrides.py \
  src/planagent/services/narratives/service.py \
  src/planagent/services/narratives/models.py \
  src/planagent/services/simulation/scenarios.py src/planagent/api/routes/_deps.py
.venv/bin/python -m ruff check <same files> tests/test_direction_overrides_api.py \
  tests/test_direction_overrides_hardening.py

# Smoke (Sprint 0, revert docs/sprint0/smoke-evidence.json afterward)
.venv/bin/python docs/sprint0/smoke_e2e.py
```

Before each pytest run, check `df -m /dev/shm` (≥200M free
required for this track's subsets) and never touch another
track's TMPDIR. The full suite was not run here; it needs the
partitioned-chunk gate (see `~/AGENTS.md`).

## 6. Known limits

- **No live Postgres proof.** The FK-ordered delete and the
  Postgres matcher message are reasoned + unit-tested (message
  strings only), never executed against Postgres. The
  Postgres migration drill folds into the hub re-run (parent
  track); this delete path is not covered by it.
- **WAL-only concurrency proof.** The race test runs on SQLite
  in WAL mode (rollback-journal SQLite would deadlock the
  choreography: a read transaction blocks the writer's
  commit). Postgres concurrency behavior is untested.
- **Fresh-branch scope.** `delete_scenario_branch` removes
  exactly what `create_scenario_run` writes for a fresh
  branch (single initial prediction versions, no superseding
  chains). Rows attached later by other flows (evidence
  links, replay packages) are not deleted; if one blocks the
  deletion, the branch survives for explicit human cleanup.
- **Audit leftovers by design.** `EventArchive` rows and
  event-bus emissions from a discarded branch are left in
  place (append-only audit trail, irreversible by design).
- **Defined fallbacks survive as orphans.** Unknown-identity
  post-commit failure (nothing safe to discard) and discard
  failure both leave the branch in place; each outcome reason
  names the branch id for explicit human cleanup. No
  background reaper exists.
- **Pre-existing collision-row window, unchanged.** If a
  mapping row is deleted between the upfront name check and
  the store pass, the collision lookup raises `KeyError`
  (identical in the base code). Not fixed here; the
  stored-row equivalent was fixed (fallback to the committed
  record id), but that fallback path itself has no dedicated
  test.
- **Unchanged from OPTION-B.md §6:** no cockpit UI (sibling
  track); domain gates beyond corporate untested at API level;
  formula-graph interplay untested; synchronous branch
  execution; midpoint fork default is a convention.

## 7. Cockpit check

None: backend only, no endpoint or response-shape change.
Reason text for `skipped`/`failed` outcomes is extended; the
cockpit renders reasons as text (unverified — no real-browser
check, same as the base track).

## 8. Deferred (out of scope, recorded deliberately)

- Postgres execution proof for the delete path + the race
  path (hub re-run scope, parent track).
- Locking for same-name races: proven unnecessary by T7 (§2).
- A background orphan reaper: rejected — every discard is
  synchronous; the defined fallbacks are explicit.
- The pre-existing collision-row-vanish window (§6).

## 9. Commits on this branch

- `a70248b` — Harden option B: discard post-commit orphan
  branches, resolve same-name races as skipped (implementation
  + 14 tests + 1 updated assertion)
- (this commit) — Option B hardening report

## 10. What was NOT verified

- The delete path or the race path against live Postgres
  (SQLite only; Postgres matcher message tested as a string).
- The full backend suite (neighbor subsets only, per task;
  the chunked gate belongs to the merge track).
- Real-browser rendering of any kind.
- Concurrency beyond two choreographed callers (no
  load/stress test, no >2-way race).
- The stored-row concurrent-delete fallback path (defensive
  code, no dedicated test).
- The refresh guard against a real database failure (tested
  with a mocked `refresh` raising only for branch rows).
- Live-LLM behavior: none is involved in this track (no LLM
  touchpoint added).
- Domain gates beyond corporate, and formula-graph interplay
  (§6, unchanged from the base track).

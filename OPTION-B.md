# Option B — Directions as variable overrides

Branch: `strategy-engine/option-b-variable-overrides`, from Sprint 20 tip
`23aafb7` (branch `strategy-engine/sprint20-cockpit-seminar`, the tip when
this build started; the tip moved to `8c1b00f` during the build on a
BACKLOG-only merge — this branch touches no BACKLOG.md, so the merge is
clean). Ho resolved the order question 2026-11-18 ("全都做好"): option C
was built and merged first, option B follows it.

A fourth direction source alongside explicit definitions (Sprint 13),
rule derivation (Sprint 14), and LLM proposals (option C): a direction
names fixed-value overrides for variables bound on the anchor run, and
applying it creates a NEW simulation run — a scenario branch of the
anchor — whose variable bindings carry the overrides. The direction is
stored as an `active` mapping pointing at the child run, with the
override spec pinned in an `override_record`. Overriding is explicit
only — no background auto-creation, no scheduler or worker hook, no
auto-trigger from generation, derivation, or proposals (the Sprint 9
automation boundary).

## 1. What was built

### Overrides (`services/narratives/overrides.py`, new, pure + port)

- `build_override_set(anchor_bindings, overrides)`: each overridden
  variable keeps the anchor's bound definition (unit, evidence,
  description, scope tags) with its distribution replaced by `fixed`
  at the override value. An override id not bound on the anchor
  refuses with `direction_override_unknown_variable`, naming the
  valid ids. No range check against the original distribution:
  setting a value outside the sampled range is the point of a
  what-if.
- `validate_merged_overrides(anchor_bindings, override_set,
  root_scope)`: merges with the Sprint 3 branch semantics
  (`merge_variable_sets`: override wins per id) and gates the
  merged set with `validate_variable_set` plus the
  decomposition-root scope cross-check when the anchor carries a
  tree. Failures raise `direction_override_invalid` naming the
  issues, before any run is created.
- `assumption_line(name, overrides)`: one deterministic assumption
  line per direction (override ids in sorted order), carried onto
  the branch record as its audit trail.
- `BranchRunner` port (`is_available()` + `create_branch()`),
  mirroring the `SkillLLMPort` pattern: the narratives service
  never imports the simulation service. `BranchRequest` carries
  the fork step, the merged variable set, and the assumption
  lines; `BranchResult` carries the branch id, child run id, and
  fork step.

### Persistence (`domain/models.py`, migration 0042)

- `DirectionMappingRecord.override_record`: nullable JSON pinning
  the override spec (variable id → fixed value), the scenario
  branch id, the fork step, and the `override_hash`. NULL on every
  non-override row. `origin` gains the `override` value.
- Migration `0042_direction_override_record` revises
  `0041_direction_proposal_status`, uses `batch_alter_table`, and
  downgrades by dropping the column. Drill on scratch SQLite:
  upgrade 0041→0042 (column appears; seeded row backfills
  `override_record` NULL) → downgrade to 0041 (column gone, row
  survives) → re-upgrade to head (backfill holds). See §4.

### Service (`services/narratives/service.py`, extended)

- `override(session, run_id, request)`: explicit trigger only.
  Order of operations, each refusing before the next starts:
  1. Anchor must exist (404) and be completed
     (`direction_requires_completed_run`).
  2. Domain branchability gates, mirroring scenario branching
     (`_check_override_domain`): military runs need a force,
     corporate runs need a company, other domains are unsupported
     (`direction_override_domain_unsupported`).
  3. The anchor must carry bound variables
     (`_read_anchor_bindings`, same fragment and discipline as
     `_read_anchor_variables`; absent fragments mean no bindings,
     malformed fragments are corrupt data). No bindings →
     `direction_override_requires_bindings`.
  4. The anchor's MECE tree is read (corrupt fragments refuse);
     every named MECE branch must exist on it
     (`direction_unknown_mece_branch`; branches with no tree →
     `direction_mece_branches_without_tree`).
  5. Whole-request grounding: for EVERY direction, the override
     set is built (unknown ids refuse), the merged set is
     validated, and a state snapshot must exist at the fork step
     (`direction_override_no_snapshot`). Any failure refuses the
     whole request with zero branches created.
  6. Runner availability is checked AFTER grounding validation
     and before any branch is created: a missing runner refuses
     the whole request with `direction_override_unavailable`
     (503 via the route), zero writes.
  7. Directions whose name already has a mapping are skipped
     (no-clobber): no branch run is created and the existing row
     is left untouched, whatever its origin or status.
  8. Each remaining direction creates one scenario branch via
     the configured runner. A branch failure is reported
     per-direction (`failed`, reason carried) and leaves the
     others unaffected; the failed direction's uncommitted work
     is rolled back so no orphan rows survive it.
  9. Stored directions are `active` mappings with origin
     `override`, `position` continuing the anchor's sequence,
     and the `override_record` pinned. The response names the
     monte-carlo endpoint for each child run: no ensemble is
     created eagerly (§2).
- `fork_step` defaults to the branch midpoint convention
  (`max(1, tick_count // 2)`), matching the scenario-branch
  default; an explicit `fork_step` is honored.
- Derive's no-clobber rule extends to override rows: derivation
  skips a name held by an `override` row (the row pins a
  human-authored spec and its child run; only an explicit human
  edit/delete may resolve it).
- `_mapping_to_read` carries `origin: "override"` and the
  `override_record` through to the read model.

### Endpoints (`api/routes/narratives.py`, extended) + wiring (`api/routes/_deps.py`)

- `POST /runs/{run_id}/directions/override` → 201 with
  `DirectionOverrideRead` (per-direction outcomes + the anchor's
  mappings). Error mapping follows the Sprint 9/11 pattern:
  `DirectionError` → 400 with `{"code", "message"}`
  (`direction_override_unavailable` → 503), `LookupError` → 404,
  malformed payloads → 422.
- `SimulationBranchRunner` in `_deps.py` adapts the port to
  `SimulationService.create_scenario_run`: the merged variable
  set becomes the branch's inline `variable_set` (the Sprint 3
  inline-merge semantics), and the assumption line is carried
  onto the branch record. Branch execution runs synchronously in
  INLINE mode, exactly as the scenario-branch endpoint does.
  Wired in `_cache_business_services` (where the simulation
  service is already cached) and in the `get_narrative_service`
  fallback. When no runner is wired, `_NoBranchRunner` reports
  unavailable and the endpoint 503s.

### Models (`services/narratives/models.py`, extended)

- `DirectionOverrideSpec`: `name` (1–120, stripped), `overrides`
  (`{variable_id: value}`, 1–100 entries, keys stripped, empty
  keys and post-strip collisions refused, values must be finite
  numbers — strings, booleans, NaN, and infinities refused with
  the variable-table discipline), `arm` (default `baseline`),
  `mece_branches` (stripped, deduped, blanks refused),
  `fork_step` (≥1, optional). Extra fields forbidden.
- `DirectionOverrideRequest`: 1–4 uniquely named specs
  (`MAX_DIRECTIONS`).
- `DirectionOverrideOutcome`: `stored` (mapping/branch/child ids,
  fork step, child status, next-step reason), `skipped`
  (name collision, no branch created), or `failed` (branch
  creation failed, reason carried, other directions unaffected).
- `DirectionOverrideRead`: anchor id, `override_hash` (SHA-256
  over the canonical request JSON — the same request always
  hashes the same), directions considered, outcomes, mappings.
- `DirectionMappingRead.origin` gains `"override"` and carries
  `override_record`.

### Frontend: none (API-first, deliberate — see §7)

No cockpit changes. The existing mappings endpoint already serves
override rows; no override composer or review UI was built.

## 2. Design decisions

### The Sprint 14 definition, and the interpretation (explicit)

SPRINT14.md records option B in exactly one line — "directions
that trigger new simulation runs" — and §8 names two open product
decisions: "override shape, who may create runs". Those decisions
were never recorded anywhere else in the repo. The following
interpretation is the minimal faithful reading; it is stated here
so a reviewer can disagree with the interpretation rather than
hunt for it:

1. **Override shape: fixed values only** — `{variable_id: value}`.
   The child run samples each named variable at exactly that
   value. The anchor's bound definition is otherwise preserved,
   so the override is a delta, not a redefinition. Full
   distribution surgery stays available via the scenario-branch
   endpoint, which accepts a whole `VariableSet`; option B's
   contract is the direction-level one: "what if X were V".
2. **Who may create runs: the explicit human caller**, and nobody
   else. No background creation, no auto-trigger, no separate
   permission layer: the endpoint follows the same access as the
   other directions endpoints, exactly as scenario branching
   does. If run-creation quotas or roles are wanted later, they
   belong in front of this endpoint, not inside the override
   semantics.
3. **Branch semantics: fork from a snapshot.** The child run
   forks from the anchor's state snapshot at `fork_step`
   (midpoint default) and runs the remaining ticks with the
   overridden bindings. Overrides apply from the fork point
   forward; pre-fork history is inherited. A fresh-from-tick-0
   re-simulation is a different primitive and is deliberately
   not built here.
4. **No eager ensemble.** Creating the run is the definition's
   whole job. A Monte Carlo ensemble is a separate explicit step
   with its own endpoint and trial cost; the response names the
   monte-carlo URL for each child run, and narrative generation
   refuses with the existing `narrative_requires_ensemble` until
   the ensemble exists.
5. **Grounding: stored bindings only.** Override ids must already
   be bound on the anchor (the option C discipline). An override
   naming an unbound variable refuses the whole request before
   any run is created. No range check: out-of-range values are
   legitimate what-ifs.
6. **Two failure classes, kept apart.** Grounding failures
   (unknown variable/branch, invalid merged set, missing
   snapshot, non-completed anchor) refuse the WHOLE request
   before any branch exists. Branch execution failures happen
   per direction, after grounding passed, and are reported
   per-direction without aborting the others. Availability
   (no runner wired) is a third class: it refuses the whole
   request as 503, checked after grounding so an invalid
   request still gets its 400.
7. **No-clobber, extended both ways.** Override skips ANY
   existing name (derived, authored, proposed, or override —
   the name check does not consult origin or status), and
   derive skips override rows. The override row is never
   silently rewritten by any automated path.
8. **Arm resampling is opt-in per direction**
   (`resample_variables`, fix/arm-resample). Default `false`:
   the child run starts from the anchor's fork-snapshot state,
   exactly as before — a sampled variable that names a state
   field keeps the forked value, so when every remaining driver
   variable is pinned FIXED the arm's Monte Carlo ensemble
   collapses to a degenerate point estimate (P10 = P50 = P90;
   the first backtest run measured this on all three cases) and
   `most_robust` duplicates `highest_p50`. With
   `resample_variables: true` on a direction, that direction's
   child re-draws its non-pinned variables from their own
   distributions, deterministically from the run seed, and the
   re-drawn values take precedence over the inherited fork state
   for exactly the state fields they cover; pinned FIXED
   overrides still sample at exactly their pinned value, and
   every other forked state field is unchanged. The flag is
   stored on the child's `scenario` fragment (and in the
   mapping's `override_record`), so Monte Carlo trials and
   replays of the child inherit it, and a re-fork inherits the
   stored setting unless its request states one explicitly.
   The same flag exists on `ScenarioRunCreate`, so the direct
   scenario-branch endpoint offers the same opt-in.

### Refuse, not flag

As in option C: an ungrounded override is a refusal, not a
warning carried alongside a created run. The one deliberate
exception is the per-direction `failed` outcome, which exists
because branch execution happens after grounding passed and a
mid-flight failure must not silently discard the directions
that already succeeded.

### What was deliberately NOT built

- Fresh-from-tick-0 re-simulation; distribution-level overrides.
- A cockpit override composer or review UI (API-first, as option C).
- Automatic ensemble creation after branching.
- A permission/quota layer for run creation.
- Override directions for non-branchable domains (the scenario
  branching gates are reused, not re-decided).
- Any change to generation: override rows are `active` mappings
  and flow through the existing resolution unchanged.

## 3. Integration points

- **Scenario branching (Sprint 3)** is the execution engine: the
  merged set travels as the branch's inline `variable_set`, the
  child run's variables fragment carries `branch_override: true`,
  and the assumption line lands on the branch record. No
  scenario-branch code was modified.
- **Direction mappings** are the storage: same table, same
  unique name constraint, same position ordering. Generation
  resolves `active` rows regardless of origin, so override
  directions need no generation change — proven end to end in
  §4.
- **Derivation** gains one skip rule (override rows); its rules,
  candidates, and family logic are untouched.
- **Proposals** are untouched: the accept/reject flow, the
  `proposed` status, and the prompt system do not intersect
  with override rows (which are `active` from birth, because a
  human authored the spec — there is nothing to review that the
  caller did not already state).
- **Migration chain**: 0042 revises 0041; the column is nullable
  with no backfill beyond NULL, so existing rows are unaffected.

## 4. Verification

### New tests: 36 passed (19 unit + 17 API)

- `tests/test_direction_overrides_unit.py`: 19 passed.
- `tests/test_direction_overrides_api.py`: 17 passed.
- Neighbor regression (untouched behavior around the change):
  `test_direction_derivation_api.py`,
  `test_direction_proposals_api.py`, `test_narratives_api.py`,
  `test_distributions_api.py` — 83 passed, 0 failed.

### Arm resampling (fix/arm-resample, 2026-11-19): 4 new tests, all passed

- `tests/test_arm_resample.py`: 4 passed — resampled arm
  ensemble non-degenerate (P10 < P50 < P90, 18 distinct trial
  values of 20) while the same-pin control arm stays degenerate
  (P10 = P50 = P90 = 0.1082, the backtest's Huawei B value);
  same-seed re-run reproduces identical trial values; pinned
  FIXED values land exactly (driver variable and state-field
  variable alike); `most_robust` selects the safe arm while
  `highest_p50` selects the risky arm on a crafted case.
- Neighbor regression for the flag plumbing (no behavior change
  at the default): `test_direction_overrides_api.py`,
  `test_direction_override_reforks_api.py`,
  `test_direction_overrides_hardening.py`,
  `test_direction_overrides_unit.py`, `test_distributions_api.py`,
  `test_tick_drivers.py`, `test_direction_derivation_api.py`,
  `unit/test_direction_derivation.py`,
  `test_trial_values_api.py`, `test_robustness_api.py`,
  `unit/test_replay_comparison.py`,
  `test_simulation_action_selection.py`,
  `test_s_layer_real_splits.py` — 204 passed, 0 failed.
  (Full suite left to the integration gate, per the task.)

### Full backend suite (the gate): 1976 passed, via 4 partitioned chunks

The 132 test files were partitioned in collection order into 4
contiguous chunks (37/33/31/31 files), each run to green
separately with a fresh `/dev/shm` TMPDIR. Logs at
`~/workspace/verification/option-b-2026-11-18/chunk-0{0..3}.log`:

| Chunk | Files | Result | Time |
|-------|-------|--------|------|
| 00 | 37 | 508 passed, exit 0 | 483.82s |
| 01 | 33 | 485 passed, exit 0 | 149.87s |
| 02 | 31 | 453 passed, exit 0 | 35.55s |
| 03 | 31 | 530 passed, exit 0 | 9.27s |
| **Total** | **132** | **1976 passed, 0 failed** | |

The chunk union equals the collect-only count (1976), so no test
was skipped or double-counted. The known order-dependent file
(`test_variable_templates_api.py`, in chunk 01) passed in-chunk.
Single-process full runs were not attempted: the ≥750M /dev/shm
gate failed at run time (647M free; a sibling track's live
TMPDIR held 147M) and the protocol is fail-closed — see §10.

### Behavior evidence (all asserted test values, with test names)

| # | Behavior | Test |
|---|----------|------|
| 1 | Override returns 201; midpoint fork_step 2 for tick_count 4; child COMPLETED; branch_count 1 | `test_override_creates_child_run_and_stores_active_mapping` |
| 2 | Stored mapping: origin `override`, status `active`, position 0, arm `baseline`, branches `["Demand"]`, `proposal_record` NULL, `user_edited` false | same |
| 3 | `override_record` pins `{cash: 80.0}`, branch id, fork_step 2, and the response `override_hash` | same |
| 4 | Child run's bindings carry cash `fixed` 80.0 with `branch_override: true`; branch assumptions carry the rendered line | same |
| 5 | Explicit fork_step 1 honored in outcome and record | `test_override_explicit_fork_step_is_honored` |
| 6 | Same request → same `override_hash`; second call skips; 1 mapping, branch_count stays 1 | `test_override_same_request_same_hash` |
| 7 | Unknown variable → 400 `direction_override_unknown_variable`; 0 mappings, branch_count 0 | `test_override_refuses_unknown_variable_and_creates_nothing` |
| 8 | Unknown MECE branch → 400 `direction_unknown_mece_branch`; 0/0 | `test_override_refuses_unknown_mece_branch_and_creates_nothing` |
| 9 | fork_step 99 → 400 `direction_override_no_snapshot`; 0/0 | `test_override_refuses_missing_snapshot_and_creates_nothing` |
| 10 | One bad direction refuses the valid one too, before any branch: 400, 0/0 | `test_override_refuses_one_bad_direction_before_any_branch` |
| 11 | QUEUED anchor → 400 `direction_requires_completed_run` | `test_override_refuses_noncompleted_anchor` |
| 12 | Anchor without bindings → 400 `direction_override_requires_bindings` | `test_override_refuses_anchor_without_bindings` |
| 13 | Unknown run → 404 | `test_override_unknown_run_404` |
| 14 | Empty directions, duplicate names, string value, empty overrides → 422 (×4); 0/0 | `test_override_rejects_invalid_payloads` |
| 15 | Name collision skips with no branch; record keeps the first value (80.0); branch_count stays 1 | `test_override_skips_existing_name_without_creating_branch` |
| 16 | User-edited row never overwritten; branch_count stays 0 | `test_override_never_overwrites_user_edited_mapping` |
| 17 | No runner wired → 503 `direction_override_unavailable`; 0/0 | `test_override_without_runner_returns_503_and_writes_nothing` |
| 18 | Scripted runner failing call 2 → outcomes `[stored, failed]`; 2 calls made; 1 mapping (`First`, `child-1`) | `test_override_partial_branch_failure_leaves_others_stored` |
| 19 | Derive skips the `highest_p50` outcome naming an override row; row kept (origin, arm, child run) | `test_derive_skips_override_direction` |
| 20 | Generate before ensemble → 400 `narrative_requires_ensemble`; after ensemble → 201 with the mapping id and the Demand trace (scope `[demand]`) | `test_override_then_ensemble_then_generate` |
| 21 | `build_override_set` replaces the distribution, keeps unit/evidence/description/scope; refuses unknown ids naming the valid ones; allows out-of-range 999 | `test_build_override_set_*` (3 tests) |
| 22 | Merged set: cash fixed 80, burn kept 20, internal kept; scope mismatch refuses naming `burn`; no tree skips the scope check | `test_validate_merged_overrides_*` (3 tests) |
| 23 | Assumption line deterministic and id-sorted | `test_assumption_line_is_deterministic_and_sorted` |
| 24 | Model validation: strip/dedupe, string/bool/NaN/inf rejected, int→float, empty/blank/collision/fork_step-0/extra/duplicate/0-and-5-direction cases refused, 4 directions accepted | `test_override_spec_*` / `test_override_request_*` (12 tests) |

### Type + lint

- `mypy` on the 7 touched source files: no issues.
- `ruff check` on the touched files: no new findings versus the
  base except one B008 for the new endpoint's `Depends(...)`
  default — the same pattern all 12 pre-existing endpoints in
  that file use. All other findings are pre-existing and
  unchanged in kind and count.
- `ruff format --check`: clean on all touched files except
  `domain/models.py`, whose format diffs are all pre-existing
  regions (seminar tables); the file was left unformatted
  rather than churned.

### Migration drill (scratch SQLite, §1)

Upgrade 0041→0042 (column appears, seeded row NULL, version at
head) → downgrade to 0041 (column gone, row survives) →
re-upgrade to head (column back, NULL holds). Drill DB removed
afterward.

### Sprint 0 smoke: PASS

`docs/sprint0/smoke_e2e.py` → `SMOKE: PASS` (exit 0); the
evidence file was reverted afterward.

## 5. How to run / verify

```bash
# New tests for this track
TMPDIR=/dev/shm/pytest-tmp-optb env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest \
  tests/test_direction_overrides_unit.py tests/test_direction_overrides_api.py -q

# Neighbor regression
TMPDIR=/dev/shm/pytest-tmp-optb env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest \
  tests/test_direction_derivation_api.py tests/test_direction_proposals_api.py \
  tests/test_narratives_api.py tests/test_distributions_api.py -q

# Chunked full gate (see §4): the 132 test files partitioned into
# /tmp/optb-chunk-00..03 in collection order; run each chunk to green
# with a fresh TMPDIR dir. Single-process full runs need the flock
# helper + the >=750M /dev/shm gate (see ~/AGENTS.md).

# Type + lint (new/changed files)
.venv/bin/python -m mypy src/planagent/services/narratives/overrides.py \
  src/planagent/services/narratives/models.py src/planagent/services/narratives/service.py \
  src/planagent/services/narratives/__init__.py src/planagent/api/routes/narratives.py \
  src/planagent/api/routes/_deps.py src/planagent/domain/models.py
.venv/bin/python -m ruff check src/planagent/services/narratives/ \
  src/planagent/api/routes/narratives.py src/planagent/api/routes/_deps.py \
  src/planagent/domain/models.py migrations/versions/0042_direction_override_record.py \
  tests/test_direction_overrides_api.py tests/test_direction_overrides_unit.py

# Migration drill on scratch SQLite (upgrade 0041→0042, downgrade, re-upgrade)
PLANAGENT_DATABASE_URL="sqlite+aiosqlite:////dev/shm/drill-0042.db" \
  .venv/bin/python -m alembic upgrade 0041_direction_proposal_status
# ... seed a direction_mappings row, then upgrade head / downgrade / upgrade head

# Smoke (Sprint 0, revert docs/sprint0/smoke-evidence.json afterward)
.venv/bin/python docs/sprint0/smoke_e2e.py

# 1. A completed run with bound variables and an MECE tree (see SPRINT3.md), then:
# 2. Override (creates one branch run per direction):
#    POST /runs/{id}/directions/override
#    {"directions": [{"name": "Boost cash", "overrides": {"cash": 80},
#                     "mece_branches": ["Demand"]}]}
# 3. Ensemble the child run, then generate from stored mappings (active only):
#    POST /runs/{child_run_id}/monte-carlo {"trials": 200, "metric": "cash"}
#    POST /runs/{id}/narratives {}
```

## 6. Known limits

- **No cockpit UI.** Override directions can only be created via
  the API. The cockpit directions view lists mappings through
  the existing endpoint, so override rows appear there with
  origin `override` — how `Directions.tsx` renders that origin
  is unverified (no real-browser check; the known proposal
  mislabeling gap is adjacent, not fixed here).
- **Post-commit runner failure can orphan a branch.** If the
  branch runner fails AFTER its internal commit but before
  returning (e.g. while building the result), the branch row
  survives while the outcome reports `failed`. The rollback in
  `override()` only covers uncommitted work. This shape was
  observed during development (an adapter bug raised after the
  branch committed); the adapter was fixed, but the residual
  window is inherent to the port boundary. Orphan branches are
  harmless scenario branches — visible in scenario-compare, not
  referenced by any mapping.
- **Concurrent same-name requests are untested.** Two simultaneous
  override calls naming the same direction can both pass the
  name check; the second insert then hits the unique constraint.
  This matches the existing propose/derive shape (check-then-
  insert, no locking) and is recorded, not fixed, here.
- **Domain gates beyond corporate are untested at the API level.**
  The military/other-domain branches mirror the scenario-branch
  gates line for line but were not exercised (only corporate
  runs exist in the API fixtures).
- **Formula-graph interplay is untested.** Overriding a variable
  that feeds a formula (including `tick_driver` formulas) passes
  the merged-set gate, but no test exercises a run whose
  bindings carry formulas alongside an override.
- **Synchronous branch execution.** Like the scenario-branch
  endpoint, branch runs execute inline in the request. Long
  branches block the response; no QUEUED mode is offered.
- **Midpoint fork default.** The default fork step is a
  convention, not an analysis: callers with a meaningful fork
  point should pass `fork_step` explicitly.

## 7. Cockpit check

Not applicable: no frontend changes (API-first, deliberate).
The mappings list endpoint already serves override rows; no
cockpit verification was run.

## 8. Deferred (out of scope, recorded deliberately)

- Cockpit override composer + review UI.
- Fresh-from-tick-0 re-simulation as a second override mode.
- Distribution-level overrides (replace a variable's whole
  distribution, not just its value).
- Run-creation quotas/roles in front of the endpoint.
- Optional auto-ensemble after branching.
- Serialization of concurrent same-name override requests.

## 9. Commits on this branch

- `3f4b33f` — Directions as variable overrides: overrides module +
  BranchRunner port, override-record migration 0042, service +
  endpoint + wiring adapter, 36 tests (19 unit + 17 API)
- (this commit) — Option B report

## 10. What was NOT verified

- The full backend suite in a SINGLE process. The gate ran
  chunked (§4): at run time the ≥750M /dev/shm gate failed
  (647M free; a sibling track's live TMPDIR held 147M), and the
  protocol is fail-closed. The chunk union covers all 1976
  collected tests in collection order; the known order-dependent
  file (`test_variable_templates_api`) sits in chunk 01 and its
  chunk result stands as recorded in §4.
- Real-browser rendering of any kind.
- The migration against Postgres (SQLite drill only).
- Concurrent override requests (§6).
- Domain gates beyond corporate, and formula-graph interplay (§6).
- Live-LLM behavior: none is involved in this track (no LLM
  touchpoint added).

# Cockpit override polish — variable-picker search + edit stored fixed values (re-fork)

Closes the two remaining limits recorded in COCKPIT-OVERRIDE-UI.md
§6: the override form's variable picker had no search (unusable at
100 bound variables), and stored override fixed values could not be
edited in place. Both are closed here; the second one by re-fork
semantics, not by rewriting the pinned record.

- Branch: `strategy-engine/cockpit-override-polish`, base `9ddc3c4`
- Date: 2026-11-18
- Scope: backend (one new endpoint, no migration) + frontend
  (picker search + inline re-fork form). No LLM anywhere.
- Status: implemented, tested, lint + build green, live-backend
  check green over real HTTP. NOT merged, NOT pushed. No
  real-browser check was available (§10).

## 1. What was built

### Feature A — variable-picker search (frontend only)

`components/cockpit/OverrideDirectionForm.tsx`, extended. Each
variable row in the override form now carries a draft-only `filter`
string and a "筛选变量" text input above its `<select>`. The visible
options are the bound variables whose id, description, unit, or
distribution summary contains the filter text as a
case-insensitive substring (`variableMatchesFilter`); the
currently selected variable always stays listed, so filtering
never orphans a picked value. An empty visible list shows "没有匹
配的变量，换个筛选词或清空筛选。" The definition/evidence display
for the picked variable is unchanged.

### Feature B — re-fork endpoint (backend)

`POST /runs/{run_id}/directions/mappings/{mapping_id}/refork`,
201. Request: `{overrides: {variable_id: fixed value}, fork_step?:
int}` (`DirectionOverrideReforkRequest`, extra=forbid, 1..100
overrides, `fork_step >= 1` when present). Response:
`DirectionOverrideReforkRead` — the updated mapping read plus
`branch_id`, `child_run_id`, `fork_step`, `child_status`,
`override_hash`, and a `reason` naming the monte-carlo next step
and stating the previous branch run was left untouched.

`services/narratives/service.py`: `refork_override_mapping`,
placed directly after `override()`. Order of operations:

1. Load the mapping via `_mapping_for_run` (404 when the id is
   unknown or belongs to another run).
2. Origin check: only `override` (`direction_mapping_not_override`,
   400). Status check: only `active`
   (`direction_mapping_not_active`, 409).
3. Anchor must be COMPLETED (`_completed_anchor`); grounding
   identical to option B, all BEFORE any branch is created:
   stored bindings only (`direction_override_requires_bindings`
   when the anchor has none), `build_override_set` +
   `validate_merged_overrides` against the MECE root scope
   (unknown variable → `direction_override_unknown_variable`,
   whole-request refusal, zero branches), snapshot must exist at
   the fork step.
4. Omitted `fork_step` defaults to the anchor midpoint
   (`max(1, tick_count // 2)`) — the same default as option B,
   NOT inherited from the old record (§2).
5. Runner availability (`direction_override_unavailable`, 503);
   then one new scenario-branch run via the Sprint 3 inline
   merge, with `assumption_line(mapping_name, overrides)`.
6. Post-commit failure reuses the hardening mechanism:
   `BranchCreationFailed` → rollback + `_discard_branch_best_effort`
   + `direction_override_refork_failed` naming the branch id and
   the discard outcome. A plain runner exception → rollback +
   the same named code. Nothing is left half-written.
7. Re-fetch the mapping row: if it vanished (concurrent delete
   between read and write), discard the new branch and raise
   `direction_mapping_deleted_concurrently` (409, new entry in
   `_DIRECTION_STATUS_CODES`) — a named error, never a 500.
8. Repoint the SAME mapping (same id, name, position):
   `source_run_id` + `override_record` `{overrides, branch_id,
   fork_step, override_hash}` + `user_edited=True`, commit,
   refresh, return. The OLD branch run and its rows are never
   touched: append-only history, no delete.

`services/narratives/models.py`: `_normalize_override_values`
factored out as the shared helper (identical behavior;
`DirectionOverrideSpec`'s validator now delegates to it), plus
the two new models. No migration: `override_record` is JSON.

`api/routes/narratives.py`: the route, plus the 409 status-code
entry. No other route touched.

### Feature B — inline re-fork form (frontend)

`pages/Directions.tsx`, extended. Stored-list rows with
`origin === 'override' && status === 'active'` get an "编辑固定
值" button. It opens an inline form (replacing the row view, the
same pattern as the existing rename form) prefilled with the
current fixed values (one input per pinned override, labeled
`{variableId} 的固定值`) and the current fork step, labeled "新分
叉步（留空用默认中点）". A note above the form states the
semantics: saving creates a new branch run and repoints the
mapping; the old branch run is kept untouched. Save validates
finite values and `fork_step >= 1` (client-side refusals, no
POST), omits the `fork_step` key when the input is blank, calls
`directionsApi.reforkMapping`, then reloads from the server and
closes the form. Refusal codes surface as text in the mapping
error banner and the form stays open; a 404 closes the form and
reloads (the row is gone). `api/engineTypes.ts` +
`api/engine.ts` gained `DirectionOverrideReforkRequest` /
`DirectionOverrideReforkRead` and `reforkMapping`.

The stored-list callback now computes `overrideRecord` once per
row (previously `parseOverrideRecord` was called inline for the
summary only); behavior unchanged.

## 2. Design decisions

### Edit = re-fork, never rewrite

A stored override mapping's fixed values are baked into its
branch run's bindings. Silently rewriting the pinned
`override_record` would lie about what the branch contains. So
"edit" creates a new branch with the new values and repoints the
same mapping at it; the old branch survives for audit and for
any narrative that already resolved the old child run. This is
the semantics the task forced, and the UI states it in the form
note rather than hiding it.

### Omitted fork_step = midpoint, not inheritance

When the fork-step input is left blank, the re-fork uses the
anchor midpoint — the same default option B uses for a fresh
override — even when the old record carries an explicit fork
step. Inheriting the old step silently would couple the new
branch to a choice the user is not seeing; the prefilled input
shows the old step, so keeping it is one non-action (leave the
value), while clearing it is an explicit "use the default".
Documented in the request model's docstring.

### Grounding refuses before branching, always

The unknown-variable, missing-bindings, missing-snapshot, and
wrong-origin/inactive checks all run before `create_branch` is
called. A refused re-fork creates zero branches, zero rows: the
unknown-variable test asserts `branch_count` stays 1 and the
live check asserts it stays 2 (§4).

### Concurrent delete is a named 409, not a 500

The mapping row is re-fetched after branch creation and before
the repoint write. If it is gone (or belongs to another anchor),
the new branch is discarded best-effort and the caller gets
`direction_mapping_deleted_concurrently` (409). The choreographed
test deletes the row mid-flight from inside a scripted runner
and asserts the 409, the discard, and the original branch's
survival.

### What was deliberately NOT built

- No in-place rewrite of `override_record` (forbidden by the
  semantics above).
- No search filter on any other picker; only the override form's
  variable selector, where 100 bound variables made it necessary.
- No range check on re-fork values (option B interpretation,
  OPTION-B.md §2: fixed values only, stored-bindings-only
  grounding, no range check).
- No migration, no new table, no worker/scheduler involvement.

## 3. Integration points

- Reuses option B wholesale: `build_override_set`,
  `validate_merged_overrides`, `_snapshot_exists`,
  `assumption_line`, `_completed_anchor`, `_read_anchor_bindings`,
  `_read_mece`, and the `BranchCreationFailed` /
  `_discard_branch_best_effort` hardening path. The re-fork
  differs from `override()` only in that it repoints an existing
  mapping instead of storing new ones.
- No-clobber preserved: the repoint writes exactly one row (the
  mapping named in the URL); the wrong-origin and
  another-run-404 tests assert other rows are untouched.
- Frontend reuses the existing review-queue error-banner pattern
  (`mappingError`, code + message) and the existing reload-from-
  server pattern (`reloadMappings()`).
- The `overrideSummaryText` / `parseOverrideRecord` display
  module is untouched; the re-fork form reads the same parsed
  record the summary reads.

## 4. Verification

All counts below are from runs on this branch, in the
`mingjian-override-polish` worktree (own `.venv`, editable
install, `planagent.__file__` verified inside the worktree).
pytest via `env -u NO_PROXY -u no_proxy .venv/bin/python -m
pytest`, TMPDIR `/dev/shm/pytest-tmp-polish` (removed after;
`/dev/shm` had 710M free at the first run).

### New backend tests: 26 passed

`tests/test_direction_override_reforks_api.py` (new file),
**26 passed in 36.02s, exit 0** (re-run on the final code after
the ruff fixes; the first run passed 26 in 31.89s). 10
model-validation cases (1 normalization + 9 parametrized
rejects) + 16 API tests:

- `test_refork_creates_new_branch_and_repoints_mapping` — happy
  path: 201; one mapping (same id, name, position); old child
  keeps `cash` fixed 80.0, new child fixed 90.0;
  `branch_count` 2; assumption line `Direction 'Boost cash':
  override cash=90.0.`; record `{overrides, branch_id,
  fork_step, override_hash}`.
- `test_refork_explicit_fork_step_is_honored` — fork_step 3
  stored and returned; omitted fork_step defaults to midpoint
  (2 of 4 ticks) in the happy-path test.
- `test_refork_refuses_unknown_variable_and_creates_nothing` —
  400 `direction_override_unknown_variable`, `branch_count`
  stays 1, zero new rows.
- `test_refork_refuses_missing_snapshot_and_creates_nothing` —
  fork_step beyond the stored snapshots refused, nothing
  created.
- `test_refork_refuses_wrong_origin` — authored mapping via
  ensemble + POST mappings → 400
  `direction_mapping_not_override`.
- `test_refork_refuses_inactive_mapping` — status flipped to
  `rejected` via direct DB → 409
  `direction_mapping_not_active`.
- `test_refork_refuses_noncompleted_anchor` — status flipped to
  QUEUED → named refusal.
- `test_refork_requires_bindings` — bindings fragment stripped
  via direct DB → `direction_override_requires_bindings`.
- `test_refork_unknown_mapping_404`,
  `test_refork_mapping_of_another_run_404` — both 404.
- `test_refork_rejects_invalid_payloads` — 422s (empty
  overrides, non-finite values, fork_step 0, extra keys).
- `test_refork_without_runner_returns_503_and_writes_nothing` —
  503 `direction_override_unavailable`, zero rows.
- `test_refork_post_commit_failure_discards_new_branch` —
  scripted runner raising `BranchCreationFailed` with a branch
  id: named failure, discard called with that id.
- `test_refork_post_commit_failure_without_identity_discards_nothing`
  — `BranchCreationFailed` with no id: named failure naming the
  manual-cleanup need, no discard attempted.
- `test_refork_plain_branch_failure_reports_named_error` —
  plain exception → rollback + named code, no 500.
- `test_refork_concurrent_delete_surfaces_conflict_and_discards_branch`
  — scripted runner deletes the mapping row mid-flight: 409
  `direction_mapping_deleted_concurrently`, discard called with
  the new branch id, mappings list empty, original branch
  survives.

### Neighbor backend subsets: 167 passed

One run, 10 files, **167 passed in 401.90s, exit 0**:
`test_direction_override_reforks_api.py` (26),
`test_direction_overrides_unit.py`,
`test_direction_overrides_api.py`,
`test_direction_overrides_hardening.py`,
`test_direction_derivation_api.py`,
`test_direction_proposals_api.py`, `test_narratives_api.py`,
`test_distributions_api.py`, `test_phase2_simulation_api.py`,
`test_phase3_military_api.py`. (The run started before the
ruff-only fixes below; the refork file was re-run on the final
code: 26 passed, exit 0. The fixes were a removed stale `noqa`,
a reformatted ternary, and two `next(...)` rewrites in test
code — no behavior change.)

### New frontend tests: 8 passed, Directions 40/40, full suite 319/319

`src/pages/Directions.test.tsx` extended (+8 tests). Touched
file: **40 passed, exit 0** (32 existing + 8 new). New:

- Filter: `filters the variable picker by typed text and
  restores all options when cleared`; `matches the picker
  filter against descriptions case-insensitively, and picking a
  filtered variable shows its definition` (filter `MONTHLY`
  matches `burn`'s description; picking it shows "Monthly burn"
  + evidence); `keeps the picker usable with 100 bound
  variables` (101 options unfiltered, 2 for filter `var-97`,
  101 again after clearing — option counts scoped with
  `within`).
- Re-fork: `reforks an override mapping with edited fixed
  values and reloads the stored list` (prefill 80 + fork step 2;
  posts `{overrides: {cash: 90}, fork_step: 2}` to the exact
  `/refork` URL; reloaded summary reads `变量覆盖：cash=90 ·
  分叉步 2`); `omits fork_step from the refork payload when the
  fork-step input is cleared`; `surfaces a refork refusal with
  its code and keeps the form open`
  (`direction_override_unknown_variable` + message shown, value
  input still present); `shows the edit-fixed-values action
  only on active override rows` (exactly 1 button across 6 rows
  of mixed origin/status); `refuses a non-finite refork value
  without posting` (zero posts).

Full frontend suite: **319 passed (32 files), exit 0** (311 at
base + 8 new). Lint: exit 0. Build: exit 0. The built bundle
(`dist/assets/index-*.js`) contains the `refork` call path and
the new labels `筛选变量` / `编辑固定值` (grep-verified).

### Ruff + mypy

- mypy on the 3 touched backend files: `Success: no issues
  found`, exit 0.
- Ruff on the 3 touched backend files + the new test file: 14
  findings, ALL `B008` in `routes/narratives.py`. Base
  (`9ddc3c4`, via stash comparison): 13 B008, all pre-existing.
  The 1 new B008 is the new endpoint's `Depends(...)` default —
  the same pattern all 13 pre-existing endpoints in that file
  use (option B added its B008 the same way). Zero new findings
  of any other kind: an initially flagged unused `noqa` in the
  new handler and two `RUF015` slices in the new test file were
  fixed, and the new test file is `ruff format`-clean. The
  remaining `ruff format` diffs in `service.py` are all in
  pre-existing regions (one hunk inside the new method was
  reformatted to match).
- Frontend: `npm run lint` exit 0 (eslint, no warnings shown).

### Sprint 0 smoke: PASS

`.venv/bin/python docs/sprint0/smoke_e2e.py` → `SMOKE: PASS`,
exit 0. Evidence file reverted (`git checkout --
docs/sprint0/smoke-evidence.json`); no diff remains.

### Live-backend check: 16/16 steps + review queue over real HTTP

Real uvicorn (`planagent.main:app`, port 8101) + fresh real
SQLite DB (`/dev/shm/live-polish.db`) + a driver script over
real HTTP (httpx, no proxy, no TestClient, no mocked fetch),
using the UI's exact request shapes. All steps passed, exit 0:

1. `GET /health` → 200. 2. `POST /simulation/runs` (variable
   set + passing MECE tree, 4 ticks, seed 7) → 201 COMPLETED.
3. `GET /runs/{id}/variables` → 200, `cash` bound. 4. `GET
   /runs/{id}/mece` → 200. 5. `POST
   /runs/{id}/directions/override` (UI shape, `fork_step`
   omitted) → 201, outcome `stored`. 6. `GET mappings` → 1 row,
   origin `override`, record `{cash: 80}`, fork_step 2
   (midpoint). 7. `POST .../mappings/{id}/refork` `{cash: 90,
   fork_step: 2}` → 201, same mapping id, new child run id, new
   branch id, record `{cash: 90}`. 8. `GET mappings` → still 1
   row, same id/name. 9. `GET scenario-compare` →
   `branch_count` 2. 10. Old child variables → `cash` fixed
   80.0 (append-only proof). 11. New child variables → `cash`
   fixed 90.0. 12. Re-fork with unknown variable → 400
   `direction_override_unknown_variable`. 13. `branch_count`
   still 2. 14. `POST /runs/{id}/monte-carlo` → 201 (ensemble
   for the authored row). 15. `POST mappings` (authored) → 201.
   16. Re-fork the authored row → 400
   `direction_mapping_not_override`.

Review queue over the same live server: two `proposed` rows
were seeded directly in SQLite (documented setup — the only
HTTP producer is the option-C propose endpoint, which requires
a live LLM; the seeded rows mirror exactly what the propose
service stores). `POST .../accept` → 200, status `active`;
`POST .../reject` → status `rejected`; a third seeded proposal
confirmed accept → 200 + `active`, and re-accept → 400
`direction_mapping_not_proposed`. Final GET showed all five
rows with the expected statuses.

Vite dev server (port 3000, `VITE_API_PROXY_TARGET` pointing
at the live uvicorn) served the page (200) and proxied
`/api/runs/{id}/directions/mappings` → 200 with all five rows:
the exact path the UI uses reaches the real backend.

Servers stopped and the live DB removed after the check.

## 5. How to run / verify

Backend (from the worktree root):

```sh
env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest \
  tests/test_direction_override_reforks_api.py -q
```

Frontend (from `frontend-v2/`): `npx vitest run
src/pages/Directions.test.tsx`; full suite `npx vitest run`;
`npm run lint`; `npm run build`.

Live check: start uvicorn with the smoke-script env pattern
(`PLANAGENT_DATABASE_URL` to a scratch SQLite file,
`PLANAGENT_EVENT_BUS_BACKEND=memory`, inline ingest/simulation
defaults on, empty LLM keys), then drive the endpoints in §4
over HTTP. No browser is available on this VM (§10).

## 6. Known limits

- No real-browser verification (§10): the filter and re-fork
  form are verified by jsdom tests + the live API check, not by
  driving the rendered page.
- The re-fork form edits only the pinned overrides: it cannot
  add a variable the mapping never pinned, or drop one. Adding
  a variable is a new override direction (the creation form),
  by design.
- No search filter on the variable picker of any other form.
- The concurrent-delete test choreographs the race with a
  scripted runner (same technique as the hardening tests); no
  multi-process race proof.
- The live-backend check used SQLite, not Postgres: the repoint
  is one row update + commit, but the FK-order and locking
  behavior on Postgres is unproven (same standing limit as the
  hardening track).
- The review-queue live check seeded proposed rows directly in
  SQLite (§4); the propose endpoint itself was not exercised
  live (needs an LLM).

## 7. Cockpit check

No real-browser check was possible (§10). The next-best
coverage, all recorded in §4: jsdom tests driving the actual
components (filter behavior, prefill, refusal surfacing, button
visibility), the production build succeeding, the built bundle
containing the new code paths, and the vite-dev proxy path to
the live backend returning real data.

## 8. Deferred (out of scope, recorded deliberately)

- Adding/dropping pinned variables from the re-fork form (new
  override direction covers it).
- A cockpit form for stored OEM production shares (S-layer
  follow-up, unrelated).
- Postgres proof of the repoint + discard paths (hub retry
  track owns live Postgres verification).
- Real-browser end-to-end drive of the Directions page (no
  browser automation path exists on this VM; §10).

## 9. Commits on this branch

- `ce776b1` — Variable-picker search + re-fork endpoint and
  inline form, 26 backend tests (10 model + 16 API) + 8
  frontend tests
- (this commit) — Override-polish report

## 10. What was NOT verified

- **Real browser: NOT run.** No browser automation path exists
  on this VM: no `chromium` / `google-chrome` / `firefox`
  binary, no `playwright` CLI or Python module, no
  `~/.cache/ms-playwright`, no camoufox cache, no puppeteer
  cache, empty global npm tree, nothing browser-like in
  `/usr/bin` (checked 2026-11-18). The Directions page was
  never driven in a real browser: no click-through of create
  override → search filter → edit → review accept was observed.
  Nothing in this report claims otherwise.
- **Live LLM proposal quality / propose endpoint live:** not
  run (no LLM in this track; proposed rows for the review
  check were seeded directly, §4).
- **Postgres:** the re-fork endpoint, the repoint write, and
  the discard path were proven on SQLite only (tests + live
  check). No live Postgres proof.
- **Full backend suite:** not run (neighbor subsets only, per
  the task; the chunked gate belongs to the merge track).
- **Multi-caller re-fork races:** only the single scripted
  concurrent-delete choreography; no >2-caller stress, no
  two-simultaneous-reforks-of-one-mapping proof.
- **The write-denial gate** did not strike during this track's
  runs; no run in §4 needed an environmental re-run.

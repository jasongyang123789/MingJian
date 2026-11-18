# Cockpit override-creation UI

Closes the "no cockpit UI" gap in OPTION-B.md §6: override
directions (option B) can now be created from the cockpit
directions view instead of only via the API.

- Branch: `strategy-engine/cockpit-override-ui`, base `4669016`
- Date: 2026-11-18
- Scope: FRONTEND ONLY. Zero backend/Python changes; the option B
  endpoint, service, and migration 0042 are untouched.
- Status: implemented, tested, lint + build green. NOT merged,
  NOT pushed. No real-browser check was available (§10).

## 1. What was built

### Override-creation form (`components/cockpit/OverrideDirectionForm.tsx`, new)

A self-contained Card on `/cockpit/directions`, below the derive
card and above the stored-mappings card. It fetches its own bound
variables for the anchor run (`GET /runs/{id}/variables`, via
`useApi` + the `nullOn404` pattern) and renders:

- A collapsed-by-default toggle ("新建变量覆盖方向"). Collapsing
  keeps the form's branch checkboxes and name inputs from colliding
  with the generate form's identical labels in existing tests.
- 1–4 override specs (backend `MAX_DIRECTIONS`), each with:
  direction-name input; arm selector (`baseline`/`strategy`);
  optional fork-step input, blank = backend midpoint default
  (the key is omitted from the payload, never sent null);
  one or more variable rows — a picker over the anchor's BOUND
  variables showing id + unit + current definition
  (`distributionSummary`: e.g. `cash · USD · normal(μ=10, σ=2)`),
  the chosen variable's description/evidence line underneath,
  and a fixed-value input per row. New rows default to the next
  unpicked bound variable; already-picked variables are disabled
  in the other rows' pickers. MECE-branch checkboxes come from
  the anchor's tree (branch names passed in as props).
- Client-side validation mirroring the backend contract
  (`DirectionOverrideSpec`/`DirectionOverrideRequest`): names
  stripped, non-empty, ≤120 chars, unique per request; ≥1
  override per spec; every row names a bound variable, no
  duplicates within a spec; values finite numbers (empty string
  rejected before `Number()`); fork_step blank or an integer
  ≥ 1. The first problem is shown in the page's single
  `ErrorBanner`; nothing is posted until the request is
  well-shaped. The backend still re-validates everything
  server-side, and its refusals surface with code + message.
- On submit: `POST /runs/{id}/directions/override`, then the
  per-direction outcomes from the response are rendered —
  stored → status label + verbatim reason (which carries the
  monte-carlo next step) + a structured child run / branch /
  fork step / child status line; skipped → collision reason;
  failed → reason — plus the directions-considered count and
  the request hash. Mappings are reloaded from the server
  afterward (`onMappingsChanged`). No auto-ensemble, no new
  polling, no background work.
- Honest states: while variables load, a spinner; on variables
  error, an `ErrorBanner` with retry; when the anchor has no
  bound variables, a plain message (no form, no disabled
  submit pretending otherwise) naming the backend refusal code
  `direction_override_requires_bindings`.

The component is mounted with `key={selectedRunId}` so switching
the anchor run remounts it: specs, outcomes, and errors never
leak across runs.

### Display module (`components/cockpit/directionMappingDisplay.ts`, new, pure)

- `ORIGIN_LABELS` / `STATUS_LABELS`: exhaustive maps over the
  backend's four origins (`derived`/`authored`/`llm_proposal`/
  `override` → 推导/手动/LLM 提案/变量覆盖) and three statuses
  (`active`/`proposed`/`rejected` → 可用/待评审/已拒绝).
  `originLabel`/`statusLabel` fall back to the raw value for
  unknown future literals — never to a wrong label — and to
  nothing when the value is missing.
- `parseOverrideRecord`: reads an `override` row's pinned record
  — fixed-value overrides (finite numbers only, variable-id
  order), `branch_id`, `fork_step`, `override_hash` — dropping
  malformed fields instead of rendering them raw. Returns null
  when the row carries no record.
- `overrideSummaryText`: the one-line summary for the stored
  list, e.g. `burn=20 · cash=80 · 分叉步 2`; null when nothing
  renderable is pinned, so no summary line shows at all.

This module deliberately does NOT parse proposal records: the
sibling proposal-review branch owns that surface (see §2).

### Types + API client (`api/engineTypes.ts`, `api/engine.ts`, extended)

- `DirectionMappingRead` fixed to the backend shape: `origin`
  widened from `'derived' | 'authored'` to all four literals
  (new `DirectionMappingOrigin` / `DirectionMappingStatus`
  types), plus `status`, `proposal_record`, `override_record`.
  This was the root cause of the stored-list mislabel (§2).
- New `DirectionOverrideSpec` / `DirectionOverrideRequest` /
  `DirectionOverrideOutcome` / `DirectionOverrideRead` types,
  mirroring `services/narratives/models.py` field for field
  (`fork_step` optional on the spec; outcome fields nullable
  exactly as the backend serves them).
- `directionsApi.createOverrides(runId, payload)` posts to
  `/runs/{id}/directions/override`.

### Directions view wiring (`pages/Directions.tsx`, extended)

- Renders the `<OverrideDirectionForm>` card (§1, first block).
- Stored list: the `derived ? 推导 : 手动` ternary is replaced by
  the origin + status label maps, and `override` rows show the
  one-line override summary (`变量覆盖：cash=80 · 分叉步 2`).
  The generate-from-stored counting is NOT changed (the sibling
  branch's adjacent fix; out of scope here — see §2).

### Fixtures (`test/engineFixtures.ts`, extended)

- The two existing mapping fixtures gain `status: 'active'` and
  null `proposal_record` / `override_record`.
- New `directionMappingProposed` (origin `llm_proposal`, status
  `proposed`, with a proposal record) and
  `directionMappingOverride` (origin `override`, override record
  `{overrides: {cash: 80}, branch_id: 'branch-1', fork_step: 2}`).

## 2. Design decisions

### The mislabel root cause, and the fix

At this base, `Directions.tsx` rendered every non-`derived`
mapping as 手动 — so LLM proposals and override rows both showed
as manual input. The root cause was the stale frontend type:
`DirectionMappingRead.origin` only allowed two literals, so the
page could not have distinguished the others even if it tried.
The fix is the type update plus exhaustive label maps with a
raw-value fallback: a future fifth origin renders as itself,
never as a wrong label.

### Sibling-branch overlap (expected, recorded)

The proposal-review branch (`strategy-engine/cockpit-proposal-review`,
merged as `1713ceb` on the main line AFTER this branch's base)
touched the same surface on its own branch: the same
`DirectionMappingRead` type fix, a `directionMappingDisplay`
module with the same label maps and override-record parsing
semantics, the same stored-list label fix, and the same fixture
updates — plus a proposal review queue this branch does not
build. This branch was built on base `4669016` only, so a later
merge of the two lines WILL conflict in `engineTypes.ts`,
`Directions.tsx`, `engineFixtures.ts`, and
`directionMappingDisplay.ts`. That is expected and fine: the
overlapping pieces were deliberately kept semantically identical
(label strings, record-parsing rules, fixture field values), so
the merge is a union — take either side's label/summary code,
keep this branch's form, keep the sibling's review queue. The
one deliberate asymmetry: this branch's display module has no
proposal-record parser; the merge takes the sibling's.

### What was deliberately NOT built

- No proposal-record parsing, no review queue (sibling scope).
- No change to generate-from-stored counting (sibling's
  adjacent fix; this branch's stored list shows all rows, and
  generation still counts all rows as before).
- No auto-ensemble after branching, no polling (option B
  semantics: the child run has no ensemble until someone
  explicitly runs monte-carlo on it; the outcome text says so).
- No range check on fixed values (option B interpretation:
  a fixed value may sit outside the original distribution —
  that is the point of a what-if; the form says so in its
  intro text).
- No fork-step upper-bound check against snapshot existence
  (the backend owns snapshot knowledge; the form validates
  ≥ 1 integer only and says the backend checks the rest).

## 3. Integration points

| Piece | Contract |
|---|---|
| `POST /runs/{id}/directions/override` | `DirectionOverrideRequest` (1–4 specs); 201 `DirectionOverrideRead` with per-direction outcomes + anchor mappings. Request/refusal shapes per `services/narratives/models.py` and `api/routes/narratives.py`. |
| `GET /runs/{id}/variables` | `VariableRunRead`; `bindings.variables` is the picker source. 404 (no variables fragment) → `nullOn404` → the no-bindings message. |
| `GET /runs/{id}/directions/mappings` | Reloaded after a successful override POST; override rows render with the summary line. |
| MECE branch names | Passed down from the page's existing tree load; the form adds no MECE fetch. |

No new backend endpoint, no new wiring, no migration.

## 4. Verification

All commands run personally in this worktree
(`~/workspace/mingjian-override-ui/frontend-v2`), Node v24.22.1,
`node_modules` inside the worktree. Logs:
`~/workspace/verification/override-ui-2026-11-18/`.

### Baseline (before changes, base `4669016`)

- Full vitest: **269 passed / 269**, exit 0 (95.85s).
- Lint: exit 0. Build: exit 0.

### New tests: 23 passed (10 unit + 13 page)

`directionMappingDisplay.test.ts` (10):

- `labels every backend origin exactly once, never as manual input`
- `labels every backend status`
- `falls back to the raw value for unknown values, and to nothing when missing`
- `reads overrides in variable-id order with branch, fork step, and hash`
- `returns null for a missing record`
- `drops malformed fields instead of rendering them raw`
- `treats a non-object overrides value as no overrides`
- `renders fixed values plus fork step on one line`
- `renders values alone when no fork step is pinned`
- `returns null when nothing renderable is pinned`

`Directions.test.tsx` (13; mock fetch extended with the variables
endpoint and an override POST handler that echoes specs into
stored outcomes and appends the new mappings, so reload
assertions are real):

- `shows the override form with bound variables and their current definitions`
- `creates an override direction, omits fork_step, and shows the stored outcome`
- `sends fork_step when provided`
- `creates two override directions in one request`
- `adds a variable row defaulting to the next unpicked bound variable`
- `refuses an empty direction name without posting`
- `refuses missing and non-finite fixed values without posting`
- `refuses duplicate direction names without posting`
- `refuses a fork_step below 1 without posting`
- `shows skipped and failed outcomes from the response`
- `surfaces an override refusal with its code and message`
- `labels every mapping origin and status, with an override summary`
- `shows an honest message when the anchor has no bound variables`

### Behavior evidence (asserted values, with test names)

- Payload shape: `{directions: [{name: 'Cash at 80', overrides:
  {cash: 80}, arm: 'baseline', mece_branches: ['Demand']}]}` with
  NO `fork_step` key when the input is blank; `fork_step: 2`
  when `2` is entered; two specs in one request keep their
  distinct names/overrides
  (`creates an override direction…`, `sends fork_step when
  provided`, `creates two override directions in one request`).
- Picker shows `cash · USD · normal(μ=10, σ=2)` and
  `burn · USD/mo · fixed = 20`, plus the chosen variable's
  description and `证据：finance-2026`
  (`shows the override form…`).
- Stored outcome renders `已存入`, the verbatim reason including
  `No ensemble yet: run POST /runs/run-child-1/monte-carlo`,
  the structured line `子 Run run-child-1 · 分支 branch-1 ·
  分叉步 1 · 状态 COMPLETED`, and after reload the stored-list
  summary `变量覆盖：cash=80 · 分叉步 1`
  (`creates an override direction…`).
- Skipped renders `已跳过` + the collision reason; failed
  renders `创建失败` + `Branch creation failed: boom`
  (`shows skipped and failed outcomes…`).
- Backend refusal renders `direction_override_unknown_variable`
  + `Valid variables: burn, cash`, with no outcome block
  (`surfaces an override refusal…`).
- Validation: empty name, missing value, `abc`, `Infinity`,
  duplicate names, fork_step `0` each show their specific
  message and post nothing (`posted` stays length 0)
  (`refuses an empty direction name…`,
  `refuses missing and non-finite fixed values…`,
  `refuses duplicate direction names…`,
  `refuses a fork_step below 1…`).
- Stored list: `推导 · 可用`, `手动 · 可用 · 已编辑`,
  `LLM 提案 · 待评审`, `变量覆盖 · 可用`, summary
  `变量覆盖：cash=80 · 分叉步 2`, and `手动` appears exactly
  once (`labels every mapping origin and status…`).
- No bindings: the no-bindings message shows and no toggle
  button exists (`shows an honest message…`).

### Full frontend suite (the gate): 292 passed

- Full vitest after changes: **292 passed / 292**, exit 0
  (108.76s) — 269 baseline + 23 new, zero regressions.
- Lint (`npm run lint`): exit 0.
- Build (`npm run build`, `tsc -b && vite build`): exit 0.
- No flakes observed in any run. The known chart-test 5s
  timeouts under load did not occur here.

### Iteration record (honest)

The first targeted run of the two touched files showed 32/34
passing with 2 failures, both ambiguous test assertions (a
regex matching two elements), not product bugs: `/run-child-1/`
matched the outcome `<li>` and its inner structured line, and
`/必须是 ≥ 1 的整数/` matched the help paragraph and the error
banner. Both assertions were tightened to unique text; no
product code changed. The re-run passed 34/34, and the full
gate then passed 292/292.

## 5. How to run / verify

```sh
cd frontend-v2
npm ci
npx vitest run src/components/cockpit/directionMappingDisplay.test.ts src/pages/Directions.test.tsx
npx vitest run
npm run lint
npm run build
```

## 6. Known limits

- **No real-browser check** (§10). Layout, focus order, and the
  collapsed/expanded interaction are asserted only through
  jsdom + Testing Library.
- **No live-backend check.** All page tests use mocked fetch;
  the payload contract was verified against the backend source
  (`models.py`, route), not against a running server.
- **Variable picker is a plain select.** At the 100-variable cap
  it is usable but has no search/filter; a long picker is a
  known rough edge, not a correctness issue.
- **Client validation shows the first problem only.** One
  `ErrorBanner`, matching the page pattern; the user fixes
  problems one at a time.
- **No editing of an override record after creation.** The
  existing mapping edit flow changes name/source only; changing
  a direction's fixed values means creating a new override
  direction (the old mapping stays, per the no-clobber rule).
- **Fork-step help is advisory.** The form cannot know which
  steps have snapshots; the backend refusal is the authority.
- **Sibling merge conflicts expected** (§2). The overlap is
  deliberate and semantically identical; the merge is a union.
- Backend-side limits from OPTION-B.md §6 are unchanged by this
  track: post-commit orphan window, concurrent same-name
  requests untested, Postgres migration drill not run,
  formula-graph interplay untested.

## 7. Cockpit check

The cockpit IS the change. Verified through vitest only (§4);
no real-browser rendering was available (§10).

## 8. Deferred (out of scope, recorded deliberately)

- Proposal-record parsing + review queue (sibling branch).
- Generate-from-stored active-only counting (sibling branch).
- Search/filter on the variable picker (worth doing if the
  100-variable cap makes the select painful in practice).
- Editing an override direction's fixed values in place.
- Bulk override import (e.g. paste a table of variable=value).

## 9. Commits on this branch

- `9f14c92` — Cockpit override-creation UI: override form, label
  maps, override summaries (implementation + 23 tests)
- (this commit) — Cockpit override-creation UI report

## 10. What was NOT verified

- Real-browser rendering of any kind (layout, focus, the
  expand/collapse interaction in a real browser).
- Behavior against a live backend (payload contract verified
  against backend source only; mocked fetch in all tests).
- The merge with the sibling proposal-review line (conflicts
  expected per §2; the union was reasoned about, not executed).
- Backend behavior of any kind (frontend-only track; the
  backend suite was not run — base `4669016` was already
  chunk-gate green at 2004 tests, and no backend file changed).
- Live-LLM behavior: none is involved in this track (no LLM
  touchpoint added).

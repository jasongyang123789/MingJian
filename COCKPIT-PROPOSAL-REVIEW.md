# Cockpit proposal-review UI + direction origin labels

Branch: `strategy-engine/cockpit-proposal-review`, from tip `4669016`
(branch `strategy-engine/sprint20-cockpit-seminar`). Ho ordered
2026-11-18 ("全都做好") closing two known Track B gaps: no cockpit
proposal-review UI, and `Directions.tsx` mislabeling LLM-proposed
direction rows as "手动" (manual).

Frontend work only — no backend/Python change, no new endpoint, no
change to generation/derivation behavior. The backend (option C,
merged) is the source of truth: proposals are stored mappings with
status `proposed` and origin `llm_proposal`, accept/reject move them
to `active`/`rejected`, and generation resolves `active` rows only.
The UI reflects that state; it never reinterprets it.

## 1. What was built

### The type fix (root cause of the mislabel)

`DirectionMappingRead` in `frontend-v2/src/api/engineTypes.ts` was
stale: `origin: 'derived' | 'authored'` with no `status`,
`proposal_record`, or `override_record` — the frontend type did not
even know proposals exist, so the view defaulted every non-derived
row to "手动". The type now matches the backend
`DirectionMappingRead` exactly:

- `origin: 'derived' | 'authored' | 'llm_proposal' | 'override'`
  (as `DirectionMappingOrigin`)
- `status: 'active' | 'proposed' | 'rejected'`
  (as `DirectionMappingStatus`)
- `proposal_record` / `override_record` as
  `Record<string, unknown> | null`

### Review queue (`src/pages/Directions.tsx`, "待评审提案" card)

Rendered whenever a run is selected, between the derive card and the
stored-mappings card. It lists only `status === 'proposed'` rows,
each with its grounding as served by the API:

- name, source run / arm, origin + status labels
- MECE branches the direction traces to
- key variables, rationale, model, template id/version, and
  proposal hash (shortened) from `proposal_record`
- explicit **接受** (accept) and **拒绝** (reject) actions wired to
  the existing endpoints
  (`POST /runs/{id}/directions/mappings/{id}/accept|reject`, no
  body). After either action the list reloads from the server
  (`reloadMappings`); the row leaves the queue because its status
  changed, and appears in the stored list under its new status.
  Reject uses the page's existing two-step confirmation (rejection
  is terminal per the backend: the row is retained for audit and
  can only be deleted afterward); accept is a single click.
  Review failures surface the backend's code + message (the accept
  path re-validates grounding server-side; a stale proposal stays
  queued with the refusal shown). A 404 reloads the list back to
  the truth, mirroring the delete handler. No auto-accept, no
  polling beyond the view's existing loads.

### Origin + status labels (every rendering site)

`src/components/cockpit/directionMappingDisplay.ts` (new, pure)
holds exhaustive label maps, used by both the queue and the stored
list — the only two places that render mapping origin/status
(verified by grep: `Directions.tsx` was the sole rendering site):

- origins: derived → 推导, authored → 手动, llm_proposal → LLM 提案,
  override → 变量覆盖
- statuses: active → 可用, proposed → 待评审, rejected → 已拒绝

The maps are `Record<Origin, string>` / `Record<Status, string>`,
so a future backend literal fails the typecheck until labeled.
At runtime an unknown value falls back to the raw value itself —
never to a wrong label — and a missing value renders as nothing.
`parseProposalRecord` / `parseOverrideRecord` read the pinned
records defensively: only well-shaped fields surface, malformed
fields are dropped rather than rendered raw, override values are
finite numbers in variable-id order. The stored list also shows a
one-line override summary (fixed values + fork step) on `override`
rows.

### Generate-from-stored counts active rows only

The "将使用的映射" display and the generate button's disabled
state previously counted every stored mapping, including proposed
and rejected rows the backend would never resolve. They now use
`active` rows only, with a distinct message when stored mappings
exist but none is active. This is a display correction to match
backend generation resolution, not a behavior change.

### API client (`src/api/engine.ts`)

`directionsApi` gains `acceptMapping` / `rejectMapping` (POST, no
body), following the existing `derive` no-body POST pattern. No
other client change.

## 2. Design decisions

1. **Queue + full list, not queue instead of list.** Proposed
   rows appear in both: the queue is the action surface, the
   stored list is the complete record. A row leaves the queue by
   changing status, which is visible in both places after the
   server reload.
2. **Reject confirms, accept does not.** Rejection is terminal
   for the row (backend rule); acceptance is recoverable (the
   row can be deleted afterward). The two-step reject matches
   the page's existing delete confirmation.
3. **Records parsed, never dumped.** `proposal_record` and
   `override_record` are untyped JSON; the UI renders named
   fields only, so a malformed record degrades to fewer lines
   instead of a raw dump or a crash.
4. **No propose-from-cockpit action.** The ordered gap was the
   review UI; proposals are still created via the API. Creating
   proposals from the cockpit is deferred (§8), not smuggled in.
5. **No status reinterpretation.** The UI never infers usability
   from origin or anything else: `status` decides the queue, the
   labels, and the generate display, exactly as the backend
   defines it.

## 3. Integration points

- **Option C backend**: accept/reject endpoints and the
  `DirectionMappingRead` shape (status, proposal_record) are
  consumed as implemented; no backend change was needed.
- **Option B backend**: `override` origin and `override_record`
  are labeled and summarized; the override creation endpoint is
  untouched.
- **Generation (Sprint 13/14)**: untouched. The generate card's
  stored-mappings display now mirrors the backend's active-only
  resolution.
- **Fixtures** (`src/test/engineFixtures.ts`): the two existing
  mapping fixtures gained the new backend fields (`status:
  'active'`, null records); three fixtures were added —
  `directionMappingProposed`, `directionMappingRejected`,
  `directionMappingOverride`.

## 4. Verification

All commands run personally in `frontend-v2` (Node v24.22.1,
`npm ci` exit 0, 302 packages). Baseline was measured before any
change; the full suite is flaky under this VM's load (see below),
so every count below is the honest per-run record, not a
cherry-pick.

### New tests: 19 (11 unit + 8 page)

- `src/components/cockpit/directionMappingDisplay.test.ts`: 11
  passed — exhaustive origin/status labels, unknown-value
  fallback, proposal/override record parsing incl. malformed
  input, hash shortening.
- `src/pages/Directions.test.tsx`: 8 new tests, all passed
  (fetch-mocked, in-memory mappings, following the file's
  existing pattern; accept/reject handlers added to the mock):

| # | Behavior | Test |
|---|----------|------|
| 1 | Proposed row in the queue with grounding (key variables, rationale, model, template, hash, MECE branches); labeled LLM 提案 · 待评审; no 手动 anywhere | `shows proposed mappings in the review queue with grounding, never labeled manual` |
| 2 | Empty queue text when nothing is proposed | `shows an empty review queue when nothing is proposed` |
| 3 | Accept POSTs to `/accept` with no body; row leaves the queue and shows LLM 提案 · 可用 in the stored list | `accepts a proposal, posts to the accept endpoint, and moves it out of the queue` |
| 4 | Reject needs two-step confirmation (no POST before confirm), then POSTs to `/reject`; row leaves the queue and shows 已拒绝 | `rejects a proposal only after two-step confirmation, and shows it as rejected` |
| 5 | A 400 refusal surfaces code + message and the proposal stays queued | `surfaces a review refusal with its code and keeps the proposal queued` |
| 6 | All four origins + all three statuses labeled in the stored list; override row shows its override summary | `labels every mapping origin and status in the stored list` |
| 7 | Generate-from-stored lists only active rows | `generates from stored mappings using only active rows` |
| 8 | Generate-from-stored disabled when no mapping is active, with the no-active message | `disables generate-from-stored while no mapping is active` |

### Full frontend suite (vitest)

| Run | Result |
|---|---|
| Baseline, run 1 (before changes) | 267 passed, 2 failed (31 files, 269 tests) |
| Baseline, run 2 (before changes) | 269 passed, 0 failed |
| After, touched files only | 30 passed, 0 failed (2 files) |
| After, full run 1 | 286 passed, 2 failed (32 files, 288 tests) |
| After, re-run of the 2 failing files | 50 passed, 0 failed |
| After, full run 2 | 287 passed, 1 failed (32 files, 288 tests) |

The only failures in any run are 5s-timeout flakes in two
chart-heavy tests unrelated to this change —
`Charts.test.tsx > renders ensemble histograms and all robustness
charts for a run` and `LoopViews.test.tsx > ComparisonView >
renders arm delta tables…` — which failed identically at baseline
and pass in isolation (50/50 in the targeted re-run). No failure
in any run touched the directions code or the new tests. No
single fully-green post-change full run was captured; the record
above is stated as-is.

### Lint + build

- `npm run lint` (eslint): exit 0, before and after.
- `npm run build` (`tsc -b && vite build`): exit 0, before and
  after (only the pre-existing chunk-size warning).

## 5. How to run / verify

```bash
cd frontend-v2
npm ci
npx vitest run src/components/cockpit/directionMappingDisplay.test.ts src/pages/Directions.test.tsx
npx vitest run
npm run lint
npm run build
```

## 6. Known limits

- **No real-browser check.** None is available on this VM; layout
  and visual behavior are unverified (§10).
- **No live-backend check.** Accept/reject wiring is verified
  against mocked fetch; endpoint shapes (POST, no body,
  `DirectionMappingRead` response) were taken from the backend
  route code, not exercised against a running server.
- **Queue is per-run.** There is no cross-run proposal queue;
  proposals are reviewed in the anchor run's directions view.
- **Concurrent reviewers** are not coordinated: two sessions
  reviewing the same proposal race at the backend (the second
  gets `direction_mapping_not_proposed`, surfaced as an error),
  and each action reloads from the server afterward.
- **Full-suite flakiness under load** (chart-test 5s timeouts)
  predates this change and is unrelated; see §4.

## 7. Cockpit check

Not applicable beyond the tests above: no real-browser rendering
was run (none available). The review UI follows the page's
existing Card/ErrorBanner/confirmation patterns and the mocked
render tests assert the rendered output.

## 8. Deferred (out of scope, recorded deliberately)

- Proposing directions from the cockpit (POST /directions/propose
  UI with topic input + proposal review of the propose response).
- Override-direction creation UI (POST /directions/override).
- A cross-run proposal queue.
- Raising the chart-test timeouts / fixing the full-suite flakes.

## 9. Commits on this branch

- `90491c0` — Cockpit proposal-review UI + exhaustive direction
  origin labels (implementation + 19 tests, 7 files)
- (this commit) — Cockpit proposal-review report

## 10. What was NOT verified

- Real-browser rendering of any kind (no browser on this VM).
- Accept/reject against a live backend (mocked fetch only).
- Live-LLM proposal quality (unchanged by this track; the UI
  only reviews what the backend stored).
- Behavior with a backend older than option C (the UI expects
  `status` / records on every mapping row; missing values render
  as no label rather than crashing, but this was not exercised
  against a real old server).
- Visual accessibility beyond Testing Library role queries
  (aria-labeled review buttons, existing focus styles).

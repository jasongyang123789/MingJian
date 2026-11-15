# Sprint 12 — Cockpit cleanup: template deletion + analysis launch buttons

Branch: `strategy-engine/sprint12-cockpit-cleanup`, from
`strategy-engine/sprint11-monitoring-worker` (`0c36dc9`). Nothing
pushed.

This sprint closes the two cockpit gaps deferred since Sprint 8:
template deletion (blocked by the 204-no-body transport gap) and
ensemble/analysis launch buttons (the Charts page named the POST
endpoints in its empty states but offered no way to run them). It is
frontend-only: the diff against `0c36dc9` touches `frontend-v2/`
only (verified: `git diff --stat 0c36dc9..HEAD -- src tests
migrations` is empty), no backend file changed, no migration, and
the backend suite was not re-run as a gate — the Sprint 0 smoke was
re-run to confirm the backend still behaves (PASS, see §4).

All new frontend tests run against mocked `window.fetch` — no live
backend, no live LLM. Live backend integration and real deliberation
rendering remain UNVERIFIED on this VM (see §8).

## 1. What was built

### 1. Template deletion (`/cockpit/variable-templates`)

- **204-safe transport.** `api.deleteNoContent` (`api/client.ts`)
  goes through the shared `requestResponse` (auth refresh, timeout,
  error handling) and never parses a response body, so a 204
  resolves to `void` instead of rejecting on the empty body. The
  JSON-parsing `api.delete` is untouched — one upstream caller
  (`deleteWatchRule`) expects a body. `variablesApi.deleteTemplate`
  uses the new path; the stale "No delete client" comment in
  `engine.ts` was replaced with the new discipline.
- **Delete button + inline confirmation.** Each non-built-in row
  has a 删除 button; the first click arms an inline confirmation
  ("确认删除「name」？" + 确认删除 / 取消) in the row, the second
  executes. Built-in rows render the button disabled with the
  title "内置模板只读，不可删除", using the same `is_builtin`
  marking the editor already uses for the read-only badge and
  detail view (§2). The list is never updated optimistically: it
  reloads only after the backend answers, and the success notice
  states that existing runs carry a template snapshot and are
  unaffected (§2).
- **Errors stay honest.** A failed delete shows the backend's
  message via `parseApiError` (code + message when the detail is
  structured) in an `ErrorBanner` above the list; the row stays.
  A 404 means the list was stale, so the list reloads to the truth
  and the error still shows.
- **Unsaved-changes interaction (decided, §2).** Deleting the
  template open in the editor goes through the existing
  `guardUnsaved` (dirty draft → `window.confirm` before the draft
  is discarded with its template); deleting any other template
  never touches the draft and never prompts. On a successful
  delete of the open template, the editor closes.

### 2. Charts launch buttons (`/cockpit/charts`)

New `AnalysisLaunchers.tsx` (`components/cockpit/`): one launcher
per empty state that names a POST endpoint. Every launcher runs
the analysis for the selected run, then reloads the stored
fragment — charts still only ever render stored data (Sprint 8
discipline; the POST response is never rendered directly). Every
launcher has a running state (button disabled, "运行中…"), a
failure state (honest `ErrorBanner` with retry re-running the same
launch), and a note stating the fixed backend defaults it uses.

- **Ensemble** (`MonteCarloLauncher`, in the no-ensemble empty
  state): metric dropdown populated from the run's template state
  fields (`GET /runs/{id}/variables`); when the run carries no
  variables fragment, a typed metric input instead. Payload is the
  backend defaults: 50 trials, null seed, loss_threshold 0, no
  strategy levers. After a successful launch the robustness
  section refetches too, so its per-analysis launchers appear
  once the ensemble exists (a refresh signal, §3).
- **Tornado** and **Bootstrap**: one click, backend defaults
  (quantiles 0.10/0.90, all variables; statistics mean/median/
  p_loss, 1000 draws, level 0.90). No inputs exist because the
  backend models give every field a default.
- **Threshold search** (`ThresholdSearchLauncher`): variable
  dropdown from the run's bound variable ids (typed fallback when
  the fragment is missing) plus a target-probability input
  (default 0.5). Mode is fixed to `p_loss`, direction to
  `increasing`; the rest are backend defaults (20 trials per
  evaluation, 8 iterations, tolerance 0.001). The launch button
  stays disabled while the target is not a finite number in
  (0, 1) — an affordance, not a verdict; the backend enforces.
- The section-level "暂无稳健性分析" state (no robustness fragment
  at all) deliberately gets **no** buttons: the analyses need an
  ensemble, and the state's text already guides the user to run
  one first (§2).

Charts stay fixed 720px (Sprint 8 deterministic rendering — not
changed). No new dependency, no new type mirrors: the four
request/response shapes already existed field-for-field in
`engineTypes.ts` and the four POST clients already existed in
`engine.ts`; this sprint only wires them to buttons.

## 2. Design decisions

### Built-in read-only marking (confirmed from code)

Built-in presets are synthesized from pack code
(`services/variables/presets.py: builtin_template`) and never
touch the database; their ids are `builtin:<domain_id>`, and the
read shape carries `is_builtin: true`. The list returns built-ins
first, then stored templates. The delete button uses exactly the
`is_builtin` flag the Sprint 8 editor already uses for the
"内置 · 只读" badge and the read-only detail view — one marking,
everywhere. Defense in depth: the backend refuses built-in
deletion anyway (`_stored_record_or_raise` in
`api/routes/variables.py` raises 400 with a plain-string detail),
and the UI surfaces that 400 honestly if it ever fires.

### Referenced-template deletion (confirmed from code)

There is no foreign key from `SimulationRun` to
`VariableTemplateRecord`, and DELETE performs no reference check
(`session.delete` + flush + commit in `store.py`). That is safe
because runs store a template + bindings + validation **snapshot**
in `configuration["variables"]` at creation time (the audit trail
`GET /runs/{run_id}/variables` reads back). Deleting a template
removes it from future use only; existing runs, ensembles, and
calibration fits keep working off their snapshots. The success
notice says so in the UI, so the behavior is visible, not just
documented here.

### Two-step inline confirmation, not `window.confirm`

The dirty-draft guard uses `window.confirm`, but deletion gets an
inline two-step arm/confirm in the row: it is explicit, it names
the template being deleted, it needs no browser dialog, and it is
directly testable. The `window.confirm` guard still applies on
top of it in exactly one case: deleting the template open in the
editor with a dirty draft — there the user confirms twice (arm,
then discard), which is the safer composition for a destructive
action over unsaved work.

### Backend-default payloads, minimal inputs

Only the values the backend requires with no default become
inputs: the monte-carlo metric and the threshold-search variable
+ target. Everything else is the backend default, stated in a
note under each button. Trials, levers, seeds, quantiles, bounds,
and threshold mode/direction stay API-only (§6) — a launch button
is not a parameter form, and inventing cockpit-side defaults
beyond the backend's would be a second source of truth.

### Options come from the run, validity stays with the backend

Metric options are the run template's state fields and variable
options are the run's bound variable ids, both from the stored
variables fragment. When the fragment is missing (404), typed
inputs replace the dropdowns and the backend validates (unknown
metric → 400 `monte_carlo_unknown_metric`; fixed/bernoulli
threshold variables → the Sprint 4 400s). The UI never pre-filters
variables by distribution type: that rule belongs to the backend,
and duplicating it would drift.

## 3. Integration points

- Transport (`api/client.ts`): `requestNoContent` +
  `api.deleteNoContent`. Error path unchanged: non-2xx still
  throws `ApiError` with status + body.
- Clients (`api/engine.ts`): `variablesApi.deleteTemplate`.
  `distributionsApi.runMonteCarlo` and
  `robustnessApi.{tornado,bootstrap,thresholdSearch}` already
  existed and are used unchanged.
- Delete UI (`pages/VariableTemplates.tsx`): `confirmingDeleteId`
  / `deleting` / `deleteError` state; `handleDelete` composes
  `guardUnsaved` for the open template only; the armed row, the
  disabled built-in button, and the delete `ErrorBanner` live in
  the list card.
- Launchers (`components/cockpit/AnalysisLaunchers.tsx`):
  `useLaunchAction` (busy/error + `parseApiError` display, the
  Sprint 11 pattern), `useRunVariables` (the variables fragment
  via `nullOn404`), `LauncherShell` (button + defaults note +
  error banner), and the four launcher components.
- Page wiring (`pages/Charts.tsx`): launchers under the four
  per-analysis / no-ensemble empty states; a `robustnessRefresh`
  counter passed into `RobustnessSection` as part of its `useApi`
  dependency, so a successful ensemble launch refetches the
  robustness bundle. The `useApi` reload-after-POST pattern is
  the same one the Sprint 9/11 loop pages use.
- No changes to the simulation engine, firewall, robustness,
  distributions, skills, calibration, or living-loop code; no
  chart component changed; the 720px fixed rendering is untouched.

## 4. Verification

Frontend: 169 → **195 tests (23 files), all passing**; `npm run
lint` exits 0 with zero errors/warnings; `npm run build`
(`tsc -b && vite build`) passes with only the pre-existing
chunk-size warning (JS 894.58 kB; no code-splitting, as before).
Full output: `docs/sprint12/verify-frontend.log`. New tests, all
mocked fetch:

- `client.test.ts` (2) + `engine.test.ts` (1): the 204-safe path
  (§5).
- `VariableTemplates.test.tsx` (7): delete success + cancel +
  built-in disabled + 400 + 404 + dirty-draft guard + other-
  template delete.
- `Charts.test.tsx` (16): per launcher — success refresh, failure
  + retry, running-disabled — plus metric/variable selection,
  typed fallbacks, and target-range gating.

Backend: not re-run as a gate — the diff touches `frontend-v2/`
only (see the header). Sprint 0 smoke re-run: **PASS** (health →
ingest → 4-tick simulation → decision trace → workbench →
options; the refreshed `smoke-evidence.json` was reverted per
the Sprint 2–11 precedent, keeping this branch's diff to Sprint
12 work).

### Behavior evidence (all asserted test values, with test names)

- 204 transport (`client.test.ts`, `engine.test.ts`):
  `deleteNoContent` resolves `undefined` on a 204 with no body
  and sends DELETE to `/api/variable-templates/t1`
  (`resolves void on a 204 with no body, without parsing JSON`);
  a 404 rejects with status 404 (`propagates API errors with
  their status instead of resolving`); `deleteTemplate('t1')`
  hits DELETE `/api/variable-templates/t1` and resolves
  undefined (`deletes a variable template with the 204-safe
  path`).
- Delete flow (`VariableTemplates.test.tsx`):
  `deletes a custom template only after inline confirmation and
  refreshes the list` — no DELETE before confirmation; DELETE to
  `/api/variable-templates/tmpl-1` with a null body; notice
  "已删除模板「AI line case」。已有 Run 带有该模板的快照，不受
  影响。"; the row leaves the table. `cancelling the delete
  confirmation sends nothing` — zero DELETEs, the confirm UI
  closes. `disables delete for built-in templates` — the button
  is disabled with title "内置模板只读，不可删除".
- Delete errors (`VariableTemplates.test.tsx`):
  `surfaces a delete failure honestly and keeps the list` — the
  400 plain-string detail renders, the row and its delete button
  stay, no deletion notice. `reloads the list when the backend
  says the template is already gone` — the 404 message renders
  and the stale row leaves the table.
- Delete vs dirty draft (`VariableTemplates.test.tsx`):
  `asks before discarding a dirty draft when deleting the open
  template` — `window.confirm` called; declining sends no DELETE
  and the 'edited' draft stays; accepting sends the DELETE and
  the editor closes ("未选中模板").
  `deleting another template leaves a dirty draft untouched` —
  `window.confirm` not called, DELETE sent, 'edited' draft stays.
- Ensemble launch (`Charts.test.tsx`):
  `runs an ensemble from the empty state and refreshes the
  charts` — metric select defaults to `cash`; POST body exactly
  `{trials: 50, seed: null, metric: 'cash', loss_threshold: 0,
  strategy_levers: {}}`; the baseline histogram renders and the
  robustness section refetches ("尚未运行龙卷风分析" appears).
  `runs an ensemble with the selected metric` — POST metric
  `pipeline`. `falls back to a typed metric when the run has no
  variables fragment` — typed `readiness` reaches the POST, and
  the button is disabled while the input is empty.
  `shows the backend error and retries the ensemble launch` —
  banner `monte_carlo_unknown_metric：Metric 'nope' is not a
  state field…`, no histogram, retry renders it.
  `disables the ensemble button while the launch is in flight` —
  "运行中…" disabled until the held response releases.
- Tornado / bootstrap (`Charts.test.tsx`):
  `runs a tornado analysis from its empty state and refreshes the
  chart` — POST body exactly `{low_quantile: 0.1, high_quantile:
  0.9, seed: null, variables: null}`; the tornado chart renders.
  `runs a bootstrap analysis from its empty state and refreshes
  the chart` — POST body exactly `{statistics: ['mean', 'median',
  'p_loss'], draws: 1000, seed: null, level: 0.9}`; the bootstrap
  chart renders. Both have a failure test (structured 400 code +
  message in the banner, no chart, retry renders the tornado
  chart) and a running-disabled test ("运行中…" disabled).
- Threshold search (`Charts.test.tsx`):
  `runs a threshold search from its empty state with the chosen
  variable and target` — variable select defaults to `cash`,
  target defaults to 0.5; changed to `cac` / 0.3, the POST body
  is exactly `{variable: 'cac', mode: 'p_loss', target: 0.3,
  direction: 'increasing', bounds: null, trials_per_evaluation:
  20, max_iterations: 8, tolerance: 0.001, seed: null,
  loss_threshold: null}`; the threshold chart renders.
  `disables the threshold launch while the target is out of
  range` — target 1.5 and empty disable the button, 0.3 enables
  it, zero POSTs sent. `falls back to a typed variable when the
  run has no variable bindings` — typed `cac` + default target
  0.5 reach the POST. `shows the backend error for a failed
  threshold search` — banner
  `robustness_threshold_fixed_variable：Variable 'cash' is
  fixed…`, no chart. `disables the threshold button while the
  launch is in flight` — "运行中…" disabled until release.

## 5. How to run / verify

- Delete: `/cockpit/variable-templates` → 删除 on a custom
  template → confirm inline. Built-in rows show a disabled
  button.
- Launch: `/cockpit/charts` → pick a run → the empty states offer
  运行 Ensemble / 运行龙卷风分析 / 运行 Bootstrap 分析 /
  运行阈值搜索. The ensemble launcher needs a metric (dropdown
  from the run's state fields); the threshold launcher needs a
  variable + target probability.
- Reproduce the numbers: `cd frontend-v2 && npm test -- --run`
  (195 tests), `npm run lint`, `npm run build`. Log:
  `docs/sprint12/verify-frontend.log`.

## 6. Known limits

- Launch parameters beyond the backend defaults are API-only:
  trials, strategy levers, seeds, tornado quantiles/variables,
  bootstrap draws/level, threshold bounds/mode/direction. The
  threshold launcher is fixed to `p_loss` / `increasing`.
- The 30s transport timeout on slow analyses is unexercised
  (pre-existing Sprint 8 note); a 200-trial ensemble or a long
  threshold search against a live backend may hit it.
- No delete affordance for templates from any other surface
  (run creation still picks from the list; a deleted template
  simply no longer appears).
- The `useApi` list fetch in `VariableTemplates` passes a fresh
  `[]` dependency literal, so the list refetches on every render
  — pre-existing Sprint 8 behavior, noticed during testing, left
  untouched as out of scope.
- Charts render at a fixed 720px width and do not resize with the
  viewport (Sprint 8 deliberate choice, unchanged). The JS bundle
  grew past the 500 kB warning threshold long ago (now ~895 kB);
  no code-splitting was done.

## 7. Deferred (out of scope, recorded deliberately)

- Decision-direction narrative output (still needs the LLM +
  presentation design).
- Alerting / notifications on fired triggers, event-driven
  evaluation, retention policy for evaluation rows (Sprint 11
  deferred items, unchanged).
- Ordering-guard version suppression, joint multivariate
  threshold fitting, automatic weight restore (Sprint 10
  deferred items, unchanged).
- Everything still deferred from Sprints 5–11: real backend
  integration / live LLM rendering, Docker stack verification,
  GitHub-side fork (needs Ho's account).

## 8. Commits on this branch

- `ac2502a` — Sprint 12: 204-safe delete transport +
  deleteTemplate client
- `4289655` — Sprint 12: template delete button with inline
  confirmation
- `69f5fe9` — Sprint 12: Charts launch buttons for ensemble and
  robustness analyses
- (this commit) — Sprint 12 report, backlog update, verification
  log

## 9. What was NOT verified

- Docker Compose stack (no container runtime on this VM) — as in
  all previous sprints.
- Live-LLM deliberation quality (Sprint 6 central open item) and
  real backend integration — untouched by this sprint, still
  unverified.
- The new delete/launch flows against a real backend: the
  frontend tests use mocked fetch, and the views were not
  exercised against a running backend (the `/api` proxy, 401
  refresh, and 30s timeout on slow analyses are unexercised).
- The `window.confirm` dirty-guard composition on delete is
  covered by unit tests with a mocked `confirm`, not by a real
  browser session.

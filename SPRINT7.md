# Sprint 7 — Cockpit UI

Branch: `strategy-engine/sprint7-cockpit`, from
`strategy-engine/sprint6-skills` (`83ba896`). Nothing pushed.

This sprint builds the decision cockpit: typed frontend clients and
views over the Sprint 1–6 backend, following the untouched upstream
`frontend-v2` conventions (client objects in `src/api/`, `useApi`
hooks, `Card`/`StatusBadge`/`EmptyState`/`ErrorBanner` UI components,
Chinese page chrome, Tailwind + lucide). No new framework or state
library was introduced. **No backend code was changed** — the
Sprint 1–6 API surface covered every view, so the backend suite was
never re-run as a gate (the diff against `83ba896` touches
`frontend-v2/` only, verified by `git diff --stat HEAD -- src tests`,
empty) and the Sprint 0 smoke was re-run to confirm the backend still
behaves (PASS, see §6).

All 60 new frontend tests run against mocked `window.fetch` — no live
backend, no live LLM. Live backend integration and real deliberation
rendering against a live LLM remain UNVERIFIED on this VM (see §7).

## 1. Route map

| Route | Page | Contents |
|---|---|---|
| `/cockpit` | `Cockpit.tsx` | Run picker + Sprint 1–5 fragment sections (§3) |
| `/cockpit/deliberations` | `Deliberation.tsx` | Deliberation launcher + history (§2) |
| `/cockpit/mece` | `MeceAuthoring.tsx` | MECE proposal + manual validation (§4) |
| `/cockpit/templates` | `TemplateProvenance.tsx` | 17-template provenance inventory (§5) |

A "决策驾驶舱" menu item was added to the sidebar (flat `MENU_ITEMS`
convention, placed after 场景模拟). Sub-navigation between the four
cockpit routes is a `CockpitNav` tab bar on each page, with the active
tab derived from the current path. The deliberation page reads the
selected run from the `?run=` URL parameter and keeps it in sync on
selection (mirroring the existing session-in-URL pattern).

## 2. API clients + types

`frontend-v2/src/api/engineTypes.ts` mirrors the backend Pydantic
shapes field-for-field (read from
`src/planagent/api/routes/{mece,variables,distributions,robustness,calibration,skills}.py`
and the matching service modules, not guessed); nullable backend
fields are `T | null`. This includes the full deliberation result
shapes: `StrategyTeamResult` (intake, shortlist, synthesis, panel
tally, verification, tournament, war-game playbook, pre-mortem) and
`AdvisoryBoardResult` (positions, revisions, forced debate, decision
contract), plus `StageRecord` (template id + version + contract
version + model).

`frontend-v2/src/api/engine.ts` exposes six client objects following
the `endpoints.ts` pattern:

- `meceApi`: `validate`, `propose`, `getRunMece`
- `variablesApi`: `validate`, `listTemplates`, `getTemplate`,
  `createTemplate`, `updateTemplate`, `getRunVariables`
- `distributionsApi`: `runMonteCarlo`, `getMonteCarlo`, `replay`,
  `getDeterminism`
- `robustnessApi`: `getRobustness`, `evaluate`, `registerGate`,
  `listGates`, `evaluateGates`
- `calibrationApi`: `getFirewall`, `policyFit`, `ruleWeightFit`,
  `listFits`, `getFit`, `applyRuleWeights`
- `skillsApi`: `runStrategyTeam`, `runAdvisoryBoard`,
  `listDeliberations`

Shared helpers: `parseApiError` recovers the structured FastAPI
`{"detail": {code, message, ...}}` payload (falling back to the raw
string detail or the transport message); `isLlmUnavailable` /
`isLlmContractFailure` classify 503 `skill_llm_unavailable` vs 502
`skill_contract_failed`; `nullOn404` converts a 404 into `null` so a
missing stored fragment renders as an empty state instead of an error.

One deliberate omission: no template delete client. Deletion returns
204 with no body and the shared `api` transport always parses JSON;
no Sprint 7 view deletes templates. Documented in code.

14 client tests pin every path/method/body, error propagation, the
`parseApiError` cases, and `nullOn404`.

## 3. Run cockpit (`/cockpit`)

A run picker (select + status badge) drives seven fragment sections,
each fetched independently through a generic `FragmentSection`
wrapper built on `useApi` + `nullOn404`:

- **MECE verdict** — `GET /runs/{id}/mece`: recursive tree with scope
  tags, validation verdict, issue list with kind labels, and the
  per-check table (root + per-node coverage).
- **Variable bindings** — `GET /runs/{id}/variables`: template id +
  snapshot, merged variable set with a one-line distribution summary
  per variable (`triangular(60, 100, 140)`), provenance (`evidence_ref`
  / `estimate:`), scope, and formula bindings.
- **Ensemble** — `GET /runs/{id}/monte-carlo`: per-arm P10/P50/P90 +
  loss probability, trial count, paired flag, seed, and the stored
  trial run ids.
- **Determinism** — `GET /runs/{id}/determinism`: input hash, per-tick
  state hashes, sampled values (applied vs not), seed.
- **Robustness** — `GET /runs/{id}/robustness`: expected shortfall
  (both tails + paired), tornado rows ranked by swing, threshold
  search results including the honest `reachable: false` note ("阈值在
  搜索区间内不可达"), bootstrap intervals, and the pinned
  `trial_values_hash`.
- **Decision gates** — `GET /runs/{id}/decision-gates`: registered
  gates with their `ensemble_existed_at_registration` evidence flag
  and evaluation outcomes.
- **Firewall audit** — `GET /runs/{id}/firewall`: cutoff, included
  and excluded claim ids.
- **Calibration history** — `GET /calibration/fits?domain_id=…&limit=50`,
  scoped by the selected run's domain: fit kind, inputs hash, prior
  vs fitted values (`changes.metrics` for policy fits,
  `changes.rules` for rule-weight fits — the two shapes were verified
  from `services/simulation/calibration.py`), LOO RMSE where present,
  and the calibrated template version hint (`calibrated_template_id`).

A missing fragment (404) renders an empty state, never an error; a
run must be selected before any section appears. Calibration fits are
domain-scoped, not run-scoped — the section says so.

## 4. Deliberation launcher + results (`/cockpit/deliberations`)

The launcher form covers both pipelines: topic/decision, mode
(strategy-team `standard`/`deep`, advisory-board `quick`/`standard`),
strategy-team options (`decision_question`, `include_premortem`,
`failure_date`), advisory options (free-text options, one per line),
context lines, and output language. Launch uses manual `useState`
error handling — deliberately NOT `useApiAction`, which stringifies
errors, because the raw error object is needed for the 503/502 banner
(§6). Launch is disabled with an explanatory note when the selected
run's status is not `COMPLETED` (the backend's
`skills_requires_completed_run` gate); history remains viewable.

History comes from `GET /runs/{id}/skills/deliberations`, newest
first, each record expandable to its full result with stage
provenance (template id + version + contract version + model per
stage):

- **Strategy team**: shortlist table (ranked, with scores) →
  synthesis rendered as the Pyramid (recommendation, 3 arguments,
  supporting evidence, risks) → panel tally with `must_address`
  flags highlighted (MUST ADDRESS badge; a flag is must-address when
  ≥2 distinct lenses flag the same normalized statement) →
  tournament bracket (deep mode: head-to-head wins + champion) →
  war-game playbook (rounds, plays, stop reason) → pre-mortem
  (failure modes, causes, preventive actions).
- **Advisory board**: Round 1 lens score table (5 lenses, weighted
  direction) → revisions → forced-debate disagreements → decision
  contract card (verdict, why-now, conditions, go/kill criteria,
  owner, deadline, review date, assumptions). A veto is a blocking
  red banner only when `has_unmitigated_veto` is true; a mitigated
  veto (`validate_first` verdict) renders as an amber note naming the
  mitigation path. The weighted-direction arithmetic is rendered from
  the backend-computed values, never recomputed in the UI.

## 5. MECE authoring (`/cockpit/mece`)

A proposal form (topic, context lines, dimensions defaulting to
Demand / Capability / Economics / Risk, output language) calls
`POST /mece/propose` and renders the proposal in one round trip: the
tree, the validation verdict with issues inline (each issue shows its
kind label, node, and scope tags), and stage provenance. A copy-JSON
button and a collapsible JSON block expose the raw tree for run
creation. When the verdict is FAIL, a single re-propose button sends
the failing tree back as `existing_tree` — the backend's revision
path, exposed as one honest step with a session proposal counter and
an explicit note that no revise-until-valid loop exists. A separate
manual panel validates pasted JSON through `POST /mece/validate`,
with client-side rejection of malformed JSON and non-object payloads
before any request is sent.

## 6. Honest LLM states + template provenance

`LlmStatusBanner` distinguishes the two failure modes as a product
requirement, both rendered with `role="alert"`:

- **503 `skill_llm_unavailable`** — amber banner: "未配置 LLM，无法启
  动 deliberation", explaining that the LLM target is unconfigured
  and the launcher stays visible and usable. It never hides the
  deliberation surfaces.
- **502 `skill_contract_failed`** — red banner: "LLM 输出未通过契约
  校验（502）", naming the offending template id when the payload
  carries one.
- Any other error renders as a generic red error banner with the
  recovered message.

Both states are tested at the component level and end-to-end through
the deliberation page's mocked launch (503 keeps the launcher
enabled; 502 never shows the 503 text).

`frontend-v2/src/data/skillTemplates.ts` ships the 17-template
inventory as static data — id, title, source repo, source file,
license note, version — copied verbatim from the backend
`list_templates()` output. No `GET /skills/templates` endpoint was
added (deliberately deferred per SPRINT6.md §7). The provenance page
(`/cockpit/templates`) pins all 17 rows and states plainly that the
inventory is static frontend data, with the backend registry as the
source of truth; stage records in deliberation results link each
output to its template id + version.

## 7. Verification

Frontend (Node v24.22.1 / npm 10.9.4, this VM):

- `npm test`: 14 files / **73 tests pass** (baseline 5 files / 13
  tests; +60 new: 14 client, 28 cockpit-component, 7 deliberation
  page, 5 MECE authoring, 4 cockpit page, 2 provenance). Fixtures in
  `src/test/engineFixtures.ts` are assembled from the recorded
  backend outputs in `tests/fixtures/skill_outputs/`; aggregates are
  the backend-computed values (tally with 2 must-address flags,
  Round 1 weighted 7.2/6.4/5.6, final 82/11, 71/11, 58/11,
  tournament 2-1-0, war-game loop 2 rounds `two_quiet_rounds`).
- `npm run build` (`tsc -b && vite build`): passes, 1780 modules.
- `npm run lint`: exit 0, zero errors and zero warnings. Two issues
  found and fixed during the sprint: `distributionSummary` moved out
  of a component file into `format.ts` (react-refresh
  only-export-components), and `verbatimModuleSyntax` type-only
  imports in the pages.

Backend: untouched (empty diff over `src/` + `tests/`). The Sprint 0
smoke (`docs/sprint0/smoke_e2e.py`) re-ran PASS on the new branch
(health → ingest → 4-tick simulation, all `rule_engine` → decision
trace → workbench → options). The 1085-test backend suite was not
re-run: nothing backend-side changed, and re-running it would verify
nothing about this sprint.

Rendered-output evidence: the component and page tests assert the
rendered DOM for every view above, including the 503 banner, the 502
banner, the veto banner (both blocking and mitigated variants), the
must-address highlighting, the tournament bracket, the decision
contract card, and the unreachable-threshold note. No dev-server
smoke check was run: the app sits behind an auth gate and no backend
runs on this VM, so a served page would show the gate, not a cockpit.

## 8. Known limits

- Read-only cockpit: variable-template editing and distribution
  visualization (named in the pre-sprint BACKLOG sketch) were NOT
  built — bindings and ensembles are displayed, not edited or
  charted. The living-strategy loop (monitor → re-simulate) was not
  built either. All three are recorded as next steps in BACKLOG.md.
- The deliberation launcher is synchronous: a deep run makes up to
  17 sequential LLM calls behind one request, and the UI shows a
  single "running" state with no per-stage progress. Latency is
  unmeasured (no live LLM on this VM).
- Deliberation history shows only the stored records for the
  selected run; there is no cross-run deliberation index.
- The static template inventory can drift from the backend registry;
  the provenance page says so, and stage records remain the
  authoritative per-output provenance.
- `formatNumber` rounds display values to 2 decimals; stored values
  keep full precision and nothing displayed feeds back into a
  computation.

## 9. Unverified (stated plainly)

- **Live backend integration**: no view has ever talked to a running
  backend. Types were read from backend source and fixtures from
  recorded outputs, but a real request/response round trip —
  including the `/api` proxy, auth refresh on 401, and the 30s client
  timeout against a slow deliberation — has not been exercised.
- **Real deliberation rendering**: no stage output from a live LLM
  has ever been rendered. Fixture rendering proves the views handle
  the contract shapes; it says nothing about live output quality
  (the Sprint 6 central open item stands).
- Docker Compose stack and LLM-backed backend paths remain
  unverified since Sprint 0 (no container runtime, no key on this
  VM).

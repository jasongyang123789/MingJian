# Sprint 8 — Variable-template editing + distribution charts

Branch: `strategy-engine/sprint8-templates-charts`, from
`strategy-engine/sprint7-cockpit` (`ec006e1`). Nothing pushed.

This sprint adds the two cockpit capabilities Sprint 7 deferred:
editing for the Sprint 2 variable templates (with the Sprint 4
formula graph and Sprint 5 calibration provenance), and distribution
charts over the Sprint 3 ensembles and Sprint 4 robustness results.
Unlike Sprint 7, one minimal backend addition proved necessary: the
monte-carlo GET response carries summary statistics plus trial run
ids only, so a read-only trial-values endpoint was added (§5) —
read-only exposure of stored values, no numeric-core change, no
validation-semantics change. Everything else is frontend, following
the Sprint 7 conventions (typed clients, `useApi`, `Card`/
`StatusBadge`/`EmptyState`/`ErrorBanner`, Chinese page chrome,
Tailwind + lucide, no new framework or state library).

All new frontend tests run against mocked `window.fetch` — no live
backend, no live LLM. Live backend integration and real deliberation
rendering remain UNVERIFIED on this VM (see §8).

## 1. Route map

| Route | Page | Contents |
|---|---|---|
| `/cockpit/variable-templates` | `VariableTemplates.tsx` | Template list, built-in detail, create/edit form (§2–3) |
| `/cockpit/charts` | `Charts.tsx` | Ensemble histograms + robustness charts (§4) |

Two tabs were added to `CockpitNav` (变量模板, 分布图表); the sidebar
menu item is unchanged. The charts page mirrors the deliberation
page's `?run=` URL-parameter sync with the shared `RunPicker`.

## 2. Template editor

`frontend-v2/src/pages/VariableTemplates.tsx` + `src/components/
cockpit/TemplateEditor.tsx` + `src/components/cockpit/templateDraft.ts`.

**List.** All templates from `GET /variable-templates`, built-ins
first (backend order). Built-ins carry a 内置 · 只读 badge;
calibrated versions carry a 已校准 badge derived from
`GET /calibration/fits?limit=100` (policy-threshold fits with a
`calibrated_template_id`). If the fits fetch fails, the list still
renders with a note that calibration flags are unavailable — the
failure never blocks template work.

**Detail (built-ins).** Selecting a built-in opens a read-only
detail view (`TemplateReadView`): state defaults, policy thresholds,
variables (with distribution summaries), formulas, internal table.
No inputs render. The action is an explicit “内置、只读——复制后编
辑” button. For calibrated versions the detail shows a provenance
card from the fit record: fit id, source template, ridge strength /
seed, observation count, `inputs_hash`, and the per-metric
prior → fitted threshold changes, with the note that the source
template was never modified.

**Create / edit.** The form edits a `TemplateDraft` — a flat,
row-based shaping of the template — and converts it back to the
backend payloads with `draftToCreate` / `draftToUpdate` /
`draftToVariableSet`. Field inventory, mapped to the backend models
(`services/variables/models.py`):

| Form section | Backend model | Fields |
|---|---|---|
| 基本信息 | `VariableTemplateCreate` | name, domain_id (create only — update payloads never carry `domain_id`; `VariableTemplateUpdate` forbids it), description |
| 变量表 | `VariableDefinition` + `VariableDistribution` | id, unit, evidence_ref, description, scope_tags (comma-separated), distribution type + the parameters relevant to that type only (fixed: value; normal: mean/std; triangular & beta_pert: min/mode/max; bernoulli: p) |
| 公式图 | `FormulaDefinition` | output, description, expression (§3) |
| 状态默认值 | `TemplateStateField` | name, description, default |
| 策略阈值 | `MetricPolicySpec` | metric, preferred_direction (increase/decrease), alert/critical thresholds |
| 内部情况表 | `internal` dict | key/value rows (duplicate keys collapse to the last row — JSON object semantics, noted on the form) |

New rows start empty (distribution `fixed`, numeric parameters
null, strings empty). **Cleared required numbers stay null in the
draft and are sent as null** — the single documented cast in
`draftToCreate` / `draftToUpdate` marks the boundary — so the
backend reports them as 422 shape errors naming the field, instead
of the client inventing a number. Update sends the full draft
(wholesale replacement, per the backend's update semantics).

**Duplicate.** “复制为新模板” prefills a create form from the
source template's full content with “（副本）” appended to the name.
There is no gap for built-ins: the list response already carries the
complete synthesized preset (state fields + policies), so
duplication needs no extra fetch.

**Validation discipline.** The backend validator is the only
arbiter. The form has a “校验变量表（后端）” button calling
`POST /variables/validate`; the result renders inline via
`ValidationIssuesView` (verdict badge, issues with kind/variable/
message, check records). The button's scope is stated on the form:
the endpoint covers variables + formulas + internal only —
template-level checks (state-field duplicates, policy threshold
ordering) run at save time through the same backend validator.
Create/update rejections surface inline the same way:
`parseValidationResult` (new in `engine.ts`, §6) recovers the
`validation` object from a 400 `variable_validation_failed`
response, and the raw server message renders as an alert banner.
No validation rule is re-implemented client-side; the only
client-side constraints are affordances (per-type parameter fields,
the formula vocabulary in §3), never presented as verdicts.

**Unsaved-changes protection.** The dirty baseline is the
`JSON.stringify` of the draft at load, create-start, or last
successful save. A dirty indicator shows in the card header and
beside the save button; switching templates or starting a create
while dirty asks `window.confirm` before discarding; a
`beforeunload` listener guards page unload while dirty. After a
successful save the list reloads, the form re-baselines from the
saved template, and a confirmation notice shows.

## 3. Formula editor constraints

The expression editor (`ExpressionEditor` in `TemplateEditor.tsx`)
constructs only what the Sprint 4 formula graph accepts, by
construction:

- Node kinds: number literal, reference, binary operation.
- Operation nodes have exactly two argument sub-editors; the
  operator dropdown offers exactly the six backend operators
  (add / subtract / multiply / divide / min / max).
- Reference options are the draft's variable ids plus the outputs
  of formulas listed *before* the current one — list order is the
  topological order, so forward references (and therefore cycles)
  cannot be constructed.
- A reference to an id that is not (or no longer) known stays
  visible in the dropdown, flagged “不在已知 id 中，后端校验会拒
  绝”, and the backend rejects it on save — the editor never
  silently drops it.
- No UI depth cap: the backend's depth limit (15) is the
  validator's call, not the editor's.
- `expressionFromJson` / `expressionToJson` (in `templateDraft.ts`)
  convert between stored JSON and the editable tree. Anything
  outside the vocabulary (unknown operator, wrong arity, extra
  keys, non-number literal) renders read-only as raw JSON with a
  note, and round-trips untouched on save — the backend can never
  have stored such an expression through validation, so this path
  is defensive only.

## 4. Distribution charts

`frontend-v2/src/pages/Charts.tsx` + `src/components/cockpit/
DistributionCharts.tsx` + `src/components/cockpit/RobustnessCharts.tsx`
+ pure transforms in `src/components/cockpit/chartData.ts`.

**Charting approach.** `recharts` ^3.8.1 was already a dependency
with zero usage; it is used now, and no new dependency was added.
All charts use fixed sizes (720px wide; heights computed from row
counts for vertical charts) and no animation — no
`ResponsiveContainer`, which cannot measure in jsdom — so rendering
is deterministic in tests and identical on every load. The bundle
grew past Vite's 500 kB chunk-size warning threshold (JS 477 kB →
850 kB); the warning is informational, the build exits 0, and no
code-splitting was done (recorded as a known observation in §7).

**Ensemble histograms** (`EnsembleHistograms`). Trial values come
from the §5 endpoint; the two arms share bin edges (Sturges' rule,
clamped to 5–30 bins) so shapes compare directly. P10/P50/P90 and
threshold reference lines use the stored ensemble summary — never
recomputed from the bins. Bins sitting entirely at or below the
loss threshold are shaded red (a straddling bin is left unshaded:
only fully-below bins are marked). A degenerate arm (every trial
identical) renders as a single spike bin via a centered unit-wide
window. The paired-delta histogram subtracts trial values by index
and is labeled a display-only derivation; the paired summary
numbers in its caption are the backend's.

**Robustness charts** (`TornadoChart`, `BootstrapChart`,
`ThresholdSearchChart`). All render stored Sprint 4 rows: tornado
range bars ranked by swing with the base-outcome reference line;
bootstrap interval bars with estimate dots (a `Line` with no stroke,
dots only); threshold-search probes sorted by value with the target
line and, only when reachable, the threshold line. The unreachable
state keeps the probe points and target line and states plainly
that no probe crossed the target within the bounds. Expected
shortfall is not charted (text rendering on `/cockpit` suffices;
it was not in the sprint's chart list).

**Honest degradation.** No ensemble → empty state naming
`POST /runs/{id}/monte-carlo`. Ensemble present but trial values
unavailable (404) → “Trial 值不可用” note stating no distribution
will be fabricated from summary statistics. Each robustness chart
has its own empty state naming its POST endpoint; no robustness
data at all → a section-level empty state. Display numbers use
`format.ts` (integers as-is, otherwise up to 4 decimals trailing-
zero-trimmed — correcting SPRINT7.md's “2 decimals” description,
which does not match the code); stored values keep full precision
and display values never flow back into computation.

## 5. Backend: read-only trial-values endpoint

The trial-values question was resolved from code: `MonteCarloResult`
carries summary statistics plus `trial_run_ids` only, and the
monte-carlo GET returns exactly that — no endpoint exposed trial
values. Fetching up to 200 trial rows one by one from the frontend
was rejected; a minimal read-only addition was justified.

- `GET /runs/{run_id}/monte-carlo/trial-values` → new
  `MonteCarloTrialValues` model (`extra=forbid`): ensemble_id,
  base_run_id, metric, loss_threshold, baseline/strategy value
  lists (index-paired), `trial_values_hash`, protocol.
- `SimulationDistributionsMixin.get_monte_carlo_trial_values`
  re-reads trial rows via the stored ensemble ids through the
  Sprint 4 robustness helpers (`_trial_values_for_ensemble`,
  `_trial_values_hash`) — the same discipline: nothing re-executed,
  the same hash pins the input set, and missing rows/values raise
  `RobustnessError("robustness_trial_values_missing")` → 400, the
  same mapping the robustness routes use. Unknown run or no
  ensemble → 404, matching the monte-carlo GET.
- No numeric-core code was touched (simulation/robustness/
  calibration math unchanged), no validation semantics changed, no
  migration. The endpoint is covered by 3 backend tests
  (`tests/test_trial_values_api.py`): re-aggregation of the
  returned values reproduces the stored summary exactly and the
  hash equals the one on an expected-shortfall analysis; 404 cases;
  and a corrupted trial row (summary replaced directly in the
  scratch DB — no API deletes runs) → 400 with the robustness code.

## 6. API layer changes

- `engineTypes.ts`: `MonteCarloTrialValues` interface mirroring the
  new backend model field-for-field.
- `engine.ts`: `distributionsApi.getTrialValues`; `readErrorDetail`
  helper shared by `parseApiError` and the new
  `parseValidationResult` (recovers a `VariableValidationResult`
  from a 400 `variable_validation_failed` detail, with a shape
  guard — anything else returns null); `parseApiError` gained a
  readable join for FastAPI 422 array details (`loc: msg; …`)
  instead of dumping the raw body. `ApiErrorInfo` semantics
  unchanged — callers use `.message` for display strings.
- No delete client was added (the 204-no-body transport gap noted
  in Sprint 7 stands; deletion is out of scope for this sprint).

## 7. Verification

Backend: full suite **1088 passed, 0 failed** in 299.75s
(`env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest -q`;
concluding lines in `docs/sprint8/test-full.log`) — 1085 from
Sprint 7 plus the 3 new trial-values tests. Sprint 0 smoke re-run:
**PASS** (health → ingest → 4-tick simulation → decision trace →
workbench → options; the refreshed `smoke-evidence.json` was
reverted per the Sprint 2–6 precedent, keeping this branch's diff
to Sprint 8 work). `mypy` clean on the touched backend files and
`ruff` shows only the pre-existing B008 `Depends()` pattern in the
new route (same handling as Sprints 1–5); the new test file is
`ruff format`-clean.

Frontend: 73 → 132 tests (21 files), all passing; `npm run lint`
exits 0 with zero errors/warnings; `npm run build` (`tsc -b &&
vite build`) passes with only the informational chunk-size warning
above. New tests, all mocked fetch:

- `templateDraft.test.ts` (7): draft round-trips, update payload
  omits `domain_id`, null passthrough for cleared numbers,
  expression vocabulary accept/reject, ref scoping.
- `TemplateEditor.test.tsx` (13): form rendering, distribution
  parameter switching, formula op-tree rendering, ref-option
  scoping incl. unknown-ref flagging, out-of-vocabulary read-only
  rendering, inline validation/save-error rendering, read view +
  calibrated provenance.
- `VariableTemplates.test.tsx` (9): list flags, built-in read-only
  + duplicate affordance, duplicate prefill, edit + save without
  `domain_id`, rejected save with inline server issues, pre-save
  check, blank create, dirty-guard confirm/cancel, calibrated
  edit note.
- `chartData.test.ts` (9): Sturges clamping, binning incl. max-in-
  last-bin, below-threshold marking, degenerate spike, shared
  edges, paired deltas, tornado ranking, evaluation sorting,
  bootstrap flattening.
- `DistributionCharts.test.tsx` (4): both histograms with markers
  and captions, per-bin bars (recharts omits zero-height bars, so
  assertions count non-empty bins), loss-bin shading, paired-delta
  histogram.
- `RobustnessCharts.test.tsx` (5): tornado ranking + base line,
  bootstrap intervals + estimate dots, threshold found vs
  unreachable (reference-line presence asserted inside the SVG).
- `Charts.test.tsx` (7): run selection, full render, no-ensemble /
  no-trial-values / per-analysis / no-robustness empty states,
  reachable-threshold state.
- `engine.test.ts` additions: `getTrialValues` path, 422 detail
  joining, `parseValidationResult` recovery + null shapes.

Behavior evidence (from the mocked suites, not a live backend):
the rejected-save test posts a 400 carrying the backend's
`variable_validation_failed` payload and asserts the issues render
inline with the form and draft intact; the charts tests assert the
unreachable threshold state renders probe points with no threshold
line, and the no-trial-values state renders no histogram at all.

## 8. Known limits

- Read-only cockpit otherwise: no template deletion (204 transport
  gap), no run-ensemble / run-analysis launch buttons — the charts
  page names the POST endpoints in its empty states instead.
- The editor has no revise-until-valid loop and no per-field
  client-side verdicts (by design); authors iterate against the
  backend validator.
- The pre-save check covers variables + formulas + internal only;
  template-level issues surface at save time (stated on the form).
- Histogram binning is Sturges' rule, fixed per render; no
  bin-count control. Tornado is one-variable-at-a-time as stored.
  Threshold search assumes monotonicity as stored.
- The calibrated-version flag reads at most 100 fits (the list
  endpoint's maximum); a deployment with more fits could miss a
  flag. Fits load failure degrades to “flags unavailable”, never
  blocks the list.
- The static template-provenance inventory (`/cockpit/templates`)
  can still drift from the backend registry (Sprint 7 note stands).
- Recharts adds ~370 kB to the JS bundle; no code-splitting.
- Charts render at a fixed 720px width and do not resize with the
  viewport (deliberate, for deterministic rendering).

## 9. Unverified (stated plainly)

- Real backend integration: no view has talked to a running
  backend (the `/api` proxy, 401 refresh, and 30s timeout on slow
  deliberations are unexercised). The trial-values endpoint is
  verified only through backend tests + mocked frontend tests.
- Real deliberation quality against a live LLM (Sprint 6 central
  open item, unchanged).
- Docker Compose stack (no container runtime on this VM).
- The `window.confirm` dirty guard and `beforeunload` behavior are
  covered by unit tests with a mocked `confirm`, not by a real
  browser session.

## 10. Deferred (not built)

Living-strategy loop (monitor → re-simulate); calibration
hardening (intercept/centering, weight persistence, scenario-run
weighting, fit-quality gates); decision-direction narrative output;
real backend integration / live LLM rendering; template deletion;
ensemble/analysis launch buttons in the cockpit.

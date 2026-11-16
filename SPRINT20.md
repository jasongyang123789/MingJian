# Sprint 20 — cockpit seminar views (frontend only)

Date: 2026-11-16. Branch: `strategy-engine/sprint20-cockpit-seminar`,
from `e35c0ce` (Sprint 18 tip). Frontend only: the diff contains zero
`.py` files and zero backend files. Built only against the API surface
as it exists at `e35c0ce`; no dependence on the parallel Sprint 19
backend work. Ho-directed 2026-11-16 15:36 ("全都开始做", the queued
S18-row cockpit item).

## 1. What was built

Two new cockpit routes plus a nav tab, a typed API client, view
components, and pure helpers. No charts: tables and lists only.

### 1.1 Routes and navigation

- `/cockpit/seminars` — seminar list for the picked run + create form
  (`frontend-v2/src/pages/Seminars.tsx`, 723 lines).
- `/cockpit/seminars/:id` — seminar detail
  (`frontend-v2/src/pages/SeminarDetail.tsx`, 571 lines).
- `研讨` tab in `CockpitNav`; routes registered in `App.tsx`.
- The list page follows the established `RunPicker` + `?run=` pattern
  (Automotive.tsx precedent).

### 1.2 List page (`/cockpit/seminars`)

- Table of `SeminarSummaryRead` rows: topic (link to detail), status
  badge, roster size, finals count, report versions, seminar id.
- Honest empty state when the run has no seminars.
- Create form: topic, decision question, options, context lines,
  pipeline (strategy_team / advisory_board), mode (options depend on
  the pipeline: standard/deep vs quick/standard), max_rounds,
  quiet_rounds, max_concurrency, output language, include_premortem,
  failure date, roster editor (add/remove rows; per-row model id,
  endpoint form, temperature, timeout, max_rounds), chair mode, chair
  model (model mode only), budgets (`max_stage_calls`,
  `max_tokens`), retry settings (`max_retries`,
  `retry_backoff_seconds`), near-duplicate threshold.
- Client-side validation mirrors the backend's refusal shapes before
  any POST: topic required, roster ≥ 2 with unique non-empty model
  ids, endpoint exactly one form (target OR inline with api_key_env +
  model), numeric fields numeric. Problems render as an amber list;
  no request is sent while any problem stands.
- Agent mode hides the chair fields and explains that the chair model
  config is shape-only (stored as `glint-agent`, never called); the
  create POST sends
  `chair_model = {model_id: 'glint-agent', endpoint: {target: 'primary'}, ...}`
  for shape stability.
- Create success shows the new seminar id, the frozen snapshot hash
  prefix, and a link to the detail page. Server errors render
  verbatim; no phantom state.

### 1.3 Detail page (`/cockpit/seminars/:id`)

Sections, in page order:

- **Action bar** — explicit buttons only: 推进一波 (advance), 定稿
  (finalize), 合成报告 / 合成（产出主控简报） (synthesize), with
  `allow_partial` and `deterministic_fallback` checkboxes and the
  chair mode shown. Each action shows its result or the backend's
  error inline. No auto-refresh, no polling (Sprint 9 boundary);
  sections reload through an explicit `dataVersion` counter bumped
  after a successful action.
- **Overview** — roster progress table (per-model status, rounds,
  final flag, latest board seq, endpoint summary by name only —
  env-var names, never values), budgets panel (stage calls and
  tokens: used / limit / remaining, from the audit ledger), and the
  diagnosis summary (error counts by kind, total tokens with
  prompt/completion split, total duration, stage calls/attempts,
  retries, fallbacks, queue waits).
- **Chair brief + submission** (agent mode only) — see §1.5.
- **Reports** — version buttons (latest selected by default) + the
  full document reading view (see §1.4).
- **Board timeline** — seq-ordered digests rendered as quotations
  with model + round labels, snapshot seq, confidence, key
  arguments, kill criteria, changes, and a reflection-missing flag.
  Header copy states board content is quotation, not instruction
  (design §4.3).
- **Rounds comparison** — rounds grouped per model, sorted by round:
  stage counts with pinned template/contract versions and reported
  accounting (model, attempts, duration, tokens), reflection
  (critique, per-model responses with stance, changes, confidence +
  basis, open questions), and failures with kind, stage, and
  message.
- **Finals** — verbatim verdicts per model: recommendation, ranked
  alternatives, confidence, key evidence, load-bearing assumptions,
  kill criteria, dissent held, rounds summary, board snapshot seq,
  and the final stage record.
- **Audit log** — seq-ordered events with kind + model_id filters
  (applied by an explicit button; model_id is an exact match, per
  backend semantics), per-event detail lines, stage call id, round,
  and timestamp.

### 1.4 Report reading view

`ReportDocumentView` renders the full `SeminarReportDocument`:

- Header: version, partial flag, production path / cluster
  production, chair, finals used / roster size, report hash, and the
  fallback reason when present.
- Unified recommendation with basis and provenance badge; agreement
  shown side by side (chair level vs computed recommendation
  agreement) with the note that the two disagree by design.
- Canonical claims with per-source citations (item id, model, round,
  field, stance, original text) and the full `merge_map`
  (`item_id→claim index`).
- **Disagreements are prominent**: red cards, one per item, with the
  claim, the stances present, and every position quoted verbatim
  with its sources. Copy states disagreements are never averaged
  away.
- Alternatives: Borda totals + ranking (computed) beside the chair
  ranking and aggregation rule (deliberated).
- Key evidence and kill criteria with source models; minority report
  marked verbatim; rounds evolution quoted per model; open
  questions; chair notes; computed metrics (agreement, confidence
  distribution, dedup counts, disagreement count, round counts);
  audit appendix (case snapshot hash, stage pins, board seq range,
  model/chair configs, token usage).
- Provenance badges reuse `ProvenanceBadge` from
  `DirectionViews.tsx` (computed / deliberated / template) — the
  same union as `SeminarProvenance`, not a duplicate.

### 1.5 Chair brief view + submission form (agent mode)

- `ChairBriefView` renders the brief: version + hash, pre-pass item
  table (item id, model, round, field, original text), exact /
  near-duplicate group counts with the pinned threshold and the
  excluded dissent-placeholder count, near-duplicate candidate
  groups, deterministic clusters with merge_map, computed metrics,
  verbatim verdicts, participation note, absent models with
  reasons, partial flag, and the submit endpoint string.
- **The brief is shown only in-session.** There is no GET endpoint
  for stored briefs at `e35c0ce`; the brief exists in the UI only
  as returned by the synthesize action. The empty state says so
  plainly: a page refresh requires re-synthesizing a new brief
  version. This is a backend-surface fact, stated honestly, not
  papered over.
- `ChairSubmissionForm`: brief-version input (blank = latest),
  two JSON textareas (ClaimClusters payload, SeminarSynthesis
  payload). Client-side JSON validation with inline errors; the
  server's contract/coverage errors display verbatim; success shows
  the new report version, production path, chair, and partial flag.
- Prefill buttons: "填入确定性聚类作为起点" builds a coverage-valid
  ClaimClusters payload from the brief's deterministic clusters
  (every pre-pass item exactly once — tested); "填入综合模板" fills
  a SeminarSynthesis template with `【…】` placeholders. Submit is
  disabled and warned while any `【` placeholder remains, so
  placeholder text can never be written into a versioned report.
- Copy states the submission is validated before any write and the
  brief pins the verdict set (server behavior, surfaced in the UI).

### 1.6 API client and types

- `src/api/engineTypes.ts` — Sprint 20 section: roster/config,
  `SeminarDetailRead`, `BoardRowRead`, `RoundRowRead`,
  `FinalRowRead`, `SeminarReportDocument` (all document keys from
  `composer.py::compose_report`), `PrepassRead`, `ClustersRead`,
  `ComputedMetricsRead`, `ChairBriefRead`, `AuditEventRead`, and
  all request/response reads. Shapes were read from
  `src/planagent/api/routes/seminars.py` and the seminar service
  modules, not guessed.
- `src/api/engine.ts` — `seminarApi` with all 13 endpoint functions
  (see §2). `synthesize` returns `SynthesizeRead | ChairBriefRead`,
  discriminated by `isChairBrief` (briefs carry `brief_version`,
  reports carry `version`).
- `src/components/cockpit/seminarUtils.ts` (277 lines) — pure
  helpers kept out of the component file per the react-refresh
  rule (Phase 2 `automotiveUtils.ts` precedent): `isChairBrief`,
  `auditDetailLines` (one summary shape per audit kind, from the
  recorder call sites; unknown kinds fall back to raw JSON),
  `clustersPrefillFromBrief`, `synthesisTemplate`,
  `parseJsonTextarea`, `endpointSummary`, `stageRecordSummary`,
  `formatDurationMs`, `formatNumber`, plus the value consts
  `SEMINAR_TARGET_NAMES` and `SEMINAR_AUDIT_EVENT_KINDS`
  (`engineTypes.ts` is types-only under `verbatimModuleSyntax`).
- `src/components/cockpit/SeminarViews.tsx` (907 lines) — the
  presentational components listed in §1.3–§1.5.

## 2. Endpoint → view mapping

| Endpoint | View / action |
|---|---|
| `GET /runs/{id}/seminars` | List table on `/cockpit/seminars` |
| `POST /runs/{id}/seminars` | Create form (201 → success box + link) |
| `GET /seminars/{id}` | Detail overview: roster, budgets, diagnosis; report version list |
| `POST /seminars/{id}/advance` | 推进一波 button (result: wave no, per-model round/status) |
| `POST /seminars/{id}/finalize` | 定稿 button (result: per-model final statuses) |
| `POST /seminars/{id}/synthesize` | 合成 button; model mode → report version, agent mode → chair brief |
| `POST /seminars/{id}/chair-synthesis` | Chair submission form (201 → new report version) |
| `GET /seminars/{id}/board` | Board timeline |
| `GET /seminars/{id}/rounds` | Rounds comparison |
| `GET /seminars/{id}/finals` | Finals verbatim |
| `GET /seminars/{id}/reports` | Exposed in `seminarApi` as `listReports`; the page derives the version list from `GET /seminars/{id}` detail (`reports[]`) instead, so this function is currently unused by the pages |
| `GET /seminars/{id}/reports/{version}` | Report reader (version buttons) |
| `GET /seminars/{id}/audit?kind=&model_id=` | Audit log with filters |

## 3. Design decisions

1. **Brief is in-session only** (§1.5) — no GET brief endpoint
   exists; the UI states this instead of faking persistence.
2. **Server errors verbatim** — `ApiError` messages carry the
   backend's code + detail; create, action, and submission errors
   render them unchanged.
3. **Prefill + placeholder guard** (§1.5) — the deterministic
   clusters are a valid starting point; template placeholders can
   never be submitted.
4. **Disagreements prominent, never averaged** (§1.4) — red cards
   with every position quoted.
5. **Per-kind audit summaries** — `auditDetailLines` renders one
   human line per event kind from the recorded detail shapes;
   unknown kinds show raw JSON rather than nothing.
6. **Explicit reload, no polling** — the `dataVersion` counter
   re-fetches sections only after a successful action (Sprint 9
   boundary).
7. **Agent-mode chair config is shape-only** — `glint-agent` with
   target `primary`, never called; the form says so.
8. **Endpoint summaries show names only** — target names and env-var
   names; no secret material can appear (the API never returns
   values).
9. **No charts** — the seminar data is text (digests, verdicts,
   claims, events); tables and lists carry it without loss.
10. **Client validation mirrors backend refusals** — roster ≥ 2,
    endpoint exactly-one-form, numeric fields — so the common
    refusals surface before any POST, while server errors remain
    the authority when they occur.

## 4. Verification

Evidence discipline: every number below is from a run in the
`mingjian-s20` worktree on 2026-11-16.

- **Typecheck**: `npx tsc -b` in `frontend-v2/` — clean, exit 0.
  (One error was found and fixed during the build: `runAction`
  passed a possibly-undefined `seminarId` to API calls; a guard was
  added at the top of the function.)
- **Tests**: `npx vitest run` — **31 files, 269 tests, 0 failed**
  (base 228 + 41 new). New tests, all fetch-mocked with fixtures
  mirroring the backend shapes:
  - `seminarUtils.test.ts`: 11 — brief/report discrimination,
    duration/endpoint/stage summaries, audit lines for 8
    representative kinds + unknown-kind fallback, prefill coverage
    (every item exactly once), template fields, JSON parsing.
  - `SeminarViews.test.tsx`: 12 — budgets/diagnosis numbers, roster
    table, board quotes with model + round + seq, rounds grouping
    with reflection and failure detail, finals verbatim, report
    recommendation/Borda/provenance/merge_map, disagreements
    prominent with both sides quoted, fallback reason, audit rows,
    brief contents.
  - `Seminars.test.tsx`: 6 — list with detail links, empty state,
    roster < 2 blocked client-side with zero POSTs, create success
    with POST body asserted, server error verbatim with no phantom
    state, agent mode hides chair fields and sends `glint-agent`.
  - `SeminarDetail.test.tsx`: 12 — header/budgets/diagnosis/board/
    finals/audit rendering, advance, finalize, action error inline,
    synthesize with toggle values asserted in the POST body, report
    version switching, audit filters as query parameters, brief →
    submission form, malformed JSON rejected with zero POSTs,
    placeholder guard disables submit, valid submission shows the
    new report version with the POST body asserted, server coverage
    error verbatim.
- **Lint**: `npm run lint` — exit 0, no findings.
- **Build**: `npm run build` — exit 0. Rolldown emits the chunk-size
  warning (bundle 1,007.82 kB, gzip 275.93 kB); the build succeeds.
- **Diff hygiene**: the code diff (excluding this report and the
  BACKLOG.md entry) is 12 files, all under `frontend-v2/src/`,
  zero `.py` / backend files; `git diff --shortstat` over the code
  commits reports 4,670 insertions, 0 deletions. Worktree clean at
  handoff.
- **Process note**: two files (`seminarUtils.ts`,
  `SeminarDetail.tsx`) lost all leading indentation to a
  write-tool artifact on first write; both were rewritten with
  byte-preserving stdin writes and verified with
  `grep -c '^  '` (204 and 500 indented lines respectively) before
  the test files were written the same way.

## 5. Known limits

- **Brief lost on refresh** — no GET brief endpoint at `e35c0ce`
  (§1.5). Re-synthesizing produces a new brief version; the old
  version remains stored server-side but is not re-readable from
  the cockpit.
- **Shared 30s client timeout** — the pre-existing `api` client
  timeout may trip on long live-model waves (advance/finalize/
  synthesize against real models). Not solved here; the failure
  surfaces as an inline error and the seminar state is unchanged
  server-side only insofar as the backend's own semantics hold.
- **No live-backend or real-browser verification in this sprint** —
  tests are fetch-mocked; rendering against a running backend and
  in a real browser is still unverified (as in prior sprints).
- **Audit filter model_id is an exact match** (backend semantics);
  there is no substring search.
- **No pagination** — board, rounds, finals, and audit lists render
  in full, as the backend returns them.
- `listReports` is exposed in the client but unused by the pages
  (§2); kept for completeness of the typed surface.

## 6. Deferred / deliberately not built

- Auto-refresh / polling (Sprint 9 boundary).
- Brief persistence or a GET brief endpoint (backend change; out of
  scope for this frontend-only sprint).
- Charts or visualizations of seminar data.
- Any dependence on unmerged Sprint 19 additions.
- Any backend change whatsoever.
- Direction auto-derivation UI (Sprint 14) is untouched; seminars
  surface reports only.

## 7. Commits

On `strategy-engine/sprint20-cockpit-seminar` from `e35c0ce`:

- `b14d7f7` — Sprint 20: seminar API types + seminarApi client
  (shapes from routes/seminars.py)
- `35d081b` — Sprint 20: seminar view components + pure helpers
  (board/rounds/finals/report/audit/brief)
- `6b3e0c4` — Sprint 20: seminars list/create + detail pages,
  routes, nav tab
- `8510d47` — Sprint 20: seminar view + page tests (41 new, 269
  total)
- (this commit) — Sprint 20: report + BACKLOG entry

Not pushed, not merged. Merge order per the parent plan: Sprint 19
first, then Sprint 20 (disjoint diffs; Sprint 20 touches frontend
only).

# Backlog — strategic simulation engine (MingJian base)

Living sprint plan. **This file supersedes the PRD PDF's sprint-plan
section** (`strategy-engine-prd-architecture.pdf`) in the details below:
the enrichments for Sprints 3–5 were approved by Ho on 2026-11-13 after
the PRD was written. The PRD's framing (as-is inventory → six gaps →
Epics E0–E6 → architecture deltas D1–D9) still stands; only the sprint
contents below take precedence where they differ.

Base: MingJian fork (`~/workspace/mingjian-base/`), agile incremental
development on the most full-featured existing project. scenario-lab is
the second donor for ensemble/calibration modules, not a second base.
Nothing is pushed; a GitHub-side fork needs Ho's account.

## Done

- **Sprint 0 — baseline.** Working fork, as-is architecture map,
  baseline tests 736 passed, E2E smoke PASS on SQLite + in-memory bus.
  Report: `SPRINT0.md` (branch `strategy-engine/sprint0-baseline`).
- **Sprint 1 — MECE layer (PRD delta D1).** Scope-tag validator + run
  creation gate (refuses before any row is written) + validate/audit
  endpoints; tests 736 → 763 passed. Report: `SPRINT1.md` (branch
  `strategy-engine/sprint1-mece`).
- **Sprint 2 — variable tables (PRD deltas D2/D3).** Validated
  variable tables (1–30 variables, distributions + provenance) +
  domain-pack templating (built-in corporate/military presets) + run
  bindings with merge and MECE scope cross-check + template CRUD/audit
  API + migration `0029_variable_templates`; tests 763 → 801 passed.
  Report: `SPRINT2.md` (branch `strategy-engine/sprint2-variables`).
- **Sprint 3 — determinism + sampling (PRD deltas D4/D5).** Canonical
  JSON + SHA-256 input/state hashes + hash-verified replay; seed → RNG
  wiring (gap G6 closed) with golden-run byte-identity; seeded paired
  Monte Carlo over the Sprint 2 variable tables (P10/P50/P90 + loss
  probability + paired deltas, stored on the base run); branch-level
  variable overrides with decomposition-branch scope ownership; tests
  801 → 850 passed. Report: `SPRINT3.md` (branch
  `strategy-engine/sprint3-distributions`).

- **Sprint 4 — robustness evaluation + formula graph (PRD deltas
  D6/D7).** Expected shortfall / tornado sensitivity / threshold
  search / pre-registered decision gates (per taylanakgn) + bootstrap
  intervals (per jasonrkeen), grafted onto the Sprint 3 persisted
  ensembles, all pure/deterministic with stored audit results; plus a
  no-arbitrary-code formula graph (per agilhaykal) evaluated per trial
  before the tick loop, validated at template/binding time with gate
  discipline, persisted via migration `0030_variable_template_formulas`,
  with a golden test porting the prototype's variables through the
  graph. Tests 850 → 912 passed. Report: `SPRINT4.md` (branch
  `strategy-engine/sprint4-robustness`).

- **Sprint 5 — calibration loop + hindsight firewall (PRD delta D8).**
  Decision-time evidence cutoff (per saisrikolanu): runs record
  `decision_time` (explicit, or creation-time default), claim reads
  filter to `created_at <= decision_time`, the cutoff enters the
  Sprint 3 input hash so replays reproduce the same evidence set,
  plus a firewall audit endpoint reporting exactly which claims were
  kept out. Ridge-to-prior calibration (per jasonrkeen): policy
  thresholds fit from stored run outcomes and stored as NEW template
  versions with provenance (source runs, shrinkage, inputs hash;
  prior never overwritten), rule weights fit from decision-record
  match counts and applied only through an explicit audited apply
  step; seeded bootstrap intervals reuse the Sprint 4 primitive;
  fits recorded in the new `calibration_fits` table (migration
  `0031_calibration_fits`). Gap G5 closed. Tests 912 → 963 passed.
  Report: `SPRINT5.md` (branch `strategy-engine/sprint5-calibration`).

## Sprint 6 — skill grafts (done, PRD delta D9)

- Grafted the verified strategy skills as versioned prompt templates /
  pipeline stages over the existing LLM adapter: McKinsey
  strategy-team pipeline (intake → fan-out → generate-and-filter →
  synthesis → verifier panel; deep mode adds tournament +
  loop-until-done), 5-persona advisory board (CRIT intake → 5 lenses
  → forced debate → revisions → decision contract), gambit
  pre-mortem as a fourth verifier lens, flingjie MECE authoring as a
  proposal aid only (Sprint 1 validator disposes, unchanged).
  Strategic-partner skipped (dev-process skill, no deliberation
  stage maps); gambit decide/options skipped (duplicate coverage);
  advisory "full" mode unsupported (no research worker wired).
  Agent-teams adaptation recorded: waves run as sequential stage
  calls over a shared context store, not parallel agents.
- 17 templates with provenance + license notes (flingjie: no license
  declared, structure adapted, wording original); one Pydantic
  contract per template; stages consume engine artifacts as rendered
  context (MECE, variables, ensemble, robustness, Sprint 5
  calibration deltas, firewall cutoff) and write only the
  append-only `skill_deliberations` summary fragment (no migration).
  No new LLM client; unavailable LLM is 503, malformed output 502,
  nothing fabricated. 4 endpoints. Tests 963 → 1085 passed, all
  without a live LLM call. Live deliberation quality UNVERIFIED
  (no key). Report: `SPRINT6.md` (branch
  `strategy-engine/sprint6-skills`).

## Sprint 7 — cockpit UI (done)

- Cockpit UI delivered on `strategy-engine/sprint7-cockpit` (see
  SPRINT7.md): typed API clients + types for all Sprint 1–6
  endpoints; run cockpit (`/cockpit`) with MECE verdict, variable
  bindings, ensemble, determinism, robustness, decision gates,
  firewall audit, and domain-scoped calibration history; deliberation
  launcher + results (`/cockpit/deliberations`, `?run=` URL param,
  history newest-first, veto banners, stage provenance); MECE
  authoring (`/cockpit/mece`, propose + inline issues + single
  re-propose via `existing_tree`, manual validate panel); static
  17-template provenance inventory (`/cockpit/templates`); honest
  503-vs-502 LLM banners, tested both. Frontend 13 → 73 tests, lint
  and build green. No backend changes; Sprint 0 smoke re-run PASS.
  Live backend integration and real deliberation rendering against a
  live LLM remain UNVERIFIED.
- NOT built (deferred, not done): variable-template editing,
  distribution visualization/charts, living-strategy loop
  (monitor → re-simulate). These were named in the pre-sprint sketch
  but outside the Sprint 7 task scope; they are next-step candidates.
- Decision-direction narrative output (pre-mortems, 48-hour first
  steps, LLM narrative/red-team layer): still deferred; consumes the
  Sprint 4 robustness outputs + Sprint 5 fitted templates, needs LLM
  access + presentation design.
- Product decisions still open: making decomposition/bindings mandatory,
  LLM-assisted decomposition authoring (must pass the same gates).

## Sprint 8 — variable-template editing + distribution charts (done)

- Delivered on `strategy-engine/sprint8-templates-charts` (see
  SPRINT8.md): template editor UI (`/cockpit/variable-templates`,
  list/detail/create/edit, built-ins read-only with duplicate
  affordance, calibrated-version flags + fit provenance, backend
  validator as sole arbiter with inline server issues, formula
  editor constrained to the Sprint 4 graph vocabulary, dirty-state
  protection) and distribution charts (`/cockpit/charts`, ensemble
  histograms from trial values + paired-delta view, tornado,
  bootstrap intervals, threshold search incl. honest unreachable
  state, all with honest empty states). One minimal backend
  addition: read-only `GET /runs/{id}/monte-carlo/trial-values`
  re-reading trial rows via stored ids with the Sprint 4 hash
  discipline (no numeric-core or validation change). Frontend
  73 → 132 tests, lint and build green; backend 1085 → 1088
  tests, Sprint 0 smoke re-run PASS. Live backend integration and
  real deliberation rendering against a live LLM remain UNVERIFIED.
- NOT built (deferred, not done): living-strategy loop, calibration
  hardening, decision-direction narrative output, template deletion,
  ensemble/analysis launch buttons in the cockpit.

## Sprint 9 — living-strategy loop: monitor → re-simulate (done)

- Delivered on `strategy-engine/sprint9-living-loop` (see
  SPRINT9.md): append-only loop record (3 tables + migration 0032)
  linking baseline run → observations → pre-registered trigger
  evaluations → re-simulation runs → comparisons → review decisions;
  pure trigger evaluation (threshold / Sprint 4 gate statistics /
  repeated deviation, fired/quiet/no-data all recorded) and pure
  ensemble comparison (per-arm deltas, gate re-evaluation,
  threshold drift, evidence caveat when cutoffs differ); re-simulation
  through the existing creation path (MECE/variable/firewall gates
  engage, refused runs write zero rows, cutoff advances honestly
  with both cutoffs + both input hashes on the record); 11 loop
  endpoints; cockpit UI (`/cockpit/loops`, timeline, trigger
  builder, observation recording, iteration actions, comparison
  histograms reusing the Sprint 8 components with an
  ensemble-identity check). No scheduler, no worker hook, no LLM
  calls: every action is explicit. Frontend 132 → 163 tests, lint
  and build green; backend 1088 → 1125 tests (37 new: 25 pure-module
  unit + 12 API), Sprint 0 smoke re-run PASS. Live backend
  integration and real deliberation rendering against a live LLM
  remain UNVERIFIED; real scheduled monitoring does not exist yet
  (designed automation boundary, needs Ho's decision).
- NOT built (deferred, not done): calibration hardening,
  decision-direction narrative output, template deletion,
  ensemble/analysis launch buttons, monitoring worker / scheduled
  evaluation.

## Sprint 10 — calibration hardening (done)

- Delivered on `strategy-engine/sprint10-calibration-hardening`
  (see SPRINT10.md): target centering for rule-weight fits
  (default-on intercept, `center_target: false` reproduces exact
  Sprint 5 values; demo LOO 45.31 → 11.50, weights 32.70/21.44 →
  2.65/1.00); persistent current-weights record (new table +
  migration 0033, current-weights read + explicit restore, no
  automatic restore); scenario-children handling (`include` /
  `exclude` / `family` row weighting, both fit kinds);
  fit-quality gate vs the prior-only baseline (whole-fit refusal
  with zero rows for rule weights, per-metric `quality_gate`
  reason + version suppression for policy fits); per-metric
  Pearson correlation diagnostics (recorded, never refusing).
  Backend 1125 → 1163 tests (38 new, all hand-verified), Sprint 0
  smoke re-run PASS, mypy/ruff clean. Cockpit checked, no UI
  change needed (gate-failed fits render honestly; suppressed
  versions never flag templates). Live backend integration and
  real deliberation rendering against a live LLM remain
  UNVERIFIED.
- NOT built (deferred, not done): decision-direction narrative
  output, template deletion, ensemble/analysis launch buttons,
  monitoring worker / scheduled evaluation.

## Sprint 12 — cockpit cleanup: template deletion + launch buttons (done)

- Delivered on `strategy-engine/sprint12-cockpit-cleanup`
  (see SPRINT12.md): frontend-only, closing the two cockpit gaps
  deferred since Sprint 8. Template deletion: a 204-safe
  transport path (`api.deleteNoContent`, never parses a body)
  plus `variablesApi.deleteTemplate`; the list offers a delete
  button with two-step inline confirmation, disabled for
  built-ins (same `is_builtin` marking as the read-only view;
  the backend refuses built-ins with 400 anyway). Deleting the
  template open in the editor goes through the unsaved-changes
  guard; deleting any other template never touches the draft.
  Confirmed from code: runs carry a template snapshot, so
  deletion cannot break existing runs. Charts launch buttons:
  the four empty states that named POST endpoints now run them
  (ensemble, tornado, bootstrap, threshold search) with
  backend-default payloads, running/failure states with retry,
  and a reload of the stored fragment afterward — charts still
  render stored data only. Metric/variable options come from the
  run's variables fragment, with typed fallbacks; validity stays
  with the backend. Frontend 169 → 195 tests (26 new), lint 0,
  build passes; zero backend/src changes (diff touches
  `frontend-v2/` only); Sprint 0 smoke re-run PASS. Launch
  parameters beyond backend defaults stay API-only; Docker stack
  and live backend integration remain UNVERIFIED.
- NOT built (deferred, not done): decision-direction narrative
  output, alerting on fired triggers, event-driven evaluation,
  retention policy for evaluation rows, ordering-guard version
  suppression, joint multivariate threshold fitting, automatic
  weight restore.

## Sprint 11 — monitoring worker, evaluate + record only (done)

- Delivered on `strategy-engine/sprint11-monitoring-worker`
  (see SPRINT11.md): the SPRINT9.md §10 worker, authorized by Ho
  2026-11-15 — one monitoring cycle evaluates every loop's active
  trigger registration against all recorded observations and
  records the outcome in a new `loop_evaluations` table (migration
  0034). Fingerprint dedup (canonical SHA-256 of observation ids +
  registration + triggers) means unchanged inputs write no new
  row; failed evaluations are recorded as error rows, and one
  loop's failure never aborts the cycle. The automation boundary
  holds by construction: the cycle's only writes are evaluation
  rows — no runs, no iterations, no state transitions. Endpoints
  `POST /loops/monitoring/evaluate` (one cycle on demand) and
  `GET /loops/{loop_id}/evaluations` (history, newest first);
  worker registered in `worker_cli` (11th worker) with a
  conservative 1-hour default interval
  (`PLANAGENT_MONITORING_WORKER_INTERVAL_SECONDS`) and a compose
  service (`advanced` profile, following the calibration worker).
  Cockpit shows the evaluation history plus a run-once button.
  Backend 1163 → 1192 tests (29 new), frontend
  163 → 169, Sprint 0 smoke re-run PASS, mypy/ruff clean. No
  alerting on fired triggers (recorded + shown, nothing pushes);
  Docker stack and live backend integration remain UNVERIFIED.
- NOT built (deferred, not done): decision-direction narrative
  output, template deletion, ensemble/analysis launch buttons,
  alerting on fired triggers, event-driven evaluation,
  retention policy for evaluation rows.

## Sprint 13 — decision-direction narrative output (done)

- Delivered on `strategy-engine/sprint13-decision-narrative`
  (see SPRINT13.md): the last mile of the four-layer vision. A
  pure deterministic composer assembles 1–4 directions from stored
  artifacts only — ensembles, tornado/threshold/ES/bootstrap
  results, decision gates, skill deliberations, the MECE tree,
  calibration fits, loop triggers — each direction with an outcome
  distribution (P10/P50/P90 + loss probability), key drivers,
  tripwire signals, a pre-mortem, a 48-hour first step, and a MECE
  trace. Every section carries a provenance mark
  (computed/deliberated/template); absent deliberations yield
  explicit template notices, never fabricated analysis. Directions
  come only from explicit definitions in the generation request
  (the codebase has no direction source: options lack ensemble
  links, branches lack direction semantics). Ranking is P50
  descending, ties by name. The artifact is a versioned,
  append-only, hashed JSON body in a new `decision_narratives`
  table (migration 0035, revises 0034) with `inputs_hash` +
  `content_hash` (canonical JSON + SHA-256); same inputs compose
  byte-identical bodies, asserted by test. Endpoints
  `POST/GET /runs/{id}/narratives`, `GET` one, and an optional
  `POST .../polish` (strictly separated: polished text lives in
  `decision_narrative_polishes`, marked LLM-generated; 503/502
  write nothing; fixture-driven tests only, live quality
  UNVERIFIED). Refusals are loud and named (no ensemble, unknown
  source run/branch/deliberation, loop mismatch, corrupt
  fragments). Cockpit `/cockpit/directions`: generate form (name +
  source run + arm + MECE checkboxes), version history, reading
  view with provenance badges, polish section. Backend 1192 → 1231
  tests (39 new), frontend 195 → 206 (11 new), lint 0, build
  passes, mypy clean (203 files), migration upgrade → downgrade →
  re-upgrade verified, Sprint 0 smoke re-run PASS. Docker stack,
  live-LLM quality, and live backend integration remain UNVERIFIED.
- NOT built (deferred, not done): direction auto-derivation,
  polished-text verification, loop/deliberation-pin controls in
  the cockpit form, narrative deletion/retention, alerting on
  fired triggers, event-driven evaluation, retention policy for
  evaluation rows, ordering-guard version suppression, joint
  multivariate threshold fitting, automatic weight restore.

## Sprint 14 — direction auto-derivation + persisted mappings (done)

- Delivered on `strategy-engine/sprint14-direction-derivation`
  (see SPRINT14.md): Ho chose options A + D together after the
  design discussion. A pure deterministic derivation
  (`derivation-rules-v1`, no LLM, no new runs) applies three
  rules in fixed order over the anchor run's scenario family
  (Sprint 10 family rule): highest P50, most robust (loss
  probability, then lower-tail expected shortfall), baseline
  control — with exact documented tie-breaks, per-rule outcomes
  (produced/none/duplicate/skipped), dedup, and byte-identical
  results (canonical JSON + SHA-256, asserted by test).
  Derivation is an explicit POST only; it upserts mappings
  by name and NEVER overwrites a user-edited mapping
  (no-clobber rule). Persisted direction mappings live in a new
  `direction_mappings` table (migration 0036, revises 0035;
  unique names per anchor run in code + DB constraint; explicit
  position order) with list/create/update/delete endpoints and
  refuse-before-write reference validation. Narrative
  generation resolves directions from stored mappings when the
  request omits them (inline definitions win; cap 4; mapping
  ids pinned in the inputs hash and on the row); neither
  directions nor mappings refuses naming the derive endpoint.
  The derive path reads the expected-shortfall sub-fragment
  directly and is NOT affected by the known Sprint 13
  robustness/gates fragment bug (verified 2026-11-16, fix on
  its own branch after Sprint 14; generation from mappings
  inherits the refusal on enriched runs, pinned by test).
  Cockpit `/cockpit/directions` gains a derive button with
  outcomes display, a mappings list with inline rename/re-point
  editing and two-step-confirm delete, generate-from-stored
  with the mappings-used line. Backend 1231 → 1265 tests (34
  new), frontend 206 → 212 (6 new), lint 0, build passes, mypy
  clean (204 files), migration upgrade → downgrade →
  re-upgrade verified, Sprint 0 smoke re-run PASS. Docker
  stack, live-LLM quality, and live backend integration
  remain UNVERIFIED.
- NOT built (deferred, not done): directions as variable
  overrides (option B), LLM-proposed directions with grounding
  validation (option C), polished-text verification,
  loop/deliberation-pin controls in the cockpit form, mapping
  version history, narrative deletion/retention, alerting on
  fired triggers, event-driven evaluation, retention policy
  for evaluation rows, ordering-guard version suppression,
  joint multivariate threshold fitting, automatic weight
  restore, the Sprint 13 fragment-bug fix (own branch, after
  Sprint 14).

## Fix batch 1 — narratives fragment bug + LLM adapter bug (done)

- Delivered on `strategy-engine/fix-batch1-narratives-adapter`
  (see FIX-BATCH-1.md), right after Sprint 14, as approved by
  Ho on 2026-11-16. Not a numbered sprint: two verified bugs
  fixed, with regression tests, no migration, no UI change.
  (1) Narrative generation refused any run with stored
  robustness results or registered gates (verified over real
  HTTP 2026-11-16): `_assemble_direction` validated raw stored
  fragments against read models requiring a top-level `run_id`
  the writers never store. Fixed by validating each
  sub-fragment on its own model and injecting `run_id` — the
  services' own read-path construction; genuinely corrupt
  fragments still refuse before any write. Sprint 14's pinned
  refusal test is replaced with 14 regression tests (5 success
  on enriched runs, 9 corrupt-refusal). (2) LLM adapter bug
  (verified 2026-11-16): `generate_json_for_target` returned
  `(meta, None)` for every successful response because
  `_extract_json_payload` returns a `str` the caller required
  to be a `dict`. Fixed by parsing the payload (`json.loads`,
  decode error → `None`), keeping the requires-dict contract;
  the fix is byte-identical to the verified worktree patch.
  11 new tests pin the REAL method against a fake SDK client
  (previously untested — how the bug shipped). Backend
  1265 → 1289 tests, 0 failed; mypy clean (204 files); Sprint
  0 smoke PASS. Live-LLM verification remains with the
  separate deliberation harness, untouched by this batch.

## Sprint 15 — skill prompt/contract alignment, both directions (done)

- Delivered on `strategy-engine/sprint15-skill-alignment`
  (see SPRINT15.md), from fix batch 1 tip `ba513ef`, as Ho
  directed on 2026-11-16 ("两个方向都做，做完了重新测试").
  No LLM call anywhere in this sprint; the live harness
  re-test is the parent's job after verification. All 17
  skill templates audited field-by-field against their
  Pydantic contracts: 2 evidenced mismatches (the 2026-11-16
  kakouai capture: intake_classify's missing framework
  index + object-shaped wave_plan; crit_intake's nested
  objects where flat strings are required) and 8
  inspection-only shape wordings; 10 prompts rewritten to
  specify exact shapes, 7 byte-identical. The real
  21-framework index exists in the grafted McKinsey skill
  source and is now rendered into the intake prompt.
  Contract side: a deterministic `mode="before"` validator
  normalizes structured shapes to the canonical shapes
  downstream already consumes (object/list → labeled flat
  string; object → one string per key for `list[str]`;
  `{"name", "description"}` option items → name, description
  dropped by design and flagged); conforming input validates
  byte-identical (pinned over 11 fixtures); `extra="forbid"`
  stays; `frameworks` min-1 relaxed to an empty-list default
  (no code consumes it except by serialization). The exact
  captured stage-1 outputs are golden fixtures and now
  validate. Template + contract versions bump `1` → `2` as
  a set (existing single-constant precedent); deliberation
  records pin the versions used. Backend 1289 → 1349 tests,
  0 failed; mypy clean (204 files); Sprint 0 smoke PASS;
  no frontend file changed. Limits: live verification NOT
  done; later-stage templates fixed by inspection only,
  stages 2+ still unobserved live.

## Phase 1 — automotive domain pack + per-tick drivers + split gates (done)

- Delivered on `strategy-engine/phase1-auto-pack` (see
  PHASE1-AUTO-PACK.md), from Sprint 15 tip `ad92029`, as Ho
  directed on 2026-11-16 ("做就行"; full-chain skeleton at
  once, dynamics coarse first; China market; production
  volume spine incl. Audi; bottom layer OEM → nameplate →
  generation → trim → product → supplier share; simulated
  industry-average values authorized, labeled). Design
  authority: the auto-model synthesis (Parts B + C + Ho
  answers). No LLM call anywhere; no cockpit UI changes.
  New: the `automotive` domain pack (27 state fields with
  synthesis §C1 defaults, 10 sales-strategy actions, 6
  event types incl. policy-calendar + DMS switch, 3 actor
  templates with empty overrides, 12-tick default); 10
  keyword-only rules for the §C2 chain; per-tick variable
  drivers (flagged formulas evaluated every tick after
  rule effects, scope = sampled + initial derived + current
  state + `tick`, replay-stable); variable-scaled rule
  effects (`scale_by`, fallback factor 1.0, fixed rules
  unchanged); the built-in automotive template (24
  variables, 8 formulas — 3 initial + 5 drivers — sparse
  B2 fitment-lookup assumption data, replaceable via the
  template mechanism with zero code change); split gates
  (sum-to-1 at nameplate/generation/trim/supplier levels +
  one-host backstop, refuse-before-compute, 400
  `split_validation_failed`, zero rows); automotive report
  generation; loop re-simulation inherits the split
  fragment. Wiring proof: moving the
  consumer-confidence-proxy mode 1.0 → 1.2 moves the retail
  ensemble P50 186.87 → 191.52 (+2.48%); same-seed reruns
  byte-identical; the 10% tax lever cuts retail P50 by
  exactly the 0.9375 level factor. Backend 1349 → 1430
  tests, 0 failed; mypy clean; ruff zero new findings vs
  baseline; migration 0037 up/down/re-up verified; Sprint 0
  smoke PASS. Limits: dynamics coarse by design (literal
  coefficients, no public elasticities); one global
  generation index; S-layer not engine-wired; income/LPR/
  materials links and NEV/ICE dual-track dynamics not
  modeled; cockpit has no automotive views.

## Sprint 16 — seminar core: multi-model rounds over a frozen case (done)

- Delivered on `strategy-engine/sprint16-seminar-core` (see
  SPRINT16.md), from Phase 1 tip `0c5fceb`, as Ho directed on
  2026-11-16 (approved the seminar-mechanism design, start at
  S16). Design authority: the seminar design doc (§16 S16 row;
  §2–§6, §9, §12). Backend only; no live LLM call anywhere
  (fixture/fake-port driven); no scheduler/worker/background
  progression (Sprint 9 boundary). New: migration 0038 with all
  five seminar tables (seminars, seminar_rounds, seminar_board,
  seminar_finals, seminar_reports — the last table-only, S17
  writes it); the parameterized SkillLLMPort (target/temperature/
  timeout per roster entry, defaults primary/0.3, keys only from
  environment variable names); frozen case snapshots (canonical
  JSON + SHA-256; later run products never enter); the append-only
  board (monotonic seq, wave-start snapshot reads, latest_per_model
  policy, quotation rendering with the §4.3 trust boundary); the
  round engine (analysis via existing pipelines + new
  `seminar.reflect` stage, quiet-rounds convergence + hard cap,
  per-model failure isolation, reflection failure preserving the
  analysis); `seminar.reflect` + `seminar.final_verdict` templates
  and contracts (separate registry, version 1 — the 17-template v2
  pin untouched); create/advance/finalize endpoints (chair 503
  with zero rows; GET/synthesize are S17). Acceptance: 3 fake
  models × 3 waves with board seqs 1–9 in wave × roster order and
  snapshot versions 0/3/6; quiet convergence stops a stable model
  at 3 of 5 rounds while a flip-flopping model runs to the cap;
  single-model failures isolated with zero rows beyond passed
  stages. Backend 1430 → 1510 tests, 0 failed; mypy clean; ruff
  zero new findings vs baseline; migration 0038 up/down/re-up
  verified; Sprint 0 smoke PASS. Limits: live port path untested
  (S18 live smoke); no retries/taxonomy/budgets (S18); no token
  accounting; convergence compares exact normalized strings;
  concurrent advances to one seminar are not serialized. Note:
  the full suite has outgrown /tmp's 512M tmpfs — full runs now
  need `TMPDIR=/dev/shm/pytest-tmp`.

## Sprint 17 — seminar chair synthesis: clustering, metrics, versioned reports (done)

- Delivered on `strategy-engine/sprint17-seminar-synthesis` (see
  SPRINT17.md), from S16 tip `4dc21eb`. Design authority: the
  seminar design doc (§16 S17 row; §7 clustering, §8 synthesis +
  deterministic composer, §9 schema, §12 endpoints). Backend
  only; no live LLM call anywhere (fixture/fake-port driven);
  no scheduler/worker/background progression (Sprint 9 boundary
  — synthesis only on explicit POST). No new migration
  (seminar_reports already exists from 0038); the 17-template
  v2 pin untouched. New: deterministic claim pre-pass (exact
  duplicate groups) + LLM semantic clustering with a
  code-built, coverage-enforced merge_map and disagreements
  derived from mixed stances (preserved, never averaged);
  deterministic metrics in code (pairwise recommendation
  agreement, confidence distribution, Borda count, dedup
  statistics) next to the chair's judgment; `seminar.cluster`
  + `seminar.synthesize` contracts and templates (separate
  registry, now 4 templates, version 1, §4.3 trust boundary
  pinned); deterministic composer fallback (Sprint 13
  provenance discipline) with the production path recorded;
  POST /seminars/{id}/synthesize (versioned, append-only
  reports; minimum-2-finals refusals before any write;
  allow_partial partial reports; re-synthesis keeps the same
  deterministic-input hash) and the GET endpoints (detail,
  board, rounds, finals, reports, run seminars). Acceptance:
  2 models × 2 rounds → 11 items → 7 claims, 1 disagreement,
  Borda 3–3 tie broken by name; chair failure → recorded
  deterministic fallback, no exception; 1 final refuses with
  zero rows. Backend 1510 → 1571 tests, 0 failed; mypy clean;
  ruff zero new findings vs 4dc21eb; Sprint 0 smoke PASS.
  Limits: live chair path untested (S18 live smoke); no
  retries/taxonomy/budgets/token accounting (S18); exact-string
  claim matching only; concurrent synthesizes to one seminar
  are refused, not serialized; no cockpit view (S18).

## Phase 2 — S-layer wiring, transmission links, dual track, prompts, cockpit (done)

- Delivered on `strategy-engine/phase2-auto` (see
  PHASE2-AUTO-PACK.md), from Sprint 16 tip `4dc21eb`, built in
  parallel with Sprint 17 (separate worktree/branch), as Ho
  directed on 2026-11-16 (S-layer wired to snapshots; income/LPR/
  materials links + NEV/ICE dual track; cockpit UI; two-
  subpopulation structure for all nameplates; co-occurrence
  prompts, never hard rules). Design authority: the Phase 1
  report, the domain-pack design draft, the auto-model synthesis,
  and the co-occurrence verification report incl. appendices 1–3
  (Q1–Q11 rulings, prompt-system directive, no-generalization
  rule). No LLM call anywhere; no migration. New: S-layer
  computation over stored snapshots (trajectory extraction
  excluding tick 0, per-tick effective structures, caller-supplied
  OEM shares summing to 1, supplier-row/share attribution with
  prospects at 0, strict-prices mode); transmission drivers
  (price/income/penetration/margin + 4 dual-track drivers; F1
  split so income/LPR/price terms apply per tick, not once);
  3 new YAML rules; per-nameplate generation schedules (linear
  interpolation, exactly two generations, hard structural gates);
  the 22-entry prompt catalog (R1–R13/X1–X5/AVM1/BUNDLE1/SCREEN1/
  EMBED1) with the (code, product-line) alias layer, the P.O
  decomposition catalog, and a 9-fact morphology registry; 4 new
  automotive endpoints + the prompt/catalog endpoints; the
  `/cockpit/automotive` page (launcher, trajectory, S-layer form,
  prompt evaluation, catalog). Phase 1 hard gates unchanged; no
  product-level sum gate added. Acceptance: a chip-supply shock
  moves production below baseline every tick and computed sales
  below 75% of baseline. Backend 1510 → 1604 tests, 0 failed;
  frontend 212 → 228, lint + build pass; smoke PASS. Limits:
  coefficients remain labeled assumptions (no public
  elasticities); two rates are documented literals at the Sprint
  2 30-variable cap; schedules are two-generation only; the
  global transition index is still advanced; morphology registry
  holds 9 facts by design; one-host backstop {P01, P04} still
  pending Ho's confirmation.

## Sprint 18 — seminar hardening: retries, budgets, token accounting, near-duplicate pre-pass, synthesize queue, observability + audit log, agent-chair mode (done)

- Delivered on `strategy-engine/sprint18-seminar-hardening` (see
  SPRINT18.md), from merge commit `0ff7642`, per Ho's directives
  of 2026-11-16 14:50 (Glint himself is the chair model; add the
  missing retries + budgets + token accounting; pre-pass beyond
  exact-string matching; concurrent synthesize queues instead of
  refusing; observability + audit logs so any problem is
  locatable). Design authority: the seminar mechanism design
  (§10 error taxonomy/retries/budgets, §16 S18 row), SPRINT16.md,
  SPRINT17.md. No LLM call anywhere. New: agent-chair mode
  (`chair_mode` model/agent; synthesize produces a stored
  versioned chair brief with HTTP 200, no model chair call;
  `POST /chair-synthesis` accepts ClaimClusters + SeminarSynthesis
  under the same contracts and merge-map coverage rule, reports
  with `production_path` `agent_chair` and chair `glint-agent`);
  timeout-only retries (max 2, fixed backoff, per-seminar config);
  per-seminar budgets (`max_stage_calls` 200, `max_tokens`
  1,000,000, seeded from the audit ledger, `budget_exhausted`
  kind); token accounting (scripted usage in fixtures, SDK usage
  on the real port, stage records + rollups + report appendix);
  near-duplicate pre-pass (Jaccard token-set similarity, pinned
  0.8 threshold, single-pass greedy, no chaining, advisory only);
  synthesize queue (per-seminar lock, `queue_wait` events, the
  in-flight refusal removed, stuck state named); the append-only
  `seminar_audit_events` table + `seminar_chair_briefs` table
  (migration 0039, up/down/re-up drilled), 13 event kinds,
  `GET /audit` with kind/model filters, diagnosis summary on GET
  detail, and a formalized six-kind error taxonomy. Backend
  1665 → 1743 tests, 0 failed; smoke PASS; ruff zero new findings;
  mypy clean. Limits: live port path untested (fixture-pinned
  only); the Sprint 6 port returns no usage; the synthesize lock
  is per-process; near-duplicate similarity is token-set Jaccard
  only; version max+1 has no unique constraint; no audit
  retention policy; cockpit seminar views + live smoke still
  queued.

## Sprint 19 — seminar durability: distributed synthesize lock, audit retention, similarity upgrade (done)

- Delivered on `strategy-engine/sprint19-seminar-durability` (see
  SPRINT19.md), from S18 tip `e35c0ce`, per Ho's directives of
  2026-11-16 15:36 (close the S18 limits: per-process lock, no audit
  retention, Jaccard-only similarity). No LLM call anywhere; no
  scheduler/worker (Sprint 9 boundary). New: a lock abstraction with
  two providers selected per seminar by config — `process` (S18
  asyncio-Lock behavior, default) and `lease` (distributed DB leases,
  migration 0040 `seminar_synthesize_leases`, SQLite+Postgres-neutral
  SQL, holder-keyed expiry takeover with fencing tokens, backoff
  polling + configurable wait timeout, `lease_takeover` audit events,
  `seminar_synthesize_lock_timeout` refusal); an explicit audit
  retention policy (`audit_retention_max_events` /
  `audit_retention_max_age_days`, defaults 1000/90, policy-floor
  refusal, `POST /seminars/{id}/audit/purge` writing one
  `retention_purged` summary with monotonic seq and budget-ledger
  roll-forward, `GET /audit/retention` + `retention` on GET detail,
  `GET /audit` shape unchanged); a similarity upgrade (CJK-aware
  tokenization, char-bigram Jaccard combined by MAX with token-set
  Jaccard at the 0.8 threshold, conservative stdlib stemming, zero
  re-pinning of existing tests) plus a pluggable embedding seam
  (`ClaimSimilarity` / `VectorProvider` protocols, fake provider in
  tests, config switch, no real provider). Backend 1743 → 1819
  tests, 0 failed; smoke PASS; ruff zero new findings; mypy clean;
  migration 0040 drill verified by hand. Limits: no lease renewal
  (600s TTL + stuck-state check); lease provider opt-in per seminar;
  diagnosis reflects surviving events only (budgets roll forward);
  lease path verified on SQLite only; no real embedding provider.

## Sprint 20 — cockpit seminar views: list/create + detail, board/rounds/finals, versioned reports, audit log, agent-chair brief + submission (done, frontend only)

- Delivered on `strategy-engine/sprint20-cockpit-seminar` (see
  SPRINT20.md), from `e35c0ce`, per Ho's 2026-11-16 15:36
  "全都开始做". Frontend only: zero `.py` / backend files; built
  only against the API surface at `e35c0ce`, no dependence on the
  parallel Sprint 19 backend work. New routes `/cockpit/seminars`
  (list + create form with roster editor, pipeline-dependent modes,
  chair mode, budgets, retry settings) and
  `/cockpit/seminars/:id` (action bar: advance/finalize/synthesize
  with allow_partial + deterministic_fallback toggles; roster
  progress, budgets, diagnosis; board timeline as quotations;
  per-model rounds comparison; verbatim finals; versioned report
  reader with provenance badges, claims + merge_map, disagreements
  prominent, Borda alternatives, minority report; audit log with
  kind + model_id filters and per-kind detail lines; agent-mode
  chair brief view + ClaimClusters/SeminarSynthesis submission
  form with client-side JSON validation, verbatim server errors,
  deterministic-cluster prefill, and a placeholder guard). Typed
  `seminarApi` (13 endpoints) + types read from
  `routes/seminars.py`. No auto-refresh, no polling. Frontend 228
  → 269 tests, 0 failed; `tsc -b`, lint, and build all clean.
  Limits: the chair brief is in-session only (no GET brief endpoint
  at `e35c0ce`; refresh requires re-synthesizing); the shared 30s
  client timeout may trip on long live-model waves; no
  live-backend or real-browser verification in this sprint.

## Fix batch 2 — live-smoke truncation: unified output cap + truncation kind (done)

- Delivered on `strategy-engine/fix-batch2-truncation`
  (see FIX-BATCH-2.md), from the S19+S20 merge tip `58a56a8`, as
  approved by Ho on 2026-11-16 (Ho also directed the cap policy:
  one loose unified cap, no per-template micro-tuning). Not a
  numbered sprint: one verified live bug fixed, its
  misclassification fixed, and every LLM output cap swept. (1)
  Root cause, verified from the live smoke recorder file: a
  `mckinsey.diagnose` call requested 1500 tokens, the provider
  enforced it exactly (`finish_reason "length"`, 1500 completion
  tokens, JSON cut mid-string), and the audit misreported it as a
  `contract` failure — `finish_reason` appeared nowhere in `src/`.
  The same run shows another provider ignoring the cap and
  returning up to 2408 tokens for a legitimate output, so the
  cliff threatens every model. Fixed with one shared cap,
  `JSON_CONTRACT_MAX_TOKENS = 8000` (3.3x the observed 2408),
  applied to all 17 skill templates, all 4 seminar templates,
  the `generate_json_for_target` default, all 7 structured-output
  sites, all 4 debate sites, both Jarvis sites, all 6 provider
  defaults, and the polish cap; only proven-tiny outputs keep
  small caps (change-detection 8/120, the 32-token connection-test
  ping). Template/contract versions unchanged (parameter-only).
  Budgets + timeouts untouched. (2) Truncation is now surfaced
  (`finish_reason` threaded from both call paths onto
  `SkillLLMResponse`, recorded in the audit detail) and
  classified distinctly: new `SkillTruncatedError` (subclassing
  `SkillContractError`, message names the truncation and the cap)
  and new taxonomy kind `truncated` (seventh kind; never
  retried). Retry-on-truncation is a follow-up option, not
  implemented. No migration, no frontend change (the cockpit
  renders the kind as a free string), no model change (the
  re-run keeps `gpt-5.4` as regression proof). 21 new tests;
  backend 1819 → 1840, 0 failed. Live-LLM verification of the
  fix awaits the re-run on this branch.

## Track A — variable cap 30 → 100 + two literal rates promoted (done)

- Delivered on `strategy-engine/var-cap-100` (see VAR-CAP-100.md),
  from `ccc3490`, per Ho's 2026-11-17 ruling 5. `MAX_VARIABLES`
  30 → 100 (both enforcement gates already read the constant, so
  the refusal kind and messages render the new cap with no logic
  change; the agilhaykal 30-pin attribution is preserved honestly
  in the docstring, the raise recorded as Ho's decision); the
  cockpit label "最多 30 个" → "最多 100 个" (no frontend
  enforcement exists; the backend validator is the single
  enforcement point). The Phase 2 automotive template grows
  30 → 32 variables: `income_growth_rate_annual` (fixed 0.05,
  `NBS via synthesis B4`) and `nev_penetration_monthly_drift`
  (fixed 0.002, `assumption:pending-calibration`); the income
  and penetration tick drivers now reference the variables, and
  the driver outputs (`income_index` 1.0042, `nev_penetration`
  0.481) are asserted identical to the old literal behavior.
  1 new test; branch collects 1841. Subsets green (57 cap +
  template tests, 13 automotive API, smoke PASS); frontend
  268/1 with the same pre-existing Charts flake as the pristine
  baseline, tsc/eslint/build green. Full-suite gate NOT green
  on the branch: best attempt 268 failed / 1573 passed, all
  classified environmental (262 disk I/O + 5 EPERM, 0
  AssertionError, 0 failures in any track-touched file).
  Limits: the penetration drift stays a placeholder magnitude
  (calibration v3 ahead); no Docker verification. Merged as
  `9c00759` (the merge message records the gate gap).
- NOT promoted (out of scope, per the report): the other pack
  literals (price-driver speed, pull-forward decay,
  inventory/chip responses, generation-transition step);
  `MAX_FORMULAS` (40) untouched.

## Track D — retry on truncation + empty response (done)

- Delivered on `strategy-engine/retry-truncation-empty` (see
  RETRY-TRUNCATION-EMPTY.md), from `ccc3490`, per Ho's ruling 9
  (retry on truncation approved; the 2026-11-17 live smoke
  showed the empty response needs the same treatment). Extends
  the Sprint 18 timeout-only retry policy to two more transient
  kinds: the port now affirmatively flags observed-empty
  responses (`empty_response` on `SkillLLMResponse`; a bare
  `payload=None` with no signal stays a plain contract
  failure); the taxonomy gains the eighth kind
  `empty_response` (`SkillEmptyResponseError` subclasses
  `SkillContractError`, like `SkillTruncatedError`);
  `InstrumentedPort` retries RETURNED unusable responses
  (`finish_reason="length"` or the empty flag) under the
  identical treatment (max 2 retries, fixed backoff, budget
  check before every attempt, per-attempt audit), and on
  exhaustion returns the last unusable response so the stage
  runner classifies `truncated` / `empty_response` exactly as
  before; three audit-truthfulness fixes in the same loop
  (finished outcome names the true result; the retry event's
  `error_kind` is no longer hardcoded `"timeout"`). Malformed
  content stays a contract error, never retried. No migration,
  no frontend, no template or version change. Net +29 tests
  (30 added, 1 renamed) → 1869 collected. Gate by partition
  (chunks 01–04: 281 + 311 + 254 + 329 passed, with 2
  unresolved template-listing-order failures in chunk 02 in a
  file untouched by this track) plus a 326-test ring run green
  and smoke PASS; four full-suite attempts all environmentally
  defeated (207/207 failure sections disk I/O / EPERM /
  no-temp-dir, 0 assertion/logic failures). Limits: no
  live-LLM verification (fixture-driven only); same-cap retry
  can re-truncate at 3× call cost; the deliberation path does
  not set the empty flag; no clean single full-suite run
  (chunks 00/05 never ran; cross-chunk order dependence
  unverified). Merged as `b7c53b6`.

## Track E — HUD fitment semantics re-check (done)

- Delivered on `strategy-engine/hud-fitment-check` (see
  HUD-FITMENT-CHECK.md), from `ccc3490`, re-checking the model
  P.O catalog against Ho's 2026-11-17 ruling (P-HUD coexists
  with W/AR-HUD on the same vehicle; penetration rates
  non-exclusive) and Q7 (rates independent, sums need not be
  100%). Verdict: no code enforces or assumes HUD exclusivity
  — no HUD sum gate, no single-choice logic, no HUD overlap
  prompt; the one-host backstop covers {P01, P04} only. Two
  TEXT fixes, zero behavioral change: the HUD_AR catalog note
  rewritten (it asserted substitution and promised a prompt
  that does not exist) and a coexistence note added to the
  HUD_P entry; the prompt-engine docstring qualified ("one
  solution per function" is the normal case behind the
  substitution prompts, never a universal rule). 2 regression
  tests pin the ruling (rates 0.6/0.5/0.4 summing to 1.5
  validate; production volume 100 yields 60/50/40 units
  independently; 0 anomaly prompts). Blast-radius subset
  164/164; full-suite gate NOT achieved (5 attempts, all
  environmental: 331/231/347 failures, all disk I/O / EPERM /
  setup, 0 assertion failures). Limits: AR-vs-W substitution
  asserted neither way (not ruled on); the C-HUD parts-library
  question is separate; no Docker verification. Merged as
  `74e1368`.

## Track C — polish re-check (done)

- Delivered on `strategy-engine/polish-recheck` (see
  POLISH-RECHECK.md), from `ccc3490`, closing the Sprint 13 gap
  (nothing re-validated polished text against the artifact).
  New pure module `services/narratives/recheck.py`:
  `check_polish` compares the polished text against the
  deterministic markdown — numbers as a multiset with exact
  `Decimal` equality (percent ≡ decimal; code spans, UUIDs,
  and identifiers excluded; hyphen ranges yield the first
  endpoint only) plus per-kind provenance-mark counts
  (`[computed]` / `[deliberated]` / `[template]`). A 3-line
  gate in `NarrativeService.polish` runs the check after the
  polish pass returns and before any row is written; failure
  raises `narrative_polish_recheck_failed`, mapped to 502,
  with zero writes. No migration, no template/prompt change,
  no frontend change. 26 tests (24 unit + 2 API: altered
  number → 502 with zero writes; dropped mark → 502 with zero
  writes); unit chunk 1229/1229 green; narratives subsets 66 +
  39; smoke PASS. The root+stress chunk (637 tests) never went
  green: four attempts, all environmental (0 AssertionError;
  tmpfs overflow + the write-denial gate). Limits: live-LLM
  polish quality and the false-refusal rate unverified; mark
  attachment not verified (reordering passes); numbers written
  as words read as dropped figures (fails safe); trace-id
  content not verified; no retry-on-recheck-failure. Merged
  as `0fce5aa`.

## Track B — option C: LLM-proposed decision directions (done)

- Delivered on `strategy-engine/option-c-llm-directions` (see
  OPTION-C.md), from `ccc3490`, Ho-approved 2026-11-16 (the
  Sprint 14 option C). A third direction source alongside
  explicit definitions (Sprint 13) and rule derivation (Sprint
  14): `POST /runs/{run_id}/directions/propose` (template
  `narrative.direction_proposals` v1, `extra="forbid"`, the
  shared 8000-token cap) renders the grounding surface
  deterministically (MECE branches, scenario-family ensembles,
  bound variables, optional guidance); the whole proposal set
  is grounding-validated before any write — an unknown branch,
  run, or variable refuses the entire request with zero rows
  (refuse, not flag), while name collisions are per-proposal
  `skipped` outcomes and proposals never overwrite anything.
  Proposals store as `direction_mappings` rows
  (`origin="llm_proposal"`, migration 0041 adds `status` +
  `proposal_record`, pre-existing rows backfill to `active`);
  explicit accept/reject endpoints (accept re-validates
  references; a stale accept refuses and the row stays
  `proposed`); generation resolves active-only; derive skips
  non-active rows. API-first, no frontend change. 42 tests
  (17 unit + 25 API, fixture-driven); gate by a 6-chunk
  partitioned run (1882 passed, 0 failed; chunk logs under
  `docs/option-c/`); five single-process full runs all
  environmentally defeated (1,440 FAILED lines, 0 assertion
  failures); migration 0041 up/down/re-up drilled on scratch
  SQLite; smoke PASS. Limits: live-LLM proposal quality
  unverified; no cockpit proposal-review UI, and
  `Directions.tsx` mislabels proposal rows as '手动' (the
  backend is authoritative); variable grounding covers stored
  bindings only; the position max+1 race stands as in S14;
  the empty-tree anchor is untested. Merged as `5ba761d`
  (merge conflicts in the narratives `__init__.py` and
  `service.py` — Track C recheck imports vs proposals imports
  — resolved by keeping both, per the merge message).
  `pytest --collect-only` at the merged tip collects 1940
  tests (1840 + 1 + 29 + 2 + 26 + 42).
- NOT built (deferred, per the report): cockpit proposal-review
  UI, proposal ranking/scoring/automatic acceptance, Sprint 14
  option B (variable-override runs), proposal
  regeneration/diffing, a `direction_mapping_history` table.

## Dockerfile build fixes for the hub verification (done)

- Two one-line `Dockerfile` commits on this branch, both found
  during Docker full-stack verification on the hub:
  `3f2bdc5` pins the api base image to
  `python:3.12-slim-bookworm` (`python:3.12-slim` now resolves
  to Debian trixie, where `libgdk-pixbuf2.0-0` was renamed and
  the apt step fails deterministically, exit 100); `23aafb7`
  routes pip installs through the Tencent PyPI mirror (the hub
  uplink runs ~15–20KB/s with stalls exceeding pip's 15s
  default timeout; Ho chose a domestic mirror; the apt line is
  untouched so the cached apt layer stays valid). No test
  evidence in-repo; Docker stack verification remains open
  (see Standing open items).

## Next steps (candidates, need Ho's decision)

- Configure an LLM key and run one real deliberation end-to-end
  (Sprint 6 central open item: live deliberation quality unverified;
  Sprint 7 adds live backend integration as unverified).
- Docker Compose stack verification on a machine with a container
  runtime; GitHub-side fork (needs Ho's account).

## Standing open items

- GitHub-side fork of MingJian needs Ho's account (no GitHub auth in
  the dev environment; nothing pushed).
- Docker Compose stack verification needs a machine with a container
  runtime; LLM-backed paths (debate, LLM-assisted simulation, reports)
  need a real key. Both unverified since Sprint 0.
- Frontend baseline verified on Node v24.22.1 (2026-11-13): vitest 5 files / 13 tests pass, production build (`tsc -b && vite build`) passes, `npm run lint` (eslint) clean — the SPRINT0 "needs Node 22" note no longer holds for test, build, or lint.

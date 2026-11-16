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

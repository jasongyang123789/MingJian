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

## Next steps (candidates, need Ho's decision)

- Configure an LLM key and run one real deliberation end-to-end
  (Sprint 6 central open item: live deliberation quality unverified;
  Sprint 7 adds live backend integration as unverified).
- Living-strategy loop: monitor → re-simulate from the cockpit.
- Calibration hardening (persist current weights, intercept/centering,
  exclude/weight scenario children, fit-quality gates).
- Docker Compose stack verification on a machine with a container
  runtime; GitHub-side fork (needs Ho's account).

## Standing open items

- GitHub-side fork of MingJian needs Ho's account (no GitHub auth in
  the dev environment; nothing pushed).
- Docker Compose stack verification needs a machine with a container
  runtime; LLM-backed paths (debate, LLM-assisted simulation, reports)
  need a real key. Both unverified since Sprint 0.
- Frontend baseline verified on Node v24.22.1 (2026-11-13): vitest 5 files / 13 tests pass, production build (`tsc -b && vite build`) passes, `npm run lint` (eslint) clean — the SPRINT0 "needs Node 22" note no longer holds for test, build, or lint.

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

## Sprint 3 — determinism + sampling (next)

- Determinism hardening (approved enrichment, per adadsws): canonical
  JSON + SHA-256 state hash + replay; seed → RNG wiring (gap G6);
  golden-run test (same seed → byte-identical snapshots).
- Seeded paired Monte Carlo over the Sprint 2 variable tables (per
  agilhaykal/strategic-simulation): sample the validated distributions,
  run baseline-vs-strategy pairs on shared seeds, aggregate P10/P50/P90
  per scenario. Formula graph (derived variables, no arbitrary code) if
  it fits cleanly.
- Branch-level bindings: per-branch variable overrides in
  `create_scenario_run`, same gate; per-branch scope ownership.
- Entry points: `SPRINT2.md` §7.

## Sprint 4 — robustness evaluation (approved enrichment)

- Expected shortfall / tornado sensitivity / threshold search /
  pre-registered decision gates (per taylanakgn) + bootstrap intervals
  (per jasonrkeen), grafted onto the Sprint 3 sampling runner.
- Distribution layer (PRD deltas D4/D5): aggregate across sampled runs;
  scenario-lab ensemble statistics as the aggregation reference.

## Sprint 5 — calibration + deliberation integrity (approved enrichment)

- Hindsight firewall (per saisrikolanu): deliberate separation of
  evidence available at decision time from later outcomes.
- Ridge-to-prior calibration (per jasonrkeen): shrink heuristic
  constants toward calibrated priors using stored run outcomes.
- Gap G5 (uncalibrated heuristic constants) is the target.

## Sprint 6+ — skill grafts + cockpit UI

- Graft the verified Claude Code strategy skills (mckinsey-strategy-team,
  5-persona-advisory-board, strategic-partner, gambit) as prompt
  templates / pipeline stages; prompt/orchestration only, no Claude Code
  runtime features.
- Cockpit UI: MECE authoring, variable-table editing, distribution
  visualization, living-strategy loop (monitor → re-simulate).
- Product decisions still open: making decomposition/bindings mandatory,
  LLM-assisted decomposition authoring (must pass the same gates).

## Standing open items

- GitHub-side fork of MingJian needs Ho's account (no GitHub auth in
  the dev environment; nothing pushed).
- Docker Compose stack verification needs a machine with a container
  runtime; LLM-backed paths (debate, LLM-assisted simulation, reports)
  need a real key. Both unverified since Sprint 0.
- Frontend vitest suite never run (Node 24 vs required 22).

# Sprint 2 — Variable tables (PRD deltas D2/D3)

Date: 2026-11-13. Branch: `strategy-engine/sprint2-variables` (local only,
never pushed), branched from `strategy-engine/sprint1-mece` (`195b8b8`).
Baseline: `SPRINT0.md`, `SPRINT1.md`, `docs/as-is-architecture.md`.

## 1. What was built

A variable-table layer upstream of simulation, porting the variable-table
semantics of agilhaykal/strategic-simulation ("SimplifySimulation",
`backend/engine.py`, verified from source during research) and the
prototype's variable + internal-situation tables
(`~/workspace/strategy-engine/case_example.json`):

- **Module** `src/planagent/services/variables/` — dependency-free
  Pydantic models (`models.py`), a pure deterministic validator
  (`validator.py`), built-in preset synthesis + run-configuration
  resolution (`presets.py`), and storage helpers (`store.py`). The
  validator has no LLM, no randomness, no I/O: identical input yields
  byte-identical output.
- **Variable tables** — a set holds 1–30 variables, each with a unit, a
  distribution (`fixed` / `normal` / `triangular` / `beta_pert` /
  `bernoulli`) plus parameters, and an `evidence_ref` provenance
  reference (an explicit `estimate: ...` reference counts as provenance).
  Sets also carry the prototype's `internal` table (free-form
  key/value context: decision-maker style, team, runway, …).
- **Domain-pack templating** — the hardcoded domain-pack state defaults
  and `_STATE_POLICIES` thresholds are generalized into stored, editable
  templates. The existing corporate/military packs become built-in
  presets (`builtin:corporate`, `builtin:military`) synthesized from the
  pack code at read time, so identical defaults hold by construction —
  presets are never stored or edited.
- **Gate** — `SimulationRunCreate` gains `variable_template_id` and
  `variable_set`. When attached, `create_simulation_run` resolves the
  template, merges the template's variable set with the inline set
  (inline wins per variable id), validates the effective set, and
  cross-checks variable scope tags against the decomposition scope when
  both are attached. Invalid bindings raise before any run row is
  written, mirroring the MECE gate; there is no bypass. Runs without a
  template or bindings behave exactly as before.
- **Execution wiring** — a run carrying a template starts from the
  template's state defaults (before the actor-template and
  `initial_state` overlays, which keep their precedence) and scores
  action alignment, decision-option risk text, and branch comparisons
  against the template's policies. All threading uses optional
  parameters defaulting to the built-in behavior.
- **Endpoints** — `POST /variables/validate` (pure validation; always
  200, verdict in the payload), template CRUD under
  `/variable-templates` (built-ins listed first, read-only), and
  `GET /runs/{run_id}/variables` (stored audit trail). All served bare
  and under `/api`, like all routers.
- **Persistence** — stored templates live in a new `variable_templates`
  table (Alembic migration `0029_variable_templates`, verified upgrade
  + downgrade on scratch SQLite). The template snapshot, merged
  bindings, and validation result are stored in the run's existing
  `configuration` JSON column under the `variables` key, so later
  template edits never rewrite a run's audit trail.

## 2. Validator semantics

Per variable:

- **Distributions** — `fixed` requires `value`; `normal` requires
  `mean` and `std` with `std > 0`; `triangular`/`beta_pert` require
  `min`/`mode`/`max` with `min <= mode <= max` and `min != max`;
  `bernoulli` requires `p` with `0 <= p <= 1`. Missing parameters are
  reported per parameter (`missing_parameter`); violations have
  distinct kinds (`invalid_bounds`, `degenerate_bounds`, `invalid_std`,
  `invalid_probability`). Parameters for other distribution types are
  ignored when present, as in the reference; all numeric parameters
  must be finite JSON numbers (strings, booleans, NaN, and infinities
  are rejected at the model layer).
- **Provenance** — every variable must declare a unit (`missing_unit`)
  and an `evidence_ref` (`missing_evidence_ref`). Both default to empty
  in the model so missing values surface as structured validation
  issues rather than 422s, matching the empty-set rule.
- **Set structure** — at least 1 and at most 30 variables
  (`empty_set`, `too_many_variables`); duplicate ids rejected
  (`duplicate_variable`); duplicate or blank scope tags reported
  (`duplicate_scope_tag`, `invalid_scope_tag`).

Per template (in addition to the per-variable rules):

- State field names must be unique (`duplicate_state_field`). A
  template may carry zero variables (defaults/policies only); the
  empty-set rule does not apply to templates.
- Policy thresholds must be ordered consistently with the direction:
  `increase` requires `alert > critical`, `decrease` requires
  `alert < critical` (`invalid_policy_thresholds`). Built-in presets
  satisfy this by construction.

Cross-check (only when a run carries both a decomposition and
bindings): every variable scope tag must appear in the decomposition
root's scope (`scope_tag_outside_decomposition`). This is root-level
only — per-branch ownership of variables is deferred to Sprint 3.

Deliberate deviations from the reference, documented here:

- The reference validates a whole request (variables + formula graph)
  in one function; here the set validator, the template validator, and
  the scope cross-check are separate pure functions composed by the
  gate, so the validate endpoint, template CRUD, and run creation all
  share the same rules.
- The reference's formula graph and paired Monte Carlo sampling are
  NOT ported in this sprint — sampling belongs to Sprint 3 (see §6).
- The reference rejects correlation between variables; this sprint
  keeps that limit honestly (see §6).

## 3. Integration points

| Change | File |
|---|---|
| `variable_template_id` / `variable_set` fields on the create payload | `src/planagent/domain/api.py` |
| Gate (`_resolve_variable_bindings`) + fragment threading into run creation; effective defaults/policies in `_execute_run` and `_generate_decision_options` | `src/planagent/services/simulation/engine.py` |
| `_resolve_initial_state` accepts template state defaults | `src/planagent/services/simulation/domain_packs.py` |
| Optional `policies` threaded through `_select_action` → `_rank_action_candidates` → `_score_state_alignment` | `src/planagent/services/simulation/impact.py` |
| Optional `policies` on `score_branch_delta`, `metric_compare_score`, `summarize_branch_trajectory`, `metric_outcome_label` | `src/planagent/services/simulation_branching.py` |
| Branch comparisons use the parent run's effective policies; child runs inherit the parent's `variables` fragment via the existing configuration copy | `src/planagent/services/simulation/scenarios.py` |
| Refusal error shapes: 400 `variable_validation_failed` (with validation result) and `variable_template_not_found` / `variable_template_domain_mismatch` | `src/planagent/api/routes/simulation.py` |
| New router + registration | `src/planagent/api/routes/variables.py`, `src/planagent/api/routes/__init__.py` |
| `VariableTemplateRecord` model | `src/planagent/domain/models.py` |
| Migration `0029_variable_templates` | `migrations/versions/0029_variable_templates.py` |

The gate sits in the service, not the route, so every caller of
`create_simulation_run` is gated identically. `VariableValidationError`
and `VariableTemplateError` subclass `ValueError`, so generic
`ValueError` handlers still surface a readable summary; only the
simulation route returns the structured detail. The `services/variables`
package `__init__` exports only the dependency-free modules, so
`domain/api.py` can import `VariableSet` without pulling in the pack
registry or the database layer (same pattern as Sprint 1's MECE
module); `presets` and `store` are imported from their submodules.

## 4. Verification

Environment quirks from Sprint 0 apply unchanged: run pytest with
`env -u NO_PROXY -u no_proxy` (VM proxy vars break httpx client
construction); `.venv` (Python 3.12.3); SQLite + in-memory event bus;
no Docker, no LLM keys.

Full suite (CI command `python -m pytest -q`, sanitized env):
**801 passed, 0 failed, 233.31s** (clean re-run on the finished
branch; an earlier identical run took 229.46s) — the 763 Sprint-1
baseline tests plus 38 new tests. Log: `docs/sprint2/test-full.log`.

New-test breakdown:

- `tests/unit/test_variable_validator.py` — each distribution's valid
  params, missing params, and invalid params; missing unit/provenance;
  empty and oversized sets (30 OK / 31 refused); duplicate ids; scope
  tag issues; scope cross-check; merge semantics (override wins, order
  preserved, internal merge); `validate_or_raise`; template checks
  (duplicate state fields, policy ordering, zero-variable templates,
  oversized templates).
- `tests/unit/test_variable_presets.py` — built-in presets match pack
  defaults and `_STATE_POLICIES` exactly for both domains (field and
  policy counts pinned); unknown domain; resolution helpers with and
  without a fragment; `_resolve_initial_state` equivalence via preset
  snapshot; custom-template overlay; configuration-fragment round-trip;
  branching functions with custom policies.
- `tests/unit/test_variable_golden.py` + `tests/fixtures/` — the
  prototype example case (4 variables, 5 internal entries; fixture
  ported verbatim from the reference case, low/base/high mapped to
  triangular min/mode/max) with a byte-stable expected serialization.
- `tests/test_variable_templates_api.py` — validate endpoint (pass /
  fail kinds / bare + `/api` prefix); template CRUD lifecycle;
  invalid-template and unknown-domain refusal with nothing stored;
  built-in read-only rules and 404s; run binding with preset snapshot
  audit; template + inline merge audit; no-bindings 404; gate refusals
  (invalid set, unknown template, domain mismatch) with zero runs
  created; scope cross-check refusal and acceptance; preset
  equivalence (snapshots identical, tick 0 through tick 2); custom
  state defaults at tick 0 with `initial_state` precedence; scenario
  branch inheritance of the parent template.

Regression notes:

- The first focused run on this branch showed 1 failure:
  `test_unsupported_domain_raises` builds a `SimpleNamespace` stand-in
  for `SimulationRunCreate` that lacked the new fields. Fixed by adding
  `variable_template_id=None, variable_set=None` to the stand-in
  (test-double update, intent unchanged; same pattern as Sprint 1).
- `builtin_template` initially caught only `KeyError` from
  `registry.get`; unknown domains raise `ModuleNotFoundError` from the
  registry's on-demand import path. Fixed by catching both and raising
  `ValueError` (unknown template ids now 404/400 cleanly instead of
  500ing).
- `docs/sprint0/smoke_e2e.py` re-run on this branch: PASS (unchanged
  no-template flow; the smoke evidence file was reverted after the run
  so it does not pollute the diff).
- `ruff format --check` tree-wide: same single pre-existing unformatted
  file as the Sprint 1 baseline (`docs/sprint0/smoke_e2e.py`); all new
  and touched files are formatted. `ruff check` tree-wide: 477 findings
  on the Sprint 1 baseline → 483 here; the +6 are B008 on the new route
  module, the `Depends()`-default pattern every existing route module
  uses. Zero other net-new findings (verified apples-to-apples against
  a worktree of the Sprint 1 branch).
- `mypy src/planagent/` is clean: no issues in 159 source files (153
  Sprint-1 files + 6 new: 5 in `services/variables/` + 1 route module).
- Migration `0029_variable_templates` verified by hand on scratch
  SQLite: `alembic upgrade head` creates the table with all columns and
  indexes and stamps `0029_variable_templates`; `alembic downgrade
  0028_recommendation_version_integrity` drops it. The existing
  migration tests pass in the full suite, and the fresh-DB `create_all`
  path is exercised by every API test's scratch database.

## 5. How to run / verify

```bash
git checkout strategy-engine/sprint2-variables
env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest -q tests/unit/test_variable_validator.py tests/unit/test_variable_presets.py tests/unit/test_variable_golden.py tests/test_variable_templates_api.py
env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest -q   # full suite
.venv/bin/python docs/sprint0/smoke_e2e.py                  # Sprint 0 smoke
```

Example: validate a variable set, create a template, refuse a bad run:

```bash
curl -s -X POST localhost:8000/variables/validate -d '{
  "variables": [{"id": "cac", "unit": "yuan",
    "distribution": {"type": "triangular", "min": 8000, "mode": 12000, "max": 20000},
    "evidence_ref": "estimate: founder judgment"}]}'
# -> 200 {"is_valid": true, "variable_count": 1, "checks": [...], "issues": []}

curl -s -X POST localhost:8000/variable-templates -d '{
  "name": "Lean SaaS", "domain_id": "corporate",
  "state_fields": [{"name": "cash", "default": 80.0}]}'
# -> 201 {"id": "...", "is_builtin": false, ...}

curl -s -X POST localhost:8000/simulation/runs -d '{...,
  "variable_template_id": "builtin:military"}'
# -> 400 {"detail": {"code": "variable_template_domain_mismatch", ...}}
```

## 6. Known limits

1. **Distributions are validated, never sampled.** No Monte Carlo
   runner exists yet: variable values do not influence tick dynamics.
   The template's state defaults and policies DO affect execution
   (initial state, action scoring, risk text, branch comparison), but
   sampling over the variable distributions is Sprint 3 work
   (seeded paired MC per the reference).
2. **No correlation between variables.** The reference rejects it
   explicitly, and this sprint keeps that limit: variables are
   validated independently, and no covariance structure is stored.
3. **Branch-level bindings are inherited, not owned.** Scenario child
   runs inherit the parent's `variables` fragment (template snapshot +
   bindings) through the configuration copy, and branch comparisons use
   the parent's effective policies. Per-branch variable overrides and
   per-branch scope ownership are Sprint 3 items; the scope
   cross-check is root-level only.
4. **Bindings are opt-in.** Runs without a template or inline set are
   unaffected by design (back-compat with all existing callers and the
   Sprint 0 smoke flow).
5. **No formula graph.** The reference's formula graph (derived
   variables computed from other variables, no arbitrary code) is not
   ported; variables are independent inputs. Grafting it is a Sprint
   3/4 decision.
6. **No template authoring UI.** Templates are submitted as JSON.
   Frontend work (Sprint 6+ per the PRD) is untouched.
7. **Docker stack / LLM paths** remain unverified, as in Sprints 0–1
   (no container runtime, no keys on this VM). The gate was verified on
   the SQLite + in-memory-bus dev path only.
8. **Scope tags are exact strings**, as in Sprint 1: no normalization
   or semantic matching is attempted.

## 7. Sprint 3 entry points

1. **Determinism hardening (approved enrichment)** — canonical JSON +
   SHA-256 state hash + replay, per the adadsws deterministic
   market-game engine: hash the run inputs (template snapshot +
   bindings + seed + decomposition) at creation, hash state per tick,
   and add a replay path that re-executes from the stored inputs and
   compares hashes. Thread `SimulationRun.seed` into a
   `random.Random` (G6) so the sampler below is reproducible; add a
   golden-run test (same seed → byte-identical snapshots). The
   `variables` + `mece` configuration fragments are the audit-trail
   pattern to build on.
2. **Seeded paired Monte Carlo (reference: SimplifySimulation)** —
   sample the validated variable sets (fixed/normal/triangular/
   beta_pert/bernoulli) with a seeded RNG; run baseline-vs-strategy
   pairs on shared seeds; aggregate distributions (P10/P50/P90) per
   scenario. The validator's distribution vocabulary is the contract:
   the sampler must accept exactly the distributions the validator
   accepts.
3. **Branch-level bindings** — accept per-branch variable overrides in
   `create_scenario_run`, validated with the same gate, and record
   them in the child run's fragment (overriding the inherited
   snapshot). Consider per-branch scope ownership against the
   decomposition tree's branches, not just the root scope.
4. **Distribution layer (Sprint 4, approved enrichment)** — expected
   shortfall / tornado / threshold search / pre-registered decision
   gates (per taylanakgn) + bootstrap intervals (per jasonrkeen),
   grafted onto the Sprint 3 sampling runner; scenario-lab ensemble
   statistics remain the reference for the aggregation shape.
5. **Calibration (Sprint 5, approved enrichment)** — hindsight
   firewall (per saisrikolanu) + ridge-to-prior calibration (per
   jasonrkeen), using the stored validation results and run outcomes.

## 8. Commits on this branch

- `5947a5e` — variable-table models, pure validator, built-in presets
- `cd53df6` — persistence (model, migration, store)
- `d4c580b` — variable gate + domain-pack templating wiring
- `6df02de` — variable template API + run-binding audit endpoints
- `bd46893` — validation-model fixups found while writing tests
- `0b0b783` — tests for variable tables (38 new)
- (this doc) — Sprint 2 report + backlog + full-suite log

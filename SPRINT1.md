# Sprint 1 — MECE layer (PRD delta D1)

Date: 2026-11-13. Branch: `strategy-engine/sprint1-mece` (local only,
never pushed), branched from `strategy-engine/sprint0-baseline`
(`33efcfb`). Baseline: `SPRINT0.md`, `docs/as-is-architecture.md`.

## 1. What was built

A MECE decomposition layer upstream of simulation, ported from the v0.1
prototype's `check_mece` semantics (`~/workspace/strategy-engine/`):

- **Module** `src/planagent/services/mece/` — Pydantic models for
  decomposition trees (recursive branches with scope tags) and
  validation results, plus a pure, deterministic validator. No LLM, no
  randomness, no I/O: validation is a pure function of the submitted
  tree, and identical input yields byte-identical output.
- **Gate** — `SimulationRunCreate` gains an optional `decomposition`
  field. When attached, `SimulationService.create_simulation_run`
  validates it first and refuses on FAIL: `MeceValidationError` is
  raised before any run row is written, so refusal leaves nothing
  behind. There is no bypass flag. When no decomposition is attached,
  runs behave exactly as before.
- **Endpoints** — `POST /mece/validate` (pure validation; always 200,
  verdict in the payload) and `GET /runs/{run_id}/mece` (stored audit
  trail). Both are served bare and under `/api`, like all routers.
- **Persistence** — the passing decomposition + validation result are
  stored in the run's existing `configuration` JSON column under the
  `mece` key. No Alembic migration: no new table/column was needed.

## 2. Validator semantics

At every node with children:

- **Mutual exclusivity** — children's scope tags must be pairwise
  disjoint. Each shared tag is reported with the two sibling branches.
- **Exhaustiveness** — the union of children's scope tags must equal
  the parent node's scope. Missing tags (`gap`) and tags outside the
  parent scope (`extra`) are reported separately, with sorted tag lists.
- **Structure** — a decomposition with no branches (`empty_tree`), a
  branch covering no scope tags (`empty_branch`), duplicate tags inside
  one branch's own scope list (`duplicate_tag`), and trees deeper than
  10 levels (`max_depth_exceeded`) all fail.

Overlap detection is structural (scope-tag identity). The
HypothesisTree Pro reference (`mece_validator.py`) was consulted only
for its L1/L2/L3 structure and hard-vs-soft failure distinction; its
keyword-heuristic overlap detection was explicitly NOT adopted.

Deliberate deviations from the prototype, documented here:

- The prototype is silent on a root with no children (no records, so it
  "passes"). Here an undecomposed tree fails with `empty_tree`: a
  decomposition that does not decompose is not a decomposition.
- The prototype flags a tag repeated inside one branch as an overlap
  with itself. Here that is a distinct `duplicate_tag` issue located at
  the owning branch; `overlap` is reserved for tags shared across
  siblings.
- Per-node check records cover `mutual_exclusion`, `exhaustiveness`,
  and `structure` at internal nodes only (as in the prototype); the
  `issues` list is the complete failure inventory, including leaf-level
  problems located at precise node paths (`root / A / A1`).

## 3. Integration points

| Change | File |
|---|---|
| `decomposition: DecompositionTree \| None` field on the create payload | `src/planagent/domain/api.py` |
| Gate + audit-trail fragment in run configuration | `src/planagent/services/simulation/engine.py` (`create_simulation_run`, `_create_corporate_run`, `_create_military_run`, `_mece_configuration_fragment`) |
| Refusal error shape: 400, `{"code": "mece_validation_failed", "message": ..., "validation": {...}}` (repo's dict-detail shape, cf. `api/edition.py`) | `src/planagent/api/routes/simulation.py` |
| New router + registration | `src/planagent/api/routes/mece.py`, `src/planagent/api/routes/__init__.py` |

The gate sits in the service, not the route, so every caller of
`create_simulation_run` (API route, admin replay, assistant, watch
execution) is gated identically. `MeceValidationError` subclasses
`ValueError`, so any generic `ValueError` handler still surfaces a
readable summary; only the simulation route returns the structured
detail. Scenario branching (`create_scenario_run`) does not accept
decompositions and is untouched — see §6.

## 4. Verification

Environment quirks from Sprint 0 apply unchanged: run pytest with
`env -u NO_PROXY -u no_proxy` (VM proxy vars break httpx client
construction); `.venv` (Python 3.12.3); SQLite + in-memory event bus;
no Docker, no LLM keys.

<!-- FINAL NUMBERS: filled in from the clean re-run on the finished branch. -->
Full suite (CI command `python -m pytest -q`, sanitized env):
**763 passed, 0 failed, 244.72s** (clean re-run on the finished
branch) — the 736 Sprint-0 baseline tests plus 27 new tests (18
validator unit tests, 2 golden tests, 7 API tests). Log:
`docs/sprint1/test-full.log`.

New-test breakdown:

- `tests/unit/test_mece_validator.py` — disjoint pass; overlap/gap/
  extra failures; empty tree; duplicate tags (within-branch and root
  scope); empty-scope branches; nested branches (pass + deep overlap +
  deep gap); single-branch full/partial coverage; max depth;
  determinism + input purity; `validate_or_raise`; model rejection of
  empty names/blank tags.
- `tests/unit/test_mece_golden.py` + `tests/fixtures/` — the prototype
  example case (12 scope tags, 4 branches; fixture copied verbatim from
  the reference case) with a byte-stable expected serialization.
- `tests/test_mece_api.py` — validate endpoint (pass/fail/422, bare +
  `/api` prefix); gate refusal with zero runs created (overlap and gap
  cases); gate pass + audit-trail retrieval; no-decomposition runs
  unchanged; 404s.

Regression notes:

- The first full run on this branch showed 1 failure:
  `test_unsupported_domain_raises` builds a `SimpleNamespace` stand-in
  for `SimulationRunCreate` that lacked the new field. Fixed by adding
  `decomposition=None` to the stand-in (test-double update, intent
  unchanged). No production-code change was needed.
- `docs/sprint0/smoke_e2e.py` re-run on this branch: PASS (unchanged
  no-decomposition flow).
- `ruff format --check` is clean tree-wide. `ruff check` has 441
  pre-existing baseline findings; this sprint adds zero net-new
  findings except B008 on the new route, the `Depends()`-default
  pattern every existing route module uses.
- `mypy src/planagent/` is clean: no issues in 153 source files
  (verified on this branch; the new package is fully typed).
- One combined focused run showed 4 API-test failures while a full
  suite ran concurrently on this small VM; clean re-runs (isolated
  modules and the full suite, single-process) pass consistently, so
  this was treated as environmental contention, not order-dependence.

## 5. How to run / verify

```bash
git checkout strategy-engine/sprint1-mece
env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest -q tests/unit/test_mece_validator.py tests/unit/test_mece_golden.py tests/test_mece_api.py
env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest -q   # full suite
.venv/bin/python docs/sprint0/smoke_e2e.py                  # Sprint 0 smoke
```

Example refusal (overlap case):

```bash
curl -s -X POST localhost:8000/simulation/runs -d '{...,
  "decomposition": {"topic": "...", "root": {"name": "R",
    "scope": ["demand", "cost"],
    "children": [{"name": "Demand", "scope": ["demand", "cost"]},
                 {"name": "Cost", "scope": ["cost"]}]}}}'
# -> 400 {"detail": {"code": "mece_validation_failed",
#      "message": "Decomposition failed MECE validation; simulation refused.",
#      "validation": {"is_mece": false, "issues": [{"kind": "overlap", ...}]}}}
```

## 6. Known limits

1. **Decomposition is opt-in.** Runs without an attached decomposition
   are unaffected by design (back-compat with all existing callers and
   the Sprint 0 smoke flow). Making it mandatory is a product decision
   for a later sprint, not taken here.
2. **Scenario branches are not gated.** `create_scenario_run` creates
   child runs without a decomposition payload; gating branches (or
   inheriting the parent's decomposition) is Sprint 2+ work.
3. **No decomposition authoring UI.** Trees are submitted as JSON.
   Frontend work (Sprint 6+ per the PRD) is untouched.
4. **No LLM-assisted decomposition.** Trees are user-supplied. An
   LLM-suggested tree would still pass through this same validator
   before any run — the gate does not care where the tree came from.
5. **Docker stack / LLM paths** remain unverified, as in Sprint 0 (no
   container runtime, no keys on this VM). The gate was verified on the
   SQLite + in-memory-bus dev path only.
6. **Scope tags are exact strings.** Near-duplicate tags ("cost" vs
   "costs") are distinct tags; no normalization or semantic matching is
   attempted. That is intentional: the validator checks structure, not
   meaning.

## 7. Sprint 2 entry points

1. **Variable tables (PRD D2/D3)** — generalize
   `simulation/domain_packs/*/pack.py` defaults +
   `services/simulation_branching.py:_STATE_POLICIES` into stored,
   editable templates. Natural companion: let decomposition branches
   carry variable bindings, validated against the same scope tags.
2. **Branch gating** — thread the parent run's stored decomposition
   into `create_scenario_run`, or accept an overriding decomposition
   per branch with the same gate.
3. **Seed/RNG wiring (G6)** — thread `SimulationRun.seed` into a
   `random.Random` in `services/simulation/engine.py` / `impact.py`;
   add a golden-run test (same seed → byte-identical snapshots). The
   MECE audit trail in `configuration` is the pattern to follow for
   recording run inputs.
4. **Distribution layer (PRD D4/D5)** — sampling runner around
   `_execute_run`; aggregate `StateSnapshotRecord` /
   `DecisionRecordRecord` across runs; graft scenario-lab ensemble
   statistics. MECE validation stays a pre-run gate: sample runs of a
   refused decomposition must never execute.

## 8. Commits on this branch

- `208c329` — MECE module (models + validator)
- `422bdfe` — gate integration + endpoints + error shape
- `0d4bac6` — tests + golden fixtures
- `10ac98a` — lint/format polish + test-double fix
- (this doc) — Sprint 1 report + full-suite log

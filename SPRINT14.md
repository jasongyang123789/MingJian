# Sprint 14 — Direction auto-derivation + persisted mappings

Branch: `strategy-engine/sprint14-direction-derivation`, from
`strategy-engine/sprint13-decision-narrative` @ `e96abd0`. Nothing
pushed. Ho chose options A + D together on 2026-11-16, after the
design discussion: deterministic rule-based derivation (A) plus
persisted direction mappings (D). All three priority items landed:
(1) backend derive + mappings + narrative integration, (2) cockpit
derive + mappings UI, (3) delete UI. No LLM call was made anywhere
in this sprint — derivation is pure arithmetic over stored
ensembles, and generation from mappings reuses the Sprint 13
deterministic composer unchanged.

This sprint closes the deliberate gap Sprint 13 left open:
directions no longer come only from explicit per-request
definitions. The engine can now derive 1–3 directions from the
anchor run's scenario family by versioned rules, store them as
editable mappings, and generate narratives from the stored
mappings — with a no-clobber rule that never silently overwrites a
user's edit.

## 1. What was built

### Derivation (`services/narratives/derivation.py`, new, pure)

`derive_directions(anchor_run_id, candidates) -> DerivationResult`
is a pure function: no I/O, no clock, no randomness, no new runs.
The service assembles `DerivationCandidate` records from the
stored ensembles of the anchor run's scenario family; the
derivation applies three versioned rules (`derivation-rules-v1`)
in fixed order and reports an outcome for EVERY rule. The result
carries no ids or timestamps, so its canonical JSON + SHA-256 is
stable across repeated derivations (asserted by test, §4).

Candidate set: every COMPLETED run in the anchor run's scenario
family (root ancestor + descendants, the Sprint 10 family rule)
that has a stored ensemble, each `(run, arm)` pair one candidate.
Arms are the ensemble's two fixed summaries, `baseline` and
`strategy`.

Rules, in evaluation order (tie-breaks pinned exactly — see §2):

1. `highest_p50` → "Highest P50": max P50; ties by lowest loss
   probability, lowest run id, lowest arm.
2. `most_robust` → "Most robust": min loss probability; ties by
   stored lower-tail expected shortfall (present beats absent,
   higher value wins), highest P50, lowest run id, lowest arm.
3. `baseline_control` → "Baseline": the anchor run's `baseline`
   arm, when the anchor has a stored ensemble.

Dedup: a rule selecting a `(run, arm)` pair already taken by an
earlier rule reports `duplicate` (naming the earlier rule) and
emits nothing. Directions are capped at `MAX_DIRECTIONS` (4; with
3 rules the cap never binds in v1). Names are mechanical, from
the rule; renaming is the mapping layer's job. A rule that finds
no candidate reports `none` with the reason — nothing is
fabricated.

### Persistence (`domain/models.py`, migration 0036)

New table `direction_mappings` (migration
`0036_direction_mappings`, revises `0035_decision_narratives`,
verified upgrade → downgrade → re-upgrade on scratch SQLite; see
§4): id, anchor_run_id (FK, index), name, source_run_id (FK),
arm, mece_branches (JSON), deliberation_id (nullable), origin
(`derived` | `authored`), rule_id / rules_version / rule_record
(the derivation outcome detail + derivation hash, on derived
rows), user_edited flag, position (generation order), created_at
/ updated_at. Names are unique per anchor run, enforced in code
AND by a DB unique constraint (`uq_direction_mappings_anchor_name`).

The same migration adds a nullable `direction_mapping_ids` JSON
column to `decision_narratives`, recording which mappings a
generation resolved its directions from (NULL for inline
generations and pre-Sprint-14 rows). The artifact body is
untouched: content hashes keep their Sprint 13 meaning.

Storage choice justification: a new table, not a run-summary key
— same reasoning as Sprint 13's narratives table. Mappings are
independently queryable, editable, deletable rows with their own
identity (generation pins their ids); a summary fragment cannot
carry uniqueness, ordering, or edit history. The
`direction_mapping_ids` column (rather than a join table) fits
because the link is informational and append-only: deleting a
mapping must not touch generated narratives, and the column
preserves the audit trail after deletion.

### Service (`services/narratives/service.py`, extended)

- `derive`: explicit trigger only. The anchor must exist (404)
  and be COMPLETED; the family is enumerated (up-walk to the
  root with cycle/dangling guards, then breadth-first descent);
  candidates are assembled from stored ensembles plus the
  lower-tail expected-shortfall sub-fragment (see the known-bug
  note below). No ensembles anywhere in the family → named 4xx
  `direction_no_ensemble` stating the monte-carlo endpoint to run
  first, before any write. Produced directions are upserted
  by name; a user-edited mapping of the same name is NEVER
  overwritten — the outcome is reported as `skipped` and the row
  is left untouched (the no-clobber rule). Renaming a mapping
  frees its mechanical name: the next derive inserts a fresh row
  under that name. The response carries the derivation hash,
  family size, candidates considered, every rule's outcome, and
  the full post-write mapping list.
- Mapping CRUD: `list_mappings` (position order), `create_mapping`
  (authored, position max+1), `update_mapping` (rename/re-point;
  omitted fields unchanged; explicit null clears only the
  deliberation pin; any successful update sets `user_edited`),
  `delete_mapping` (mappings only — generated narratives are
  untouched, asserted by test). Every write validates references
  before any row is written: source run exists + COMPLETED +
  holds an ensemble, MECE branches name branches of the anchor
  tree, deliberation pins exist on the source or anchor run.
  Name conflicts refuse with `direction_mapping_name_conflict`.
- Generation integration: `NarrativeGenerateRequest.directions`
  is now optional. Inline definitions always win (Sprint 13
  behavior, including input pins, byte-identical). When omitted,
  definitions resolve from stored mappings in position order,
  capped at 4, and the mapping ids used are pinned in the
  inputs hash (service layer only — the composer is untouched
  except for one docstring line, see §3) and stored on the row.
  Neither directions nor mappings → named 400
  `narrative_requires_directions`, naming the derive endpoint.

Known-bug note (read carefully): the derive path reads the
`expected_shortfall` sub-fragment directly with its own model. It
deliberately does NOT validate the whole robustness fragment
against `RobustnessRead`: the stored fragment has no top-level
`run_id` (writers store per-analysis sub-fragments), so
whole-fragment validation always fails — the verified Sprint 13
bug in `_assemble_direction` (see §6 and the verification report
at `~/workspace/verification/backend-integration-2026-11-16/REPORT.md`
§5). The fix gets its own branch after Sprint 14, as directed;
Sprint 14 changes no Sprint 13 validation behavior. The derive
path follows the Sprint 6 context-builder precedent (sub-key
access) and the services' own read paths (validate each
sub-fragment individually).

### Endpoints (`api/routes/narratives.py`, extended; no new wiring)

- `POST /runs/{run_id}/directions/derive` (200): derivation run
  + outcomes + mappings. 200, not 201: a derive may legitimately
  write zero rows (all outcomes none/duplicate/skipped).
- `GET /runs/{run_id}/directions/mappings`: position order.
- `POST /runs/{run_id}/directions/mappings` (201): authored mapping.
- `PUT /runs/{run_id}/directions/mappings/{mapping_id}`: update.
- `DELETE /runs/{run_id}/directions/mappings/{mapping_id}` (204,
  empty body, Sprint 12 `deleteNoContent` precedent).

Error codes (all `DirectionError` → 400 with a `{"code",
"message"}` detail; missing runs/mappings → 404):
`direction_requires_completed_run`,
`direction_no_ensemble` (names the monte-carlo endpoint),
`direction_mapping_name_conflict`,
`direction_unknown_source_run`,
`direction_source_run_not_completed`,
`direction_source_run_no_ensemble`,
`direction_unknown_mece_branch`,
`direction_mece_branches_without_tree`,
`direction_deliberation_not_found`,
`direction_corrupt_fragment`. Request-shape violations (empty
name, 0 directions in an explicit list, explicit nulls on
non-nullable update fields) are Pydantic 422s.

### Cockpit directions view (`frontend-v2`, `/cockpit/directions` extended)

- Derive card: "推导方向" button + outcomes display (every rule:
  rule label, what was selected with P50/loss, or why nothing /
  duplicate / skipped), rules version, family size, candidates
  considered, derivation hash; refusal errors shown with code +
  message.
- Mappings card: list with origin badges （推导/手动） and
  "已编辑" marks, inline rename/re-point editing (name + source
  run + arm; saving marks the row user-edited), and two-step
  confirmation delete (Sprint 12 precedent; 404 reloads the list
  back to the truth). Honest empty state.
- Generate card: "使用已存方向映射生成" toggle — when on, the
  drafts hide, the mappings to be used (first 4, position order)
  are listed with an over-cap note, and generation posts no
  `directions` key; the button disables while no mappings exist.
- The reading view shows which stored mappings a narrative used
  ("本简报使用了已存映射：…", resolved by id; a deleted mapping
  shows as such with a short id). Inline generations show no
  such line.

## 2. Design decisions

### Tie-break rules (exact, as implemented)

Candidates are pre-sorted by `(run_id, arm)`; each rule is a
total order, so selection is deterministic and independent of
input order (asserted by test with shuffled inputs).

- `highest_p50` key: `(-p50, p_loss, run_id, arm)` — highest P50,
  then lowest loss probability, then lowest run id, then lowest
  arm (`baseline` < `strategy` alphabetically).
- `most_robust` key: `(p_loss, es_missing, -es_value, -p50,
  run_id, arm)` — lowest loss probability, then a stored
  lower-tail expected shortfall beats none, then the HIGHER
  shortfall value wins (the tail mean is less bad: -2.0 beats
  -5.0), then highest P50, then ids. Only the lower tail counts:
  the loss-probability primary already assumes lower-is-worse
  (loss = below the threshold), and an upper-tail shortfall
  answers a different question; upper-tail-only results are
  treated as absent. The alpha of a deciding shortfall is pinned
  on the outcome. Known limitation, stated plainly: shortfall
  values computed at different alphas are compared as stored
  numbers; the pinned alpha keeps the comparison auditable, and
  the default alpha (0.05) is what the cockpit and tests use.
- `baseline_control`: no ordering — the anchor's `baseline` arm
  if present among the candidates, else `none`.

### Rule evaluation order and dedup

Rules run in fixed order (highest_p50 → most_robust →
baseline_control); the FIRST rule to select a `(run, arm)` pair
owns it. Later rules report `duplicate` naming the owner. This
makes the "Highest P50" direction stable: it is never stolen by
a later rule. The derivation record lists every rule's outcome,
including `none` and `duplicate` — a silent rule would hide
exactly the information a reviewer needs.

### The no-clobber rule

Derive upserts by name, but a mapping with `user_edited` set is
never overwritten — not even re-pointed. Rationale: a rename or
re-point is the user asserting judgment over the rule; silently
reverting it on the next derive would destroy work and trust.
The `skipped` outcome says so explicitly. Renaming frees the
mechanical name (a fresh derived row appears under it), which is
the escape hatch when the user wants the rule's choice back
alongside their edited one. `user_edited` is set by ANY
successful update (even a no-op save) and is never cleared by
derive; there is no API to clear it (deliberate: clearing would
re-expose the row to overwrites without an audit trail).

### Position, not timestamps, orders mappings

Generation order is the explicit integer `position`: derive
writes in rule order, authored rows take max+1. Timestamps
cannot order rows written in one transaction (identical
instants), and ids are random UUIDs. Updates never change
position; deletes leave gaps, which is harmless.

### What was deliberately NOT built

- No automatic derivation: derive is an explicit POST, never
  triggered by narrative generation (Sprint 9 automation
  boundary). Generation from mappings reads rows; it never
  derives.
- No new simulation runs: derivation reads stored ensembles
  only. Directions as variable overrides (option B from the
  design discussion) remain a future design, not this sprint.
- No LLM involvement: no proposal stage, no naming stage. Names
  are mechanical; the user renames.
- No mapping versioning/history: updates overwrite the row
  (updated_at bumps). Generated narratives keep their own
  versioned artifacts; mappings are working state, not
  deliverables.
- No deliberation-pin or MECE-branch editing in the cockpit form
  (API-only, same boundary as Sprint 13's form). Derived
  mappings carry no branches/pins; users add them via the API.

## 3. Integration points

- **Reads only, plus its own table.** The narratives service
  reads run fragments (ensembles, expected-shortfall
  sub-fragments), the `strategy_loops` table not at all, and
  writes only `direction_mappings` + the new narrative column.
  No behavior change to the simulation engine, firewall,
  robustness, distributions, skills, calibration, or living-loop
  packages; no existing endpoint, model, or migration was
  modified (only additive wiring: new record class, new column,
  new routes in the existing narratives router, new service
  methods).
- **Composer untouched except one docstring line.** The module
  docstring's rule 1 ("directions come ONLY from the request's
  definitions") is corrected to mention stored mappings resolved
  by the service. Zero behavior change; the diff is docstring
  only, verified by inspection.
- **Reuse, not duplication.** Canonical JSON + SHA-256 from
  Sprint 3, the Sprint 10 family rule (root ancestor +
  descendants via `parent_run_id`), `_collect_branches` from the
  composer (single source of truth for branch names), the
  Sprint 9/11 route error-mapping pattern, the Sprint 12
  204-safe delete transport + two-step confirmation.
- **Frontend.** Extended route + new typed clients and mirrors
  only; no existing component was modified except the Directions
  page itself. `NarrativeGenerateRequest.directions` became
  optional in the mirror (matching the backend); the
  `narrativeRead` fixture gained `direction_mapping_ids: []`.
- **Migration chain.** `0036_direction_mappings` revises
  `0035_decision_narratives`; head is 0036 after upgrade.

## 4. Verification

- Full backend suite: **1265 passed / 0 failed** in 378.88s
  (baseline 1231 + 16 new derivation unit tests + 18 new API
  tests). Log: `docs/sprint14/test-full.log` (force-added past
  the `*.log` ignore, per precedent). Note: the first full-suite
  run reported 42 failures, all `sqlite3.OperationalError:
  database or disk is full` — `/tmp` (512M tmpfs) had filled
  with pytest scratch directories; none of the 42 was a Sprint
  14 test. After clearing `/tmp/pytest-of-root`, the re-run
  passed fully; the log holds the clean re-run.
- Frontend: **212 passed** (baseline 206 + 6 new),
  `npm run lint` clean, `npm run build` passes.
- `mypy src/planagent/`: clean, 204 source files, no issues.
- `ruff check` on new/changed files: clean except the
  pre-approved B008 `Depends()` pattern (9 occurrences in
  `api/routes/narratives.py`: 4 from Sprint 13 + 5 new
  endpoints) and 35 findings in `domain/models.py` verified
  byte-identical at HEAD via `git show HEAD:` — pre-existing,
  left untouched; this sprint's additions introduced zero new
  findings there. `ruff format` clean on new/changed files.
- Migration: scratch SQLite upgrade 0035 → 0036 (table +
  column present, unique constraint present), downgrade →
  0035 (both gone), re-upgrade → head
  `0036_direction_mappings`.
- Sprint 0 smoke re-run: **PASS** (health → ingest → 4-tick
  simulation → decision trace → workbench → options); the
  refreshed `smoke-evidence.json` was reverted per precedent.

### Behavior evidence (all asserted test values, with test names)

Derivation — tie-breaks, dedup, byte identity
(`tests/unit/test_direction_derivation.py`):

- `test_derive_highest_p50_tie_breaks_by_loss_then_run_then_arm`:
  P50s 30/10/30/30 with losses 0.2/0.1/0.1/0.1 select
  (run-b, baseline) — the three-way P50 tie breaks on loss,
  then run id, then arm.
- `test_derive_most_robust_prefers_shortfall_then_p50`: p_loss
  tied at 0.1 across three candidates; the stored shortfall
  beats none (run-a baseline loses despite P50 50), and -2.0
  beats -5.0; the winner pins expected_shortfall -2.0, alpha
  0.05.
- `test_derive_most_robust_falls_back_to_p50_without_shortfall`:
  with no shortfall stored, the p_loss tie breaks on P50
  (run-b, P50 40).
- `test_derive_baseline_control_selects_anchor_baseline` /
  `test_derive_baseline_control_none_without_anchor_ensemble`:
  the anchor baseline is selected even with P50 1.0 / loss 0.9;
  without an anchor ensemble the outcome is `none` naming the
  anchor run.
- `test_derive_duplicate_reported_and_not_emitted`: a single
  candidate yields statuses `[produced, duplicate, duplicate]`,
  both duplicates naming `highest_p50`, exactly 1 direction.
- `test_derive_duplicate_names_earlier_rule_only`: statuses
  `[produced, duplicate, produced]`, directions
  `["Highest P50", "Baseline"]`.
- `test_derive_empty_candidates_all_rules_none`: all three
  outcomes `none`, zero directions.
- `test_derive_same_inputs_byte_identical`:
  canonical JSON and SHA-256 equal across two derivations with
  shuffled candidate order.
  `test_derive_different_input_changes_hash`: P50 30 vs 31
  yields different hashes.
- `test_lower_tail_shortfall_returns_value_and_alpha` /
  `test_lower_tail_shortfall_ignores_upper_tail` /
  `test_lower_tail_shortfall_absent_without_result`: lower tail
  returns (-3.5, 0.1) baseline / (-1.5, 0.1) strategy; upper
  tail and absent results return (None, None).

Derivation + mappings — API (`tests/test_direction_derivation_api.py`,
real runs + scenario branches + ensembles through the HTTP layer):

- `test_derive_writes_mappings_from_family`: parent + 2
  children, ensembles on all three → family_size 3,
  candidates_considered 6, rules_version
  `derivation-rules-v1`, all three rule outcomes matching the
  winners computed from the stored summaries read back via the
  API, mappings in position order with origin `derived` and the
  derivation hash pinned in each rule_record; a second derive
  returns the identical derivation_hash and the same mapping
  ids.
- `test_derive_refuses_without_ensemble_and_writes_nothing`:
  400 `direction_no_ensemble`, message names the run's
  monte-carlo URL; mappings list stays empty.
- `test_derive_refuses_noncompleted_anchor` /
  `test_derive_unknown_run_404`: 400
  `direction_requires_completed_run` / HTTP 404.
- `test_derive_uses_lower_tail_shortfall`: lower-tail ES stored
  at alpha 0.1 → derive SUCCEEDS (200) on the enriched run and
  the most_robust outcome pins the selected arm's stored ES
  value and alpha 0.1.
- `test_derive_ignores_upper_tail_shortfall`: upper-tail ES
  stored → most_robust outcome carries expected_shortfall null.
- `test_derive_never_overwrites_user_edited_mapping`: re-pointing
  "Highest P50" then re-deriving yields outcome `skipped`
  (reason names user-edited) and the row keeps the user's arm
  with `user_edited` true.
- `test_derive_recreates_freed_name_after_rename`: renaming a
  derived mapping then re-deriving restores the mechanical name
  as a fresh row alongside the renamed one, names unique.
- `test_create_mapping_and_name_conflict`: 201, origin
  `authored`, position 0; duplicate name → 400
  `direction_mapping_name_conflict`, list stays at 1.
- `test_create_mapping_refusals`: unknown source run,
  non-completed source, ensemble-less source, unknown MECE
  branch, unknown deliberation pin, branches-without-tree —
  each a named 400, zero rows written.
- `test_update_mapping_sets_user_edited_and_revalidates`:
  rename + re-point + arm change apply with `user_edited`
  true; conflicting rename and unknown branch refuse and leave
  the row unchanged.
- `test_mapping_wrong_run_404`: update/delete under the wrong
  run id are 404; the mapping survives.
- `test_generate_from_mappings_uses_position_order_and_caps_at_four`:
  5 stored mappings → narrative with 4 directions,
  `direction_mapping_ids` equal to the first 4 mapping ids in
  position order, visible on list/get too.
- `test_generate_with_null_directions_uses_mappings`:
  explicit `"directions": null` resolves stored mappings.
- `test_generate_inline_definitions_win_over_mappings`: inline
  directions produce the inline-named direction with
  `direction_mapping_ids` empty.
- `test_generate_without_directions_or_mappings_refuses`: 400
  `narrative_requires_directions`, message names the derive
  endpoint.
- `test_delete_mapping_leaves_narratives_untouched`: DELETE →
  204 with an empty body; the generated narrative keeps its
  content_hash and its (now-dangling, informational) mapping
  id; mappings list empty.
- `test_generate_refuses_enriched_run_known_sprint13_bug`:
  run + ensemble + tornado → 400
  `narrative_corrupt_fragment` — the known Sprint 13 bug,
  pinned explicitly (see §6). This test documents current
  behavior until the fix branch lands; it is expected to
  change there.

Cockpit (`Directions.test.tsx`, mocked fetch):

- Derive posts and renders every rule outcome (version, family
  size, selection text, duplicate note) plus the written
  mapping; a 400 refusal shows its code and message.
- Mapping edit posts exactly `{name, source_run_id, arm}` and
  shows the renamed row; delete requires the two-step
  confirmation and removes only the confirmed row.
- Generate-from-stored posts `{topic: null, loop_id: null}`
  with NO directions key and shows "本简报使用了已存映射：
  Highest P50"; with no mappings the toggle shows the honest
  hint and the generate button is disabled.

## 5. How to run / verify

```bash
# Backend unit + API tests for this sprint
env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest tests/unit/test_direction_derivation.py tests/test_direction_derivation_api.py tests/test_narratives_api.py -q

# Full backend suite (log at docs/sprint14/test-full.log)
env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest -q

# Type + lint (new/changed files)
.venv/bin/python -m mypy src/planagent/
.venv/bin/python -m ruff check src/planagent/services/narratives/ src/planagent/api/routes/narratives.py tests/unit/test_direction_derivation.py tests/test_direction_derivation_api.py
.venv/bin/python -m ruff format --check src/planagent/services/narratives/ src/planagent/api/routes/narratives.py tests/unit/test_direction_derivation.py tests/test_direction_derivation_api.py

# Migration check on scratch SQLite
PLANAGENT_DATABASE_URL="sqlite:////tmp/mig36/check.db" .venv/bin/python -m alembic upgrade head
PLANAGENT_DATABASE_URL="sqlite:////tmp/mig36/check.db" .venv/bin/python -m alembic downgrade 0035_decision_narratives
PLANAGENT_DATABASE_URL="sqlite:////tmp/mig36/check.db" .venv/bin/python -m alembic upgrade head

# Frontend
cd frontend-v2 && npm test -- --run && npm run lint && npm run build

# Smoke (Sprint 0, revert the evidence file afterward)
env -u NO_PROXY -u no_proxy .venv/bin/python docs/sprint0/smoke_e2e.py
git checkout -- docs/sprint0/smoke-evidence.json
```

Derive + generate against a running backend:

```bash
# 1. A completed run with an ensemble (see SPRINT3.md), then:
curl -X POST localhost:8000/runs/<run_id>/directions/derive
curl localhost:8000/runs/<run_id>/directions/mappings
curl -X POST localhost:8000/runs/<run_id>/narratives -H 'Content-Type: application/json' -d '{}'
```

## 6. Known limits

- **KNOWN SPRINT 13 BUG (not fixed here, by direction).**
  Narrative generation returns 400
  `narrative_corrupt_fragment` on any run with stored
  robustness results or registered gates: Sprint 13's
  `_assemble_direction` validates raw fragments against
  `RobustnessRead`/`DecisionGatesRead`, which require a
  top-level `run_id` the writers never store. Verified
  2026-11-16 over real HTTP (see
  `~/workspace/verification/backend-integration-2026-11-16/REPORT.md`
  §5). The fix (with regression tests) gets its own branch
  after Sprint 14. Consequences in this sprint: generation
  from mappings inherits the refusal on enriched runs (the
  pinned test in §4 documents it); the derive path is NOT
  affected (it reads the expected-shortfall sub-fragment
  directly). Until the fix lands, narratives generate only
  on runs without tornado/gates analysis — including runs
  whose mappings were derived from enriched families.
- **Mixed-alpha shortfall comparison.** The `most_robust`
  tie-break compares stored shortfall values as numbers even
  when computed at different alphas; the alpha is pinned on
  the outcome for audit. Same-alpha comparison is the norm
  (default 0.05 everywhere in the cockpit).
- **Upper-tail metrics.** Derivation assumes lower-is-worse
  throughout (loss probability, lower-tail shortfall). Harm
  metrics where higher is worse are not modeled; upper-tail
  shortfall results are ignored by rule.
- **Family enumeration loads the whole family.** The up-walk
  + breadth-first descent issues one query per tree level;
  very large scenario families have not been load-tested.
- **Position gaps and races.** Positions are max+1 in one
  transaction with no unique constraint on position;
  concurrent writers could collide (single-writer dev path,
  same note as Sprint 13's version assignment). The name
  unique constraint is the hard backstop for duplicates.
- **No mapping history.** Updates overwrite; only `updated_at`
  records that a change happened. `user_edited` can never be
  cleared via the API.
- **Cockpit form scope.** MECE-branch and deliberation-pin
  editing stay API-only; derived mappings carry neither.
  Mapping creation from the cockpit is via derive only (no
  "author mapping" form — the generate form covers ad-hoc
  definitions).
- **ES staleness.** Derivation reads the LATEST stored
  expected-shortfall result per run; re-running the analysis
  overwrites the fragment, and derivation silently uses the
  newest. The ensemble id is pinned per candidate, but the
  shortfall's ensemble id is not cross-checked against it.

## 7. Cockpit check

The derive + mappings UI was verified with mocked-fetch tests
only (6 new frontend tests). Rendered against a live backend:
NOT verified (see §9). The page follows the Sprint 7/8/9/12/13
conventions: typed clients, type mirrors, `useApi`, `RunPicker`,
`Card`/`EmptyState`/`ErrorBanner`/`LoadingSpinner`, Chinese
chrome, honest empty states, two-step delete confirmation.

## 8. Deferred (out of scope, recorded deliberately)

- Directions as variable overrides (option B from the design
  discussion): directions that trigger new simulation runs.
  Needs the product decisions recorded in the design
  discussion (override shape, who may create runs).
- LLM-proposed directions with grounding validation (option C).
  Blocked on a working LLM endpoint; quality unverified.
- Polished-text verification (re-checking numbers/marks after
  a polish pass) — Sprint 13 limit, unchanged.
- Mapping version history / audit log; clearing `user_edited`.
- Cockpit author-mapping form; MECE-branch / deliberation-pin
  editing in the cockpit.
- The Sprint 13 robustness/gates fragment bug fix (own branch,
  approved, after Sprint 14).
- Narrative deletion / retention policy; backtest of narrative
  quality against historical decisions.

## 9. Commits on this branch

- `2485287` — pure deterministic direction derivation + mapping models
- `5291bb5` — direction_mappings table + narrative mapping-ids column (migration 0036)
- `154c18a` — derive + mappings service, routes, narrative integration, API tests
- `189b13a` — cockpit derive + mappings UI on the directions view
- (this commit) — Sprint 14 report, backlog update, verification log

## 10. What was NOT verified

- Docker Compose stack (no container runtime on this VM).
- Live-LLM deliberation/polish quality (no live call in this
  sprint; the polish hook is fixture-driven, as in Sprint 13).
- Cockpit views rendered against a live backend (mocked-fetch
  tests only). Real backend integration over HTTP was verified
  separately on 2026-11-16 (see
  `~/workspace/verification/backend-integration-2026-11-16/REPORT.md`);
  this sprint added no new verification of it.
- Worker behavior under Postgres/Redis.
- Concurrent derivation/mapping writes (see §6 position note).
- Real-browser rendering of the directions view.

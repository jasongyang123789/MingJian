# Option C — LLM-proposed decision directions

Branch: `strategy-engine/option-c-llm-directions`, from Sprint 20 tip
`ccc3490eb178233a6cfaa25d5cceb577bc4fc614` (branch
`strategy-engine/sprint20-cockpit-seminar`). Approved by Ho 2026-11-16;
built as Track B of the six parallel tracks launched 2026-11-17.

A third direction source alongside explicit definitions (Sprint 13) and
rule derivation (Sprint 14): an LLM proposes direction candidates from the
anchor run's stored artifacts, every reference is grounding-validated
before any write, proposals are stored as mappings awaiting explicit human
review, and only accepted proposals can feed narrative generation.
Proposing is explicit only — no background auto-proposal, no scheduler or
worker hook.

## 1. What was built

### Proposals (`services/narratives/proposals.py`, new, pure + port call)

- Contract: `DirectionProposal` / `DirectionProposals`, both
  `extra="forbid"`. One proposal: `name` (1–120 chars, stripped),
  `source_run_id`, `arm` (`baseline`/`strategy`, default `baseline`),
  `mece_branches` (1–20 entries, stripped, deduped, blank entries
  refused), `key_variables` (0–20, same normalization), `rationale`
  (1–2000 chars). The set holds 1–4 proposals (`MAX_DIRECTIONS`) with
  unique names enforced by a model validator.
- Prompt: `build_proposal_user_content(ProposalContext)` renders the
  grounding surface deterministically — topic, MECE branch names with
  scopes, one row per scenario-family run with an ensemble (run id,
  parent id, ensemble id, baseline/strategy P50 and loss probability),
  bound variables (id, unit, description), and the optional caller
  guidance. Empty guidance is omitted; no variables is reported honestly
  as "none bound". Same context renders byte-identical text.
- System prompt states the grounding rules: never invent a run id, branch
  name, or variable id; at least one MECE branch per proposal; do not
  compute new numbers — use only the summaries shown.
- `propose_directions(port, user_content)` calls `SkillLLMPort` with
  template id `narrative.direction_proposals`, version `1`, mirroring
  `polish_markdown` failure semantics: unavailable port raises without
  calling; contract failure raises `SkillContractError`; truncation
  (`finish_reason="length"` or `SkillTruncatedError`) raises
  `SkillTruncatedError` naming the cap; empty content raises
  `SkillContractError`. Token cap is the shared
  `JSON_CONTRACT_MAX_TOKENS` (8000, fix batch 2) via `PROPOSAL_MAX_TOKENS`.

### Persistence (`domain/models.py`, migration 0041)

- `DirectionMappingRecord` gains two columns: `status` (`String(16)`,
  NOT NULL) and `proposal_record` (nullable JSON).
- Status values: `active` (usable for generation), `proposed` (awaiting
  review), `rejected` (audit-only, terminal except delete). All
  pre-existing rows backfill to `active` via `server_default="active"`.
- `proposal_record` pins the proposal provenance: rationale,
  key_variables, model, template id/version, and the `proposal_hash`
  (SHA-256 over the canonical proposal-set JSON). Only `llm_proposal`
  rows carry one.
- Migration `0041_direction_proposal_status` revises
  `0040_seminar_synthesize_leases`, uses `batch_alter_table`, and
  downgrades by dropping both columns. Drill on scratch SQLite:
  upgrade 0040→0041 (columns appear; seeded row backfills
  `status='active'`, `proposal_record` NULL) → downgrade to 0040
  (columns gone, row survives) → re-upgrade to head (backfill holds).

### Service (`services/narratives/service.py`, extended)

- `propose(session, run_id, request)`: explicit trigger only. Refusals
  that need no LLM call happen BEFORE the port is touched: unknown run
  (404), non-completed anchor (`direction_requires_completed_run`),
  corrupt MECE fragment, no tree (`direction_proposal_requires_tree`),
  no ensemble anywhere in the family (`direction_no_ensemble`). The
  LLM output is then grounding-validated as a whole by
  `_validate_proposals` (see §2); only then are rows written.
- `_read_anchor_variables(anchor)`: the variable grounding surface —
  `configuration["variables"]["bindings"]`, a `VariableSet` dump,
  mirroring the distributions reader. Absent/non-dict fragments mean no
  bindings; present-but-malformed bindings are corrupt stored data
  (`direction_corrupt_fragment`).
- `_proposal_family_runs(family, candidates)`: one prompt row per family
  run with an ensemble, from the Sprint 10/14 candidate assembly.
- `accept_mapping` / `reject_mapping`: status-only transitions on
  `proposed` rows (anything else → `direction_mapping_not_proposed`).
  Accept re-validates references first (source run completed + ensemble
  present, branches still in the tree, variables still bound); a stale
  accept refuses and the row stays `proposed`.
- `_mapping_rows` gains `active_only`; `_resolve_definitions` (narrative
  generation from stored mappings) resolves active-only, in position
  order, capped at 4. The `narrative_requires_directions` message is
  unchanged (an S14 test asserts the derive-URL substring).
- Derive (`derive_directions`) now also skips non-active rows, in
  addition to the S14 user-edited skip.
- `_mapping_to_read` exposes `origin="llm_proposal"`, `status`, and
  `proposal_record`. PUT updates still set `user_edited` but keep
  status: editing a proposal does not accept it.

### Endpoints (`api/routes/narratives.py`, extended; no new wiring)

- `POST /runs/{run_id}/directions/propose` → 200 `DirectionProposeRead`
  (optional body: `DirectionProposeRequest` with optional `guidance`;
  no-body requests work). Per-proposal outcomes: `stored` (with
  `mapping_id`) or `skipped` (with reason). The response also returns
  the full mapping list, `proposal_hash`, `family_runs_considered`,
  template id/version, and model.
- `POST /runs/{run_id}/directions/mappings/{mapping_id}/accept` →
  200 `DirectionMappingRead` with `status="active"`.
- `POST /runs/{run_id}/directions/mappings/{mapping_id}/reject` →
  200 `DirectionMappingRead` with `status="rejected"`.
- Failure mapping (`_DIRECTION_STATUS_CODES`): unavailable → 503
  `direction_propose_unavailable`; contract failure → 502
  `direction_propose_contract_failed`; truncation → 502
  `direction_propose_truncated`; grounding failures → 400 with
  `direction_proposal_*` codes; accept/reject on a non-proposed row →
  400 `direction_mapping_not_proposed`; unknown run or wrong-run
  mapping → 404.

### Models (`services/narratives/models.py`, extended)

- `DirectionMappingRead` gains origin `"llm_proposal"`, required
  `status`, and `proposal_record`. New: `DirectionProposeRequest`
  (optional `guidance`), `ProposalOutcome`, `DirectionProposeRead`.

### Frontend: none (API-first, deliberate — see §7)

## 2. Design decisions

### Refuse, not flag

Any proposal naming a non-existent MECE branch, scenario-family run, or
variable refuses the WHOLE propose request before any write, following
the S13/S14 refuse-before-write discipline. Rationale: a hallucinated
reference impeaches the whole proposal set — the LLM was shown the exact
grounding surface, so an invented reference means the set cannot be
trusted piecemeal; proposing is cheap, explicit, and retryable, so
refusing costs one more call and keeps the store clean. Name collisions
are NOT refusals: they are per-proposal `skipped` outcomes, following
derive's per-rule outcomes, because a collision says nothing about the
quality of the proposal — the existing row simply wins.

### Grounding surface (stricter than mappings)

Source runs must be members of the anchor's scenario family — stricter
than stored mappings, which allow any run — because the LLM is only
shown family runs; a proposal citing anything else is by construction
ungrounded. Variables come only from the anchor run's stored bindings
(the same fragment the distributions reader uses). Proposals require
≥1 MECE branch at the contract level; if the anchor has no tree,
propose refuses with `direction_proposal_requires_tree` BEFORE calling
the LLM. Every proposal traces to MECE branches like every other
direction; the trace is what makes the proposal checkable.

### Storage: proposals are mappings with a review status

Proposals are `direction_mappings` rows with `origin="llm_proposal"`,
`status="proposed"`, and a `proposal_record` pinning rationale,
key_variables, model, template id/version, and `proposal_hash`. No
separate proposals table: the mapping row already carries name, source
run, arm, branches, position, and the no-clobber machinery; the status
column is the review state machine, and accept is a status transition,
not a copy. Rejected rows stay as audit records (terminal except
delete); they never feed generation.

### The no-clobber rule, extended

Proposals NEVER overwrite any existing mapping — any origin, any
status, including user-edited rows. A name collision yields `skipped`
and the existing row is left untouched. Derive now also skips
non-active rows: a pending or rejected proposal is resolved only by an
explicit human accept/reject/delete, never overwritten by a rule run.
Position assignment is max+1, as in S14 (same known race; see §6).

### Template location: the narratives package, not the skills registry

The template + contract live in `services/narratives/proposals.py`
(the Sprint 13 polish precedent), NOT the skills registry, because
`tests/unit/test_skill_templates.py` pins the registry at exactly 17
templates. The proposal template is versioned (`narrative.direction_proposals`
v1) and its id/version are pinned in every `proposal_record`, so a
future template revision is traceable per proposal.

### Failure mapping mirrors polish

Unavailable → 503, contract failure → 502, truncation → 502, grounding
→ 400, each with a distinct `direction_propose_*` / `direction_proposal_*`
code and a message naming the valid values (valid runs, branches,
variables) so the caller can fix the request or retry. No failure mode
writes anything: the 503/502/400 paths all raise before the first
`session.add`.

### What was deliberately NOT built

- No cockpit proposal-review UI (API-first; see §7).
- No direction auto-derivation from proposals, no proposal ranking or
  scoring, no automatic accept on any signal — review is always human.
- No variable-override runs (Sprint 14 option B) and no proposal
  regeneration/diffing across passes; re-proposing with the same
  fixture yields the same hash and `skipped` outcomes.
- No background auto-proposal of any kind.

## 3. Integration points

- Reuses the Sprint 10 family rule (`_family_runs` +
  `_assemble_candidates`): only COMPLETED runs with stored ensembles
  become prompt rows and valid proposal sources.
- Reuses the Sprint 14 mapping machinery: `_mapping_rows` position
  order, `_mapping_to_read`, the derive skip/outcome shapes, and the
  `direction_mappings` table + unique anchor/name constraint.
- Reuses the Sprint 13 polish failure semantics and the fix-batch-2
  shared token cap (`JSON_CONTRACT_MAX_TOKENS`).
- Reuses the Sprint 2 variable fragment shape (`VariableSet` dump in
  `configuration["variables"]["bindings"]`) for the variable grounding
  surface.
- Generation (`_resolve_definitions`) is unchanged except for the
  active-only filter: inline definitions still win, stored mappings
  still resolve in position order capped at 4, and the composer still
  receives the same `DirectionDefinition` shapes with MECE traces.
- No other module reads `DirectionMappingRecord`: the new columns are
  narratives-local (verified by grep: only `api/routes/narratives.py`,
  `domain/models.py`, `services/narratives/service.py`, and the new
  `proposals.py` reference the record).

## 4. Verification

### Full backend suite (the gate): 1882 passed, via 6 partitioned chunks

Baseline at `ccc3490`: 1840 passed (fix batch 2 figure, recorded, not
re-measured on this branch). This branch collects 1882 tests (1840 +
42 new; `1882 tests collected in 7.91s`, verified). All 1882 pass,
verified by a partitioned run: the 128 test files were split into 6
disjoint whole-file chunks (314/314/314/314/313/313 = 1882; the
partition was verified disjoint and complete at build time), each
chunk run to green with 0 `FAILED` lines in its log:

- chunk 1: 314 passed in 86.09s (`/dev/shm` TMPDIR)
- chunk 2: 314 passed in 114.87s (`/dev/shm` TMPDIR; holds one of the
  two new test files)
- chunk 3: 314 passed in 115.23s (`/dev/shm` TMPDIR; holds the other
  new test file)
- chunk 4: 314 passed in 1142.95s (disk TMPDIR)
- chunk 5: 313 passed in 901.87s (disk TMPDIR)
- chunk 6: 313 passed in 1879.10s (disk TMPDIR)

Chunk logs: `docs/option-c/chunk-1.log` … `chunk-6.log`; chunk file
lists: `docs/option-c/chunk-1-files.txt` … `chunk-6-files.txt`.
Frontend untouched: no frontend tests run, none affected.

Why partitioned, not one single-process run: five single-process
full-suite attempts in the mandated configuration (lock protocol,
`TMPDIR=/dev/shm/pytest-tmp-optc`) all failed on environmental
hazards outside this track's control, and a sixth was killed mid-run
by a VM/runtime restart. Every failure in all five completed attempts
was classified per failure section: 1,440 `FAILED` lines total, zero
assertion failures, zero code errors — every section is SQLite
"database or disk is full", SQLite "disk I/O error", `PermissionError:
[Errno 1]`, or `ENOSPC`:

- Run 1: 350 failed / 1532 passed — `/dev/shm` filled by a concurrent
  sibling-track suite (340 disk-full `OperationalError` + 9 tmpfs
  EPERM). Log: `docs/option-c/test-full-run1-diskfull.log`.
- Run 2: 353 failed / 1529 passed — 343 SQLite "disk I/O error" from
  the VM-wide intermittent write fault (see below), 0 "disk is
  full". Log: `docs/option-c/test-full-run2-ioerror.log`.
- Cycle 1: 323 failed / 1559 passed — disk-full dominated.
  Log: `docs/option-c/test-full-cycle1-323failed.log`.
- Cycle 2: 180 failed / 1702 passed — disk-full; 0 of the 25 new API
  tests failed. Log: `docs/option-c/test-full-cycle2-180failed.log`.
- Cycle 3: 234 failed / 1648 passed — disk-full; 0 of the 25 new API
  tests failed. Log: `docs/option-c/test-full-cycle3-234failed.log`.
- Cycle 4: killed at 53% progress by a runtime restart; partial log
  `docs/option-c/test-full-cycle4-partial-killed.log`. An earlier
  attempt exited 120 with a 0-byte log — the write fault's signature
  under output redirection, reproduced deliberately (same command to
  a terminal: exit 1 + traceback; redirected: exit 120 + 0 bytes;
  unbuffered + redirected: exit 1 + 0 bytes, because the writes to
  the log file itself fail).

The write fault: intermittent `EPERM` on `write()` syscalls across
all filesystems (proven by strace: `write(fd, "blat", 4) = -1 EPERM`
on tmpfs and overlay alike, as root, while file creation still
worked), toggling on a minutes timescale, independently observed by
Track F the same day. The chunked run verifies the identical 1882
tests with the same runner and assertions, partitioned for
restart/fault resilience — the same adaptation the sibling tracks
adopted (disk TMPDIRs + chunked runs). A single-process green run
remains unobserved; see §10 for the order-dependence caveat.

Script-bug note (honesty record): the first chunk-runner version
captured `tail`'s exit code instead of pytest's, marking failed
chunks 1–3 as green. Caught by reading the output (the inner echo
printed exit 1 + failure counts). Fixed (explicit `return $ec`),
chunks 1–3 re-run with the fixed script and verified green
independently (0 `FAILED` lines each). The pass-1 fault logs are
preserved as `docs/option-c/chunk-N-pass1-fault.log`; all 193
failures in them classify as environmental (disk I/O error), 0
non-environmental, including the 3 new API tests that failed in
chunk 3's pass-1 run.

### New tests: 42 passed (17 unit + 25 API)

Run: `env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest
tests/unit/test_direction_proposals.py tests/test_direction_proposals_api.py`
— 42 passed in 113.80s, re-run after the final rename/format edits.
Combined with the S13/S14 narrative tests, 129 passed in 380.83s (run
before the rename/format edits; the 42-test re-run after those edits
passed).

No live LLM anywhere: the API tests bind a scripted
`SkillLLMPort` to `app.state.narrative_service` after run creation
(fixtures need real run ids); the unit tests use fixture ports.
Helpers mirror the S14 API tests (`setup_app`, `_create_run` with
`decomposition=PASSING_TREE`, `_create_ensemble`, `_branch` via
`POST /scenario/runs/{parent_id}`, non-completed runs via
`execution_mode="QUEUED"`).

### Behavior evidence (all asserted test values, with test names)

- `test_propose_stores_proposals_awaiting_review`: propose stores 2
  proposals at positions [0, 1], both `origin="llm_proposal"`,
  `status="proposed"`, with `family_runs_considered` 2 and a
  `sha256:`-prefixed `proposal_hash`.
- `test_propose_same_fixture_same_hash`: the same fixture yields an
  identical `proposal_hash` on a second propose, and the second
  propose reports both proposals `skipped` (no duplicate rows).
- `test_propose_truncated_response_raises_truncation_error_naming_the_cap`:
  the truncation error names cap 8000 and `max_tokens == 8000`.
- `test_propose_refuses_unknown_mece_branch_and_writes_nothing`: the
  refusal message names the unknown branch "Nope" and the valid branch
  "Demand"; zero rows written.
- `test_propose_refuses_unknown_variable_and_writes_nothing`: the
  refusal message names the unknown variable "nope" and the valid
  variable "cash"; zero rows written.
- `test_propose_refuses_unknown_source_run_and_writes_nothing`,
  `test_propose_refuses_run_outside_the_family`,
  `test_propose_refuses_ensemble_less_family_run`: each refuses with
  its `direction_proposal_*` code and writes nothing.
- `test_propose_refuses_without_tree_before_calling_llm` and
  `test_propose_refuses_without_ensemble_before_calling_llm`: both
  refuse with `port.calls == []` — no LLM call is spent.
- `test_propose_unavailable_returns_503_and_writes_nothing`,
  `test_propose_contract_failure_returns_502_and_writes_nothing`,
  `test_propose_truncated_returns_502_and_writes_nothing`: the three
  failure mappings, each writing nothing.
- `test_propose_never_overwrites_existing_mapping` and
  `test_propose_never_overwrites_user_edited_mapping`: a colliding
  proposal is `skipped` and the existing row (including its
  user-edited fields) is byte-unchanged.
- `test_derive_skips_proposed_mapping`: derive reports `skipped` with
  a reason containing "proposed"; the proposal row is untouched.
- `test_propose_accept_narrate_end_to_end`: propose → accept →
  generate pins `direction_mapping_ids == [mapping_id]`, with the
  narrative's MECE trace naming branch Demand and scope `["demand"]`.
- `test_generation_ignores_proposed_mappings` and
  `test_reject_mapping_excludes_it_from_generation`: proposed and
  rejected rows never feed generation; generation with only such rows
  refuses with `narrative_requires_directions`.
- `test_accept_revalidates_stale_references`: accept after the source
  run's ensemble is removed refuses with
  `direction_source_run_no_ensemble` and the row stays `proposed`.
- `test_update_proposed_mapping_sets_user_edited_keeps_status`: PUT
  sets `user_edited` and keeps `status="proposed"`.
- `test_propose_with_guidance_passes_it_to_the_prompt`,
  `test_propose_without_body_works`,
  `test_propose_refuses_noncompleted_anchor`,
  `test_propose_unknown_run_404`, `test_accept_reject_wrong_run_404`:
  guidance reaches the prompt, empty-body propose works, and the
  remaining 400/404 paths behave.
- Unit contract tests (17): valid payload with defaults; extra keys
  refused; empty and oversized sets refused; duplicate names refused;
  ≥1 MECE branch required; bad arm and missing rationale refused;
  name/branch normalization; blank branch entries refused; prompt
  builder lists the grounding surface, is deterministic, omits empty
  guidance, and reports no variables honestly; system prompt states
  the grounding rules; port returns output + model; unavailable port
  raises without calling; contract failure and empty response raise;
  truncation raises naming the cap.

### Type + lint

- mypy, full `src/planagent/` (238 files): 1 remaining error, in
  `src/planagent/services/splits/expectations.py:522` — verified
  pre-existing by reproducing it on the clean base worktree
  (`~/workspace/mingjian-base`); no changes under `splits/`; left
  untouched.
- ruff: 12 findings, all the pre-approved B008 `Depends()` pattern in
  `routes/narratives.py` (9 pre-existing + 3 new endpoints); zero
  findings in all other new/changed files. `domain/models.py`: 35
  findings, identical set at HEAD (verified via stash comparison).
  `ruff format`: 1 file reformatted (API test file), 11 unchanged.

### Sprint 0 smoke: PASS

`docs/sprint0/smoke_e2e.py` exits 0 (`SMOKE: PASS`); the evidence file
was reverted afterward. Two earlier smoke attempts failed
environmentally (`StaleDataError`, then exit 120 with an empty log)
while `/dev/shm` was 100% full from concurrent sibling suites; after
cleaning this track's stale pytest tmp dirs, the re-run passed
cleanly. The failures were never in narratives code (the smoke never
touches `direction_mappings`).

## 5. How to run / verify

```bash
# New tests for this track
env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest \
  tests/unit/test_direction_proposals.py tests/test_direction_proposals_api.py

# Full backend suite (lock protocol; log at docs/option-c/test-full.log)
# mkdir ~/workspace/.pytest-full-run.lock  (atomic; wait + retry if held)
TMPDIR=/dev/shm/pytest-tmp-optc env -u NO_PROXY -u no_proxy \
  .venv/bin/python -m pytest -q

# Chunked gate (what actually went green; see §4): the 128 test files
# partitioned into docs/option-c/chunk-N-files.txt, each chunk run to
# green separately with a health probe first. Reproduce one chunk:
TMPDIR=/dev/shm/pytest-tmp-optc env -u NO_PROXY -u no_proxy \
  .venv/bin/python -m pytest -q -p no:cacheprovider \
  $(cat docs/option-c/chunk-1-files.txt)

# Type + lint (new/changed files)
.venv/bin/python -m mypy src/planagent/
.venv/bin/ruff check src/planagent/services/narratives/proposals.py \
  src/planagent/services/narratives/service.py \
  src/planagent/services/narratives/models.py \
  src/planagent/api/routes/narratives.py tests/test_direction_proposals_api.py \
  tests/unit/test_direction_proposals.py

# Migration check on scratch SQLite (upgrade 0040→0041, downgrade, re-upgrade)
# Smoke (Sprint 0, revert docs/sprint0/smoke-evidence.json afterward)
env -u NO_PROXY -u no_proxy .venv/bin/python docs/sprint0/smoke_e2e.py
```

```bash
# 1. A completed run with an ensemble and an MECE tree (see SPRINT3.md), then:
# 2. Propose (fixture port in tests; real port via the standard skill wiring):
curl -X POST /runs/{run_id}/directions/propose -d '{"guidance": "..."}'
# 3. Review the stored proposals, then accept or reject each:
curl -X POST /runs/{run_id}/directions/mappings/{mapping_id}/accept
curl -X POST /runs/{run_id}/directions/mappings/{mapping_id}/reject
# 4. Generate from stored mappings (active only):
curl -X POST /runs/{run_id}/narratives -d '{}'
```

## 6. Known limits

- Live-LLM proposal quality is unverified: all tests are
  fixture-driven; no live propose call has been observed. Prompt
  quality, hallucination rate under real models, and guidance
  handling in the wild are unknown.
- Variable grounding covers stored bindings only: runs whose
  variables exist only in a template (never bound into the run
  configuration) show "none bound", and proposals cannot cite those
  variables.
- No Docker verification: no container runtime on this VM, so the
  migration was drilled on scratch SQLite only, never against the
  Docker stack.
- No cockpit UI: see §7.
- `user_edited` is still never clearable (S14 limit, unchanged).
- Position max+1 races as in S14: two concurrent propose/derive
  calls can collide on position (the unique anchor/name constraint
  still guards duplicates; positions may tie).
- Mixed-alpha expected-shortfall comparison in derivation is
  unchanged (S14 limit, auditable via the pinned alpha).
- Accept re-validation reads the CURRENT tree/bindings: a proposal
  accepted after the anchor's tree changed is validated against the
  new tree, not the tree the LLM saw.

## 7. Cockpit check

API-first, no frontend changes — a deliberate scope choice. The
propose/accept/reject flow is fully usable via the endpoints, and a
proposal-review UI (review queue, accept/reject buttons, provenance
display) is a follow-up, not a silent omission.

Known gap, recorded honestly: `frontend-v2/src/pages/Directions.tsx`
renders any non-`derived` origin as '手动' (manual), so a proposal row
currently mislabels in the mappings list, and the generate-from-stored
list may show proposed rows that the backend will skip. The backend is
authoritative: generation resolves active mappings only, regardless
of what the list shows. Frontend test counts are unchanged (frontend
untouched).

## 8. Deferred (out of scope, recorded deliberately)

- Cockpit proposal-review UI (see §7).
- Proposal ranking, scoring, or automatic acceptance on any signal.
- Sprint 14 option B (variable-override runs).
- Proposal regeneration/diffing across passes; proposal history beyond
  the pinned `proposal_record`.
- A `direction_mapping_history` table (S14 deferred item, unchanged).
- MECE/pin editing remains API-only (S14 limit, unchanged).

## 9. Commits on this branch

- `2cf7797` — LLM-proposed directions: proposals module, review-status
  migration 0041, service + endpoints, 42 fixture-driven tests
- (this commit) — Option C report, chunked-gate logs, chunk file lists

## 10. What was NOT verified

- A single-process full-suite green run: five attempts all failed
  environmentally (see §4); the gate is the 6-chunk partitioned run
  (1882 passed, 0 failed). Residual caveat: chunking isolates
  processes, so a hypothetical order-dependent failure that only
  manifests with all 1882 tests in one process would not be caught
  by the chunks. Mitigating evidence: the five full runs exercised
  the full ordering and produced zero non-environmental failures
  across 1,440 failure lines.
- Live LLM proposal quality (fixture-driven only; see §6).
- Full-stack behavior under Docker (no container runtime on this VM).
- Cockpit rendering of proposal rows (no frontend changes; known
  mislabel gap in §7).
- Behavior under concurrent propose/derive calls (position race in
  §6 is untested, as in S14).
- The `direction_proposal_requires_tree` path against a run whose
  tree exists but is empty (no branches): the contract requires ≥1
  branch, so any proposal would refuse on grounding; no dedicated
  test covers the empty-tree anchor.

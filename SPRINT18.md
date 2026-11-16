# Sprint 18 — Seminar hardening: retries, budgets, token accounting, near-duplicate pre-pass, synthesize queue, observability + audit log, agent-chair mode

Branch: `strategy-engine/sprint18-seminar-hardening`, from merge commit `0ff7642`
(S17 + Phase 2 merged). Status: COMPLETE. Zero live LLM calls; all new
behavior is fixture/fake-port driven.

Ho's directives (2026-11-16 14:50): Glint himself is the chair model; add the
missing retries + budgets + token accounting; the pre-pass must go beyond
exact-string matching (near-duplicates); concurrent synthesize must QUEUE /
serialize instead of refusing; add observability + recorded audit logs so any
problem is locatable and fixable/optimizable. This sprint implements all
seven items in the brief. The S18 row's cockpit seminar views + live smoke
remain queued (see §7).

## 1. What was built

### 1.1 Agent-chair mode (item 1)

`chair_mode` on the seminar config: `model` (default, S17 behavior unchanged)
vs `agent`. In agent mode:

- `POST /seminars/{id}/synthesize` produces and stores a versioned CHAIR
  BRIEF and returns it with HTTP 200 — no model chair call, no report row,
  the seminar stays `collecting` awaiting chair input. The brief carries:
  pre-pass clusters (exact + near-duplicate groups), disagreements derived
  in code, computed metrics, quoted verbatim verdicts, a participation
  note, absent models, `brief_version` + `brief_hash`, and the submit
  endpoint. Briefs are stored append-only in the new
  `seminar_chair_briefs` table (migration 0039), versioned per seminar;
  re-synthesizing produces brief version 2 with the same hash over the
  same inputs.
- `POST /seminars/{id}/chair-synthesis` accepts the chair's submission: a
  `ClaimClusters` payload AND a `SeminarSynthesis` payload, validated with
  the SAME contracts (`parse_seminar_stage_output`) and the SAME merge-map
  coverage enforcement (`expand_clusters`) as model output. Contract
  failures become 400 (`chair_submission_contract_failed`), coverage
  failures 400 (`chair_submission_coverage_failed`), both with zero report
  rows written. On success the versioned report is composed with
  `production_path` `agent_chair`, `chair_model_id` `glint-agent`
  (`AGENT_CHAIR_MODEL_ID`), and the brief version/hash recorded in the
  report envelope and header.
- Creation in agent mode skips the chair-liveness check and forces
  `chair_participates=False` (the stored `chair_model` is kept only for
  shape stability and is never used). The deterministic composer fallback
  remains available via explicit re-synthesize with
  `deterministic_fallback: true` in BOTH modes; in agent mode the fallback
  path builds no chair port at all.
- The brief PINS the verdict set: metrics for a submission are recomputed
  from the brief-pinned verdicts + the submitted clusters + fresh round
  rows, so rounds run after the brief only affect round statistics, never
  the verdict set the chair answered. `brief_version`/`brief_hash` are
  disclosed in the report header.

New refusal codes: `seminar_chair_mode_mismatch` (submission to a
model-mode seminar), `seminar_no_chair_brief` (submission before any
brief), `seminar_unknown_brief_version`.

### 1.2 Retries (item 2)

Timeout-only retries on stage calls: max 2 retries = 3 attempts, small
fixed backoff, configurable per seminar (`max_retries` 0–5, default 2;
`retry_backoff_seconds` 0–60, default 1.0). ONLY timeout errors retry —
never contract failures, never unavailable, never budget exhaustion, never
cancellation (retrying a cancellation would swallow it). Every attempt is
recorded: a `stage_call_finished` audit event per attempt (outcome +
attempt number) and a `retry` event per scheduled retry. `run_stage`
records `attempts` on the stage record.

### 1.3 Budgets (item 3)

Per-seminar budgets `max_stage_calls` (default 200) and `max_tokens`
(default 1,000,000), set at creation, stored on the seminar. Checked
BEFORE each stage call — including before each retry attempt. Exceeding
stops that model's/stage's progression with the distinct `budget_exhausted`
error kind, recorded as a `budget_exhausted` audit event plus a
`stage_failure` event carrying the kind, never silent. Remaining budget is
visible in GET detail (`budgets`: used/remaining/limits for both
budgets). The budget position is seeded from the audit ledger at the start
of each wave/finalize/synthesis, so budgets hold across waves and across
service restarts (the ledger is the source of truth, not in-memory state).

### 1.4 Token accounting (item 4)

`TokenUsage` (prompt/completion/total) captured from every port call:
`ScriptedSkillPort` returns scripted usage from fixtures
(`usage_script`, parallel to the payload queues); the real
`ParameterizedSkillPort` reads SDK usage where present and returns `None`
(rather than a fabricated 0) when the SDK reports none. Usage is stored on
stage records, rolled up per model and per seminar in the audit ledger,
visible in GET detail (`budgets` + `diagnosis`) and in the report's audit
appendix (usage rollup replaces the S17 "Not recorded" text when usage
exists). The Sprint 6 `OpenAIServiceSkillPort` path still returns no usage
— out of scope, recorded as a limit (§6).

### 1.5 Near-duplicate pre-pass (item 5)

`deterministic_prepass` now additionally groups near-duplicates:
deterministic normalized token-set similarity (Jaccard over lowercased
alphanumeric tokens, pinned default threshold 0.8, configurable per
seminar via `near_duplicate_threshold`). Grouping is single-pass greedy in
first-appearance order: each exact group joins the first near-duplicate
group whose representative set (the FIRST exact group's token set, never
moved) scores ≥ threshold, else starts a new group — NO chaining, stable
representatives, fully deterministic. Exact grouping is unchanged;
`deterministic_clusters` still clusters by exact groups only and never
merges different wordings. Near-duplicate groups are advisory candidates
rendered in the pre-pass group listing for the LLM cluster stage, which
still adjudicates semantics. Groups identical to an exact group are not
re-rendered.

### 1.6 Synthesize queue (item 6)

Concurrent synthesize requests to one seminar SERIALIZE on a per-seminar
`asyncio.Lock` held by the service instance (the service is cached on
`app.state`, so the lock spans requests). The second request waits for the
first (a `queue_wait` audit event records the wait), then proceeds on
freshly re-read state as a new version. The `seminar_synthesize_in_flight`
refusal is REMOVED for the normal concurrent case; a seminar found in
`synthesizing` state WHILE holding the lock is treated as stuck
(`seminar_synthesize_stuck`, with an audit-log pointer) — that state can
only persist after a crash mid-synthesis, since the lock holder is the
only writer. The same lock serializes chair-synthesis submissions.

### 1.7 Observability + audit log (item 7)

New append-only table `seminar_audit_events` via migration 0039
(`seminar_id`, monotonic `seq` per seminar with a unique constraint,
timestamp, nullable `model_id`, stage, kind, detail JSON, `round_no`,
`stage_call_id`). Thirteen event kinds: `stage_call_started`,
`stage_call_finished`, `retry`, `stage_failure`, `budget_exhausted`,
`fallback`, `queue_wait`, `status_transition`, `chair_brief_produced`,
`synthesis_submitted`, `report_written`, `synthesis_failed`, `refusal`.
Events are written in the same transaction as the state change they
describe (the recorder flushes with the wave/finalize/synthesis commit);
refusal events commit on their own (no other state change joins them).
`GET /seminars/{id}/audit` serves events in seq order, filterable by kind
and `model_id` (unknown kind → `seminar_audit_unknown_kind`). GET detail
gains a diagnosis summary: error counts by kind, total tokens, total
duration, stage calls/attempts, retries, fallbacks.

The error taxonomy is formalized in `services/seminar/errors.py`:
`timeout` / `contract` / `unavailable` / `budget_exhausted` / `cancelled`
/ `error`, classified consistently across audit events, round errors, and
report headers. `stage_failure` events close the one gap the port wrapper
cannot see: contract failures happen in the stage runner AFTER the port
call succeeds, so the service records them explicitly — a reader with only
the audit log can locate exactly which step failed, which call, and why.

## 2. Design decisions

1. **Every attempt counts against the budget.** Retries consume stage-call
   budget and token budget like any call; otherwise a flapping model could
   retry past its budget for free.
2. **Token budget is checked on consumed-so-far only.** A call's own tokens
   are unknowable before it runs, so a call that pushes usage over the
   limit still completes; the NEXT call is blocked. The alternative —
   estimating — would fabricate numbers.
3. **Passing budget checks are not events.** The budget position rides on
   every `stage_call_finished` detail instead, so the log stays readable;
   only exhaustion gets its own event.
4. **Diagnosis counts failures exactly once.** `error_counts` counts
   `stage_failure` + `fallback` + `synthesis_failed` events. Failed
   attempts surface via the retry count; `budget_exhausted` events are not
   double-counted (their stage failure carries the kind).
5. **"Queue" is not an error kind.** It is an audit event category
   (`queue_wait`). The taxonomy's six kinds are all failure kinds; queueing
   is not a failure.
6. **`cancelled` is classified but never retried.** Retrying a cancellation
   would swallow it.
7. **Near-duplicate grouping never chains.** The representative set is the
   first exact group's token set and never moves, so grouping is order-
   stable and a chain of pairwise-similar claims cannot collapse genuinely
   distinct claims into one group.
8. **One tracker + one instrumented chair port per synthesis.** The cluster
   and synthesize chair stages share one budget position within a
   synthesis; re-seeding between them would double-count the ledger.
9. **The brief pins verdicts; rounds stay fresh.** A submission's metrics
   recompute from brief-pinned verdicts + submitted clusters + fresh round
   rows. The chair answered a specific verdict set; later rounds must not
   silently change what the report claims the chair clustered.
10. **Chair submissions are validated before any write.** Contract +
    coverage checks run before the report row is created, so a refused
    submission leaves zero rows — the same write discipline as S17's
    synthesis refusals.
11. **Locks are never deleted.** Per-seminar locks live in a dict on the
    service instance for the process lifetime; deleting a lock after use
    would race a waiter. Memory cost is one lock per synthesized seminar.
12. **No new templates.** The agent chair reuses the existing ClaimClusters
    + SeminarSynthesis contracts; the seminar registry v1 template pins and
    the 17-template v2 pin are untouched, per the brief's constraint.
13. **The `synthesizing` state is a crash marker, not a lock.** With the
    queue lock in place, a second request can only observe `synthesizing`
    while holding the lock if a previous synthesis crashed mid-flight;
    refusing as stuck (with an audit pointer) is the honest response.

## 3. Files changed

New modules: `services/seminar/errors.py` (taxonomy),
`services/seminar/audit.py` (recorder, diagnosis, ledger, reads),
`services/seminar/instrumentation.py` (BudgetTracker, InstrumentedPort).
Extended: `services/seminar/{models,service,engine,port,chair,clustering,
composer}.py`, `services/skills/orchestration.py` (TokenUsage, usage /
attempts / duration on SkillLLMResponse + StageRecord),
`api/routes/seminars.py` (brief response, chair-synthesis, audit
endpoints), `domain/models.py` (two ORM records),
`migrations/versions/0039_seminar_audit_chair_briefs.py`,
`tests/skill_fixtures.py` (scripted usage). No automotive, splits, or
frontend file touched; no template added or changed.

## 4. Verification

- Full backend suite: **1743 passed, 0 failed** in 502.20s (lock claimed
  per protocol, `TMPDIR=/dev/shm/pytest-tmp-s18`; log force-added at
  `docs/sprint18/test-full.log`). 1743 = 1665 at the merge base + 78 new
  S18 tests. The 141 pre-existing seminar tests are included in the
  1743 and pass under S18 code.
- New-test subset re-run: **78 passed** in 25.35s — 18 agent-chair, 11
  hardening, 7 API, 42 unit (6 errors + 14 instrumentation + 7 audit +
  15 near-duplicates). Command in §9.
- Ruff: zero new findings on touched files vs `0ff7642`. The 38 findings
  on touched files are all pre-existing (`domain/models.py` 35,
  `services/skills/orchestration.py` 3 — identical finding sets at the
  base, line-shifted only, none on S18-added lines). Six findings in new
  S18 files were fixed (unused noqa/imports, import order, intentional
  `asyncio.TimeoutError` alias pins kept with `UP041` noqa).
- Mypy: clean — `no issues found in 18 source files` (seminar package +
  seminars route + skills orchestration).
- Migration 0039 drill on a scratch DB: upgrade to 0038 (no
  `seminar_audit_events` / `seminar_chair_briefs` tables) → upgrade head
  (both tables present, audit columns `id, seminar_id, seq, model_id,
  stage, kind, detail, round_no, stage_call_id, created_at`) →
  downgrade to 0038 (both tables gone) → upgrade head again;
  `alembic current` reports `0039_seminar_audit_chair_briefs (head)`.
- Sprint 0 smoke re-run: **PASS**; the refreshed `smoke-evidence.json`
  was reverted per precedent.
- Frontend: untouched (no frontend file changed, no re-run).
- Template pins untouched: the 17-template v2 pin and the seminar
  registry v1 pins are unchanged; no new template was added.

## 5. Behavior evidence (all asserted test values, with test names)

Acceptance criteria (brief items 1–7), all fake-port driven:

**Agent-chair.** `test_synthesize_in_agent_mode_produces_a_stored_brief`:
brief version 1, hash `sha256:`-prefixed, 11 pre-pass items, 3 exact
groups, 2 finals used, disagreements `[]`, participation note contains
"agent chair", status stays `collecting`, 0 report rows, 1 brief row, a
`chair_brief_produced` audit event.
`test_submission_writes_agent_chair_report`: version 1,
`production_path` + `cluster_production` both `agent_chair`, chair
`glint-agent`, agreement `low`, clusters `stage` is `None`, envelope
carries `chair_mode`/`brief_version`/`brief_hash`/`submitted_by`, and
`synthesis_submitted` + `report_written` events exist.
`test_submission_with_dropped_item_refuses_with_zero_rows`: coverage
refusal names `I9`, 0 report rows, status stays `collecting`, a `refusal`
event is recorded. Contract refusals
(`test_submission_with_contract_violation_refuses_with_zero_rows`,
`test_submission_with_bad_synthesis_contract_refuses`), mode mismatch,
no-brief, and unknown-brief-version refusals all leave 0 rows.
`test_resubmission_creates_a_new_version_with_the_same_hash`: versions 1
and 2, identical hash, 2 report rows.
`test_deterministic_fallback_flag_skips_chair_calls_in_model_mode`: the
chair port records zero calls.
`test_synthesize_on_stuck_seminar_refuses_with_named_code`:
`seminar_synthesize_stuck`, 0 rows, status stays `synthesizing`.

**Retries.** `test_timeout_then_success_completes_the_round_with_attempts_recorded`:
both models complete, the flaky stage records `attempts == 2`, one
`retry` event with `error_kind` `timeout`, intake outcomes
`["timeout", "ok"]`.
`test_timeout_retry_exhaustion_fails_the_round_as_timeout`: 3 timeouts
(1 + 2 retries), round error kind `timeout`, 2 retry events, the other
model completes.
`test_contract_failure_is_not_retried`: 0 retry events, exactly 1 intake
call, round error kind `contract`.
Unit: `test_only_timeouts_are_retryable` (timeout true; contract /
unavailable / cancelled false), `test_cancellation_is_never_retried`,
`test_timeout_retries_then_succeeds_with_backoff`.

**Budgets.** `test_stage_call_budget_stops_the_wave_and_is_recorded`
(`max_stage_calls=5`): exactly 5 `stage_call_finished` events, both
rounds fail with kind `budget_exhausted`, diagnosis
`error_counts == {"budget_exhausted": 2}`, `stage_calls_remaining == 0`.
`test_budget_holds_across_waves_via_the_ledger` (24 calls): wave 1
completes, wave 2 fails with `budget_exhausted` — the ledger, not
memory, carries the position.
Unit: `test_token_budget_blocks_the_call_after_the_limit_is_reached`
(the over-limit call completes, the next is blocked),
`test_retry_attempts_consume_stage_call_budget`,
`test_budget_check_runs_before_each_retry_attempt`.

**Token accounting.**
`test_token_accounting_flows_to_stage_records_detail_and_report` (15
tokens per call × 24 calls): stage records carry the scripted usage,
`tokens_used == 360`, `tokens_remaining == 1_000_000 - 360`,
`stage_calls == 24`, `stage_call_attempts == 24`.

**Near-duplicates.** `test_jaccard_similarity_boundaries`: empty/empty
1.0, one-empty 0.0, 4-shared-of-5-union exactly 0.8.
`test_near_duplicates_group_at_the_default_threshold`: exact groups
`[["I1"], ["I2"]]`, near groups `[["I1", "I2"]]`, count 1, threshold
0.8. `test_genuinely_distinct_claims_never_group`: 3 singletons, count
0. `test_below_threshold_pair_does_not_group`: 2/3 < 0.8 stays split.
`test_threshold_is_configurable`: 0.5 groups the pair, 1.0 splits it.
`test_grouping_is_deterministic_and_byte_identical`,
`test_grouping_uses_first_match_and_stable_representatives` (no
chaining), `test_deterministic_clusters_still_group_exact_only`.

**Queue.** `test_concurrent_synthesizes_serialize_into_versions_1_and_2`
(`asyncio.gather` + a 0.2s slow chair port): versions `{1, 2}`,
identical report hash, exactly 1 `queue_wait` event with `wait_ms > 0`,
2 report rows, status `reported`.

**Audit log.** `test_audit_endpoint_lists_events_in_seq_order_with_filters`:
seqs start at 1 and ascend, 24 `stage_call_started` events (2 models ×
12 calls), kind + model_id filters exact.
`test_refusal_writes_only_the_audit_event`: 1 `refusal` event with code
`seminar_no_finals`, 0 report rows.
`test_detail_diagnosis_summarizes_a_failed_wave`:
`error_counts == {"contract": 1}` via one `stage_failure` event,
13 stage calls (1 + 12), 0 tokens (no scripted usage).
`test_flush_assigns_consecutive_seqs_from_stored_max`: seqs 8/9 continue
a stored max of 7.
API (`tests/test_seminar_s18_api.py`): brief returns 200 with
`submit_endpoint` `POST /seminars/{id}/chair-synthesis`;
chair-synthesis returns 201 with `agent_chair` / `glint-agent`;
coverage failure returns 400 with 0 reports; the audit endpoint filters
and rejects unknown kinds with 400; detail shows
`stage_calls_used == 50` (2 models × 25 calls) with default budgets
200 / 1,000,000.

## 6. Known limits

- Live port path untested (no live LLM by design): SDK usage capture,
  timeout re-raise, and retry behavior against a real endpoint are
  fixture-pinned only. The Sprint 6 `OpenAIServiceSkillPort` returns no
  usage.
- No token accounting on the deliberation (non-seminar) path.
- The synthesize lock is per-process: two processes (two workers) could
  still race. The deployment is single-process; a distributed lock is
  deferred.
- Near-duplicate similarity is token-set Jaccard only — no stemming, no
  embeddings, no paraphrase detection. Genuinely distinct claims with
  high token overlap group as candidates; the LLM cluster stage (or the
  agent chair) adjudicates.
- `version` / `brief_version` use max+1 with no unique constraint (same
  pre-existing pattern as S14/S17); the queue lock serializes writers
  within a process.
- Concurrent advances are unserialized (pre-existing S16 limit, unchanged).
- The audit log has no retention/rotation policy; long seminars grow it
  unboundedly.
- Diagnosis `error_counts` does not include deliberation-stage failures
  outside seminars.
- No cockpit seminar views yet (queued); no live smoke yet (queued).

## 7. Deferred / deliberately not built

- Cockpit seminar views + live smoke (S18 row's remaining items; queued
  behind this hardening, per Ho's 14:50 re-scope).
- Direction-as-variable-overrides (option B) and LLM-proposed directions
  (option C) — unchanged from S14.
- A new template for the agent chair — considered, rejected: the existing
  contracts suffice (decision 12).
- Distributed locking, audit retention, token accounting on the
  deliberation path — deferred, listed as limits above.
- HTTP-level concurrent-synthesize test: the service-level `asyncio.gather`
  test satisfies the brief's minimum; an HTTP-level test would need two
  TestClients sharing one service across event loops, which `asyncio.Lock`
  does not support (locks bind to a loop). Production runs a single loop
  and is unaffected.

## 8. Commits

- `54cc62e` — Sprint 18 implementation: retries, budgets, token
  accounting, audit log, agent-chair mode, near-duplicate pre-pass,
  synthesize queue (migration 0039, fixture usage support)
- `d4b632a` — lazy chair port on the deterministic path; record
  `stage_failure` audit events; diagnosis counts failures exactly once
- `580e880` — S18 agent-chair, hardening, and API tests + unit tests
- `305cd57` — ruff fixups in new S18 files
- (this commit) — Sprint 18 report, backlog update, verification log

## 9. Reproduce

```bash
git worktree list  # ~/workspace/mingjian-s18 on strategy-engine/sprint18-seminar-hardening
cd ~/workspace/mingjian-s18
# New-test subset (78 tests):
TMPDIR=/dev/shm/pytest-tmp-s18 env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest \
  tests/test_seminar_agent_chair.py tests/test_seminar_hardening.py \
  tests/test_seminar_s18_api.py tests/unit/test_seminar_errors.py \
  tests/unit/test_seminar_instrumentation.py tests/unit/test_seminar_audit.py \
  tests/unit/test_seminar_near_duplicates.py -q
# Full suite (claim the lock first; see §4):
mkdir ~/workspace/.pytest-full-run.lock
TMPDIR=/dev/shm/pytest-tmp-s18 env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest -q
# Sprint 0 smoke (revert the evidence file afterwards):
env -u NO_PROXY -u no_proxy .venv/bin/python docs/sprint0/smoke_e2e.py
git checkout -- docs/sprint0/smoke-evidence.json
# Migration drill (scratch DB):
PLANAGENT_DATABASE_URL=<redacted>
  .venv/bin/python -m alembic upgrade 0038_seminar_tables
PLANAGENT_DATABASE_URL=<redacted>
  .venv/bin/python -m alembic upgrade head   # 0039
PLANAGENT_DATABASE_URL=<redacted>
  .venv/bin/python -m alembic downgrade 0038_seminar_tables
PLANAGENT_DATABASE_URL=<redacted>
  .venv/bin/python -m alembic upgrade head   # re-up
```

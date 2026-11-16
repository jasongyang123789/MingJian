# Sprint 19 — Seminar durability: distributed synthesize lock, audit retention, similarity upgrade

Branch: `strategy-engine/sprint19-seminar-durability` (from S18 tip `e35c0ce`).
Base suite: 1743 passed. This sprint: 76 new tests, 0 failed; full suite
1819 passed (see §4). No live LLM calls anywhere; fixture/fake-port only.
No scheduler, worker, or background job (Sprint 9 boundary) — the purge is
an explicit endpoint only.

Sprint 19 closes the three limits Sprint 18 carried forward: the
synthesize lock was per-process, the audit log had no retention policy,
and the near-duplicate pre-pass used token-set Jaccard only.

## 1. What was built

### 1.1 Distributed synthesize lock (lock abstraction + lease provider)

- `src/planagent/services/seminar/locks.py` (new): a `SynthesizeLockProvider`
  protocol (`acquire(seminar_id)` async context manager yielding a
  `LockAcquisition`: `wait_ms`, `contended`, `took_over_expired`,
  `previous_holder_id`, `fencing_token`, `holder_id`) with two providers
  selected per seminar by config:
  - `ProcessLockProvider` — Sprint 18 behavior preserved exactly: one
    `asyncio.Lock` per seminar id, never deleted, unbounded wait. This is
    the default (`synthesize_lock_provider="process"`).
  - `LeaseLockProvider` — distributed DB leases. Acquire is one transaction
    per attempt: INSERT the row (fresh acquire, fencing token 1); on
    `IntegrityError`, SELECT the row — missing means retry, unexpired means
    poll, expired means a conditional UPDATE keyed ONLY on the observed
    `holder_id` (no DB-side datetime comparison, so the same code path
    works on SQLite and Postgres; the holder-match alone is atomic
    because holders never extend and holder ids are unique per
    acquisition). A successful takeover increments the fencing token.
    Waiters poll with backoff (0.05s doubling to a 0.25s cap) up to a
    configurable wait timeout (default 120s); exceeding it raises
    `LockTimeoutError`. Release deletes only where `seminar_id` AND
    `holder_id` match, best-effort (failures swallowed with a debug log;
    the TTL is the backstop). Defaults: TTL 600s (covers the slowest
    observed live synthesis, ~235s, with margin), wait timeout 120s.
    The provider takes a constructor-injected async session factory;
    the service defaults it lazily to `get_database().session`.
- Migration 0040 (`migrations/versions/0040_seminar_synthesize_leases.py`,
  new) + ORM record `SeminarSynthesizeLeaseRecord`: table
  `seminar_synthesize_leases` — `seminar_id` (PK, FK to seminars),
  `holder_id`, `fencing_token`, `expires_at`, `acquired_at`,
  `holder_label`. Drill verified by hand on a scratch DB (see §4).
- Service wiring (`service.py`): `synthesize_seminar` and
  `submit_chair_synthesis` read ONLY the frozen config before locking
  (scalar `select(SeminarRecord.config)` — the row never enters the
  session identity map, so the under-lock state read cannot see a stale
  cached instance), choose the provider, and acquire. A contended
  acquisition records the existing `queue_wait` audit event (unchanged
  shape: `wait_ms`, `trigger`); a takeover records the new
  `lease_takeover` event naming the previous holder and the new fencing
  token. A lease wait timeout records a refusal event and raises
  `SeminarServiceError("seminar_synthesize_lock_timeout")`. The
  `seminar_synthesize_stuck` semantics are unchanged (the stuck-state
  check still runs under the lock). Both entry points share the same
  provider code path, so a submission and a synthesize serialize
  against each other exactly as in Sprint 18.
- New audit kind `lease_takeover` (15 kinds total); `DiagnosisSummary`
  gains `lease_takeovers`.

### 1.2 Audit retention policy (explicit purge endpoint)

- Config: `audit_retention_max_events` / `audit_retention_max_age_days`
  on `SeminarConfig` / `SeminarCreateRequest` (`int | None`, `None` = no
  floor on that dimension), global defaults 1000 events / 90 days, set at
  seminar creation.
- `POST /seminars/{id}/audit/purge` (200, `AuditPurgeRead`): body
  `keep_last_n` and/or `older_than_days` (at least one required — a
  missing-criteria body is a 422 shape error). An event survives only if
  it satisfies EVERY given bound (among the newest K by seq AND younger
  than the cutoff); age is strict (exactly at the cutoff is kept).
  Criteria below the configured policy floor refuse with
  `seminar_retention_floor` and only a refusal event written (no
  deletions). The purge deletes the oldest events beyond the limit in
  one DELETE, then writes ONE `retention_purged` summary event in the
  same transaction — always, even when nothing is deleted (deleted_count
  0). The summary's seq continues monotonically from the pre-purge max
  (explicit seq, inserted directly, not via the recorder), so seqs never
  restart even after a full wipe. The summary carries `deleted_count`,
  the deleted seq range, the criteria, the policy, per-kind counts, and
  the purged budget totals (`purged_stage_calls` / `purged_tokens`
  computed via `ledger_totals` over the victims, so totals chain forward
  when an old summary is itself purged). Purge touches audit rows only —
  reports, rounds, finals, briefs, and board rows are never modified.
- Budget ledger roll-forward (`audit.py`): `ledger_totals` now also sums
  the carried totals of surviving `retention_purged` summaries, so
  purging never resets the budget ledger — budgets hold across purges
  exactly as they hold across waves and restarts. Diagnosis, by design,
  reflects surviving events only (see decision 8).
- Retention status surfacing: a new `GET /seminars/{id}/audit/retention`
  endpoint (`AuditRetentionRead`: event count, oldest/newest seq,
  policy), a new `retention` field on `SeminarDetailRead`, and the
  retention block in the purge response. `GET /audit` keeps returning
  `list[AuditEventRead]` unchanged (see decision 7).
- Pure helper `select_purge_victims` in `audit.py` (victims in seq order;
  negative inputs raise `ValueError`; naive datetimes coerced to UTC).
  `DiagnosisSummary` gains `events_purged` (sum of `deleted_count` over
  surviving summaries).

### 1.3 Similarity upgrade (CJK tokens, stemming, bigrams, embedding seam)

- `src/planagent/services/seminar/similarity.py` (new): the scorer used
  by the near-duplicate pre-pass.
  - CJK-aware tokenization: each CJK character is one token; Latin/digit
    runs are word tokens; whitespace/punctuation separate. CJK ranges:
    U+3400–U+4DBF, U+4E00–U+9FFF, U+F900–U+FAFF, U+3040–U+30FF,
    U+AC00–U+D7A3, U+20000–U+2A6DF. CJK punctuation acts as a separator.
  - Combined score = MAX(token-set Jaccard, char-bigram Jaccard) on the
    0.8 default threshold (see decision 9). Bigram edge rule: texts with
    fewer than 2 content characters compare by equality (1.0 if equal,
    else 0.0), so distinct single-character claims never group via empty
    bigram sets.
  - Light conservative English stemming (`stem_word`): at most one rule,
    first match wins, longest suffix first — `ies`→`y` (len>4); `ing`
    strip (len>5) + undouble; `ed` strip (len>4) + undouble; `es` strip
    (len>4, stem ends s/x/z/ch/sh); `s` strip (len>3, not ending
    `ss`/`us`/`is`/`oes`). Untouched: words <3 chars, words containing
    digits. Undouble consonant set `bdgmnprt` (excludes s/l/z so
    pass/fill/buzz stay intact). No `e` is re-added (`agreed`→`agre`, a
    documented under-merge). Stemming applies only to similarity token
    sets — never to `normalized_text` (exact grouping unchanged) and
    never to bigram computation.
  - `jaccard_similarity` moved into `similarity.py` and re-exported from
    `clustering.py` (existing imports keep working). `token_set` in
    `clustering.py` is kept as the raw splitter for backward
    compatibility; scoring uses `similarity_tokens`.
  - `group_near_duplicates` gained an optional `similarity` parameter
    (default `JaccardClaimSimilarity`); the representative is still the
    first exact group's normalized TEXT (stable, never moves — the same
    no-chaining discipline). `deterministic_prepass` gained an optional
    `similarity` parameter and records `"similarity_provider"`
    (`"jaccard"`/`"embedding"`) in its output dict; the
    `render_prepass_groups` header names the provider. The pre-pass
    remains advisory only.
  - Embedding seam: `ClaimSimilarity` protocol (`name` + `similarity`
    over normalized texts), `VectorProvider` protocol (`vector_for`
    returns a tuple or None), `VectorScorer` protocol,
    `CosineVectorScorer` (clamped [0,1]; 0.0 on zero-norm, dimension
    mismatch, or empty input), `StaticVectorProvider` (dict-backed, exact
    normalized-text lookup, used in tests), `EmbeddingClaimSimilarity`
    (missing vector → 0.0, documented, never an exception). No real
    provider ships in Sprint 19; no model downloads, no network.
- Config switch: `similarity_provider: "jaccard" | "embedding"`
  (default `"jaccard"`). The service takes an optional `vector_provider`
  (constructor injection). Requesting `embedding` without a wired
  provider refuses at creation with
  `seminar_similarity_provider_missing` (before any row is written) and
  again loudly at synthesize time (defense in depth) — never a silent
  fallback to Jaccard.
- Existing near-duplicate tests: ZERO re-pinning was needed. All 45
  pre-existing tests in `test_seminar_near_duplicates.py`,
  `test_seminar_clustering.py`, and `test_seminar_templates.py` pass
  unchanged under the upgraded scorer — no existing expectation changed
  grouping, so there are no changed expectations to document.

## 2. Design decisions

1. **Lease takeover keyed on holder_id only, never on a DB-side datetime
   comparison.** SQLite and Postgres render bound datetimes differently;
   comparing `expires_at` in SQL would need dialect-specific handling.
   The conditional UPDATE matches only the observed `holder_id`: atomic
   because holders never extend a lease and holder ids are unique per
   acquisition. Expiry is judged in Python from the SELECTed row.
2. **Fencing token starts at 1 on fresh insert, +1 on takeover, and resets
   after release+reinsert.** Holder-id uniqueness is the primary guard;
   the token orders successive holders of one contended row and is
   reported in the takeover audit event.
3. **No lease renewal in Sprint 19.** The 600s TTL covers the slowest
   observed synthesis (~235s) with margin; the `synthesizing`
   stuck-state check is the second defense if a slow holder is taken
   over. Renewal is deferred (see §7).
4. **Config read before locking is a scalar read, not a row load.** The
   config is frozen at creation, so reading it pre-lock is sound; the
   scalar form keeps the row out of the identity map so the under-lock
   read is always fresh. Mutable state is never read before the lock.
5. **The service never derives a lease session from the caller's session.**
   A probe showed `AsyncSession.get_bind()` returns the sync Engine,
   which cannot build an AsyncSession. The lease session factory is
   constructor-injected, defaulting lazily to `get_database().session`
   (file-SQLite uses NullPool: a fresh connection per session, which is
   what makes the multi-connection contract real).
6. **Purge always writes the summary event, even on a no-op.** The
   "exact-limit no-op" means no old events are deleted — but the purge
   itself is still recorded, so every purge request leaves exactly one
   audit trace and seqs stay gapless-by-construction from the reader's
   point of view.
7. **Retention status is NOT added to `GET /audit` responses.** The brief
   asked for retention status in GET /audit responses and GET detail
   diagnosis; the sibling Sprint 20 cockpit track builds against
   `GET /audit` returning `list[AuditEventRead]`, so that shape is
   preserved. Retention status is served via the new
   `GET /seminars/{id}/audit/retention` endpoint, the new `retention`
   field on `SeminarDetailRead`, and the purge response. Diagnosis
   carries `events_purged` / `lease_takeovers` counters but not the
   policy block. This is the one deliberate deviation from the brief's
   literal wording; the information is served, at stable shapes, in
   three places instead of one.
8. **Diagnosis reflects surviving events only; budgets roll forward.**
   After a purge, diagnosis `stage_calls`/`total_tokens` drop (the
   finished events are gone), while `budgets` holds exactly via the
   carried summary totals. Rationale: budgets are a ledger (money spent
   stays spent); diagnosis is a summary of what the log still shows.
   Pinned in `test_budgets_and_diagnosis_hold_across_full_purge`.
9. **Combined similarity score = MAX, not weighted.** Either strong signal
   proposes a candidate because the signals catch different shapes
   (token overlap vs character overlap); the pre-pass is advisory, so
   recall matters more than precision, and the 0.8 threshold stays on
   the combined score. Pinned both ways in tests (a tokens-only pair and
   a bigrams-only pair each group at 0.8).
10. **Embedding scorer never raises on a missing vector (0.0), but a
    missing PROVIDER refuses loudly.** A missing vector for one claim is
    a data gap (score 0.0, no grouping); a missing provider for a whole
    seminar is a configuration error (refuse at creation, never silently
    fall back to Jaccard).
11. **`queue_wait` is recorded only when the acquisition actually
    contended.** Unchanged from Sprint 18: the process provider reports
    `contended` from `lock.locked()` at acquire time; the lease provider
    reports it when the first INSERT fails. A solo synthesize writes no
    `queue_wait` event.
12. **Report hashes change vs Sprint 18.** `compute_report_hash` covers
    the pre-pass, which now carries `similarity_provider` — the same
    inputs hash differently than under S18. This is a deterministic
    input change, not nondeterminism: same-version resynthesis tests
    compare within one version and pass.

## 3. Files changed

- New: `src/planagent/services/seminar/similarity.py`,
  `src/planagent/services/seminar/locks.py`,
  `migrations/versions/0040_seminar_synthesize_leases.py`,
  `tests/unit/test_seminar_similarity.py`,
  `tests/unit/test_seminar_locks.py`,
  `tests/unit/test_seminar_audit_retention.py`,
  `tests/test_seminar_lease_lock.py`, `tests/test_seminar_retention.py`,
  `tests/test_seminar_s19_api.py`, `docs/sprint19/test-full.log`.
- Modified: `src/planagent/services/seminar/clustering.py`,
  `src/planagent/services/seminar/audit.py`,
  `src/planagent/services/seminar/models.py`,
  `src/planagent/services/seminar/service.py`,
  `src/planagent/api/routes/seminars.py`,
  `src/planagent/domain/models.py` (lease record only), `BACKLOG.md`,
  `SPRINT19.md` (this file).
- Untouched, as required: all frontend files, all automotive/splits
  code, the 17-template v2 pin, seminar registry v1 template pins (no
  new templates).

## 4. Verification

- New-test subset (76 tests): 19 similarity + 10 lease-lock unit + 19
  unit retention + 13 service retention + 7 lease-queue/similarity
  service + 8 API — all passed in one run (76 passed).
- Pre-existing seminar subset (219 tests across 17 files, incl. all
  near-duplicate, clustering, hardening, agent-chair, and API tests):
  all passed, zero re-pinning.
- Full suite: 1819 passed, 0 failed (base 1743 + 76 new), run with the
  lock protocol (`mkdir ~/workspace/.pytest-full-run.lock`,
  `TMPDIR=/dev/shm/pytest-tmp-s19`, lock released + TMPDIR cleaned
  after). Log force-added at `docs/sprint19/test-full.log`.
- Sprint 0 smoke: PASS (`docs/sprint0/smoke_e2e.py`); the evidence file
  was reverted afterwards.
- Ruff: `ruff check` on all touched files reports exactly the 35
  pre-existing findings in `src/planagent/domain/models.py` (verified
  identical at `e35c0ce`) — zero new findings. New files are
  `ruff format`-clean; two pre-existing format hunks in `service.py`
  and one in `clustering.py` were left untouched as pre-existing drift.
- Mypy: clean on all touched seminar files + the seminars route module
  (`Success: no issues found in 7 source files`).
- Migration drill (scratch DB, by hand): upgrade to
  `0039_seminar_audit_chair_briefs` → no `seminar_synthesize_leases`
  table; upgrade head → table present with columns
  `seminar_id, holder_id, fencing_token, expires_at, acquired_at,
  holder_label`; downgrade to 0039 → table gone; re-upgrade →
  `alembic current` reports `0040_seminar_synthesize_leases (head)`,
  columns present.
- The multi-connection serialization test uses threads with separate
  engines/connections against one SQLite file (the brief's accepted
  form), `connect_args={"timeout": 30}`.

## 5. Behavior evidence (all asserted test values, with test names)

### 5.1 Lease lock

- `test_both_lock_providers_serialize_into_versions_1_and_2`
  (parameterized `process` + `lease`): two concurrent synthesizes yield
  versions {1, 2}, identical `report_hash`, exactly 1 `queue_wait` event
  with `wait_ms > 0` and `trigger == "synthesize"`, detail status
  `reported` with 2 reports, and no lease rows remaining.
- `test_expired_lease_is_taken_over_and_audited`: a seeded expired lease
  (holder `dead-holder`, fencing 3) is taken over — exactly 1
  `lease_takeover` event with `previous_holder_id == "dead-holder"`,
  `fencing_token == 4`, `trigger == "synthesize"`; synthesis succeeds
  (version 1); no lease rows remain.
- `test_lease_wait_timeout_refuses_and_records_a_refusal`: a live seeded
  lease + 0.2s wait timeout → `SeminarServiceError` code
  `seminar_synthesize_lock_timeout`, exactly 1 `refusal` event with that
  code, zero report rows, the other holder's lease untouched.
- `test_lease_lock_provider_synthesizes_over_http` (API): a seminar
  created with `synthesize_lock_provider="lease"` synthesizes over HTTP
  (201, version 1) via the lazy `get_database()` lease factory.
- Unit (`tests/unit/test_seminar_locks.py`, 10 tests): process-provider
  serialization + uncontended acquire; lease acquire/release round-trip;
  a second acquirer waits then acquires; release deletes only for the
  holding holder; wait timeout raises and leaves the row held; invalid
  config refuses; expiry takeover bumps the fencing token; a live lease
  is never taken over; and the threads multi-connection serialization
  test.

### 5.2 Retention

- `test_purge_exact_limit_is_noop_but_writes_summary`: 3 events +
  `keep_last_n=3` → `deleted_count == 0`, `remaining_count == 4`, seqs
  [1,2,3,4], the seq-4 row a `retention_purged` summary.
- `test_purge_over_limit_deletes_oldest_only`: 5 events +
  `keep_last_n=2` → deleted 3 (seqs 1–3), survivors [4,5,6], summary
  `deleted_count == 3`.
- `test_purge_older_than_days_deletes_old_events_only`: 2 ten-day-old +
  1 current event, `older_than_days=5` → deleted 2, survivors [3,4].
- `test_purge_full_wipe_seq_continues_monotonically`: `keep_last_n=0`
  twice → first summary seq 4, second summary seq 5 (the first summary
  was itself purged); seqs never restart.
- `test_purge_below_event_floor_refuses_and_deletes_nothing`: default
  floor (1000) + `keep_last_n=5` → code `seminar_retention_floor`, both
  seeded events survive, exactly one `refusal` event added.
- `test_purge_below_age_floor_refuses`: default floor (90 days) +
  `older_than_days=10` → `seminar_retention_floor`.
- `test_purge_at_floor_boundary_is_allowed`: `keep_last_n=1000` +
  `older_than_days=90` (exactly the floor) → allowed, no-op + summary.
- `test_purge_one_seminar_leaves_another_untouched`: purging one
  seminar to seq [4] leaves the other's seqs [1,2,3].
- `test_purge_leaves_reports_rounds_finals_and_briefs_untouched`:
  rounds/finals/reports/board/brief counts identical before/after full
  purges on both a model-chair and an agent-chair seminar.
- `test_budgets_and_diagnosis_hold_across_full_purge`: 24 stage calls ×
  15 tokens → `budgets.tokens_used == 360` and `stage_calls_used == 24`
  before AND after a full purge; diagnosis `stage_calls == 0` after
  (surviving-events-only); `events_purged` equals the number of events
  the purge deleted.
- `test_retention_status_in_detail_and_read_endpoint`: after purging to
  2, detail `retention == {event_count: 3, oldest_seq: 2, newest_seq: 4,
  max_events: 2, max_age_days: 30}`.
- Unit (`tests/unit/test_seminar_audit_retention.py`, 19 tests): victim
  selection boundaries (exact-limit no-op, above-count no-op, keep-0
  deletes all, seq-order not input-order, exactly-at-cutoff kept,
  both-criteria intersection incl. the strict case where a new-but-old
  event is deleted, no-criteria no-op, negative inputs rejected, naive
  datetimes treated as UTC), ledger roll-forward incl. chained
  summaries, diagnosis counters.
- API (`tests/test_seminar_s19_api.py`): purge compacts and reports
  status (deleted range + retention block + `GET /audit` still a plain
  list); floor refusal is 400 with code; `{}` body is 422; unknown
  seminar is 404 on both new endpoints; retention endpoint returns the
  default policy (1000/90); detail includes the retention block.

### 5.3 Similarity

- `tests/unit/test_seminar_similarity.py` (19 tests): combined score is
  MAX (pinned both ways — a tokens-only pair and a bigrams-only pair
  each group at 0.8); `bigram("demand grows", "demand grows steadily")
  == 10/18`; `"abcdefghij"` vs `"abcdefghix"`: token Jaccard 0.0,
  bigram 0.8, combined 0.8; CJK `"需求增长强劲"` vs `"需求增长"`:
  combined 2/3; stemming rules incl. `ies`→`y`, undouble, `ss`/`us`
  protection, digit-containing words untouched, `agreed`→`agre`
  under-merge; single-character texts compare by equality; embedding
  seam (cosine clamp, dimension mismatch → 0.0, missing vector → 0.0).
- `test_embedding_similarity_without_provider_refuses_at_creation`:
  `embedding` with no vector provider → code
  `seminar_similarity_provider_missing`, before any row is written.
- `test_embedding_similarity_with_provider_records_provider_in_prepass`:
  with a `StaticVectorProvider`, the brief pre-pass records
  `similarity_provider == "embedding"`.
- `test_jaccard_default_records_jaccard_provider_in_prepass`: default
  records `"jaccard"` even when a vector provider is wired.

## 6. Known limits

- No lease renewal: a synthesis slower than the 600s TTL can lose its
  lease mid-flight; the `synthesizing` stuck-state check is the second
  defense, and the takeover is audited. Renewal is a future-sprint
  follow-up.
- The default lock provider is still `process` (per-process). The lease
  provider must be selected per seminar at creation; there is no global
  switch or migration of existing seminars to leases.
- Fencing tokens reset after release+reinsert (holder-id uniqueness is
  the primary guard); tokens order holders only within one contended
  row lifetime.
- Diagnosis reflects surviving events only (decision 8): after a purge,
  diagnosis `stage_calls`/`total_tokens` no longer equal the budget
  ledger. Readers must use `budgets` for cumulative totals.
- The purge summary event is itself purged by LATER purges (only the
  same-call summary is protected, by construction). The budget totals
  chain forward, but the per-purge `deleted_count` history compacts.
- Concurrent advances to one seminar are still unserialized (pre-existing
  Sprint 18 limit, unchanged — only synthesize/submission serialize).
- `max+1` version/seq assignment has no unique constraint (pre-existing
  limit, unchanged).
- The lease path is verified on SQLite only. The SQL is deliberately
  dialect-neutral (no Postgres-only constructs), but Postgres was not
  run on this VM (no Postgres available), same as all prior sprints.
- The embedding seam has no real provider: `StaticVectorProvider` is a
  test fake; wiring a real embedding model is deferred (see §7).
- No live-LLM paths were exercised (zero live calls, by design); the
  chair/synthesis behavior under the new lock is covered by fake ports
  only. Real-browser rendering and the Docker stack remain unverified
  (pre-existing).
- Report hashes differ from Sprint 18 for identical inputs (decision
  12) — expected, deterministic, and version-scoped.

## 7. Deferred / deliberately not built

- Lease renewal / heartbeat (documented limit; TTL + stuck-state check
  suffice for observed synthesis durations).
- A real embedding provider (interface + fake only, per the brief; no
  model downloads, no network).
- Direction-as-variable-overrides (option B) and LLM-proposed directions
  (option C) — pre-existing deferrals, untouched.
- A global/config-file switch for the lock provider (per-seminar config
  only, per the brief).
- Any scheduler/worker/background retention job (explicitly forbidden by
  the Sprint 9 boundary; the purge endpoint is the only purge path).
- No new templates; the 17-template v2 pin and seminar registry v1 pins
  are untouched. No frontend, automotive, or splits changes.

## 8. Commits

- `6cea937` — Sprint 19: similarity upgrade (CJK tokens, stemming,
  bigram MAX score, embedding seam)
- `998646c` — Sprint 19: distributed lease lock provider + migration 0040
- `98b96a7` — Sprint 19: retention plumbing (audit kinds, victim
  selection, ledger roll-forward, lock/similarity/retention config +
  purge models)
- `f1b1861` — Sprint 19: service + route wiring (lock providers,
  similarity switch, purge + retention endpoints)
- `70a4cb5` — Sprint 19: retention, lease-queue, similarity-switch, and
  API tests
- `3f28692` — Sprint 19: ruff/mypy fixes (UTC alias, unused import,
  protocol context-manager typing, formatting)
- (this commit) — Sprint 19 report, backlog update, verification log

## 9. Reproduce

```bash
# New-test subset (76 tests):
TMPDIR=/dev/shm/pytest-tmp-s19 env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest \
  tests/test_seminar_s19_api.py tests/test_seminar_retention.py \
  tests/test_seminar_lease_lock.py tests/unit/test_seminar_audit_retention.py \
  tests/unit/test_seminar_similarity.py tests/unit/test_seminar_locks.py -q
# Full suite (claim the lock first; see §4):
mkdir ~/workspace/.pytest-full-run.lock
TMPDIR=/dev/shm/pytest-tmp-s19 env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest -q
# Sprint 0 smoke (revert the evidence file afterwards):
env -u NO_PROXY -u no_proxy .venv/bin/python docs/sprint0/smoke_e2e.py
git checkout -- docs/sprint0/smoke-evidence.json
# Migration drill (scratch DB):
PLANAGENT_DATABASE_URL=sqlite+aiosqlite:////tmp/s19-drill.db \
  .venv/bin/python -m alembic upgrade 0039_seminar_audit_chair_briefs
PLANAGENT_DATABASE_URL=sqlite+aiosqlite:////tmp/s19-drill.db \
  .venv/bin/python -m alembic upgrade head   # 0040
PLANAGENT_DATABASE_URL=sqlite+aiosqlite:////tmp/s19-drill.db \
  .venv/bin/python -m alembic downgrade 0039_seminar_audit_chair_briefs
PLANAGENT_DATABASE_URL=sqlite+aiosqlite:////tmp/s19-drill.db \
  .venv/bin/python -m alembic upgrade head   # re-up
```

## 10. API changes for the cockpit track

- New request fields on `SeminarCreateRequest` (all optional, all with
  defaults): `similarity_provider` (`"jaccard"`/`"embedding"`,
  default `"jaccard"`), `synthesize_lock_provider`
  (`"process"`/`"lease"`, default `"process"`), `lease_ttl_seconds`
  (default 600), `lock_wait_timeout_seconds` (default 120),
  `audit_retention_max_events` (default 1000, nullable),
  `audit_retention_max_age_days` (default 90, nullable). Same fields
  echoed on `SeminarConfig` in responses.
- New field `retention` on `SeminarDetailRead` (dict:
  `seminar_id, event_count, oldest_seq, newest_seq, max_events,
  max_age_days`).
- New endpoints: `POST /seminars/{id}/audit/purge` (200,
  `AuditPurgeRead`) and `GET /seminars/{id}/audit/retention`
  (`AuditRetentionRead`).
- `GET /seminars/{id}/audit` is UNCHANGED (still `list[AuditEventRead]`).
- New audit event kinds: `lease_takeover`, `retention_purged`.
- New diagnosis counters: `lease_takeovers`, `events_purged`.
- Pre-pass dicts gain `similarity_provider` (`"jaccard"`/`"embedding"`).
- New refusal/error codes: `seminar_synthesize_lock_timeout`,
  `seminar_retention_floor`, `seminar_similarity_provider_missing`.

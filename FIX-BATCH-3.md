# Fix batch 3 — Postgres-only bugs from Docker retry 6: dialect insert + seed BigInteger

Branch: `strategy-engine/fix-batch-3-postgres-bugs`, from tip `4669016`
(branch `strategy-engine/sprint20-cockpit-seminar`). Ho approved all of
it 2026-11-18 ("两个 bug 都修，修完重跑补验").

Docker retry 6 (report
`~/workspace/verification/docker-stack-hub-2026-11-17/REPORT-retry-6-cleanup.md`)
ran the no-LLM flow against real Postgres for the first time and found
two product bugs that no SQLite test can catch, plus the worker-log
buffering root cause and two script-body issues. This batch fixes all
four. The live Postgres proof is the hub re-run after merge (see §7);
there is no Postgres on this VM, so the test strategy below is stated
explicitly instead of implied.

## 1. The bugs (verified from the live run, not assumed)

### 1.1 Bug 1 — POST /ingest/runs 500: generic insert has no `on_conflict_do_nothing`

Hub api traceback (retry 6, §6.2):

```text
File ".../services/pipeline.py", line 486, in _persist_raw_item
    .on_conflict_do_nothing(index_elements=["dedupe_key"])
AttributeError: 'Insert' object has no attribute 'on_conflict_do_nothing'
```

`pipeline.py` imported the generic `sqlalchemy.insert`, but
`.on_conflict_do_nothing()` exists only on
`sqlalchemy.dialects.postgresql.insert`. The code branches on dialect:
non-SQLite takes the ON CONFLICT branch, SQLite takes the
IntegrityError fallback — so every SQLite test skipped the broken
line, and the bug surfaced only on real Postgres.

### 1.2 Bug 2 — POST /monte-carlo 500: 63-bit trial seed into a 32-bit column

Hub api traceback (retry 6, §6.3):

```text
File ".../services/simulation/distributions.py", line 243, in _create_monte_carlo_trial
    await session.flush()
psycopg.errors.NumericValueOutOfRange: integer out of range
```

`derive_sub_seed` (`services/distributions/canonical.py`) returns a
63-bit integer (SHA-256, masked to 2^63−1). Trial runs store it in
`SimulationRun.seed`, which was `mapped_column(Integer)` — 32-bit
`integer` on Postgres (confirmed on the hub: `\d simulation_runs`
shows `seed | integer | not null`). SQLite integers are always 64-bit,
so its tests passed. The same 63-bit values also reach
`SimulationRun.seed` through robustness threshold-search probes
(`robustness.py:_create_analysis_run`), a second path to the same
failure — see the sweep in §4.

Cascade (retry 6, §6.5): with no ensemble stored, tornado, narrative
generation, and polish could not be exercised; their cascade refusals
were themselves correct.

## 2. What changed

### 2.1 Postgres branch uses the dialect insert (`services/pipeline.py`)

The non-SQLite branch now builds its statement with
`sqlalchemy.dialects.postgresql.insert` (imported as
`postgres_insert`). The generic `insert` import is removed: its only
use in the file was this branch. The SQLite branch (ORM + IntegrityError
fallback) is byte-identical behavior, untouched. The dialect condition
(`!= "sqlite"`) is unchanged — the supported non-SQLite dialect is
Postgres, and the fix makes the code match that reality instead of
re-deciding dialect policy.

### 2.2 Seed columns widen to BigInteger (`domain/models.py` + migration 0043)

`SimulationRun.seed` and `CalibrationFitRecord.seed` change from
`Integer` to `BigInteger`, with comments pinning the reason at each
site. Migration `0043_seed_columns_bigint` (revises
`0042_direction_override_record`) alters both columns via
`batch_alter_table`, with a downgrade back to `Integer`.

Why widen the columns instead of narrowing the seeds: narrowing
`derive_sub_seed` to 31 bits would change RNG streams and stored
determinism hashes. The values stay exactly as derived; the columns
grow to hold them. SQLite behavior is unchanged (its integers were
already 64-bit).

Why `calibration_fits.seed` too: it takes only `request.seed`, but
that field is an unbounded `int` in both fit request models
(`PolicyFitRequest`, `RuleWeightFitRequest`), so a 63-bit value can
reach the column through the public API — the identical failure class.
Widening it in the same migration costs nothing on SQLite and removes
the second Postgres-only 500 waiting to happen. See the audit in §4.

Note for the hub re-run: the hub stack builds its schema with
`create_all` (retry 5 report), so it picks up `BigInteger` from the
model directly; the migration covers migration-managed deployments.
Model and migration agree.

### 2.3 Unbuffered stdout in the Docker image (`Dockerfile`)

`ENV PYTHONUNBUFFERED=1` right after `FROM`. Retry 6 §4 root-caused
the empty worker logs: CPython block-buffers stdout on pipes (the
docker log driver), so `print()` status lines sat in the buffer until
~8KB accumulated. One Dockerfile serves the api and all 11 workers
(verified: every `build:` block in `docker-compose.yml` points at it;
`docker/postgres/Dockerfile` is the Postgres image and is untouched),
so this single change covers every service. No `python -u` flag
changes, no worker-code changes.

### 2.4 `verify-no-llm.sh` steps 21/23 get legal bodies (outside the fork)

Steps 21 and 23 posted `{}` and got 422s (missing required fields) —
correct request validation, wrong script. They now post the bodies
proven in the retry-6 follow-up probe (§6.4), so the 503
`skill_llm_unavailable` assertions land inside the script:

- step 21: `{"topic":"Should we launch?"}` (`StrategyTeamRequest.topic`
  is required — verified in `services/skills/models.py`)
- step 23: `{"decision":"Should we launch?"}` (`AdvisoryBoardRequest.decision`
  is required — same file)

The script lives at
`~/workspace/verification/docker-stack-hub-2026-11-17/verify-no-llm.sh`
(outside the fork; no copy exists inside the fork — checked). It still
reads the proxy header from the hub-side `.env` at runtime and prints
nothing secret. `bash -n` passes. The hub re-run must scp the updated
script — the hub-side copy is stale until then.

## 3. Evidence (every number below is an asserted test value; test named)

### 3.1 New tests: 9 passed

No live Postgres exists on this VM, so the bug-1 tests execute the
real branch code with a dialect-mocked session, and the bug-2 tests
assert the column type (which fails on the old model) plus persistence
of the exact production values. Negative controls (below) prove the
tests catch the old code.

| # | Behavior | Test |
|---|----------|------|
| 1 | Postgres branch executes a dialect `Insert` rendering `ON CONFLICT (dedupe_key) DO NOTHING`; row returned; `RAW_INGESTED` buffered | `test_postgres_branch_uses_dialect_insert_with_on_conflict` |
| 2 | Postgres branch, rowcount 0 → `None`, no re-select, no event | `test_postgres_branch_duplicate_returns_none_without_reselect` |
| 3 | SQLite branch executes no statement; ORM row with the dedupe key returned | `test_sqlite_branch_still_uses_orm_path` |
| 4 | `SimulationRun.seed` column type is `BigInteger` | `test_simulation_run_seed_column_is_bigint` |
| 5 | `CalibrationFitRecord.seed` column type is `BigInteger` | `test_calibration_fit_seed_column_is_bigint` |
| 6 | `derive_sub_seed(7, "monte-carlo", "0")` is above 2^31−1 and below 2^63 | `test_derived_sub_seed_is_63_bit` |
| 7 | The exact derived trial seed persists on a `SimulationRun` row and reads back equal | `test_63bit_derived_seed_persists_on_simulation_run` |
| 8 | A 63-bit seed persists on a `CalibrationFitRecord` row and is queryable by value | `test_63bit_seed_persists_on_calibration_fit` |
| 9 | Migration 0043: types INTEGER → BIGINT → INTEGER → BIGINT across upgrade/downgrade/re-upgrade; seeded 63-bit rows survive with values intact | `test_seed_columns_become_bigint_and_keep_rows` |

Tests 1–8 live in `tests/unit/test_fix_batch_3_postgres.py`; test 9 in
`tests/unit/test_migrations.py` (subprocess-alembic pattern, same as
the two pre-existing tests there).

### 3.2 Negative controls: the tests fail on the old code

- Bug 1: with only the `pipeline.py` fix stashed, test 1 fails with
  the exact production error:
  `AttributeError: 'Insert' object has no attribute 'on_conflict_do_nothing'`
  at `pipeline.py:486`.
- Bug 2: with the model change stashed and migration 0043 set aside,
  tests 4, 5, and 9 all fail (column type `Integer`; head stays 0042).
- Both controls were restored afterward; the working tree was
  re-verified (diffstat matches the fix).

### 3.3 Neighbor regression: 159 passed, 0 failed

| Group | Files | Result |
|---|---|---|
| Pipeline / ingest | `test_pipeline_service.py`, `test_pipeline_dedup.py`, `test_phase1_api.py` | 84 passed |
| Distributions / robustness / calibration | `test_distributions_api.py`, `test_robustness_api.py`, `test_calibration_api.py` | 54 passed |
| Narratives-adjacent + simulation API | `test_narratives_api.py`, `test_phase2_simulation_api.py` | 21 passed (29 with the 8 new tests in the same run) |

Plus `test_migrations.py` 3/3 (2 pre-existing + test 9). The full
suite was NOT run here — the main agent runs the partitioned gate at
the merged tip (see §7).

Process note: the distributions/robustness/calibration batch started
with 191M free on /dev/shm, below the 200M threshold set for this
track; it completed green with no disk errors. The other batches ran
above the threshold.

### 3.4 Migration drill (manual, scratch SQLite, DB removed afterward)

`0042 → 0043 → downgrade 0042 → re-upgrade 0043` via the alembic CLI
on `/dev/shm/drill-0043.db`, with seeded 63-bit rows in both tables:

| Step | `simulation_runs.seed` | `calibration_fits.seed` | Seeded rows |
|---|---|---|---|
| At 0042 | INTEGER | INTEGER | inserted |
| Upgrade head (0043) | BIGINT | BIGINT | values intact |
| Downgrade 0042 | INTEGER | INTEGER | values intact |
| Re-upgrade head | BIGINT | BIGINT | values intact |

Drill DB removed after the run. (The automated test 9 repeats this
same sequence; the drill is the independent manual execution.)

### 3.5 Type + lint

- `mypy` on all 5 touched Python files
  (`pipeline.py`, `models.py`, migration 0043, both test files):
  no issues.
- `ruff check` on the 3 modified tracked files: 40 findings, all
  pre-existing (35 `domain/models.py`, 4 `pipeline.py`, 1
  `test_migrations.py`) — the normalized finding multiset is
  identical to base tip `4669016` (verified via stash comparison:
  zero added, zero removed). The 2 new files are clean (one C408 in
  the new test file was found and fixed before commit).

### 3.6 Sprint 0 smoke: PASS

`docs/sprint0/smoke_e2e.py` → `SMOKE: PASS` (exit 0); the evidence
file was reverted afterward.

## 4. Sweep: every `derive_sub_seed` site and every seed column in `src/`

### 4.1 `derive_sub_seed` call sites (6, all in `src/`)

| Site | Destination | Verdict |
|---|---|---|
| `simulation/distributions.py:147` | `SimulationRun.seed` (Monte Carlo trial) | PERSISTED — the reported bug; fixed by 0043 |
| `simulation/robustness.py:564` | `_create_analysis_run` → `SimulationRun.seed` (threshold-search probe) | PERSISTED — same bug, second path; fixed by 0043 |
| `simulation/robustness.py:347–348` | `bootstrap_intervals(seed=...)` | In-memory RNG only; never stored |
| `simulation/robustness.py:412` | `distribution_median(seed=...)` | In-memory RNG only; never stored |
| `calibration/estimator.py:764–765` | `bootstrap_coefficient_intervals(seed=...)` | In-memory RNG only; never stored |
| `calibration/estimator.py:953` | `bootstrap_coefficient_intervals(seed=...)` | In-memory RNG only; never stored |

Tornado probes (`robustness.py:430,448`) pass `seed=seed` (request or
ensemble seed, not a derived sub-seed) into `_create_analysis_run`,
which writes `SimulationRun.seed` — covered by the same column
widening, as is every other `SimulationRun` construction that copies
a stored seed (replay, prediction revision, scenario branching).

### 4.2 Seed columns (2 in `domain/models.py`; no others in `src/`)

| Column | Writers | Verdict |
|---|---|---|
| `simulation_runs.seed` | Unbounded user seed (`SimulationRunCreate.seed: int = 7`, no range bound); 63-bit trial/probe seeds; copies of stored seeds | `BigInteger` (0043) |
| `calibration_fits.seed` | `request.seed` only, but unbounded `int` in both fit request models | `BigInteger` (0043) |

Ensemble seeds live only in JSON fragments and response models (no
ensemble seed column exists); Postgres JSONB holds 64-bit integers.
All other `Integer` columns in the model file are counts, rounds,
positions, and bounded quantities — none receive hash-derived or
unbounded values; all untouched.

## 5. Deliberately NOT changed

- No seed narrowing: `derive_sub_seed` and its 63-bit mask are
  untouched (RNG streams and determinism hashes must not move).
- No dialect-condition change: the `!= "sqlite"` branch test stays;
  only the statement constructor changes.
- No SQLite-branch change: the ORM + IntegrityError path is untouched.
- No `python -u` flags: `ENV PYTHONUNBUFFERED=1` covers api + workers
  from the single Dockerfile.
- No worker-code logging changes: `print()` without `flush=True` is
  fine once the interpreter is unbuffered; changing 11 workers' call
  sites was unnecessary churn.
- No `verify-no-llm.sh` changes beyond steps 21/23 (steps 3 and 8
  already exercise the two fixed endpoints; their expectations change
  from 500 to success on the hub re-run, which is the point of the
  re-run).
- No BACKLOG.md change (per the track brief; the main agent records
  the merge).

## 6. Limits (stated honestly)

- **No live Postgres proof in this batch.** Statement compilation
  against the `postgresql` dialect plus the column-type assertions
  are the strongest proof available on this VM; the end-to-end proof
  (ingest 201, monte-carlo 201, tornado/narratives/polish exercised)
  is the hub re-run after merge.
- **The Dockerfile change is unbuilt.** No Docker exists on this VM;
  the image rebuild happens on the hub re-run. The change is one
  `ENV` line with no layer-cache consequences beyond the env layer.
- **Migration 0043 was drilled on SQLite only.** The Postgres
  `ALTER COLUMN TYPE` path (integer → bigint) is standard Alembic
  DDL and was not executed anywhere; the hub stack uses `create_all`,
  so the hub re-run does not exercise the migration either. A
  migration-managed Postgres deployment would run it for the first
  time.
- **Migration 0043's downgrade cannot run while 63-bit seed rows
  exist (Postgres only; hub drill 2026-11-18, retry-7 report
  §21.5).** Downgrading bigint → integer with 63-bit values stored
  fails with `integer out of range` — Postgres narrowing-cast
  semantics, not a migration defect. The single-transaction
  downgrade rolls back cleanly: the version stays at 0043 and the
  seed rows are intact. Removing the 63-bit rows lets the downgrade
  succeed, and re-upgrading restores bigint. The SQLite drill
  (test 9) does not show this: SQLite narrowing is a no-op. This is
  a known limitation of the downgrade path, not a defect in 0043.
- **Postgres `ON CONFLICT` behavior itself is untested** (conflict
  → rowcount 0 → skip): the mocked-session test proves the statement
  shape and the rowcount-0 branch, not Postgres's execution of it.
  The hub re-run's ingest step plus a duplicate re-post would prove
  it; the script posts each item once.
- The `verify-no-llm.sh` edits are unexecuted (the script only runs
  on the hub); `bash -n` passes and the bodies are the exact ones
  proven by the retry-6 follow-up probe.

## 7. What was NOT verified

- The full backend suite in any form (single-process or chunked).
  Subsets + neighbors only, per the track brief; the partitioned
  gate runs at the merged tip.
- Live Postgres behavior of either fix (hub re-run, main agent).
- The rebuilt Docker image and unbuffered worker logs (hub re-run).
- Real-browser rendering of any kind (no frontend changes).
- Worker-ingest consumption of a real ingest run (blocked on bug 1
  until the hub re-run; retry 6 §6.5).
- The migration against Postgres (SQLite drill only; see §6).

## 8. Commits on this branch

- (implementation commit) — Postgres dialect insert, seed BigInteger
  columns + migration 0043, `PYTHONUNBUFFERED`, 9 tests.
- (this commit) — Fix batch 3 report.

`verify-no-llm.sh` (steps 21/23) is edited outside the fork and is not
part of either commit.

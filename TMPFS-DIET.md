# Tmpfs diet — the single-process full suite fits in 794M /dev/shm again

Branch: `strategy-engine/tmpfs-diet`, base `4669016`. One file changed:
`tests/conftest.py` (test-infra only; no product code, no test code, no
assertion touched). Ordered by Ho 2026-11-18 after the `939d7eb`
single-process run filled `/dev/shm` to 100% and killed 27 tests with
"database or disk is full".

Result: the single-process full suite now peaks at **1.96MB** of tmpfs
(measured, 10s sampling) instead of overflowing 794M — **2003 passed +
1 failed in 605s**, where the 1 failure is a pre-existing
order-dependent test exposed by this change (§7), not a tmpfs problem.
The chunked gate is no longer load-bearing for capacity; whether it
stays the default protocol is a decision for the parent (§8).

## 1. What was built

Two changes, both in `tests/conftest.py`:

### Per-test tmp cleanup (`remove_test_tmp_dir`, autouse, defined first)

```python
@pytest.fixture(autouse=True)
def remove_test_tmp_dir(tmp_path):
    yield
    if os.environ.get("PLANAGENT_KEEP_TEST_TMP") == "1":
        return
    shutil.rmtree(tmp_path, ignore_errors=True)
```

Deletes the test's OWN `tmp_path` tree when the test finishes. Defined
first in the file so it is set up first and torn down last — after
every test fixture and after the database-cache reset below — so no
teardown code can observe the removed directory. Deletion is
best-effort (`ignore_errors=True`): a failed removal only leaks the
dir, exactly as before, and can never fail the test.
`PLANAGENT_KEEP_TEST_TMP=1` keeps the dirs for debugging a failing
test (§4).

### Settings-cache reset (existing autouse fixture extended)

```python
@pytest.fixture(autouse=True)
def release_cached_database_and_settings_between_tests():
    yield
    reset_database_cache()
    reset_settings_cache()
```

`get_settings()` is `lru_cache`d and nothing reset it between tests, so
a test that set `PLANAGENT_DATABASE_URL` leaked its URL into every
later test that set none. The tmp cleanup exposed this leak (§7); the
fixture now closes it. Renamed from
`release_cached_database_between_tests` (autouse-only, no external
references — verified by grep).

## 2. Design decisions

### Measurements first (Step 1, before any change)

- One empty-schema scratch DB costs **1,675,264 bytes** (75-table
  schema, measured directly via `ensure_initialized` on a probe DB).
- Representative subsets, fresh TMPDIR on `/dev/shm`, leftovers
  inventoried after each run — **100% of the accumulation was `.db`
  files** under the pytest basetemp; no WAL/journal files, no exports,
  no other file types:

  | Subset | Tests | Leftover files | Leftover bytes | Largest DB |
  |---|---|---|---|---|
  | `test_mece_api` + `test_narratives_api` + `unit/test_seminar_locks` | 32 | 29 `.db` | 49,756,925 | 1,896,448 |
  | `unit/test_new_features` + `test_export_api` | 45 | 6 files | 6,701,514 | ~1.7MB |
  | `test_seminar_api` + `test_seminar_synthesis_service` + `test_task6_debate_interrupt_replay` | 47 | 40 `.db` | 69,459,390 | 1,814,528 |

  ~1.5MB per DB-creating test × ~500 such tests ≈ 750–800MB: the
  observed overflow (794M filled at 2004 tests; ~730M at 1940 tests on
  `b7c53b6`) is fully explained by pytest's never cleaning `tmp_path`
  dirs mid-session. Static analysis agrees: 521 test functions take
  `tmp_path`, 32 files build a `sqlite+aiosqlite` URL under it, zero
  `tmp_path_factory` use anywhere.
- Residual leak, measured and left alone: `TestExportService`
  (`unit/test_new_features.py`) uses `tempfile.mkdtemp()` with no
  teardown — 6 empty dirs, ~40 bytes total. Bounded, negligible; no
  second mechanism was built for it (§8).

### Why deleting a test's own tmp dir cannot change test semantics

- `tmp_path` is function-scoped and unique per test; no session- or
  module-scoped fixture takes it (verified: none exist), and the only
  fixtures taking `tmp_path` are function-scoped, so they tear down
  before this first-defined autouse fixture.
- No test can observe another test's tmp dir: zero
  `tmp_path_factory` / `getbasetemp` / basetemp reads anywhere in
  `tests/` or `src/` (verified by grep 2026-11-18).
- One apparent exception turned out to be a real finding, not a
  counterexample: one test reads another test's tmp DB file *through
  a leaked settings URL* (§7). It is reported, not papered over.

### What was deliberately NOT built

- No product-code or test-code edits of any kind (the exposed test in
  §7 needs a test-code fix; that is a follow-up, out of scope here).
- No shared state between tests, no fixture-scope widening, no
  assertion weakened.
- No `/home` TMPDIR (SQLite commits 82× slower there; ~9h suite —
  measured, see `AGENTS.md`). No `/tmp` (512M).
- No deletion-on-pass-only logic: unconditional deletion is
  deterministic and has no hook interplay; failed-test debugging uses
  the `PLANAGENT_KEEP_TEST_TMP=1` escape hatch plus reproducible
  single-test runs.

## 3. Integration points

- Scope: `tests/conftest.py` applies to the whole `tests/` tree,
  including `tests/unit/` (its own conftest has settings/seed/mock
  fixtures only, no DB fixtures, no conflict).
- Ordering: `remove_test_tmp_dir` is defined before
  `release_cached_database_and_settings_between_tests`, so its
  teardown runs after the database-cache reset. Either order would be
  safe on Linux (unlink of an open file is fine; `NullPool` holds no
  open connection between tests), but teardown-last is the cleanest
  guarantee.
- The fixture forces `tmp_path` creation for every test (including
  tests that never use it): one empty dir created and deleted per
  test, negligible cost.
- `PLANAGENT_KEEP_TEST_TMP=1` is the only new knob, debug-only,
  default off.

## 4. Verification

All logs under `~/workspace/verification/tmpfs-diet-2026-11-18/`.
All runs: `env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest`,
`planagent.__file__` verified inside `~/workspace/mingjian-tmpfs`
before every run; full/chunk runs under
`~/workspace/scripts/full-run-lock.sh --wait 3600` with fresh TMPDIR
per run, removed after.

### Before/after on the same 124 tests (Step 1 subsets, §2)

Same 8 files, same order: **124 passed** both before and after the
change. Leftovers: **126MB before → 96 bytes after** (2 tiny files in
the `mkdtemp` residue, §2). Zero `.db` files remain after the fix.

### Escape hatch

One DB-creating test
(`test_mece_api::test_validate_endpoint_returns_verdict_in_payload`):
with `PLANAGENT_KEEP_TEST_TMP=1`, the `.db` survives (1 file,
1,675,404 bytes); without it, 0 files / 54 bytes. Both runs pass.

### Leak reproduction (pair run, §7 mechanism)

`tests/test_narratives_api.py` (15 tests, each sets its own sqlite
URL) + `test_new_features.py::test_decision_options_and_hypotheses_flow`
in one invocation: before the settings reset, the single test failed
with `sqlite3.OperationalError: unable to open database file` (stale
URL into a deleted tmp dir); after the settings reset, it fails with
Postgres `Connection refused` — the honest default-URL failure,
identical to its alone-context failure. Leak closed.

### Partitioned 4-chunk gate at tip `0899b8a` (green except §7)

Collect-only: **2004 tests**, 134 files. Chunks are contiguous in
collection order (file lists `chunk-b87a58c-{0..3}.txt`, unchanged —
no test files moved).

| Chunk | Result | Time | Leftovers | Log |
|---|---|---|---|---|
| 0 (33 files) | 1 failed, 477 passed | 649.37s | 51 bytes | `chunk-0899b8a-0.log` |
| 1 (33 files) | 462 passed | 174.43s | 51 bytes | `chunk-0899b8a-1.log` |
| 2 (33 files) | 483 passed | 37.17s | 91 bytes | `chunk-0899b8a-2.log` |
| 3 (35 files) | 581 passed | 11.48s | 51 bytes | `chunk-0899b8a-3.log` |

Union: 2003 passed + 1 failed = 2004 = collect-only count. The 1
failure is the §7 test with the Postgres-refused signature (6×
`Connection refused`, 0 `disk I/O error`, 0 `unable to open database
file`, 0 `AssertionError` in the chunk-0 log). Chunks 1–3: zero
failures, zero environmental signatures.

An intermediate gate at `b87a58c` (tmp cleanup without the settings
reset) showed the same counts with the §7 test failing as CANTOPEN
(logs `chunk-b87a58c-{0..3}.log`); the settings reset changed only
that test's failure signature, proving no other test depended on the
leak.

### Single-process full run at tip `0899b8a` — the proof

Log: `full-run-0899b8a.log`, peak record:
`full-run-0899b8a-peak.txt`. Started with **794M free** (full ≥750M
gate met), preflight 3/3 SQLite probes passed, run under the flock
helper, peak sampled every 10s (`du` of the run's own TMPDIR + `df`):

- **1 failed, 2003 passed in 605.09s (0:10:05)**
- **Peak TMPDIR usage: 1,958,077 bytes (~1.87MB)**; peak `df` used:
  1908KB (sole writer — the numbers agree)
- Leftovers after the run: **89 bytes**
- The 1 failure is the §7 test (Postgres-refused, 6×; 0 `disk I/O
  error`, 0 `database or disk is full`, 0 CANTOPEN, 0 assertions)

Before/after peak tmpfs usage, measured:

| | Peak tmpfs usage | Outcome |
|---|---|---|
| Before (`939d7eb`, 2004 tests) | 794M (100% full) | 27 disk-full kills |
| After (`0899b8a`, 2004 tests) | **1.96MB** | 0 disk-full failures |

Interrupted attempts (environmental, not results): one chunk driver
killed by a VM reboot; one gate-closed chunk attempt (214 `disk I/O
error` failures + 3× pytest exit 120 at startup, all environmental,
zero assertions — re-run after the gate opened); one single-process
attempt killed by a second VM reboot at ~10% (all dots to that
point); a 90-minute space wait that never reached 750M free (sibling
tracks held ~88M) before the reboot cleared `/dev/shm` — the
completed run therefore met the full gate with no deviation.

### Lint

`ruff check` + `ruff format --check` clean on `tests/conftest.py`.

## 5. How to run / verify

```bash
# Single-process full suite (now fits; keep the lock + gate protocol)
TMPDIR=/dev/shm/pytest-tmp-<track> \
  ~/workspace/scripts/full-run-lock.sh --wait 3600 -- \
  env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest -q

# Keep one failing test's tmp dir for debugging
PLANAGENT_KEEP_TEST_TMP=1 TMPDIR=/dev/shm/pytest-tmp-<track> \
  env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest tests/<file>.py::test_<name> -q

# Lint the touched file
.venv/bin/python -m ruff check tests/conftest.py
.venv/bin/python -m ruff format --check tests/conftest.py
```

## 6. Known limits

- The §7 test fails in every context (alone, chunk, full) until it
  gets its own DB fixture. The suite is therefore 2003/2004, not
  2004/2004 — honestly, and for a reason unrelated to tmpfs.
- Peak usage was sampled every 10s; a sub-10s spike above 1.96MB
  cannot be excluded, but the bound is structural: at most one live
  test DB (~2MB max observed) plus transient journal files.
- The `mkdtemp` residue (§2) survives: 6 empty dirs + 2 tiny files
  per full run, <100 bytes. It grows only if more tests adopt the
  no-teardown `mkdtemp` pattern.
- `PLANAGENT_KEEP_TEST_TMP=1` disables the diet for that run; a full
  run with it set will overflow `/dev/shm` exactly as before. It is
  for single-test debugging only.
- The write-denial gate is unchanged and external: a run started in a
  closed window still fails environmentally (exit 120 at startup /
  `disk I/O error` mid-run). The preflight probes + chunked re-run
  mitigations in `AGENTS.md` still apply.
- No automated guard test asserts the cleanup behavior; the proof is
  the measured runs in §4. A future test that writes large artifacts
  outside `tmp_path` (e.g. under `TMPDIR` directly) would not be
  cleaned by this fixture.

## 7. Finding: one pre-existing order-dependent test (reported, not papered over)

`tests/test_new_features.py::test_decision_options_and_hypotheses_flow`
is the only test in the suite that uses the app database without
setting its own `PLANAGENT_DATABASE_URL`. Its `client` fixture builds
the real app with default settings (Postgres URL, no server on this
VM). It passed in full-suite/chunk order only because of a leak:

1. An earlier test sets `PLANAGENT_DATABASE_URL` (monkeypatch) to a
   sqlite URL under its own `tmp_path` and calls
   `reset_settings_cache()`; `get_settings()` (`lru_cache`) caches
   that URL.
2. The test ends; monkeypatch reverts the env var; the old autouse
   fixture reset the database cache but NOT the settings cache, so
   the stale URL survived.
3. This test's `get_database()` rebuilt its engine from the stale
   cached URL — pointing into the earlier test's tmp dir, which
   pytest never deleted, so the test passed.

Evidence: fails alone and file-alone (Postgres refused); fails in a
pair run after `test_narratives_api.py` with CANTOPEN (leak into a
deleted dir) before the settings reset, and with Postgres refused
after it; passed at baseline in chunk order (parent's `4669016`
gate); the settings reset changed no other test's outcome across all
2004 tests, proving exactly one test depended on the leak.

Recommended follow-up (test-code work, needs authorization, out of
scope here): give the test its own tmp-DB setup like every other API
test (monkeypatch `PLANAGENT_DATABASE_URL` to a sqlite URL under
`tmp_path` + `reset_settings_cache()`), or move it behind the same
fixture pattern its neighbors use. Until then it fails honestly in
every context.

## 8. Deferred (out of scope, recorded deliberately)

- The §7 test's fixture fix (test-code; see §7).
- `mkdtemp` cleanup for `TestExportService` (test-code; <100 bytes).
- Whether the chunked gate stays the default protocol: capacity no
  longer forces it, but the chunked gate remains a valid fallback for
  gate-closed windows. Decision for the parent.
- No guard test for the cleanup behavior was added (would be new
  test code asserting infra behavior; the measured runs are the
  proof for this track).

## 9. Commits on this branch

- `0899b8a` — Remove each test's tmp_path tree at teardown; reset
  settings cache (tmpfs diet). Single implementation commit
  (amended once to include the settings-cache reset, which the tmp
  cleanup exposed; all proof in §4 ran at this tip).
- (this commit) — Tmpfs-diet report.

`BACKLOG.md` untouched. Not merged, not pushed.

## 10. What was NOT verified

- A green 2004/2004 single-process run: the §7 test fails until its
  follow-up lands. The capacity claim (fits in 794M) is proven; the
  all-green claim is not.
- Statistical stability of the single-process result: one completed
  attempt (plus one reboot-killed attempt that was passing at 10%).
  No repeated full runs were made to bound gate-flicker flakiness.
- The change against Postgres (no Postgres on this VM; the change is
  SQLite-tmp-path-only by construction, but unproven live).
- Real-browser rendering: none involved (no UI change).
- Live-LLM behavior: none involved (no LLM touchpoint added).
- Frontend tests: untouched by this track (backend pytest only).
- Whether any future test will write large artifacts outside
  `tmp_path` (§6): no guard exists.

## 11. §7 follow-up: the order-dependent test is fixed; full run is all green (2026-11-18)

Branch `strategy-engine/tmpfs-diet-followup`, worktree
`~/workspace/mingjian-diet-followup`. Combined tip: merge
`6cd7556` (diet tip `79381d8` + sprint20 tip `bb2789f`, clean
merge, no conflicts — the diet branch touched only
`tests/conftest.py` + this report) plus fix commit `ec3effe`.
This run also serves as the full-suite gate proof for everything
merged since `4669016`. `BACKLOG.md` untouched. Not merged, not
pushed — the parent verifies and merges.

### Resolution

`tests/test_new_features.py::test_decision_options_and_hypotheses_flow`
now passes in every context. The fix is test-code only, confined
to the file's shared async `client` fixture (21 insertions, 2
deletions, one file): the fixture takes `monkeypatch` + `tmp_path`,
sets its own `PLANAGENT_DATABASE_URL` (sqlite URL under its own
`tmp_path`) and `PLANAGENT_EVENT_BUS_BACKEND=memory`, calls
`reset_settings_cache()` + `reset_database_cache()`, and only then
imports the app and enters the client context (whose lifespan
calls `get_database()` at startup). No product code changed, no
assertion weakened, no other test touched.

One correction to §7's mechanism, found while fixing: the leak
carried TWO settings, not one. The URL-only fix still failed —
with Redis connection refused (`::1`/`127.0.0.1:6379`), because
the default event-bus backend is redis and no server runs here.
The leaked `lru_cached` settings object had carried the memory
bus backend from a neighbor's `setup_app` alongside the sqlite
URL. Adding the memory-bus line (the same line every other API
test's `setup_app` sets) made the test green. The §8 first
deferred bullet is resolved by this section; the other §8 items
stand.

The shared fixture also removes the same latent order-dependence
from `test_calibration_compute`, the only other test using it:
it still passes (403 feature-gate assertions unchanged).

### Proof

- Red first: at the combined tip before the fix, the test alone
  failed with the exact §7 signature (Postgres connection
  refused, `127.0.0.1:5432`).
- Fixed test alone: 1 passed. File alone: 12 passed. Pair run
  after `tests/test_narratives_api.py` (the §7 leak scenario):
  27 passed.
- Collect-only at the combined tip: **2069 tests**.
- Full single-process run under the standing `AGENTS.md`
  protocol: fresh TMPDIR `/dev/shm/pytest-tmp-diet-followup`,
  space gate 794M free (≥750M required), preflight SQLite
  probes 3/3, serialized via `full-run-lock.sh --wait 3600`,
  TMPDIR removed after the run. Result: **2069 passed in
  617.74s, 0 failed** — collect count equals passed count.
  Peak TMPDIR usage 3,010,748 bytes (~2.87MB, 10s sampling,
  63 samples); minimum `/dev/shm` available during the run
  809,620KB — the tmpfs never came close to full. No
  environmental failure occurred; no re-run was needed.
- Ruff on the touched file: identical to base (1 pre-existing
  I001, verified by stash comparison; the fix adds no new
  finding). `ruff format --check`: clean. Sprint 0 smoke: not
  required — no non-test file changed.

Logs (new files; the diet track's logs untouched):

- `~/workspace/verification/tmpfs-diet-2026-11-18/full-run-followup-ec3effe.log`
  (2069 passed; zero FAILED/ERROR lines)
- `~/workspace/verification/tmpfs-diet-2026-11-18/full-run-followup-ec3effe-peak.txt`
  (10s TMPDIR/df samples; peak 3,010,748 bytes)

### What remains unverified

- Statistical stability: one completed all-green full run. No
  repeated full runs were made to bound gate-flicker flakiness
  (§10's caveat stands, now for the 2069 count).
- The fix against Postgres (no Postgres on this VM; the change
  is test-fixture-only, sqlite + memory bus).
- Frontend tests: untouched by this track (backend pytest only).
- Whether the chunked gate stays the default protocol (§8):
  capacity no longer forces chunking, but the decision is still
  the parent's. The chunked gate remains a valid fallback for
  gate-closed windows.
- The `mkdtemp` cleanup for `TestExportService` (§8): still
  deferred (<100 bytes, out of scope).

This closes the §10 first bullet: the all-green single-process
claim is now proven at the combined tip.

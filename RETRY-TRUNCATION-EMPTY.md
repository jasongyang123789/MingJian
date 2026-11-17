# Track D — Retry on truncation + empty response

Branch: `strategy-engine/retry-truncation-empty`, from `ccc3490`
(Sprint 20 tip + fix batch 2 merge). Date: 2026-11-17. No migration,
no frontend change, no template change, no version bump. Not a
numbered sprint: the Sprint 18 timeout-only retry policy is extended
to two more transient failure kinds, per Ho's ruling 9 (retry on
truncation approved; the 2026-11-17 live smoke showed the empty
response needs the same treatment).

## 1. The gap (verified from the live run, not assumed)

The 2026-11-17 live seminar re-run lost model-b in the agent-chair
seminar at `mckinsey.verify_assumptions`: the upstream returned an
empty response (recorder seq 67: empty content, no finish_reason, no
usage). The audit recorded it as `error_kind: "contract"` ("no usable
JSON response") and the retry policy — timeout-only since Sprint 18
— did not retry it, so model-b's whole round failed and the seminar
synthesized partial. Two distinct causes share that one outcome:

1. **Truncation** (`finish_reason="length"`): classified distinctly
   since fix batch 2, but never retried. Sampling variance means a
   re-call may produce an output that fits the cap.
2. **Empty responses**: not even classified distinctly — the port
   collapsed every unusable response into `payload=None` and the
   runners reported the generic contract message. An empty response
   is a transient upstream gap, not a property of the prompt, and
   must retry; malformed content (non-empty, unparseable) must not.

## 2. What changed

### 2.1 The port reports emptiness affirmatively (`port.py`)

`ParameterizedSkillPort` now inspects the raw response through a new
`_sdk_content` reader and sets the new `empty_response` flag on
`SkillLLMResponse` when — and only when — it observes no choices, no
message, or empty/whitespace-only content. The flag is affirmative:
a bare `payload=None` response with no signal stays a plain contract
failure, so an unknown cause is never misreported as empty. Three
collapses are deliberately unchanged:

- non-empty unparseable content → `payload=None`, flag False
  (malformed, never retried);
- a non-dict JSON value → `payload=None`, flag False;
- an SDK call failure (non-timeout) → `payload=None`, flag False,
  model None: a failed call is not an observed empty response, and
  retrying auth/5xx failures would silently extend the policy past
  "never unavailable".

The old `content or "{}"` fallback is gone: empty-string content
previously parsed to `{}` and failed later as a validation error; it
now takes the honest path (flagged empty → retried → classified
`empty_response` on exhaustion).

### 2.2 The response carries the signal (`orchestration.py`)

`SkillLLMResponse` gains `empty_response: bool = False`, defaulted
last, so every existing construction keeps working and
`dataclasses.replace` (the wrapper's `attempts` stamping) preserves
it. `run_stage` raises the new `SkillEmptyResponseError` when the
flag is set (length checked first, so a response carrying both
signals is truncation).

### 2.3 The taxonomy gains the eighth kind (`errors.py`, `engine.py`)

- `ErrorKind.EMPTY_RESPONSE = "empty_response"`.
- `SkillEmptyResponseError` (`skills/contracts.py`) subclasses
  `SkillContractError` deliberately, like `SkillTruncatedError`: the
  skills 502 mapping and the seminar failure isolation keep catching
  it, while the message names the empty response.
- `classify_error` checks `SkillTruncatedError`, then
  `SkillEmptyResponseError`, then `SkillContractError` — the ordering
  is the whole point, pinned by test.
- `run_seminar_stage` mirrors `run_stage` (seminar family/version).
- `is_retryable_error` is True for timeouts, truncations, and empty
  responses; contract (malformed), unavailable, budget exhaustion,
  and cancellation stay non-retryable.

### 2.4 The retry loop retries returned unusable responses (`instrumentation.py`)

`InstrumentedPort` is the single choke point for every seminar stage
call, but truncation/emptiness surface as RETURNED responses with
`payload=None` — the old loop only retried RAISED exceptions, so it
never saw them. The loop now also retries a returned response that
carries a retryable signal (`finish_reason="length"` or
`empty_response`), under the identical treatment: max 2 retries,
fixed backoff, budget check before every attempt (the loop-top
check covers retries unchanged), and per-attempt audit. On
exhaustion the last unusable response is returned unchanged, so the
stage runner raises the proper error and the round classifies
`truncated` / `empty_response` exactly as before — the wrapper
never invents the failure, it only buys bounded re-calls.

Audit truthfulness, three fixes in the same loop:

- The `stage_call_finished` outcome names the attempt result:
  `"ok"` only when a payload arrived; `"truncated"`,
  `"empty_response"`, or `"contract"` when the returned response
  carried no payload. (Previously every returned response recorded
  `"ok"`, including unusable ones.)
- The finished detail carries `empty_response` alongside
  `finish_reason`, so the audit explains the outcome.
- The `retry` event's `error_kind` is the true kind. It was
  hardcoded to `"timeout"`; a raised truncation/empty error (or a
  retried unusable response) now records its own kind, and the
  `error_message` names the retry reason. `_outcome_of` maps raised
  truncation/empty errors to their kinds instead of collapsing
  every retryable exception to `"timeout"`.

The chair cluster/synthesize stages share this choke point, so they
retry identically with no chair-specific code.

### 2.5 Fixtures (`skill_fixtures.py`)

`ScriptedSkillPort` gains `empty_response_script`, a parallel queue
in the exact pattern of `finish_reason_script` (fix batch 2), so
tests script the empty signal per template id in call order.

## 3. Design decisions

1. **Retry at the wrapper, not the runner.** The runners raise
   after the port returns; retrying there would duplicate the
   budget/audit machinery and split attempt accounting. The wrapper
   already owns retries, budgets, and audit — response-level retry
   keeps one choke point and covers waves, finalize, and chair
   stages uniformly.
2. **The empty signal must be affirmative.** Inferring emptiness
   from absent metadata (no finish reason, no usage) would mislabel
   malformed responses from ports that report neither. Only the
   port that inspected the raw content may set the flag.
3. **Same cap on retry, no cap raise.** Fix batch 2 noted
   retry-with-raised-cap as a follow-up option; this track retries
   the same call under the same 8000 cap, per the brief. Sampling
   variance is the mechanism; the bound (2 retries, budget-checked)
   caps the cost of a persistently truncating prompt, and exhaustion
   still says `truncated` plainly.
4. **Exhaustion returns, never raises, at the wrapper.** The
   wrapper's contract is to return the port's response; the runners
   own error raising and classification. Returning the last
   unusable response keeps every downstream handler, message, and
   kind exactly as they were for the non-retried case.
5. **Malformed content is the control group.** Every new retry path
   has a malformed twin asserting zero retries and kind `contract`,
   so the empty/malformed distinction is pinned, not just described.
6. **No new taxonomy kind for "retried".** Retries are audit events,
   not failure kinds (S18 decision 5 stands); the kinds describe
   the terminal failure only.

## 4. Files changed

Source: `services/seminar/{errors,engine,port,instrumentation,models,service}.py`
(models/service: comment-only policy wording),
`services/skills/{contracts,orchestration}.py`.
Fixtures: `tests/skill_fixtures.py` (parallel empty-signal queue).
Tests: new `tests/test_seminar_retry_truncation_empty.py` (7
service-level tests); extended `tests/unit/test_seminar_{errors,
instrumentation,port,engine}.py`,
`tests/unit/test_skill_orchestration.py`. No migration, no
frontend, no template, no BACKLOG.md change (per the brief).

Updated pinned tests (old behavior, changed deliberately): the
taxonomy exact-set test (7 → 8 kinds) and the retryability test
(`test_only_timeouts_are_retryable` → the timeout/truncated/empty
set). No other existing test needed changes.

## 5. Deliberately NOT changed

- **Retry budget/shape**: max 2 retries, fixed backoff, per-seminar
  `max_retries` / `retry_backoff_seconds` config untouched; the
  budget check-before-every-attempt semantics untouched (verified,
  not assumed — see §6).
- **Malformed JSON**: stays a plain contract error, never retried.
- **SDK call failures**: still collapse to `payload=None` with no
  signal (a failed call is not an observed empty response).
- **`OpenAIServiceSkillPort`** (deliberation path): does not set the
  empty flag — `generate_json_for_target` collapses failures without
  distinguishing emptiness, and the deliberation path has no retry
  wrapper to consume the signal. Its behavior is unchanged.
- **Narrative polish** (`polish_markdown`): out of scope (not a
  seminar stage, no taxonomy consumer); it ignores the new flag and
  keeps its existing truncation/contract behavior.
- **Template/contract versions**: parameter-only discipline holds —
  no prompt wording, no contract field changed.
- **Frontend**: `error_kind` renders as a free string, so the new
  `"empty_response"` kind displays without any frontend change (same
  argument as fix batch 2 for `"truncated"`); no consumed type
  changed.
- **No merge, no push**: for the parent agent to review, merge, and
  push.

## 6. Limits (stated honestly)

- **No live-LLM verification.** All evidence is fixture-driven
  (fake SDK clients, scripted ports). The proof is a live run in
  which an upstream empty response / truncation recovers on retry
  instead of failing the round.
- **Same-cap retry can re-truncate.** A prompt whose legitimate
  output exceeds 8000 tokens will truncate 3 times and fail as
  `truncated` — correctly, but at 3× the call cost. The bound is
  the budget; a raised-cap retry remains a future option.
- **Classification requires the port to observe the response.**
  Ports that do not set the flag (deliberation path, older fakes)
  still yield the generic contract error for empty responses; the
  bare-payload-None case is deliberately kept as `contract`.
- **A truncation that parses as valid JSON** (cut exactly at a
  structural boundary) still returns a payload and is not retried
  — the same fix-batch-2 limit, unchanged: the retry branch fires
  only on `payload=None` + signal.
- **Empty-content detection is string-based.** Non-string SDK
  content (content-part lists) renders via `str()` and reaches the
  JSON parser; exotic shapes classify as malformed, not empty.
- **Docker**: no container runtime on this VM; no full-stack claim
  is made.
- **No clean single full-suite run was achieved.** The gate was
  satisfied by partition (chunks 01–04, see §7) plus forensic
  analysis of two full runs, not by one green `pytest` invocation.
  Cross-chunk test-order dependence was not verified, and chunks
  00/05 never ran (see §7.4). The two template-ordering failures
  in chunk 02 are unresolved pending a standalone re-check (§7.3).

## 7. Evidence (written last; every number from a named run)

### 7.1 Test-count arithmetic

- Base at `ccc3490`: 1840 backend tests (per `FIX-BATCH-2.md`).
- This track: **+30 test functions added, 1 removed/renamed**,
  net **+29 → 1869**. Verified two ways: `git diff` shows +23
  `def test_` lines in modified test files and −1 (the renamed
  retryability test), plus 7 in the new file (23 + 7 = 30); the
  full-suite collection in run 4 (§7.4) totalled 218 + 1651 =
  **1869**, confirming the count independently.
- Added, by file: 11 in `test_seminar_instrumentation.py`
  (response-retry paths), 8 in `test_seminar_port.py` (empty
  signalling), 1 in `test_seminar_engine.py`, 1 in
  `test_skill_orchestration.py`, 2 in `test_seminar_errors.py`
  (the renamed retryability test + the empty-error naming test),
  7 in the new `test_seminar_retry_truncation_empty.py`.
  Removed: `test_only_timeouts_are_retryable`, replaced by
  `test_retryable_kinds_are_timeout_truncated_and_empty`.

### 7.2 The brief's required tests, each named

All seven service-level tests live in
`tests/test_seminar_retry_truncation_empty.py` and passed in
chunk 01 (§7.3) and in the ring run (§7.5):

- empty→success:
  `test_empty_response_then_success_completes_the_round`
- truncated→success:
  `test_truncated_response_then_success_completes_the_round`
- empty×3→recorded failure:
  `test_empty_response_exhaustion_fails_the_round_as_empty_response`
  (round fails with kind `empty_response`)
- truncated×3→recorded failure:
  `test_truncated_response_exhaustion_fails_the_round_as_truncated`
- malformed JSON→no retry:
  `test_malformed_response_is_not_retried` (kind `contract`,
  one attempt)
- budget-exhausted during retries:
  `test_budget_exhausted_blocks_a_scheduled_response_retry`
  (100-token budget tripped by model-a's own first attempt; only
  model-a's facts asserted — wave interleaving makes model-b's
  counts non-deterministic)
- chair stages retry identically:
  `test_chair_cluster_stage_retries_an_empty_response`
- timeout behavior unchanged: the pre-existing hardening tests
  `test_timeout_then_success_completes_the_round_with_attempts_recorded`
  and `test_timeout_retry_exhaustion_fails_the_round_as_timeout`
  (both in chunk 01, green, unmodified).

Pins that still pass unchanged: `test_empty_payload_is_not_retried_by_the_wrapper` (bare `None`, no signals) and `test_run_seminar_stage_empty_response_stays_a_plain_contract_error`.

### 7.3 Chunked full-suite verification (the gate, partitioned)

The 126 test files were split alphabetically into 6 chunks of 21
files (`~/workspace/verification/chunks-retry/chunk-00` … `chunk-05`).
Each chunk ran only after a preflight gate passed (tempfile creation
+ a SQLite CREATE/INSERT/COMMIT on the chunk TMPDIR — the gate
script is `~/workspace/verification/chunks-retry/preflight.py`),
and only while the full-suite lock was free. Results:

- Chunk 01: **281 passed, 0 failed** in 151.58s
  (`pass2-chunk-01-attempt1.log`). Contains the 7 new
  service-level tests, the hardening tests, agent-chair,
  service, and synthesis tests.
- Chunk 02: **311 passed, 2 failed** in 145.10s
  (`chunk-02-attempt1.log`). The 2 failures are both in
  `tests/test_variable_templates_api.py` —
  `test_template_crud_lifecycle` and
  `test_template_create_refuses_invalid_variables_and_unknown_domain`
  — asserting `ids[:3] == ["builtin:automotive",
  "builtin:corporate", "builtin:military"]` but observing a
  created template's UUID at index 2. This file and its code
  path (variable templates) are untouched by this track; the
  failure is a listing-order artifact of the chunk context
  (or a flake) and is UNRESOLVED pending the standalone
  re-check in §8. No other chunk-02 test failed.
- Chunk 03: **254 passed, 0 failed** in 59.76s
  (`chunk-03-attempt1.log`).
- Chunk 04: **329 passed, 0 failed** in 36.50s
  (`chunk-04-attempt1.log`). Contains unit
  `test_seminar_{engine,errors,instrumentation}.py`.
- Chunks 00 and 05: **never ran** — every attempt expired in
  the preflight gate (fault window) or the lock wait. Chunk 05
  holds unit `test_seminar_port.py` and
  `test_skill_orchestration.py`; both files were green in the
  ring run (§7.5) and in targeted runs. Chunk 00 holds no
  track-touched file.
- Chunk totals: 1175 passed + 2 failed = 1177 tests in chunks
  01–04; chunks 00+05 hold the remaining 692 tests by the
  1869 collection total.

### 7.4 Full-suite attempts (all environmentally defeated)

Four attempts under the lock protocol
(`TMPDIR=/dev/shm/pytest-tmp-retry`, unbuffered, lock released
unconditionally):

1. Exit 120 after ~28s, empty log — died during startup.
2. Exit 1 after ~1.2s, empty log — died during startup.
3. **342 failed, 1527 passed** in 644.53s. Failure-signature
   analysis: 332 `sqlite3.OperationalError: disk I/O error`
   + 19 `PermissionError: EPERM`, spanning 20+ files untouched
   by this track. (Log overwritten by run 4; counts from the
   recorded run output.)
4. **218 failed, 1651 passed** in 465.46s
   (`~/workspace/verification/pytest-full-retry.log`).
   Forensic analysis, section by section over all 207
   traceback sections in the failures list: **207/207 contain
   `disk I/O error`, `Operation not permitted`, or `no usable
   temporary directory`** — zero assertion/logic failures.
   The only two `assert 1 == 0` lines sit inside tracebacks
   rooted at `sqlite3.OperationalError: disk I/O error`.
   None of the pure-logic unit files of this track
   (`test_seminar_{errors,instrumentation,port,engine}`,
   `test_skill_orchestration`) appears in the FAILED list;
   the 7 new service-level tests appear only with the disk
   I/O signature (they passed in chunk 01's healthy window).

Root cause of the defeats: a VM-wide intermittent storage fault
(two independently toggling halves — `EPERM` on file creation
and SQLite `disk I/O error` on commit — confirmed on tmpfs AND
disk-backed paths, and also observed by sibling tracks and the
Track F live run the same day). No test-configuration workaround
was used: bypassing SQLite durability would have faked the
evidence.

### 7.5 Ring run, smoke, lint, types

- **Ring run (healthy window, before the fault worsened): 326
  passed, 0 failed in 156.61s** across 19 files: seminar
  service/synthesis/agent-chair/S18 API/hardening/retry +
  unit errors/instrumentation/port/engine/audit/near-duplicates
  + skill orchestration/prompt-shapes/templates + seminar
  templates + narratives composer + openai generate_json +
  llm output caps. Includes all 30 new/changed tests.
- **Targeted subsets:** 123 passed across the new + affected
  files (after fixing the two deliberately-updated pins and
  rewriting the single-model budget test); service file 7/7.
- **E2E smoke** (`docs/sprint0/smoke_e2e.py`): **PASS**;
  `smoke-evidence.json` reverted afterward per precedent.
- **Ruff**: clean on all touched files except 3 pre-existing
  findings in `orchestration.py` (FURB192 ×2, RUF022), verified
  present at base via `git stash` comparison (line-shifted
  only); 1 own I001 fixed.
- **Mypy**: clean — no issues in the 6 touched source files.

## 8. Re-run recipe (for the parent, when the environment recovers)

```sh
cd ~/workspace/mingjian-retry   # branch strategy-engine/retry-truncation-empty
# 1. Standalone check for the 2 chunk-02 template failures:
TMPDIR=/dev/shm/pytest-tmp-retry env -u NO_PROXY -u no_proxy \
  .venv/bin/python -m pytest -q tests/test_variable_templates_api.py
# 2. Remaining chunks (file lists preserved):
TMPDIR=/dev/shm/pytest-tmp-retry env -u NO_PROXY -u no_proxy \
  .venv/bin/python -m pytest -q $(cat ~/workspace/verification/chunks-retry/chunk-00)
TMPDIR=/dev/shm/pytest-tmp-retry env -u NO_PROXY -u no_proxy \
  .venv/bin/python -m pytest -q $(cat ~/workspace/verification/chunks-retry/chunk-05)
# 3. Single full-suite run (lock protocol):
#    mkdir ~/workspace/.pytest-full-run.lock  # atomic; wait if held
#    TMPDIR=/dev/shm/pytest-tmp-retry env -u NO_PROXY -u no_proxy \
#      .venv/bin/python -u -m pytest -q
#    rmdir ~/workspace/.pytest-full-run.lock  # unconditional release
# Gate first: TMPDIR=/dev/shm/pytest-tmp-retry .venv/bin/python \
#   ~/workspace/verification/chunks-retry/preflight.py  (exit 0 = healthy)
```

Expected on recovery: 1869 passed, 0 failed (single run), or
chunks 00+05 green + the template file green standalone.

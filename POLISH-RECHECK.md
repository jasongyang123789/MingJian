# Polish re-check — verify LLM-polished narrative text before storing

Branch: `strategy-engine/polish-recheck`, from
`strategy-engine/sprint20-cockpit-seminar` @ `ccc3490`. Nothing
merged, nothing pushed. Closes the Sprint 13 gap (SPRINT13.md §6:
"nothing in the polish path re-validates the polished text against
the artifact"; §8 deferred item "Polished-text verification").

The polish prompt already forbids changing numbers and provenance
marks, but a live LLM can still paraphrase a number or drop a mark.
The polish path now re-validates the polished text against the
deterministic markdown after the polish pass returns and BEFORE any
row is written. A failed re-check refuses storage with a detailed
error, the same house gate rule as every other narrative refusal.

## 1. What was built

### Re-check module (`services/narratives/recheck.py`, new, pure)

`check_polish(source_markdown, polished_markdown) ->
PolishRecheck` is a pure function: no I/O, no clock, no
randomness. It compares the polished text against the
deterministic markdown that was sent to the polish pass (the exact
input), not against the structured body: the markdown already
renders every figure in the body (distributions, drivers, signals,
counts), so text-vs-text is the complete comparison.

Two checks, both multiset comparisons:

- **Numbers.** `extract_numbers` pulls every number out of each
  text (rules in §2); the polished text must contain exactly the
  same numbers with the same multiplicities as the source. A
  dropped number, an invented number, or an altered number (which
  surfaces as one missing plus one extra) all fail. Key figures
  (P10/P50/P90, loss probability) are a subset of the checked
  numbers, so they are preserved exactly by the same rule.
- **Provenance.** `extract_provenance_counts` counts the three
  marks `[computed]` / `[deliberated]` / `[template]`; counts per
  kind must be equal. A dropped, added, or kind-changed mark
  fails. The footer's three marks count like any other occurrence.

`PolishRecheck` carries `passed`, the missing/extra numbers
(canonical strings, sorted by value, one entry per missing/extra
occurrence), and the missing/extra mark counts per kind.
`describe()` renders a stable, detailed failure message naming
every difference, e.g. `numbers missing from polished text: 10;
numbers invented in polished text: 11; provenance marks missing:
[computed] x1`.

### Service gate (`services/narratives/service.py`)

`NarrativeService.polish` calls `check_polish(body.markdown,
output.polished_markdown)` after `polish_markdown` returns and
before `session.add(row)`. On failure it raises `NarrativeError`
with the new code `narrative_polish_recheck_failed` and the
re-check's detail message. No row is written, and the narrative
row is untouched (as with the 503/502 polish failures). The gate
sits in the service, not in `polish_markdown`, because storage is
the service's responsibility and the hook's contract stays "run
one polish pass".

### Route mapping (`api/routes/narratives.py`)

`narrative_polish_recheck_failed` maps to **502** in
`_POLISH_STATUS_CODES`: the upstream (LLM) produced content that
fails verification against the artifact — the same class as a
contract failure (`narrative_polish_contract_failed` → 502), not
a client error. The response detail is the usual `{"code",
"message"}` shape, with the message naming the differences.

### Exports (`services/narratives/__init__.py`)

`check_polish` and `PolishRecheck` are exported alongside the
existing composer/render API.

### What was deliberately NOT changed

- No migration: no new table or column. The re-check is a
  validation pass, not stored state.
- No change to `polish.py`, the polish template, or the polish
  prompt: the gate verifies the output; it does not change what is
  asked for.
- No frontend change: the cockpit already surfaces polish errors
  generically (code + message, deterministic markdown stays
  visible), so a 502 re-check failure displays like the existing
  502 contract failure. No new client handling was needed.
- BACKLOG.md untouched, per the track brief.

## 2. Design decisions (matching rules)

All rules are documented in the `recheck.py` module docstring and
asserted by named tests (§4). The guiding principle: formatting
differences pass, value differences fail, and every rule applies
identically to both sides so a polish that preserves the form
always passes.

1. **Code spans and UUIDs contribute no numbers.** Backtick
   spans are stripped before extraction: trace ids (run,
   ensemble, deliberation, fit, loop ids) live in code spans in
   the deterministic rendering. UUIDs are stripped wherever they
   appear, so a polish that drops the backticks around an id
   still does not invent numbers from it.
2. **Boundary rules keep identifiers out.** A number token is an
   optional sign, digits with optional thousands-group commas, an
   optional decimal fraction, and an optional exponent. The
   character before the token (or its sign) must not be a letter,
   digit, `_`, `.`, or `-`; the character after must not be a
   letter, digit, `_`, or `.` followed by a digit. So `P50`,
   `v0`, `sprint13-v1`, `delib-strategy-1`, and fragments of
   `1.2.3` never yield numbers, while `P50 10`, `n=20`, and `-3`
   do. A digit run immediately after a hyphen counts as part of
   an identifier, so hyphen ranges (`10-20`) yield only their
   first endpoint; a polish that preserves the form still passes.
3. **Percent equals decimal.** A number immediately followed by
   `%` (optional spaces/tabs between) is divided by 100: `20%`
   is the same value as `0.2`, and `20%` differs from `20`. The
   renderer never emits `%`; this rule exists for the polish's
   natural rewording of probabilities.
4. **Exact decimal comparison, no epsilon.** Values compare as
   `Decimal`: `1,000` = `1000`, `10.0` = `10`, `0.10` = `0.1`,
   `1e3` = `1000`, but `0.333333` ≠ `0.333334` and `10` ≠ `11`.
   No rounding is applied anywhere.
5. **Multiset equality, not set equality.** Duplicated numbers
   must stay duplicated: a source with two `10`s and a polish
   with three fails. Same for marks.
6. **Marks are exact, case-sensitive tokens.** Only
   `[computed]`, `[deliberated]`, `[template]` count. `[Computed]`
   does not count as `[computed]`; other bracketed tokens
   (`[see note]`) are ignored entirely — they are not marks.
7. **Attachment is NOT verified.** The check confirms the
   multiset of marks is unchanged, not that each mark still sits
   next to the text it marked. Section reordering that keeps
   every mark passes. Verifying attachment would need section
   alignment; that is a documented limit (§5), not a silent gap.
8. **Non-finite sentinels are not numbers.** `NaN`/`Infinity`
   (which `format_number` can emit for pathological values) are
   words and are not checked.

## 3. Integration points

- **Reads only, writes nothing new.** The gate reads the stored
  narrative's markdown (already loaded by the polish path) and
  the polish output; it adds no queries and no tables.
- **Failure ordering.** Unavailable port (503) and contract
  failure (502) are detected before the re-check, exactly as
  before; the re-check is the third gate, after a well-formed
  polish output exists. A truncated response still raises
  `SkillTruncatedError` from the hook (fix batch 2) before the
  re-check runs.
- **No behavior change to any other path.** Generation, listing,
  derivation, and mappings are untouched; the only service change
  is the three-line gate inside `polish()` plus its docstring.

## 4. Verification

### 4.1 Suite arithmetic

`pytest --collect-only` on this branch collects **1866** tests:
**1229** under `tests/unit/`, **630** under `tests/test_*.py`, and
**7** in `tests/stress_test.py` (which matches pytest's default
`*_test.py` pattern and is missed by a `test_*.py` glob). This
branch adds **26** tests (24 + 2, §4.2); 1866 − 26 = **1840**, which
matches the pre-change baseline of 1840 passed / 0 failed cited in
`FIX-BATCH-2.md` line 105 for tip `ccc3490`. The pristine baseline
was not independently re-run (the full-run lock was held by another
track when this track started); the 1840 figure is cited, not
re-measured, and the arithmetic above reconciles it with the
current collection count.

### 4.2 New and changed tests (26)

All 24 tests in the new `tests/unit/test_narratives_recheck.py`
passed in the green unit run (§4.3). Each §2 rule maps to named
tests:

- Rule 1 (code spans / UUIDs):
  `test_extract_numbers_boundaries_identifiers_and_spans`,
  `test_code_span_id_digits_ignored_even_without_backticks_in_polish`.
- Rule 2 (boundaries / hyphen ranges):
  `test_extract_numbers_boundaries_identifiers_and_spans`,
  `test_extract_numbers_hyphen_range_yields_first_endpoint_only`.
- Rule 3 (percent): `test_extract_numbers_percent_differs_from_plain`.
- Rule 4 (exact decimal):
  `test_extract_numbers_thousands_and_decimal_tolerance`,
  `test_negative_number_sign_change_fails`,
  `test_altered_number_fails_naming_missing_and_extra`.
- Rule 5 (multiset):
  `test_multiplicity_matters_duplicated_number_fails`,
  `test_dropped_key_figure_fails`, `test_invented_number_fails`.
- Rule 6 (exact marks): `test_marks_are_case_sensitive`,
  `test_other_bracketed_tokens_are_not_marks`,
  `test_altered_provenance_mark_fails`,
  `test_added_provenance_mark_fails`,
  `test_dropped_provenance_mark_fails`.
- Rule 7 (attachment not verified):
  `test_mark_reorder_passes_attachment_is_not_checked`;
  `test_footer_marks_counted_dropping_footer_fails` pins footer
  marks as counted.
- End-to-end through the real composer + renderer (P10 0 / P50 10 /
  P90 20, p_loss 0.2):
  `test_real_rendered_markdown_good_polish_passes`,
  `test_real_rendered_markdown_altered_number_fails`.
- Message and trivial cases:
  `test_good_polish_passes_with_rewording_and_format_variants`,
  `test_identical_texts_pass`, `test_empty_texts_pass`,
  `test_describe_names_every_difference`,
  `test_describe_passed_message`.

The two new API tests in `tests/test_narratives_api.py` —
`test_polish_recheck_altered_number_returns_502_and_writes_nothing`
(P50 → 99999, asserts code + message + polish stays null) and
`test_polish_recheck_dropped_provenance_returns_502_and_writes_nothing`
(one `[computed]` dropped, same assertions) — passed in the
narratives subsets (§4.3) and in root+stress round 1 attempt 2
(§4.4). The pre-existing
`test_polish_success_stores_alongside_artifact` was rewritten: its
old fixture (`"# Polished launch brief"`, which dropped every
number and mark) now correctly fails the gate, so the test uses a
`_TransformingSkillPort` that derives the polished output from the
input markdown, rewording while preserving numbers and marks.

### 4.3 Green runs

- **Unit chunk GREEN: 1229 passed, 0 failed, 180.99s**
  (2026-11-17 ~04:07 UTC, `pytest tests/unit/`, TMPDIR
  `/dev/shm/pytest-tmp-polish`, mkdir lock held). Covers all 24
  recheck tests and every other unit test.
- **Narratives subsets: 66 passed** (composer + recheck + API
  tests, post-change: 27 composer + 24 recheck + 15 API) and
  **39 passed** after `ruff format` (24 recheck + 15 API).
- **E2E smoke PASS** (`docs/sprint0/smoke_e2e.py`);
  `docs/sprint0/smoke-evidence.json` reverted afterward (git
  status clean for that path).
- **Single-file retest:** `tests/test_trial_values_api.py`, 3/3
  passed after the `/dev/shm` cleanup (§4.4), where the same file
  had failed 0/3 while the tmpfs was full.
- **Static checks:** ruff reports only the 9 pre-approved B008
  `Depends()` occurrences in routes; mypy over
  `src/planagent/` reports 1 error in
  `src/planagent/services/splits/expectations.py:522`, verified
  pre-existing (file untouched by this diff; Phase 2 code). This
  track's files are clean under both.

### 4.4 Root+stress chunk: four attempts, all environmental

The remaining 637 tests (`tests/test_*.py` + `tests/stress_test.py`)
never produced a green run in this session. Four attempts ran under
the lock with a 3-consecutive-pass SQLite preflight (the
environment-fix probe) and per-attempt TMPDIR cleanup. Every
attempt classified ENVIRONMENTAL under the proof-run rule (zero
`AssertionError`, failures only in `OperationalError` /
`disk I/O error` / EPERM / no-space signatures). No attempt showed
a code signal, and no product or test code was edited in response
to any of them.

| Attempt | Result | Dominant signatures |
|---|---|---|
| Round 1, attempt 1 (206.24s) | 263 failed, 374 passed | EPERM 29, `OperationalError` 1255, `disk I/O error` 753 |
| Round 1, attempt 2 (278.88s) | 191 failed, 446 passed | EPERM 29, `OperationalError` 895, `disk I/O error` 537 |
| Round 2, attempt 1 (307.43s) | 186 failed, 451 passed | `No space left` 14, `OperationalError` 895, `database or disk is full` 537 |
| Round 2, attempt 2 (295.16s) | 189 failed, 448 passed | `No space left` 23, `OperationalError` 895, `database or disk is full` 537 |

Full FAILED lists and `--tb=line` output:
`~/workspace/verification/polish-root-stress-round1.log`
(446,853 bytes) and
`~/workspace/verification/polish-root-stress-final.log`
(380,982 bytes). Two facts from those lists matter:

- The failure sets differ between attempts (263 vs 191 vs 186 vs
  189) and track the environment, not the code: round 1 attempt 2
  passed everything before `test_phase2_simulation_api.py`,
  including **all 15 `test_narratives_api.py` tests** (none
  appears in that attempt's FAILED list), while round 1 attempt 1
  failed the same files. The gate opens and closes mid-run.
- Round 2's failures are a clean suffix (everything from
  `test_phase2_simulation_api.py` onward): `/dev/shm` started each
  round-2 attempt 51% full with 400M of another track's
  `pytest-tmp-optc` data (verified by `du` after the runs; that
  directory was not touched), and this chunk's own ~395M filled
  the tmpfs to 100% mid-run. All 7 `stress_test.py` tests failed
  with `OSError: [Errno 28] No space left` in both round-2
  attempts.

An earlier full-suite run (1477 passed / 389 failed, 582s) and a
410-failed root run are superseded by the four attempts above:
the 410-failure run was re-diagnosed as the same tmpfs overflow
(`/dev/shm` at 100%, 485M of this track's own accumulated
basetemp dirs, cleaned before round 1).

### 4.5 Environment saga and protocol notes

The environment, not the code, is what blocked a single green
full-suite run; see
`~/workspace/verification/environment-fix-2026-11-17/REPORT.md`
for the full root-cause analysis (Ho: "解决这个环境的问题"):

- An externally imposed, supervisor-mediated write-denial gate
  intermittently refuses write-mode opens with EPERM across all
  filesystems at once, toggling on timescales from milliseconds
  to ~55 minutes. It cannot be fixed from inside the VM.
- The VM rebooted at ~05:01 UTC on 2026-11-17 (both tmpfs mounts
  wiped), killing one full-suite attempt mid-run with SIGTERM.
- The full-run lock was held by the HUD track (05:02–05:07 UTC)
  and then by the environment-fix proof run (05:42–06:21 UTC);
  this track waited rather than running concurrently.
- TMPDIR: the track brief prescribed `/dev/shm`, and the
  standing protocol in `AGENTS.md` (written 2026-11-17) prescribes
  `/home`. `/home` was measured at 13.6s/test (66 tests in 900s
  before timeout) on this VM — a 637-test chunk would hold the
  lock for hours — so the four attempts above used `/dev/shm`
  under the exclusive lock with an empty tmpfs at round 1. Round
  2 falsified that deviation: another track's unlocked 400M made
  the tmpfs fill mid-run. The deviation is recorded here, not
  hidden; the re-run command below uses `/home` per the standing
  protocol and should be expected to need a long, stable window.

Re-run to close the gate (under `full-run-lock.sh`, after a
3-pass preflight, `/home` TMPDIR):

```
TMPDIR=~/workspace/.pytest-tmp-polish env -u NO_PROXY -u no_proxy \
  .venv/bin/python -m pytest tests/test_*.py tests/stress_test.py -q
```

together with the already-green `pytest tests/unit/` (1229
passed). No code change is expected to be needed: all four
attempts had zero assertion failures, and every test this track
added or touched has passed in a gate-open window.

## 5. Known limits

- **Live LLM polish quality is still unverified.** All polish
  tests use scripted/transforming ports. The re-check itself is
  verified against fixture polishes, but no real LLM output has
  been run through it; a live polish could fail the gate in ways
  fixtures do not cover (e.g. rewording a hyphen range, moving a
  number into a code span, or writing numbers as words — "twenty"
  is not a number to this checker and would read as a dropped
  figure). False refusals are safe (nothing is stored), but the
  false-refusal rate on live output is unknown.
- **Mark attachment is not verified** (§2 rule 7): a polish that
  moves a `[computed]` mark onto template wording passes as long
  as the counts are unchanged.
- **Numbers written as words are invisible.** "Twenty trials"
  contains no extractable number; the checker sees a dropped
  `20`, which fails the check — the safe direction, but the
  failure message will say the number is missing rather than
  naming the rewording.
- **Hyphen ranges yield only the first endpoint** (§2 rule 2): a
  polish that rewrites `10-20` as `10 to 20` fails with an
  invented `20`. Safe direction, documented.
- **Trace-id content is not verified.** Ids are excluded from
  number extraction by design; a polish that alters an id's
  characters (without changing any number or mark) passes the
  re-check. The prompt forbids it; the gate does not detect it.
- **No retry-on-recheck-failure.** A failed re-check is a
  terminal refusal for that polish call; the caller must retry
  the endpoint explicitly. Consistent with the existing
  contract-failure path (no automatic retry there either).

## 6. What was NOT verified

- Docker Compose stack (no container runtime on this VM).
- Live-LLM polish output through the re-check (no live LLM in
  tests, per the track discipline; fixtures only).
- Real backend integration / cockpit rendering of the new 502
  (the cockpit path is the existing generic polish-error display,
  unchanged).
- A single green run of the root+stress chunk (637 tests): four
  attempts all classified environmental with zero assertion
  failures (§4.4). The re-run command is in §4.5; no code change
  is expected to be needed.

## 7. Commits on this branch

- (to be filled in at commit time)

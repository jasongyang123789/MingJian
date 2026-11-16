# Fix batch 1 — narratives fragment bug + LLM adapter bug

Branch: `strategy-engine/fix-batch1-narratives-adapter`, from
`strategy-engine/sprint14-direction-derivation` @ `076de3f`
(Sprint 14 tip, including the verification commit). Nothing
pushed. Ho approved this batch on 2026-11-16, to run right after
Sprint 14. This is NOT a numbered sprint: no new feature, no
migration, no UI change — two verified bugs fixed, with
regression tests. No LLM call was made anywhere in this batch;
all new tests are fixture/fake-driven.

## 1. What was fixed

### Bug 1 — narrative generation refuses robustness/gates-enriched runs

Verified 2026-11-16 over real HTTP (see
`~/workspace/verification/backend-integration-2026-11-16/REPORT.md`
§5): `POST /runs/{id}/narratives` returned 400
`narrative_corrupt_fragment` on ANY run with stored robustness
results or registered decision gates — exactly the runs the
Sprint 13 feature is designed to summarize.

Root cause: `_assemble_direction` in
`services/narratives/service.py` validated the RAW stored
fragments against `RobustnessRead` / `DecisionGatesRead`, which
require a top-level `run_id` the writers never store. Writers
store per-analysis sub-fragments (`{"tornado": ...}`) and gate
lists (`{"registrations": [...], "evaluations": [...]}`).

Fix (`services/narratives/service.py`, `_read_robustness` /
`_read_gates` / `_read_sub_fragment`): each sub-fragment is
validated on its own model and `run_id` is injected when the
read model is built — the same construction the services' own
read paths use (`get_robustness` and `get_decision_gates` in
`services/simulation/robustness.py`), and the same shape rule
the Sprint 14 derive path follows for the expected-shortfall
sub-fragment. The ensemble id on the built `RobustnessRead`
comes from the already-validated ensemble. `_assemble_direction`
itself is otherwise untouched: the same `DirectionInputs` are
assembled, the same composer runs, the same refuse-before-write
discipline holds.

Why sub-fragment validation, not whole-fragment validation with
an injected `run_id`: the read models forbid extra keys, so
injecting `run_id` into a copy of the fragment would still
refuse any fragment carrying a key the reader does not know —
a future analysis key would break narrative generation. Reading
sub-fragments individually (as `get_robustness` does) ignores
unknown keys and stays forward-compatible; it also gives one
validation per sub-fragment, so a wrong-shaped sub-fragment is
refused with the fragment named.

Deliberate strictness difference from `get_robustness`:
`get_robustness` silently drops a non-dict sub-fragment (treats
it as absent). The narrative reader refuses it as
`narrative_corrupt_fragment`: narratives are deliverables, and
silently composing a brief from half the stored analysis would
be worse than refusing. The refusal survives for genuinely
corrupt fragments — wrong-shaped sub-fragment, non-dict
fragment, non-list gate lists — before any row is written
(§4). Sprint 14's pinned test
`test_generate_refuses_enriched_run_known_sprint13_bug`, which
documented the buggy refusal, is replaced by the regression
tests in §4, as directed.

### Bug 2 — `generate_json_for_target` always returned `(meta, None)`

Verified 2026-11-16 (see the deliberation run report at
`~/workspace/delib-run/real-deliberation-2026-11-16/REPORT.md`;
reference diff `adapter_fix.diff` in the same directory):
`OpenAIService.generate_json_for_target`
(`services/openai_client.py`) assigned the result of
`_extract_json_payload` — a `str` — to `parsed`, then returned
it only when `isinstance(parsed, dict)`. A successful JSON
response therefore ALWAYS yielded `(meta, None)`, and every
live skill stage failed. The bug is upstream (present at
`999ef36`); no test pinned the real method (callers were tested
through fakes), which is how it shipped.

Fix: parse the extracted payload string (`json.loads`,
`JSONDecodeError` → `None`) in `generate_json_for_target`,
keeping the requires-dict contract — non-dict JSON (arrays,
strings, numbers) still yields `None`. The fix is byte-identical
to the verified worktree patch (same blob hashes). The other
`_extract_json_payload` callers (feeding the string to
`model_validate_json`) are correct and untouched.

## 2. What changed

- `src/planagent/services/narratives/service.py`: new
  `_read_robustness` / `_read_gates` / `_read_gates_list` /
  `_read_sub_fragment` helpers; `_assemble_direction` reads
  fragments through them; the derive-path comment updated (the
  bug is fixed, no longer "deferred"). No composer, model,
  route, or migration change. No Sprint 13 validation behavior
  changed except the fragment-shape handling fixed here.
- `src/planagent/services/openai_client.py`: 4-line parse in
  `generate_json_for_target` (4 insertions, 1 deletion).
- `tests/unit/test_openai_generate_json.py` (new): 11 tests
  against the REAL `generate_json_for_target` with a fake SDK
  client injected into `service.clients["primary"]`.
- `tests/test_direction_derivation_api.py`: the pinned
  refusal test replaced with 14 regression tests (5 success, 9
  corrupt-refusal); file docstring updated; two small helpers
  (`_register_gates`, direct-DB summary writers following the
  monitoring corrupt-registration precedent).
- Frontend: untouched. No UI change, no frontend file modified.

## 3. Design notes

- The narrative reader treats a `None` sub-fragment / gate list
  as absent (writers never store `None`; absence and explicit
  null mean the same thing here), a present non-dict / non-list
  value as corrupt, and unknown fragment keys as ignorable.
  These three rules are each pinned by a test (§4).
- The adapter fix preserves the `(meta, None)` shape on
  unparseable output (meta present, payload `None`), matching
  the verified patch: callers (`OpenAIServiceSkillPort`,
  debate/jarvis callers) already treat a `None` payload as "no
  usable JSON" and use meta for diagnostics. A transport/client
  error still yields `(None, None)` via the existing blanket
  handler, unchanged.
- `_read_sub_fragment` uses PEP 695 type-parameter syntax
  (`def _read_sub_fragment[ModelT: BaseModel]`), as the repo's
  ruff rules require (UP047/UP049).

## 4. Verification

- Full backend suite: **1289 passed / 0 failed** in 412.43s
  (baseline 1265 + 11 adapter tests + 14 new derivation API
  tests − 1 removed pinned test). Log:
  `docs/fix-batch1/test-full.log` (force-added past the `*.log`
  ignore, per precedent). No disk-full re-run was needed
  (`/tmp/pytest-of-root` cleared before the run).
- `mypy src/planagent/`: clean, 204 source files, no issues.
- `ruff check` on changed files: clean, except 8 pre-existing
  BLE001 findings in `openai_client.py`, verified identical at
  the Sprint 14 tip (same 8 findings; the last one shifts
  880 → 883 from the +3 added lines). This batch's additions
  introduced zero new findings. `ruff format` clean on all
  changed files.
- Sprint 0 smoke re-run: **PASS** (health → ingest → 4-tick
  simulation → decision trace → workbench → options); the
  refreshed `smoke-evidence.json` was reverted per precedent.
- Frontend: untouched (no re-run; no frontend file changed).
- Regression proof (stash checks): with each fix stashed, the
  new tests fail exactly where they should. Adapter: 5 of the
  11 new tests fail on pre-fix code (the dict-returning cases);
  the 6 None/edge cases pass either way, as designed.
  Narratives: the 5 success tests fail on pre-fix code; the 9
  corrupt-refusal tests pass on both (they pin the preserved
  refusal, not the fix).

### Behavior evidence (all asserted test values, with test names)

Adapter (`tests/unit/test_openai_generate_json.py`, real method
+ fake SDK client):

- `test_valid_json_object_returns_dict_and_meta`: content
  `{"wave_plan": ["a"], "n": 1}` → meta exactly `{"model":
  "fake-model", "api_mode": "chat.completions.json"}`, parsed
  exactly the input dict; the recorded call pins model
  `fake-model`, temperature `0.3`, `response_format`
  `{"type": "json_object"}`, `max_tokens` 500, and the
  system+user message pair.
- `test_fenced_json_returns_dict` /
  `test_prose_wrapped_json_returns_dict`: fenced and
  prose-wrapped JSON both yield `{"a": 1}`.
- `test_json_array_returns_none_payload` /
  `test_json_string_returns_none_payload` /
  `test_invalid_json_returns_none_payload`: payload `None`,
  meta present (requires-dict contract preserved).
- `test_none_content_returns_empty_dict` /
  `test_empty_content_returns_empty_dict`: `None`/empty content
  → `{}` (the existing `or "{}"` fallback, pinned).
- `test_unconfigured_target_returns_none_none` /
  `test_missing_model_returns_none_none_without_calling_client`
  (zero calls recorded) / `test_client_error_returns_none_none`:
  `(None, None)` on the three failure edges.

Narratives (`tests/test_direction_derivation_api.py`, real runs
+ ensembles + analyses through the HTTP layer):

- `test_generate_succeeds_on_tornado_enriched_run`: 201,
  version 1, exactly 1 driver row, variable `cash`, drivers
  `ensemble_id` equal to the stored ensemble's id.
- `test_generate_succeeds_on_gates_enriched_run`: 201, exactly
  1 `decision_gate` signal, name `g1_value`, provenance
  `computed`, text containing "not yet evaluated".
- `test_generate_succeeds_on_fully_enriched_run`: tornado +
  expected-shortfall + bootstrap + threshold-search + gates →
  201, 1 driver row, signals include both `decision_gate` and
  `threshold_search`.
- `test_generate_from_mappings_succeeds_on_enriched_run`:
  derive on the enriched run, then generate with no directions
  key → 201, `direction_mapping_ids` equal to the derived
  mapping ids (capped at 4), direction count equal to the
  mapping count.
- `test_generate_ignores_unknown_robustness_keys`: a stored
  `future_analysis` key alongside a valid tornado fragment →
  201, 1 driver row.
- Corrupt refusals (each: 400 `narrative_corrupt_fragment`,
  message naming the fragment, narratives list stays empty —
  refusal before any write):
  `test_generate_refuses_wrong_shaped_tornado_fragment`
  (`rows: "not-a-list"`),
  `test_generate_refuses_wrong_shaped_shortfall_fragment`,
  `test_generate_refuses_wrong_shaped_threshold_search_fragment`,
  `test_generate_refuses_wrong_shaped_bootstrap_fragment`,
  `test_generate_refuses_non_dict_robustness_fragment`,
  `test_generate_refuses_non_dict_tornado_sub_fragment`,
  `test_generate_refuses_wrong_shaped_gates_fragment`
  (registration `{"id": "x"}`),
  `test_generate_refuses_non_list_gates_registrations`,
  `test_generate_refuses_non_dict_gates_fragment`.

## 5. How to run / verify

```bash
# New tests for this batch
env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest tests/unit/test_openai_generate_json.py tests/test_direction_derivation_api.py -q

# Full backend suite (log at docs/fix-batch1/test-full.log)
env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest -q

# Type + lint (changed files)
.venv/bin/python -m mypy src/planagent/
.venv/bin/python -m ruff check src/planagent/services/openai_client.py src/planagent/services/narratives/service.py tests/unit/test_openai_generate_json.py tests/test_direction_derivation_api.py
.venv/bin/python -m ruff format --check src/planagent/services/openai_client.py src/planagent/services/narratives/service.py tests/unit/test_openai_generate_json.py tests/test_direction_derivation_api.py

# Smoke (Sprint 0, revert the evidence file afterward)
env -u NO_PROXY -u no_proxy .venv/bin/python docs/sprint0/smoke_e2e.py
git checkout -- docs/sprint0/smoke-evidence.json
```

## 6. Known limits

- The adapter fix is verified against a fake SDK client only.
  Live-LLM behavior (real model output through the fixed
  method, stage 2+ deliberation quality) is NOT verified by
  this batch — that evidence comes from the separate
  deliberation harness worktree, which this batch did not
  touch. The worktree's verification-only patch is now
  redundant with the fork fix; removing it is the harness
  owner's call, not this batch's.
- The narrative reader still refuses (by design) when a stored
  sub-fragment is wrong-shaped; there is no repair path for
  corrupt stored fragments beyond re-running the analysis.
- Unknown fragment keys are ignored, not reported: a
  misspelled writer key would be silently skipped. Writers are
  the only producers and are covered by their own tests.
- No behavior change to debate/jarvis callers of
  `generate_json_for_target` beyond the fix itself: they
  previously always received `None` payloads from this method
  and now receive parsed dicts — the intended behavior, but
  their downstream handling of real payloads is exercised only
  by their existing (fake-driven) tests.

## 7. What was NOT verified

- Live-LLM deliberation/polish quality (no live call in this
  batch; the harness worktree is separate).
- Real backend integration over HTTP for the fixed paths (the
  regression tests run through the HTTP layer via TestClient,
  not a live uvicorn process).
- Docker Compose stack (no container runtime on this VM).
- Worker behavior under Postgres/Redis.
- Real-browser rendering (frontend untouched).

## 8. Commits on this branch

- `41bf6ae` — parse JSON payload in `generate_json_for_target`
  + pin real method with tests
- `a10cba6` — read robustness/gates fragments per sub-fragment
  in narrative assembly + regression tests
- (this commit) — fix batch 1 report, backlog update,
  verification log

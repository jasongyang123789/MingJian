# Fix batch 2 — live-smoke truncation: unified output cap + truncation classification

Branch: `strategy-engine/fix-batch2-truncation`, from `58a56a8` (S19+S20 merge tip).
Date: 2026-11-16. No migration, no frontend change, no model change, no retry-policy
change. Not a numbered sprint: one verified live bug fixed, its misclassification
fixed, and every LLM output cap in the codebase swept.

## 1. The bug (verified from the live run, not assumed)

The live seminar smoke (`~/workspace/delib-run/seminar-live-smoke/runs/20261116T083411Z/`,
run while this batch was written) recorded, in `llm_calls.jsonl` seq 3, a
`mckinsey.diagnose` call to wentoken `gpt-5.4`:

- requested `max_tokens: 1500`, returned `finish_reason: "length"`,
  `completion_tokens: 1500` exactly;
- content 7,644 chars, cut mid-string at `"Undefined product scope`;
- `json.loads` fails: `Unterminated string starting at: line 42 column 5`.

The seminar audit recorded it as `error_kind: "contract"`
(`"no usable JSON response"`) — a misclassification. The true cause is truncation
at the token cap. The same run shows the cap is a cliff for every model, not a
`gpt-5.4` defect: kakouai `gpt-6.1-sol`'s diagnose used 1,455 completion tokens
(45 tokens of headroom), and other stages returned up to 2,408 completion tokens
against the same requested 1,500 cap — i.e. kakouai does not enforce the
requested cap, which masked the cliff for model-a, while wentoken enforces it
exactly. `finish_reason` appeared nowhere in `src/`, so truncation was
unobservable and unclassifiable. All of this was re-verified from the recorder
file and the audit export before any code was written.

## 2. What changed

### 2.1 One loose unified cap: `JSON_CONTRACT_MAX_TOKENS = 8000`

Defined once in `src/planagent/services/skills/templates.py`, imported everywhere
it applies (one value, one definition; the module is stdlib-only, so no import
cycle — verified by importing every consumer).

Value justification (Ho's instruction: no tight per-template tuning; the
principle is that no legitimate contract output can hit the cap):

- Anchor: the largest legitimate contract output observed live, 2,408
  completion tokens (market-map stage, seq 5 of the recorder file above).
- 8,000 is 3.3x that anchor. Every contract in the codebase is a bounded JSON
  shape (lists of findings/arguments/claims with prose fields); a model would
  have to write more than triple the most verbose legitimate output observed
  to hit the cap.
- A cap is a ceiling, not a target: a loose cap costs nothing on normal
  outputs. The real guards against runaway output — the S18 seminar budget
  (200 stage calls / 1M tokens) and the per-call timeout — are untouched, per
  Ho's instruction.

Applied to (see §4 for the full sweep table): all 17 skill templates, all 4
seminar templates, the `generate_json_for_target` default, all 7
`_parse_structured_output` call sites, all 4 debate call sites, both Jarvis
call sites, all 6 provider defaults, and the narrative polish cap.

### 2.2 Truncation is surfaced and classified distinctly

Threading, end to end:

1. `OpenAIService.generate_json_for_target` reads the first choice's
   `finish_reason` defensively (`_choice_finish_reason`) and adds it to the
   returned `meta` dict (key always present; `None` when the response does
   not report one).
2. `ParameterizedSkillPort` (the seminar path that hit the bug) reads it via
   `_sdk_finish_reason` onto the response.
3. `SkillLLMResponse` gains `finish_reason: str | None = None` (defaulted, so
   every existing construction keeps working; `InstrumentedPort`'s
   `dataclasses.replace` preserves it).
4. `OpenAIServiceSkillPort` threads `meta["finish_reason"]` through.
5. All three stage runners raise the distinct error when the payload is
   `None` AND `finish_reason == "length"`: `run_stage` (skills),
   `run_seminar_stage` (seminar, incl. the chair cluster/synthesize stages
   via `chair.py`), and `polish_markdown` (narratives).
6. `InstrumentedPort` records `finish_reason` in every success-path
   `stage_call_finished` audit detail (`null` when unreported).

New error: `SkillTruncatedError` (`skills/contracts.py`), subclassing
`SkillContractError` deliberately — every existing handler (the skills 502
mapping, seminar failure isolation) keeps catching it, while the message and
the classifier name the true cause. The message always names the truncation
and the cap, e.g. `response truncated at the max_tokens cap of 8000 tokens
(finish_reason='length'); the JSON output is incomplete`.

New taxonomy kind: `ErrorKind.TRUNCATED = "truncated"` (the seventh kind;
`classify_error` checks `SkillTruncatedError` BEFORE `SkillContractError` —
the ordering is the whole point, and it is pinned by test). Truncation is
never retried under the current policy. Retry-on-truncation with a raised
cap is recorded as a follow-up option only; it is NOT implemented.

### 2.3 Version discipline: parameter-only, no version bump

`_TEMPLATE_VERSION` stays `"2"` and `SEMINAR_TEMPLATE_VERSION` stays `"1"`.
Template versions pin prompt text + contract shape; `max_tokens` is a call
parameter, not prompt content — no prompt wording and no contract field
changed, so stored stage records' version stamps stay truthful. The
seminar chair templates' explicit `max_tokens=3000` overrides were removed
(they now use the shared default); the value 3000 was set without live
evidence. Tests pinning the versions (`test_skill_prompt_shapes.py`,
`test_skill_templates.py`, `test_seminar_templates.py`) pass unchanged, and
new tests pin the cap values alongside the versions.

## 3. Evidence (every number below is an asserted test value; test named)

New tests: 21. Full suite: 1819 → 1840 passed, 0 failed
(`docs/fix-batch2/test-full.log`; 496.41s).

| Asserted fact | Test |
|---|---|
| `JSON_CONTRACT_MAX_TOKENS == 8000` | `test_shared_cap_value_is_8000` |
| All 17 skill templates: `max_tokens == 8000`, version `"2"` | `test_every_template_uses_the_shared_loose_output_cap` |
| All 4 seminar templates: `max_tokens == 8000`, version `"1"` | `test_every_seminar_template_uses_the_shared_loose_output_cap` |
| `SkillTruncatedError` message contains `"truncated"` and `"8000"`; `max_tokens == 8000`, `finish_reason == "length"`, subclass of `SkillContractError` | `test_truncation_error_names_truncation_and_the_cap` |
| `classify_error(SkillTruncatedError(...)) == "truncated"`; taxonomy set is exactly the 7 kinds | `test_classify_error_maps_each_failure_class`, `test_taxonomy_kinds_are_exactly_the_design_set` |
| Truncation is not retryable | `test_only_timeouts_are_retryable` |
| `run_stage` with payload `None` + `"length"` raises `SkillTruncatedError` naming cap 8000 | `test_run_stage_truncated_response_is_a_truncation_error_naming_the_cap` |
| `run_seminar_stage` truncation raises with `seminar-v1` in the message, classifies `"truncated"`; empty response without a finish reason stays plain `contract` | `test_run_seminar_stage_truncation_raises_truncated_error_with_seminar_family`, `test_run_seminar_stage_empty_response_stays_a_plain_contract_error` |
| `generate_json_for_target` meta carries `finish_reason == "length"` with `None` payload on truncated content; `"stop"` on complete content; `None` when the SDK omits it | `test_truncated_response_reports_length_in_meta_and_none_payload`, `test_stop_finish_reason_reported_in_meta`, `test_valid_json_object_returns_dict_and_meta` |
| `generate_json_for_target` called without `max_tokens` requests 8000 | `test_default_max_tokens_is_the_shared_loose_cap` |
| `OpenAIServiceSkillPort` threads `finish_reason == "stop"` through | `test_openai_service_port_maps_meta_and_payload` |
| `ParameterizedSkillPort`: truncated content → payload `None` + `"length"` + usage kept (completion 8000); complete content → payload + `"stop"`; omitted → `None` | `test_port_reports_length_and_none_payload_on_truncated_json`, `test_port_reports_stop_and_parsed_payload_on_complete_json`, `test_port_reports_no_finish_reason_when_sdk_omits_it` |
| `stage_call_finished` detail carries `finish_reason` (`"stop"` / `null`) | `test_finished_detail_records_the_port_reported_finish_reason`, `test_finished_detail_records_null_finish_reason_when_unreported` |
| All 6 provider defaults (`LLMProvider`, `OpenAIProvider`, `AnthropicProvider` × `generate_text`/`generate_json`) == 8000 | `test_provider_defaults_are_the_shared_loose_cap` |
| `POLISH_MAX_TOKENS == 8000`; polish truncation raises naming the cap | `test_polish_cap_is_the_shared_loose_cap`, `test_polish_truncated_response_raises_truncation_error_naming_the_cap` |
| Debate OpenAI path requests `max_tokens == 8000` | `test_debate_openai_path_requests_the_shared_cap` |
| Jarvis self-review and execute-target request `max_tokens == 8000` | `test_jarvis_self_review_requests_the_shared_cap`, `test_jarvis_execute_target_requests_the_shared_cap` |

Updated pinned tests (old behavior, changed deliberately): the taxonomy
exact-set test (6 → 7 kinds), the `generate_json_for_target` meta exact-equality
test (meta gains the `finish_reason` key), and the skill-port forwarding test
(1500 → 8000 + finish reason). No other test needed changes: the full suite
passes with only these updates plus the 21 new tests.

Ruff: `ruff check` on the changed files reports 26 errors, all pre-existing
at `58a56a8` (verified by running the same check on HEAD copies — zero new
errors introduced; the two `RUF022` `__all__` findings predate this batch).
`ruff format --check`: the new test file and `jarvis.py` are formatted; the
other touched files were already unformatted at HEAD and my lines add no new
format drift (verified hunk-by-hunk against `ruff format --diff`).

## 4. Sweep: every `max_tokens` / `max_output_tokens` site in `src/`

| Site | Before | After | Verdict |
|---|---|---|---|
| Skill templates (17) | 1500 | 8000 | Raised — live truncation + 2,408 observed (§1) |
| Seminar templates (4) | 1500 / 3000 | 8000 | Raised — shared cap; 3000 unevidenced |
| `generate_json_for_target` default | 1000 | 8000 | Raised — no caller uses the default (all 4 pass explicit values); trap avoidance, zero behavior change |
| `_parse_structured_output` sites (7): evidence extraction, report enhancement, topic analysis, X search, panel perspective, action decision, debate position | 500–1400 | 8000 | Raised — prose-bearing JSON contracts with unbounded lists; a verbose-but-legitimate output can hit 500–1400 |
| `debate/llm.py` (4: OpenAI, Anthropic, registry Anthropic, registry raw client) | 1000 | 8000 | Raised — `DebatePositionPayload` carries unbounded `arguments` (claim + reasoning each) + rebuttals + concessions |
| `jarvis.py` (2: self-review, execute-target) | 700 / 500 | 8000 | Raised — `findings` + `recommendations` lists scale with pipeline steps |
| Provider defaults (6) | 1024 | 8000 | Raised — no caller uses the defaults (all pass explicit values); trap avoidance |
| Narrative polish (`POLISH_MAX_TOKENS`) | 4096 | 8000 | Raised — output is a full rewrite of the input markdown, whose length scales with the direction count |
| `change_detection.py` significance (8) | 8 | kept | Adequate — output shape proven tiny: the prompt demands exactly one word (`high`/`medium`/`low`), the parser takes the first word |
| `change_detection.py` summary (120) | 120 | kept | Adequate — one-sentence ≤80-character Chinese summary (~40–55 tokens); prose output, no JSON parse cliff; the code truncates to 240 chars anyway |
| `OpenAITestRequest.max_output_tokens` (32, ≤256) + `test_connection` default | 32 | kept | Adequate — user-controlled connection-test ping (`"Reply with exactly: OK"`); not a contract output |
| `admin.py` passthrough | — | kept | Passes the user-supplied value through; no cap of its own |
| Seminar budget (`DEFAULT_MAX_TOKENS` 1M, `max_stage_calls` 200) | — | untouched | Not an output cap; the real guard, per Ho's instruction |
| `audit.py` / `instrumentation.py` budget fields | — | untouched | Budget accounting, not output caps |

No other LLM call sites set output limits: a grep for `max_tokens`,
`max_output_tokens`, and `max_completion_tokens` over `src/` finds only the
sites above (plus the budget fields and the kept test-ping default). No new
migrations: the audit detail gains one JSON key (`finish_reason`) in an
existing schemaless detail blob, and `RoundError.kind` is a free string
validated against the `ErrorKind` values in code.

## 5. Deliberately NOT changed

- **Retry policy**: timeout-only retries stay exactly as S18 specified.
  Retry-on-truncation (re-call with a raised cap) is a follow-up option,
  noted in `errors.py`, not implemented.
- **Model selection**: nothing. The re-run keeps wentoken `gpt-5.4` as the
  regression proof that the truncation is fixed.
- **Template/contract versions**: parameter-only change (§2.3).
- **Budgets and timeouts**: untouched (§2.1).
- **Frontend**: untouched. The cockpit renders `error_kind` as a free string
  (`seminarUtils.ts` `stage_failure` branch), so the new `"truncated"` kind
  displays without any frontend change; no consumed type changed.
- **Harness and main worktree**: untouched. All work is in the
  `mingjian-fix-truncation` worktree on this branch. The live smoke running
  concurrently serves the OLD code from `~/workspace/mingjian-base`; the fix
  takes effect only when the re-run uses this branch.
- **No merge, no push**: for the parent agent to review, merge, and push.

## 6. Limits (stated honestly)

- **No live-LLM verification of the fix yet.** The evidence is fixture-driven
  (fake SDK clients, scripted ports). The proof is the re-run: `gpt-5.4`
  diagnose must complete with `finish_reason "stop"` under the 8000 cap.
- **8000 is judgment**, anchored at 2,408 × 3.3. No live output between 2,408
  and 8,000 tokens has been observed; if a future stage legitimately needs
  more, the truncation classification now exists to say so plainly instead of
  misreporting it.
- **Classification requires the provider to report `finish_reason`.**
  Providers that omit it still yield the generic contract error (with
  `finish_reason: null` in the audit detail, so the gap is visible).
- **Provider enforcement varies.** Kakouai returned up to 2,408 tokens
  against a requested 1,500 cap; wentoken enforced 1,500 exactly. The fix
  makes the REQUESTED cap safe; it cannot make providers honor it.
- **Sweep-site coverage is uneven by construction.** The seven
  `_parse_structured_output` values and the debate Anthropic/registry paths
  share the single imported constant (one definition, no drift) but have no
  per-site behavioral tests — no fake-client tests exist for those methods,
  and writing them would mean mocking the Responses API / constructing SDK
  clients. The OpenAI debate path and both Jarvis paths DO have behavioral
  cap tests (§3).
- **A truncation that happens to parse as valid JSON** (cut exactly at a
  structural boundary) is not classified as truncation — the branch fires
  only on payload `None` + `"length"`, as specified. The `finish_reason` in
  the audit detail still records it.

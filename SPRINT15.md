# Sprint 15 — Skill prompt/contract alignment (both directions)

Branch: `strategy-engine/sprint15-skill-alignment`, from
`strategy-engine/fix-batch1-narratives-adapter` @ `ba513ef`.
Nothing pushed. Ho directed on 2026-11-16 that BOTH alignment
directions be done, then re-tested live ("两个方向都做，做完了重新测试").
This sprint does both directions in the fork; the live harness
re-test is the parent's job after verification, NOT this
sprint's (no LLM call was made anywhere here; all tests are
fixture/fake-driven).

Background: the live deliberation runs on 2026-11-16 (howtofix
and kakouai endpoints) both failed at stage 1 of both
pipelines. The kakouai run captured the models' raw outputs
(see `~/workspace/delib-run/real-deliberation-2026-11-16-kakouai/REPORT.md`
§2): valid, high-quality JSON in shapes the prompt prose
invites but the Pydantic contracts forbid. This sprint aligns
the two sides so those outputs validate: prompts specify the
exact shapes contracts enforce, and contracts normalize the
structured shapes models naturally produce.

## 1. What was built

### Prompt-side fixes (`services/skills/templates.py`)

Ten of the 17 templates were rewritten to specify the EXACT
shape of every output key (see the audit table in §2): flat
strings vs lists of strings vs objects vs mappings are now
stated per key, including explicit "never a nested object"
where the v1 prose invited structure. The `_JSON_ONLY`
instruction and the no-new-numbers rule are preserved on
every template (pinned by test for all 17). No prompt
semantics changed beyond shape specification plus the
framework index.

The missing framework index is supplied: `FRAMEWORK_INDEX`
(21 entries, adapted from the McKinsey skill source's
"Framework index" section — see §3) is rendered into the
intake prompt verbatim, and the prompt requires copying
names exactly from it.

### Contract-side coercion (`services/skills/contracts.py`)

A deterministic `mode="before"` validator on `_Contract`
normalizes structured shapes to the canonical shapes
downstream already consumes, before validation:

- object → flat string: deterministic labeled rendering
  (`"key: value"` pairs joined with `"; "`, insertion order,
  recursive);
- list → flat string: rendered items joined with `"; "`;
- object → list of strings: one rendered string per
  top-level entry, insertion order;
- list of non-strings → list of strings: each item rendered.

Canonical output shapes are UNCHANGED: conforming input
validates byte-identical to v1 (pinned by test over 11
recorded fixtures). `extra="forbid"` stays. Literals,
scores, mappings, and nested-model shapes are never coerced.
One documented information drop: `CritIntake.options`
`{"name", "description"}` items reduce to the name (the
canonical shape is names-only; downstream matches on names).
Nothing is fabricated: empty values still fail `min_length`
constraints, and a bare string for a `list[str]` field is
still a contract error (deliberate, pinned by test).

One contract constraint was relaxed: `IntakeClassification.
frameworks` lost its `min_length=1` (now defaults to an empty
list). The v1 minimum turned the model's honest empty answer
— no index was supplied, so no framework could be named —
into a pipeline failure. An empty list is a legitimate
answer once the index is supplied, and no code consumes
`frameworks` except by serializing the intake (verified by
grep). The prompt still asks for at least one framework when
any fits.

### Golden fixtures

The EXACT captured model outputs (kakouai `llm_calls.jsonl`
seq 8 = intake output, seq 9 = crit output) are copied
byte-exact into `tests/fixtures/skill_outputs/` (verified
byte-identical at copy time: 4696 and 8540 bytes; zero `sk-`
matches), with expected normalized outputs verified by
inspection against the rendering rules. Both captured
outputs now validate through the fixed contracts.

### Versioning

Template and contract versions both bump `1` → `2`. The
package versions templates and contracts as sets (single
module constants `_TEMPLATE_VERSION` /
`SKILL_CONTRACT_VERSION`); the bump marks the aligned set,
and §2 records exactly which templates changed. Deliberation
records pin the versions actually used via `run_stage`
(`template.version` + `SKILL_CONTRACT_VERSION`), unchanged
mechanically. Version-pin assertions in 5 existing test
files were updated to `"2"` as part of the bump.

## 2. Audit table — all 17 templates

Each template's system prompt + user-prompt wording was
compared against its Pydantic contract field by field
(names, types, min/max lengths, literals, nested models).
"Evidenced" = the live 2026-11-16 capture shows the
mismatch; "inspection" = found by reading prompt vs
contract. The bar for changing a prompt: its wording invites
a shape the contract forbids, or leaves a field's container
or scalar type genuinely ambiguous. A bare "(list)" for a
`list[str]` field whose items are described as statements or
names is unambiguous and was left alone.

| Template | Contract | Finding | Action |
|---|---|---|---|
| mckinsey.intake_classify | IntakeClassification | EVIDENCED: prompt references a framework index never supplied (`frameworks: []` refused by min-1); `wave_plan` prose reads as a 3-part object, contract wants `list[str]` | Rewrote shape spec; rendered the 21-entry index into the prompt |
| mckinsey.diagnose | Diagnosis | None: list-of-statements wording matches `list[str]` fields | Unchanged (byte-identical) |
| mckinsey.market_map | MarketMap | INSPECTION: `competitors (list, each with likely move)` invites per-item objects; contract wants `list[str]` | Rewrote: one string per competitor + likely move |
| mckinsey.option_generate | OptionSet | None: nested option shape described explicitly; "2-3 options" within max 6 | Unchanged (byte-identical) |
| mckinsey.filter_shortlist | Shortlist | INSPECTION: `dropped (list of option names dropped, each with a reason)` is ambiguous between strings and objects; `scores` wording does not say the values are keyed by criterion name | Rewrote: dropped = list of `{name, reason}` objects; scores = object mapping criterion name to 0-10 |
| mckinsey.synthesize | Synthesis | INSPECTION: `alternatives_considered (list of names, each with a reason)` invites per-item objects; contract wants `list[str]` | Rewrote: one string per alternative + reason |
| mckinsey.verify_assumptions | AssumptionAudit | INSPECTION (mild): `importance (1-5)` does not say integer; contract wants `int` 1-5 | One-word fix: "an integer from 1 to 5" |
| mckinsey.verify_wargame | WarGame | None: nested shapes described explicitly | Unchanged (byte-identical) |
| mckinsey.verify_execution | ExecutionReview | None: nested shapes described explicitly | Unchanged (byte-identical) |
| mckinsey.tournament_judge | TournamentJudgment | INSPECTION (mild): `criteria_scores` wording does not say the numbers are keyed by criterion name | Rewrote: object mapping criterion name to 0-10 |
| advisory.crit_intake | CritIntake | EVIDENCED: prose invites nested objects for evidence/success/reversibility/context/economics/current_preference/options (10 fields failed as "should be a valid string"); contract wants flat strings / `list[str]` | Rewrote: every field specified as a single flat string or plain-name list, "never a nested object" |
| advisory.lens_position | LensPosition | INSPECTION (mild): `option_scores` wording does not say the numbers are keyed by option name | Rewrote: object mapping option name to 0-10 |
| advisory.lens_revision | LensRevision | INSPECTION (mild): `revised_scores` wording does not say the numbers are keyed by option name | Rewrote: object mapping option name to 0-10 |
| advisory.forced_debate | ForcedDebate | None: nested disagreement shape described explicitly; `rebuttals (list)` unambiguous in context | Unchanged (byte-identical) |
| advisory.chair_synthesis | DecisionContract | INSPECTION (mild): `lens_weights` wording does not say the weights are keyed by lens name or integers | Rewrote: object mapping lens name to relevance integer 1-3 |
| gambit.premortem | PreMortem | None: nested shapes described explicitly | Unchanged (byte-identical) |
| mece.propose_tree | DecompositionTree | None: recursive tree shape described explicitly; live PASS evidence on two endpoints | Unchanged (byte-identical) |

10 templates changed, 7 byte-identical (verified by
per-template block comparison against the branch point).

## 3. Design decisions

### Framework-index source: the real index, not an invented list

The grafted skill material DOES contain the index: the
mckinsey-strategy-team clone's `SKILL.md` has a "Framework
index (21 frameworks → path → when to use)" section. The
constant adapts that table (names + groups + when-glosses)
under the same MIT attribution the templates already carry.
No list had to be invented. The index is rendered into the
prompt as literal template text built from the constant at
module level (no new slot, no orchestration change — the
index is fixed data versioned with the template).

### Coercion, not widening

The alternative — widening contracts to structured shapes
and adapting downstream consumers — was rejected per
direction: it would change every consumer of stage outputs.
Coercion keeps downstream behavior identical and confines
the change to validation. The rendering rules are total
(every JSON value renders) and deterministic (insertion
order, fixed separators), so the same raw output always
normalizes to the same canonical output.

### Per-field coercion choices

- `str` fields: dict/list input renders flat (lossless).
  Applies to every `_Contract` str field, including nested
  models (the validator is inherited).
- `list[str]` fields: dict input renders one string per key;
  list items that are not strings render flat (lossless).
  Applies to every `_Contract` list[str] field.
- `CritIntake.options` only: dict items with a string
  `"name"` key reduce to the name; the description is
  dropped (flagged here and pinned by test — the 4 captured
  descriptions are asserted ABSENT from the normalized
  output). Rationale: downstream matches on option names
  (lens scoring keys, chair's final option); a rendered
  `"name: …; description: …"` string would corrupt those
  keys. Dict items without a `"name"` key render flat.
- NOT coerced: `dict[str, Score]` / `dict[str, int]` fields
  (prompt-side fix only), literals, numeric fields, nested
  models as wholes, `None`, and bare strings for `list[str]`
  fields (still errors, per the pre-existing pinned test).
- `DecompositionTree` (`mece.propose_tree`) is not a
  `_Contract` subclass and gets no coercion: its prompt is
  precise and it has live PASS evidence on two endpoints.

### What "byte-identical" covers

On already-conforming input, `model_dump(mode="json")`
equals the input dict exactly — asserted for 11 recorded
fixtures across both pipelines plus premortem. The
coercion validator returns conforming values untouched; it
only transforms values that would otherwise fail.

## 4. Verification

- Full backend suite: **1349 passed / 0 failed** in 423.77s
  (baseline 1289 + 60 new: 26 coercion + 5 golden + 29
  prompt-shape; collection count verified: 60 tests
  collected across the three new files). Log:
  `docs/sprint15/test-full.log` (force-added past the
  `*.log` ignore, per precedent). Note: the first full run
  reported 1348 passed / 1 failed — a version-pin assertion
  in `tests/unit/test_skill_templates.py` missed in the
  first pass; fixed (one line, `"1"` → `"2"`) and the
  re-run passed fully; the log holds the clean re-run. No
  disk-full re-run was needed (`/tmp/pytest-of-root`
  cleared before each run).
- `mypy src/planagent/`: clean, 204 source files, no issues.
- `ruff check` on changed files: clean except 2 pre-existing
  findings verified identical at the branch point via
  `git show` (RUF022 `__all__` ordering in `templates.py`;
  I001 import sorting in `test_skill_orchestration.py`) and
  2 pre-existing `ruff format` nits in untouched regions of
  `contracts.py` / `templates.py` (verified via real-file
  check at the branch point). This sprint's code
  introduces zero new findings; new test files are
  format-clean.
- Sprint 0 smoke re-run: **PASS**; the refreshed
  `smoke-evidence.json` was reverted per precedent.
- Frontend: untouched (no frontend file changed, no
  re-run).

### Behavior evidence (all asserted test values, with test names)

Coercion (`tests/unit/test_skill_coercion.py`):

- `test_object_for_string_field_renders_flat`: evidence
  `{"known": "a", "unknown": "b"}` → `"known: a; unknown: b"`.
- `test_list_for_string_field_joins_items`: `["a", "b"]` →
  `"a; b"`.
- `test_nested_object_renders_recursively_in_insertion_order`:
  `{"a": {"b": "c"}, "d": ["e", "f"]}` → `"a: b: c; d: e; f"`.
- `test_scalar_values_render_as_json_literals`:
  `{"flag": true, "n": 3, "nil": null}` →
  `"flag: true; n: 3; nil: null"`.
- `test_dict_for_str_list_field_renders_one_string_per_key`:
  findings `{"a": "x", "b": "y"}` → `["a: x", "b: y"]`.
- `test_list_of_objects_for_str_list_renders_each_item`:
  `[{"k": "v"}, "plain", ["x", "y"]]` →
  `["k: v", "plain", "x; y"]`.
- `test_options_name_items_reduce_to_names`:
  `[{"name": "A", "description": "dropped"}, "B"]` →
  `["A", "B"]`.
- `test_options_dict_without_name_renders_flat`:
  `[{"label": "X"}]` → `["label: X"]`.
- `test_nested_model_fields_coerce_too`: an
  `OptionCandidate` description of `{"a": "b"}` → `"a: b"`.
- `test_conforming_input_validates_byte_identical` (11
  fixtures): `model_dump(mode="json")` equals the input
  dict exactly, for intake, diagnose, market_map,
  filter_shortlist, synthesize, verify_assumptions,
  crit_intake, lens_position, forced_debate,
  chair_synthesis, and premortem fixtures.
- Boundaries, each still raising `SkillContractError`:
  `test_empty_dict_for_required_string_still_fails`
  (evidence `{}` → `""` fails `min_length`),
  `test_bare_string_for_str_list_still_fails` (wave_plan as
  a bare string), `test_dict_scores_are_not_coerced`
  (option_scores as a list of pairs),
  `test_literal_fields_are_not_coerced` (stakes as an
  object), `test_empty_wave_plan_still_fails` (`[]` fails
  `min_length` — no fabrication).
- `test_empty_frameworks_list_validates`: frameworks `[]`
  validates and stays `[]`.

Golden fixtures (`tests/unit/test_skill_golden_fixtures.py`):

- `test_live_intake_output_validates_and_normalizes`: the
  exact seq-8 output validates; normalized output equals
  the pinned fixture; frameworks `[]`; stakes `"standard"`;
  wave_plan has 3 entries starting `wave_A: lead:`,
  `wave_B: option_mandates:`, `verifier_panel:`; 8
  constraints, 9 open questions.
- `test_live_crit_output_validates_and_normalizes`: the
  exact seq-9 output validates; normalized output equals
  the pinned fixture; options exactly `["Phased rollout",
  "Full launch", "Partner-led", "Defer or do not launch"]`;
  evidence contains `known_facts:`, `important_unknowns:`,
  `q3-marketing-report`; success contains
  `measurable_outcome:`; reversibility contains
  `can_be_tested_cheaply:` and `lasting_downside:`; 3
  questions.
- `test_evidenced_stage1_errors_no_longer_occur_for_golden_inputs`:
  both golden payloads parse without raising (the v1
  errors were frameworks min-1 + wave_plan-not-a-list and
  10 "should be a valid string" failures).
- `test_intake_normalization_drops_no_information` / `test_crit_normalization_drops_only_option_descriptions`:
  every leaf string of the raw outputs appears in the
  normalized output, except the 4 option descriptions,
  which are asserted absent (the documented drop).

Prompt shapes (`tests/unit/test_skill_prompt_shapes.py`):

- `test_framework_index_has_21_unique_entries`: 21 entries,
  unique names, every group/gloss non-empty.
- `test_intake_prompt_renders_the_framework_index`: the
  rendered prompt contains the copy-exactly instruction and
  all 21 framework names.
- Per-template shape-spec tests assert the exact key
  wording for intake, market_map, filter_shortlist,
  synthesize, verify_assumptions, tournament_judge,
  crit_intake (including `"never a nested object"` occurring
  exactly 6 times), lens_position, lens_revision, and
  chair_synthesis.
- `test_every_template_keeps_json_only_and_no_new_numbers`
  (17 templates): every rendered prompt contains "Return
  valid JSON only", "Do not compute new numbers", and "do
  not invent, adjust, or recompute them".
- `test_all_templates_are_version_2`: 17 templates, all
  version `"2"`.

## 5. How to run / verify

```bash
# New tests for this sprint
env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest tests/unit/test_skill_coercion.py tests/unit/test_skill_golden_fixtures.py tests/unit/test_skill_prompt_shapes.py tests/unit/test_skill_contracts.py tests/unit/test_skill_templates.py tests/unit/test_skill_orchestration.py tests/test_skills_api.py -q

# Full backend suite (log at docs/sprint15/test-full.log)
env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest -q

# Type + lint (changed files)
.venv/bin/python -m mypy src/planagent/
.venv/bin/python -m ruff check src/planagent/services/skills/contracts.py src/planagent/services/skills/templates.py tests/unit/test_skill_coercion.py tests/unit/test_skill_golden_fixtures.py tests/unit/test_skill_prompt_shapes.py
.venv/bin/python -m ruff format --check tests/unit/test_skill_coercion.py tests/unit/test_skill_golden_fixtures.py tests/unit/test_skill_prompt_shapes.py

# Smoke (Sprint 0, revert the evidence file afterward)
env -u NO_PROXY -u no_proxy .venv/bin/python docs/sprint0/smoke_e2e.py
git checkout -- docs/sprint0/smoke-evidence.json
```

## 6. Known limits

- **Live verification NOT done in this sprint.** No live
  LLM call was made; whether the v2 prompts + coercion
  carry both pipelines past stage 1 is proven only by the
  parent's harness re-test. The golden fixtures prove the
  exact captured stage-1 outputs now validate; they do not
  prove the next live outputs will.
- **Later-stage templates were fixed by inspection only.**
  Stages 2+ have never been observed live; further
  prompt/contract mismatches of the same kind may exist in
  later templates (the audit found only the mild dict-key
  wordings listed in §2). The harness re-test reveals them
  one stage at a time; fix them the same way, with newly
  captured outputs as regression fixtures.
- **Option descriptions are dropped by coercion** (see §3).
  If a future model returns descriptions carrying material
  distinctions between options, that information is lost at
  validation. The fixed prompt no longer invites
  descriptions, so this should not recur; the drop is
  pinned by test so any change is deliberate.
- **Coercion is deliberately narrow.** Dict-valued score
  maps, literals, and nested-model shapes are not coerced;
  a model returning scores as a list of pairs, or a
  mis-cased literal, still fails. Widen only on live
  evidence.
- **Rendering cosmetics.** The `"; "` join after a
  sentence-ending period produces `".;"` sequences in
  coerced strings. Deterministic and lossless; slightly
  unpolished in rendered context blocks.
- **The frameworks minimum was relaxed, not replaced.** An
  empty frameworks list is now accepted silently; nothing
  flags "the model chose no framework" downstream. The
  prompt asks for at least one when any fits.
- **The 10s engine `wait_for` tick timeout** (which
  cancelled 3 tick calls under CPU contention on the live
  run) is untouched — harness-side observation, not a
  skills-contract issue.

## 7. Cockpit check

No UI change: no frontend file was modified. Nothing to
check in the cockpit; the skills endpoints and deliberation
views are unchanged.

## 8. Deferred (out of scope, recorded deliberately)

- Live harness re-test past stage 1 (parent's job after
  verification) and any further alignment rounds it
  reveals.
- Dict-shape coercion (e.g. list-of-pairs → score map) and
  case-insensitive literal matching — only on live
  evidence.
- Coercion for `DecompositionTree` (mece.propose_tree) —
  not needed on current evidence (two live PASS runs).
- Variable→outcome wiring (MC trials vary only by seed;
  variable distributions never drive trial outcomes) —
  separate follow-up gating option B, not this sprint.
- Surfacing "coercion applied" in stage records (audit
  visibility for normalized outputs) — no record schema
  change was made; normalized outputs are stored as
  canonical outputs with v2 versions.

## 9. Commits on this branch

- `03655e7` — contract coercion + golden fixtures + v2 versions
- `a2d99ac` — prompt shape specs + framework index in intake
- `0bae4a5` — fix missed template-version pin in template tests
- (this commit) — Sprint 15 report, backlog update, verification log

## 10. What was NOT verified

- Live-LLM deliberation past stage 1 (no live call in this
  sprint; harness re-test pending).
- Panel behavior, debate rounds, tournament judging, and
  deep-mode war-game loops against a live model.
- Real backend integration over HTTP for the changed paths
  (regression tests run through TestClient; the skills API
  tests use the scripted port).
- Docker Compose stack (no container runtime on this VM).
- Worker behavior under Postgres/Redis.
- Real-browser rendering (frontend untouched).

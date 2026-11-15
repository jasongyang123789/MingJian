# Sprint 13 — Decision-direction narrative output

Branch: `strategy-engine/sprint13-decision-narrative`, from
`strategy-engine/sprint12-cockpit-cleanup` @ `1b5f5d6`. Nothing
pushed. All three priority items landed: (1) the deterministic
composer + JSON artifact + endpoints, (2) the cockpit directions
view, (3) the LLM polish hook, strictly separated and tested
fixture-driven. Live LLM polish quality is UNVERIFIED (no LLM key
on this VM; the provider blocks direct SDK access — see §9).

This sprint is the last mile of the four-layer vision: the engine
now turns stored simulation artifacts into a readable decision
brief — 1–4 directions, each with an outcome distribution, key
drivers, tripwire signals, a pre-mortem, and a 48-hour first step,
every section marked with its provenance and traced to the
artifacts it came from.

## 1. What was built

### Composer (`services/narratives/composer.py`, new, pure)

`compose_narrative(inputs) -> ComposedNarrative` is a pure function:
no I/O, no clock, no randomness. It validates direction references,
derives each direction from pre-loaded stored fragments, ranks
directions by P50 descending (ties by name ascending), renders the
deterministic markdown, and returns the artifact body plus the input
pins the service hashes. The input dataclasses
(`NarrativeInputs`, `DirectionInputs`, `LoopContextInput`) are the
single assembly contract between the service and the composer.

Per direction, the composer produces:

- **Distribution** (computed): the chosen arm's summary from the
  source run's stored ensemble (n/mean/min/max/P10/P50/P90/stddev/
  p_loss, metric, loss threshold, trials, seed, ensemble id), plus
  the arm's expected shortfall and bootstrap intervals when stored.
- **Drivers** (computed): the stored tornado rows in stored order,
  capped at 5; an honest note when no tornado is stored.
- **Signals**: the fixed-order union of (a) the latest gate
  evaluation outcomes, or the active registration's gates marked
  unevaluated, (b) the stored threshold search (reachable threshold
  or an honest "no threshold found" statement with bounds), (c) the
  loop's active triggers when a loop is supplied, (d) advisory
  go-threshold / kill-criterion quotes, (e) war-game playbook
  entries. No dedup across sources; each signal is labeled with its
  kind and provenance.
- **Pre-mortem** (deliberated or template): the gambit pre-mortem
  quoted from the latest strategy-team deliberation, or an explicit
  template notice naming the endpoint that would produce one.
- **First step** (deliberated or template): the advisory decision
  contract's next action, cheapest validation test, and conditions,
  or an explicit template notice.
- **MECE trace** (computed): the named branches with their scope
  tags copied from the anchor run's stored tree, or null with a note
  when the anchor run has no tree.

### Models (`services/narratives/models.py`, new)

`NarrativeGenerateRequest` / `DirectionDefinition`
(`extra="forbid"`, 1–4 directions, unique names enforced by the
model), the full artifact-body shape (`NarrativeBody` and its
section models), read shapes, and `NarrativeError` (stable code +
message). The body carries no id, version, or timestamp — those
live on the stored row — so the content hash is a pure function of
the inputs. Protocol version `sprint13-v1`.

### Renderer (`services/narratives/render.py`, new, pure)

`render_narrative_markdown(body)` renders the deterministic reading
text in fixed section order with the Sprint 6 number formatting
(integers plain, floats to 6 places, trailing zeros stripped). The
markdown is part of the body and therefore covered by the content
hash. Every section carries its provenance mark in the text
(`[computed]` / `[deliberated]` / `[template]`), and the footer
states what each mark means.

### Polish hook (`services/narratives/polish.py`, new)

`polish_markdown(port, markdown)` runs one rewrite pass through the
Sprint 6 `SkillLLMPort`. The template (`narrative.polish`, v1) and
its contract (`{"polished_markdown": str}`) live in the narratives
package, NOT in the skills registry — touching Sprint 6's pinned
17-template test was deliberately avoided. The system prompt forbids
computing new numbers, adding/removing/changing any number, claim,
provenance mark, or trace id, and inventing failure modes, signals,
or next actions. Unavailable port raises `SkillLLMUnavailable`;
malformed output raises `SkillContractError`; both are structured
failures, never silent pass-throughs.

### Persistence (`domain/models.py`, migration 0035)

Two new append-only tables (migration `0035_decision_narratives`,
revises `0034_loop_evaluations`, verified upgrade → downgrade →
re-upgrade on scratch SQLite; see §4):

- `decision_narratives`: id, run_id (FK, index), per-run 1-based
  `version`, topic, `inputs_hash`, `content_hash`, `artifact` JSON,
  created_at. Regeneration inserts a new version, never overwrites.
- `decision_narrative_polishes`: id, narrative_id (FK, index),
  model, template_id, template_version, polished_markdown,
  created_at. A polish never touches the narrative row.

Storage choice justification: a new table, not a run-summary key.
Narratives are versioned, append-only deliverables that must be
queryable on their own (list versions, fetch one, attach polishes),
following the calibration-fits precedent over the run-summary
fragment pattern. The Sprint 6 deliberation precedent (summary key)
fits append-only logs attached to a run; narratives are standalone
deliverables with their own versioning and hash identity.

### Service (`services/narratives/service.py`, new)

`NarrativeService` assembles inputs by reading stored fragments
directly with the same Pydantic models the writing services used
(Sprint 6 context-builder precedent) — no coupling to
`SimulationService`. Every direction reference is validated before
composing or persisting anything: unknown source run, non-completed
source run, missing ensemble, unknown MECE branch, missing
deliberation pin, and loop baseline mismatch all refuse before any
row is written. The service computes `inputs_hash` (request +
source artifact identities: ensemble ids, seeds, trials, metrics,
deliberation ids, gate ids, calibration fit ids, loop registration
id) and `content_hash` (SHA-256 of the canonical JSON of the body)
with the Sprint 3 canonicalization discipline. Port construction
mirrors `SkillDeliberationService` (`llm_port` > `OpenAIService` >
unavailable fallback); the port is used only by the polish path.

### Endpoints (`api/routes/narratives.py`, new; wired in `_deps.py` + `routes/__init__.py`)

- `POST /runs/{run_id}/narratives` (201): generate a new version.
  The anchor run must exist (404) and be COMPLETED.
- `GET /runs/{run_id}/narratives`: versions newest first, each with
  its latest polish or null.
- `GET /runs/{run_id}/narratives/{narrative_id}`: one version with
  its latest polish or null. A narrative under the wrong run id is
  a 404.
- `POST /runs/{run_id}/narratives/{narrative_id}/polish` (201): one
  polish pass. LLM unavailable → 503
  `narrative_polish_unavailable`, nothing written; malformed output
  → 502 `narrative_polish_contract_failed`, nothing written.

Error codes (all `NarrativeError` → 400 with a `{"code",
"message"}` detail, except the two polish codes above):
`narrative_requires_completed_run`,
`narrative_requires_ensemble` (names the direction, the source run,
and the monte-carlo endpoint to run first),
`narrative_unknown_source_run`, `narrative_source_run_not_completed`,
`narrative_unknown_mece_branch` (names the branch and the valid
names), `narrative_mece_branches_without_tree`,
`narrative_deliberation_not_found`, `narrative_loop_not_found`,
`narrative_loop_baseline_mismatch`, `narrative_corrupt_deliberation`
(a stored deliberation stage failing its contract),
`narrative_corrupt_fragment` (a stored MECE/ensemble/robustness/
gates/deliberation/loop fragment failing its model). Request-shape
violations (duplicate direction names, 0 or 5+ directions) are
Pydantic 422s.

### Cockpit directions view (`frontend-v2`, new route `/cockpit/directions`)

- Typed clients (`narrativesApi`: generate/list/get/polish) and
  type mirrors in `engineTypes.ts`, following the Sprint 7/8/9
  conventions.
- `Directions.tsx`: anchor run picker (with `?run=` search param),
  a compact generate form (topic, 1–4 direction rows: name +
  source-run select + arm select + MECE branch checkboxes taken
  from the anchor run's stored tree via the Sprint 1 endpoint),
  client-side validation (names non-empty and unique, source run
  chosen), refusal errors shown with their code and message,
  version history newest-first, and the reading view.
- `DirectionViews.tsx`: `DirectionView` renders one direction
  (distribution, drivers, signals with kind labels and pass/fail,
  pre-mortem, first step, MECE trace) with `ProvenanceBadge` pills
  （计算 / 商议引用 / 模板措辞）; `NarrativeView` renders the header
  context (version, hashes, MECE, calibration fits, loop), all
  directions, the deterministic markdown, and the polish section —
  polished text labeled LLM-generated with its model and template,
  the deterministic rendering always visible, and an honest notice
  when no polish exists. Never renders a direction the artifact
  does not contain.
- `CockpitNav` gains a 决策方向 tab. Loop selection and deliberation
  pinning stay API-only (the form sends `loop_id: null` and
  `deliberation_id: null`); this is a deliberate scope boundary,
  recorded in §6.

## 2. Design decisions

### Inputs inventory (from code, before building)

| Input | Storage location | Id fields used |
|---|---|---|
| MECE tree + validation | `SimulationRun.configuration["mece"]` (`decomposition` + `validation`) | branch names (pre-order), scope tags, `is_mece`, counts |
| Ensemble | `SimulationRun.summary["monte_carlo"]` (`MonteCarloResult`) | `ensemble_id`, `seed`, `trials`, `metric`, `loss_threshold`, per-arm summaries |
| Robustness | `SimulationRun.summary["robustness"]` (`RobustnessRead`) | `tornado.rows`, `threshold_search`, `expected_shortfall`, `bootstrap` (+ `trial_values_hash`) |
| Decision gates | `SimulationRun.summary["decision_gates"]` (`DecisionGatesRead`) | registration ids, evaluation ids, outcomes |
| Deliberations | `SimulationRun.summary["skill_deliberations"]` (append-only list of `SkillDeliberationRecord`) | deliberation id, pipeline, template ids; `panel.premortem`, `panel.wargame`, `contract` |
| Calibration fits | `calibration_fits` table (`CalibrationFitRecord`) | fit id, kind, `loo_rmse`, `inputs_hash`, `n_observations`, created_at (newest 5, anchor domain) |
| Loop triggers | `strategy_loops.triggers` (append-only `TriggerRegistration` list) | registration id, trigger definitions (latest active, else latest — the Sprint 9/11 rule) |
| Scenario branches | `SimulationRun.parent_run_id` | used only implicitly: a child run is a valid `source_run_id` |

What does NOT exist in stored form, and how the design copes:

- **No direction source.** `DecisionOption` rows (`decision_options`
  table) carry title/description/risks/confidence/ranking but no
  link to ensembles, branches, or arms, so they cannot supply
  distributions. Scenario branches carry no direction semantics.
  Deliberation option names link to no run or arm. Directions
  therefore come ONLY from explicit user-supplied definitions in
  the generation request (rule 1 below). `DecisionOption` rows are
  not quoted as analysis: no provenance mark fits user-authored
  option content.
- **No numeric actuals ingestion.** As found in Sprint 9, `Claim`
  is textual; loop triggers can only be quoted as registered
  definitions, not evaluated against live data, in a narrative.
  The monitoring worker (Sprint 11) evaluates them; the narrative
  quotes the registration.
- **No stored "recommended direction".** Deliberation
  recommendations (`synthesis.recommended_option`,
  `contract.verdict`) name options, not runs. The composer quotes
  pre-mortems, contracts, and playbooks verbatim but never treats
  a recommendation as a direction.

### Direction-derivation rules (as implemented)

1. Directions come ONLY from the request's `directions` list
   (1–4). Nothing is invented from options, branches, or
   deliberations.
2. Each definition names the direction and points at its sources:
   `name` (required), `source_run_id` (required — the run whose
   stored ensemble supplies the distribution; may be the anchor, a
   scenario child, or a re-simulation), `arm` (default `baseline`),
   `mece_branches` (optional), `deliberation_id` (optional pin).
3. The distribution is the source run's stored ensemble, chosen
   arm. The source run must be COMPLETED with a stored ensemble,
   else the whole request refuses before any write.
4. Ranking is P50 descending, ties by name ascending; ranks are
   assigned after composition and output order is ranked order.
5. MECE traces validate `mece_branches` against the anchor run's
   tree branch names (pre-order walk, first match wins for
   duplicates); scope tags are copied from the tree. If the anchor
   has no stored tree, `mece_branches` must be empty and the
   artifact records a null trace with a note.
6. Deliberation quotes come from the latest-per-pipeline record on
   the SOURCE run, falling back to the ANCHOR run. A pinned
   `deliberation_id` must exist on the source or anchor run and
   then solely determines what is quotable (a pinned strategy-team
   record yields no advisory quotes, and vice versa).
7. Drivers are the stored tornado rows in stored order (cap 5).
8. Signals union in fixed kind order: gate evaluation / active
   registration, threshold search, loop triggers, advisory
   go/kill quotes, war-game playbook. No dedup; each labeled.
9. Calibration context is header-level only (newest 5 fits for the
   anchor domain, column data).
10. `loop_id` (optional): the loop's `baseline_run_id` must equal
    the anchor run id, else refuse.
11. Topic: request topic > MECE tree topic > `run {run_id}`; the
    artifact records `topic_source`.

### Provenance taxonomy (as implemented)

Every content section carries exactly one mark:

- `computed`: derived from stored numbers (distributions, drivers,
  gate/threshold/loop signals, MECE traces, calibration context).
- `deliberated`: quoted from a stored skill output, citing the
  deliberation id + pipeline + template id. Quotes are verbatim
  field copies through the Sprint 6 contracts; a stored stage that
  fails its contract refuses the whole generation
  (`narrative_corrupt_deliberation`) rather than being
  paraphrased or skipped.
- `template`: fixed composer wording, explicitly marked. Template
  text states what is absent and names the endpoint that would
  produce it. A direction with no deliberation behind it says so;
  no pre-mortem, signal, or first step is ever fabricated.

The markdown rendering carries the same marks in text, and the
cockpit renders them as badges with explanatory tooltips.

### Determinism

The composer is pure; the body carries no ids or timestamps; the
markdown is rendered from the body and covered by the content
hash. Same inputs → byte-identical body: asserted by test, not
claimed (see §4). The service pins both hashes on the stored row so
any later reader can verify the artifact against its inputs.

### What was deliberately NOT built

- No direction auto-derivation from options/branches/deliberations
  (no stored source exists; inventing one would violate the
  provenance discipline).
- No LLM call in the default path. The polish hook is opt-in per
  narrative, post-hoc, and strictly separated.
- No loop/deliberation-pin controls in the cockpit form (API-only);
  no template deletion semantics; no ensemble/analysis launch from
  the directions view (the Charts launchers from Sprint 12 already
  cover that).
- No scheduler or worker involvement: generation is an explicit
  user action, consistent with the Sprint 9 automation boundary.

## 3. Integration points

- **Reads only.** The narratives package reads run fragments
  (MECE/ensemble/robustness/gates/deliberations), the
  `calibration_fits` table, and the `strategy_loops` table. It
  writes only its own two tables. No behavior change to the
  simulation engine, firewall, robustness, distributions, skills,
  calibration, or living-loop packages; no existing endpoint,
  model, or migration was modified (only additive wiring in
  `_deps.py` / `routes/__init__.py` and additive record classes in
  `domain/models.py`).
- **Reuse, not duplication.** Canonical JSON + SHA-256 from Sprint
  3, `format_number` from Sprint 6, `SkillLLMPort` /
  `OpenAIServiceSkillPort` / `SkillContractError` from Sprint 6,
  `select_registration` from Sprint 11, the Sprint 9/11 route
  error-mapping pattern, the Sprint 6 scripted-port test pattern.
- **Frontend.** New route + components only; `CockpitNav` gained
  one tab; `engine.ts` / `engineTypes.ts` gained the narratives
  client + mirrors; no existing component was modified except the
  nav tab list and the route table.
- **Migration chain.** `0035_decision_narratives` revises
  `0034_loop_evaluations`; head is 0035 after upgrade.

## 4. Verification

- Full backend suite: **1231 passed / 0 failed** in 376.35s
  (baseline 1192 + 26 new composer/polish unit tests + 13 new API
  tests). Log: `docs/sprint13/test-full.log` (force-added past the
  `*.log` ignore, per precedent).
- Frontend: **206 passed** (baseline 195 + 11 new: 5 page + 6
  view/badge), `npm run lint` clean, `npm run build` passes.
- `mypy src/planagent/`: clean, 203 source files, no issues.
- `ruff check` on new/changed files: clean except the pre-approved
  B008 `Depends()` pattern (4 occurrences in
  `api/routes/narratives.py`, same as every other route module).
  `ruff format` clean on new/changed files. Two findings in files
  touched only for wiring (`_deps.py`: I001 + UP017;
  `routes/__init__.py`: I001) were verified byte-identical at HEAD
  via `git show HEAD:` — pre-existing, left untouched.
- Migration: scratch SQLite upgrade 0034 → 0035 (both tables and
  all columns present), downgrade → 0034 (both tables gone),
  re-upgrade → head `0035_decision_narratives`.
- Sprint 0 smoke re-run: **PASS** (health → ingest → 4-tick
  simulation → decision trace → workbench → options); the
  refreshed `smoke-evidence.json` was reverted per precedent.

### Behavior evidence (all asserted test values, with test names)

Composer — ranking, arms, byte identity
(`tests/unit/test_narratives_composer.py`):

- `test_compose_ranks_by_p50_descending_ties_broken_by_name`:
  P50s 30/10/10 compose in order `["Alpha", "Mike", "Zulu"]` with
  ranks `[1, 2, 3]` — the 10/10 tie breaks by name ascending.
- `test_compose_uses_chosen_arm_distribution`: the `strategy` arm
  reads p50 20.0, p10 15.0, p90 25.0, p_loss 0.1.
- `test_compose_same_inputs_byte_identical_body`: canonical JSON
  of the body, content hash, and markdown are all equal across two
  compositions of the same inputs.
- `test_compose_different_seed_changes_content_hash`: seed 42 vs
  43 yields different content hashes.

Composer — provenance (`tests/unit/test_narratives_composer.py`):

- `test_compose_template_sections_when_no_deliberations_exist`:
  pre-mortem and first-step sections carry `template` provenance
  with null content; the notes name the strategy-team /
  advisory-board endpoints; signals are empty with a note; the
  drivers note names the tornado endpoint.
- `test_compose_quotes_premortem_and_contract_with_deliberation_ids`:
  pre-mortem quotes the failure narrative ("The launch failed in
  month three."), failure mode "Support overload", fatal flag "No
  fallback vendor", deliberation id `delib-strategy-1`, template
  `gambit.premortem`; first step quotes next action "Call the two
  pilot clients", cheapest test "Concierge pilot", conditions
  `["Pilot with two clients"]`.
- `test_compose_deliberation_falls_back_to_anchor_run`: a source
  run with no deliberations still quotes the anchor run's records.
- `test_compose_pinned_deliberation_restricts_quotes`: pinning the
  advisory record yields a deliberated first step and a template
  pre-mortem.
- `test_compose_unknown_pinned_deliberation_refuses` /
  `test_compose_corrupt_premortem_refuses`: codes
  `narrative_deliberation_not_found` /
  `narrative_corrupt_deliberation` (the corrupt fixture has an
  empty `failure_modes` list, violating the contract's min_length).

Composer — drivers, signals, traces
(`tests/unit/test_narratives_composer.py`):

- `test_compose_drivers_capped_at_five_in_stored_order`: 7 tornado
  rows compose to `["v0", "v1", "v2", "v3", "v4"]`, first swing 7.0.
- `test_compose_signals_union_in_fixed_kind_order`: signal kinds
  are exactly `[decision_gate, threshold_search, loop_trigger,
  advisory_contract, advisory_contract, wargame_playbook]`; the
  gate signal carries observed 10.0, passed true, evaluation id
  `eval-1`.
- `test_compose_gate_registration_without_evaluation_is_honest`:
  passed/observed are null and the text says "not yet evaluated".
- `test_compose_unreachable_threshold_search_is_honest`: the text
  says "No threshold found" and threshold is null.
- `test_compose_mece_trace_copies_scope_tags`: branches
  `["revenue", "cost"]` with scope `["b"]` for revenue; header
  context reports branch_count 3, is_mece true.
- `test_compose_unknown_mece_branch_refuses_naming_valid_branches`
  / `test_compose_branches_without_tree_refuses`: codes
  `narrative_unknown_mece_branch` (message names "Nope" and "cost")
  / `narrative_mece_branches_without_tree`.
- `test_compose_expected_shortfall_and_bootstrap_for_chosen_arm`:
  the strategy arm's ES value is -1.0, trial hash `sha256:es`, and
  the bootstrap p50 estimate is 20.0.
- `test_compose_topic_prefers_request_then_tree_then_run_id`:
  request topic wins, then the tree topic ("AI customer-service
  line"), then `run {anchor_run_id}`; `topic_source` recorded each
  time.
- `test_render_marks_provenance_and_formats_numbers`: the markdown
  contains `[computed]` and `[deliberated]` and the line "P10 0 /
  P50 10 / P90 20".

Request model (`tests/unit/test_narratives_composer.py`):

- `test_generate_request_rejects_duplicate_direction_names` /
  `test_generate_request_rejects_empty_directions` /
  `test_generate_request_rejects_more_than_four_directions`:
  Pydantic refuses duplicate names, 0 directions, and 5 directions.

Polish hook, scripted port (`tests/unit/test_narratives_composer.py`):

- `test_polish_returns_output_and_model`: output text and model
  `"fixture"`; the system prompt contains "Do not compute new
  numbers"; the script is exhausted.
- `test_polish_unavailable_port_raises`: `SkillLLMUnavailable`
  with zero port calls.
- `test_polish_contract_failure_raises`: `SkillContractError` on a
  wrong-key payload.

API (`tests/test_narratives_api.py`, real runs + ensembles through
the HTTP layer):

- `test_generate_narrative_success`: 201, version 1, both hashes
  `sha256:`-prefixed, polish null; MECE topic "Should we launch?",
  is_mece true; distribution ensemble id matches the stored
  ensemble, metric `cash`, trials 5; trace branch "Demand" with
  scope `["demand"]`; pre-mortem/first-step template; markdown
  contains "Go all in" and `[template]`.
- `test_generate_narrative_byte_identical_across_regenerations`:
  versions 1 and 2, equal content/input hashes, equal bodies,
  different ids.
- `test_generate_refuses_without_ensemble_and_writes_nothing`:
  400 `narrative_requires_ensemble`, message contains the run's
  monte-carlo URL; the list endpoint returns zero narratives.
- `test_generate_refuses_unknown_source_run` /
  `test_generate_refuses_noncompleted_anchor` /
  `test_generate_unknown_run_404`: codes
  `narrative_unknown_source_run` /
  `narrative_requires_completed_run` / HTTP 404.
- `test_generate_refuses_unknown_mece_branch`: 400
  `narrative_unknown_mece_branch`, message names "Nope" and
  "Demand".
- `test_generate_with_loop_context_and_mismatch_refusal`: loop
  context trigger_count 1, the only signal kind is `loop_trigger`,
  text contains "cash-floor"; a loop baselined on another run
  refuses with `narrative_loop_baseline_mismatch`.
- `test_list_and_get_narratives`: versions listed `[2, 1]`; get
  returns version 1 with polish null; wrong-run and missing ids
  are 404.
- `test_polish_success_stores_alongside_artifact`: 201, polished
  text, template `narrative.polish` v1, model `"fixture"`; the
  fetched narrative shows the polish while content_hash and body
  are unchanged; the script is exhausted.
- `test_polish_unavailable_returns_503_and_writes_nothing` /
  `test_polish_contract_failure_returns_502_and_writes_nothing`:
  503 `narrative_polish_unavailable` / 502
  `narrative_polish_contract_failed`, polish stays null.
- `test_polish_unknown_narrative_404`: 404.

Cockpit (`Directions.test.tsx`, `DirectionViews.test.tsx`, mocked
fetch):

- Page: empty state until a run is picked, then the form with MECE
  checkboxes; generate posts exactly `{topic: null, directions:
  [{name, source_run_id, arm, mece_branches: ["Demand"],
  deliberation_id: null}], loop_id: null}` and shows the reading
  view; a 400 refusal shows its code and message and renders no
  direction; version buttons order `[v2, v1]` and switching changes
  the header; a 503 polish shows the honest notice while the
  deterministic markdown stays visible.
- Views: distribution line "P10 2 / P50 10 / P90 18", "亏损概率
  20.0%", ES -3, bootstrap interval, driver line, gate + loop
  signals, quoted pre-mortem with fatal flag and deliberation id,
  template first-step note, MECE trace; badge labels 计算 / 商议引用 /
  模板措辞； polished text labeled LLM-generated with model
  `fixture-model`; polish error + disabled button while polishing.

## 5. How to run / verify

```bash
# Backend unit + API tests for this sprint
env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest tests/unit/test_narratives_composer.py tests/test_narratives_api.py -q

# Full backend suite (log at docs/sprint13/test-full.log)
env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest -q

# Type + lint (new/changed files)
.venv/bin/python -m mypy src/planagent/
.venv/bin/python -m ruff check src/planagent/services/narratives/ tests/unit/test_narratives_composer.py tests/test_narratives_api.py src/planagent/api/routes/narratives.py
.venv/bin/python -m ruff format --check src/planagent/services/narratives/ tests/unit/test_narratives_composer.py tests/test_narratives_api.py

# Migration check on scratch SQLite
PLANAGENT_DATABASE_URL="sqlite:////tmp/mig35/check.db" .venv/bin/python -m alembic upgrade head
PLANAGENT_DATABASE_URL="sqlite:////tmp/mig35/check.db" .venv/bin/python -m alembic downgrade 0034_loop_evaluations
PLANAGENT_DATABASE_URL="sqlite:////tmp/mig35/check.db" .venv/bin/python -m alembic upgrade head

# Frontend
cd frontend-v2 && npm test -- --run && npm run lint && npm run build

# Smoke (Sprint 0, revert the evidence file afterward)
env -u NO_PROXY -u no_proxy .venv/bin/python docs/sprint0/smoke_e2e.py
git checkout -- docs/sprint0/smoke-evidence.json
```

Generate a narrative against a running backend:

```bash
# 1. A completed run with variables + ensemble (see SPRINT3.md), then:
curl -X POST localhost:8000/runs/<run_id>/narratives -H 'Content-Type: application/json' -d '{
  "topic": "Launch decision",
  "directions": [{"name": "Go all in", "source_run_id": "<run_id>", "arm": "baseline", "mece_branches": ["Demand"]}]
}'
curl localhost:8000/runs/<run_id>/narratives
curl -X POST localhost:8000/runs/<run_id>/narratives/<narrative_id>/polish   # 503 without an LLM key
```

## 6. Known limits

- **Live LLM polish quality is unverified.** All polish tests use
  a scripted port. The prompt forbids changing numbers and marks,
  but no real output has been seen; a live run could still
  paraphrase a number or drop a mark, and nothing in the polish
  path re-validates the polished text against the artifact. A
  verification pass (re-checking numbers/marks in polished output)
  is a natural follow-up if polish is used in production.
- **Calibration context is header-only and column-level.** Fits
  are listed, not applied: the narrative does not adjust
  distributions by calibration, and the intercept from Sprint 10
  is recorded but never applied anywhere in the engine.
- **Loop triggers are quoted, not evaluated.** The narrative shows
  registered trigger definitions; whether they currently fire is
  the monitoring worker's job (Sprint 11), not the composer's.
- **Formulas run once per run; tornado is one-at-a-time; threshold
  search assumes monotonicity** (Sprint 4 limits, inherited — the
  composer quotes stored results as-is and cannot improve them).
- **Cockpit form scope.** Loop selection and deliberation pinning
  are API-only; launch parameters beyond the form (e.g. choosing a
  different arm per direction is supported; choosing per-direction
  loop context is not — the loop is narrative-level).
- **Version assignment is max+1 in one transaction.** Concurrent
  generations for the same run could theoretically collide on
  version; the dev path is single-writer SQLite and no unique
  constraint guards it. Worth a constraint if concurrent writers
  ever exist.
- **Corrupt-fragment codes are coarse.** `narrative_corrupt_fragment`
  covers MECE/ensemble/robustness/gates/deliberation-list/loop
  fragment failures with the fragment named in the message; only
  deliberation-stage contract failures get their own code.
- **No deletion.** Narratives and polishes are append-only; there
  is no delete endpoint and no cockpit delete control.

## 7. Cockpit check

The `/cockpit/directions` view was verified with mocked-fetch
tests only (11 new frontend tests: 5 page + 6 view/badge). Rendered
against a live backend: NOT verified (see §9). The page follows
the Sprint 7/8/9 conventions: typed clients, type mirrors,
`useApi`, `RunPicker`, `Card`/`EmptyState`/`ErrorBanner`/
`LoadingSpinner`, Chinese chrome, honest empty states.

## 8. Deferred (out of scope, recorded deliberately)

- Direction auto-derivation (no stored source; would require a
  direction model of its own — a design decision for Ho, not an
  implementation gap to paper over).
- Polished-text verification (re-checking numbers/marks after a
  polish pass).
- Loop/deliberation-pin controls in the cockpit form.
- Narrative deletion / retention policy.
- Backtest of narrative quality against historical decisions.

## 9. Commits on this branch

- `60d963b` — deterministic composer, renderer, polish hook + unit tests
- `b043b2b` — persistence, service, endpoints (migration 0035)
- `fd19407` — narrative API tests
- `e4c46f0` — cockpit directions view
- (this commit) — Sprint 13 report, backlog update, verification log

## 10. What was NOT verified

- Docker Compose stack (no container runtime on this VM).
- Live-LLM deliberation/polish quality (provider blocks direct
  SDK access; see `~/workspace/delib-run/real-deliberation-2026-11-15/REPORT.md`).
  No LLM call was attempted in this sprint.
- Real backend integration and cockpit views rendered against a
  live backend.
- Worker behavior under Postgres/Redis.
- Concurrent narrative generation (see §6 version-assignment note).

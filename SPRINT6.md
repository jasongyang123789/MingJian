# Sprint 6 — Skill grafts (PRD delta D9)

Branch: `strategy-engine/sprint6-skills`, from
`strategy-engine/sprint5-calibration` (`98efa3b`). Nothing pushed.

This sprint grafts the code-verified strategy skills from the research
record onto the engine's deliberation layer as versioned prompt
templates + pipeline stages: the McKinsey strategy-team pipeline, the
5-persona advisory board, the gambit pre-mortem (as a fourth verifier
lens), and the flingjie MECE authoring workflow (as a proposal aid
only). Stages consume the engine's own structured artifacts — MECE
trees, variable sets, ensemble summaries, robustness outputs, Sprint 5
calibration deltas — as context to argue about, without touching the
numeric core. Every stage output is validated against a Pydantic
contract (the OMEN artifact-chain lesson); malformed output is a
structured failure, never a silent pass-through. No new LLM client
code was written: stages call the existing `OpenAIService` through a
narrow port. No LLM call was made anywhere in this sprint — all 122
new tests run against a scripted port serving recorded fixtures.

References (read-only, code-verified in the research record):

- mckinsey-strategy-team (MIT, Joost de Leij): `SKILL.md` pipeline
  (intake → classify → fan-out → generate-and-filter → synthesis →
  adversarial verification; deep mode adds tournament +
  loop-until-done) + 21 McKinsey framework reference docs. Its
  war-gaming reference is a prompt workflow (base/adverse/aggressive
  scenarios + impact/likelihood tables), not an engine — it grafts as
  a verifier lens, not as simulation.
- 5-persona-advisory-board (MIT): CRIT intake + five lenses + scoring
  + risk veto + decision contract, pure prompts.
- gambit (MIT, skyf0xx): 46 skills, mostly brand. Only `premortem`
  grafted (see §2 for what was skipped and why).
- flingjie/strategic-issue-tree (NO license declared): the only MECE
  skill in all 8,660 repos, prompts/YAML only. Workflow structure
  adapted with original wording; no source text copied. Its prompts
  are a decomposition-AUTHORING reference only — they must never
  replace the Sprint 1 code validator; prompts propose, the validator
  disposes.
- Existing machinery built on, not duplicated: the `debate/` service
  and `OpenAIService.generate_json_for_target` (see §2 for the graft
  boundary), the Sprint 1 MECE validator, the Sprint 1–5 fragment
  storage discipline, and the Sprint 3 canonical-JSON/seed machinery
  (read-only here).

## 1. What was built

### Template library (`services/skills/templates.py`, new)

- 17 versioned prompt templates (version `"1"`), each carrying
  provenance: source repo + file + license note. Rendering is pure
  and byte-stable: `render_template` substitutes declared `{slot}`
  placeholders (`str.format` escapes for literal braces), raises
  naming every missing slot, and the registry self-validates at
  import (declared slots == used placeholders, exactly).
- Templates carry no numeric computation: every template instructs
  "Return valid JSON only. Do not compute new numbers" and numbers
  arrive only through the `context` slot. Templates are English
  (matching the sources) with an `output_language` slot (default
  `English`).
- Shared glossaries: `OPTION_MANDATES` (bull/lean/contrarian),
  `LENS_BRIEFS` + `LENS_QUESTIONS` (five advisory lenses, with the
  "interpretive frameworks, not the named figures" guardrail in the
  lens template), `DECISION_CRITERIA` (attractiveness, feasibility,
  risk, economics, strategic fit).

Template inventory (id → source file):

| Template | Source |
| --- | --- |
| `mckinsey.intake_classify` | SKILL.md Steps 0–1 |
| `mckinsey.diagnose` | 01 situation-assessment |
| `mckinsey.market_map` | 02 market-mapping + competitive-intel |
| `mckinsey.option_generate` | SKILL.md Step 5 + 03 strategic-options |
| `mckinsey.filter_shortlist` | SKILL.md Step 5 (lead filter) |
| `mckinsey.synthesize` | SKILL.md Step 6 + 06 narrative-builder |
| `mckinsey.verify_assumptions` | 01 assumption-audit |
| `mckinsey.verify_wargame` | 05 war-gaming |
| `mckinsey.verify_execution` | 04 operating-model-design + 05 risk-and-mitigation |
| `mckinsey.tournament_judge` | SKILL.md Step 7 (deep mode) |
| `advisory.crit_intake` | SKILL.md (CRIT Intake) |
| `advisory.lens_position` | SKILL.md (Five Lenses + Round 1) |
| `advisory.lens_revision` | SKILL.md (Round 3) |
| `advisory.forced_debate` | SKILL.md (Round 2 + anti-groupthink) |
| `advisory.chair_synthesis` | SKILL.md (Decision Logic + Contract) |
| `gambit.premortem` | skills/premortem/SKILL.md |
| `mece.propose_tree` | SKILL.md Phases 1–2 + templates/issue_tree.md |

### Output contracts (`services/skills/contracts.py`, new)

- One Pydantic contract per template (`CONTRACT_FOR_TEMPLATE`),
  `extra="forbid"` everywhere, scores bounded 0–10, list lengths
  bounded where the template promises them (e.g. options 1–6,
  shortlist 1–3, CRIT questions ≤ 3). Contract version `skills-v1`,
  recorded with every stored stage output.
- `parse_stage_output` raises `SkillContractError` (template id +
  contract version + per-field details) on any violation, including
  a non-object root. The MECE proposal contract reuses
  `DecompositionTree` itself, so a proposal that cannot even parse as
  a tree is a contract failure, distinct from a well-formed tree
  that fails validation.

### Context builders (`services/skills/context.py`, new, pure)

- Deterministic formatters over stored fragments only: MECE tree +
  validation verdict/issues, variable template snapshot + bindings
  (distributions, evidence refs, scope tags, formulas, internal
  situation), ensemble summary (P10/P50/P90 + loss probability +
  paired deltas), robustness outputs (expected shortfall, top-5
  tornado rows, threshold search incl. honest unreachable, bootstrap
  intervals, gate evaluations), Sprint 5 calibration deltas
  (fitted-vs-prior thresholds and rule weights, with the association
  note), and the hindsight-firewall cutoff.
- `format_number`: integers without decimals, floats to 6 places
  with trailing zeros stripped. Absent fragments render as `""` and
  are omitted; malformed lines are skipped, never fatal.
- `render_run_context` assembles sections in a fixed order. It is
  the only numeric input a skill stage receives.

### Orchestration (`services/skills/orchestration.py`, new)

- `SkillLLMPort` protocol: `is_available()` +
  `generate_json(template_id, system_prompt, user_content,
  max_tokens)`. `OpenAIServiceSkillPort` wraps the existing
  `OpenAIService` on target `"primary"` (the only target the
  deliberation layer can assume configured; `debate_*` targets
  return `(None, None)` when their keys are absent). No new LLM
  client code.
- `run_stage`: render → availability check → call → contract
  validation → `StageRecord` (stage label, template id + version,
  contract version, validated output, model name). Unavailable LLM
  raises `SkillLLMUnavailable`; empty/unparseable output raises
  `SkillContractError`. Nothing is fabricated: unlike the debate
  service's text fallback, a skill stage with no LLM fails loudly.
- Tally and weighting rules live in CODE, not prompts:
  `tally_panel_flags` (a flag is `must_address` when ≥ 2 DISTINCT
  lenses flag the same normalized statement as fatal),
  `assemble_weighted_direction` (weighted mean per option, ties by
  name, missing weights default 2),
  `detect_unanimity` + `unanimity_note` (all lenses top-rank the same
  option → steelman instruction injected into the forced debate).
- `run_strategy_team`: intake → diagnose + market_map → option
  generation per mandate (bull, lean; + contrarian in deep) →
  filter/shortlist → synthesize → verifier panel (assumptions,
  war-game, execution, + premortem) → tally. Deep mode adds the
  pairwise tournament (win counts in code, ties by shortlist order)
  and the loop-until-done war-game (extra rounds until 2 consecutive
  rounds add no NEW fatal flag, capped at 3 extra rounds). The result
  records `synthesis_recommendation_in_shortlist` as an observed
  boolean, not a refusal.
- `run_advisory_board`: CRIT intake → Round 1 (five lenses, fixed
  order) → equal-weight direction → forced debate (standard only) →
  Round 3 revisions (standard only) → chair synthesis → decision
  contract + final weighted direction (Round 3 scores × chair
  relevance weights). Quick mode skips debate/revisions. Vetoes are
  collected from Round 1 positions;
  `has_unmitigated_veto` = a veto exists AND the verdict is `choose`
  (a `validate_first`/`reject` verdict is the mitigation path; the
  veto stays recorded either way).

### MECE authoring aid (`services/skills/mece_authoring.py`, new)

- `propose_decomposition` renders `mece.propose_tree` (default
  dimensions adapted from the flingjie four-dimension checklist,
  overridable; optional existing tree for revision), parses the
  output as a `DecompositionTree`, and runs the UNCHANGED Sprint 1
  validator. Returns proposal + validation verdict + stage
  provenance. No persistence: attaching a proposal to a run goes
  through the existing creation gate, which refuses a failing tree
  before any row is written (proven by test, §4).

### Service + API

- `services/skills/service.py` (new): `SkillDeliberationService`
  requires a COMPLETED run (`skills_requires_completed_run`, mirroring
  the Monte Carlo gate), builds context from the run's fragments +
  the 5 most recent calibration fits for the run's domain + caller
  context lines, runs the pipeline, and appends a
  `SkillDeliberationRecord` to the run summary's append-only
  `skill_deliberations` list (fragment discipline, NO migration). A
  failed deliberation writes nothing. `propose_mece_tree` needs no
  run and persists nothing.
- `api/routes/skills.py` (new, 4 endpoints): `POST
  /runs/{run_id}/skills/strategy-team` (201), `POST
  /runs/{run_id}/skills/advisory-board` (201), `GET
  /runs/{run_id}/skills/deliberations`, `POST /mece/propose` (200,
  verdict in payload, following `/mece/validate`). Error mapping is
  honest about the LLM boundary: 503 `skill_llm_unavailable`, 502
  `skill_contract_failed` (with template id + contract version),
  400 for client errors, 404 for missing runs.
- Wiring: `get_skill_service` + `"skill_service"` in
  `_CACHED_SERVICE_ATTRS`/`_cache_business_services`
  (`api/routes/_deps.py`); router registered in
  `api/routes/__init__.py` (bare + `/api` prefixes, automatic).

## 2. Design decisions

### Graft boundary: shared adapter + audit patterns, not the debate workflow

The graft shares the LLM adapter interface (`generate_json_for_target`)
and the persistence/audit patterns (fragment storage, Pydantic
contracts, versioned prompts) with the existing debate service, but
does NOT put skill stages inside `DebateWorkflow`'s 4-round round plan:
`DebatePositionPayload` (SUPPORT/OPPOSE/CONDITIONAL + arguments) is a
different contract from every skill stage, and forcing skill outputs
through it would pollute both systems. The debate workflow is
untouched. Skill pipelines are their own orchestration over the same
adapter — the same relationship the simulation service has to the
debate service.

### Agent-teams adaptation (recorded, not hidden)

The McKinsey skill requires Claude Code agent teams
(`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`) with TeamCreate/Agent
primitives and parallel waves. That runtime feature does not exist
here and cannot transfer 1:1. Adaptation: "waves" run as sequential
stage calls over a shared context store — each stage's validated
output is serialized (deterministic JSON) into the next stage's
inputs. The wave STRUCTURE (what the original runs in parallel, and
in what order results combine) is preserved as stage ordering +
shared inputs, not as concurrency. The cost is latency (sequential
LLM calls), not fidelity of the argument structure. No agent-team
semantics (teammate memory, delegation, shutdown) are emulated.

### What was skipped, and why

- strategic-partner: a Claude plugin of hooks/MCP servers driving a
  development workflow (sessions, plans, verification gates). It is
  a process skill for building software, not a strategy deliberation
  skill; nothing in it maps to a deliberation stage. Only its
  "deciding and building are separate" principle is worth recording
  — and this sprint already embodies it (deliberation reads stored
  artifacts; it never edits engine state).
- gambit decide/options: overlap the McKinsey filter/synthesis and
  advisory contract stages; grafting them would duplicate the same
  decisions under different prompt wording. gambit premortem IS
  grafted: prospective hindsight is a distinct lens the McKinsey
  panel lacks.
- Advisory-board "full" mode: its deep-evidence-research step has no
  engine equivalent (no research worker is wired to skill stages);
  only `quick` + `standard` are supported. The request model rejects
  anything else.
- McKinsey loop-until-done has no natural cap in the original; here
  it is capped at 3 extra rounds with a recorded stop reason, so a
  stubborn model cannot loop the API call budget away.

### Prompt proposes, validator disposes

The flingjie prompts are the weakest-license, highest-risk input
(no license declared): only the workflow structure was adapted
(Phase 1 restate constraints, Phase 2 issue-tree checklist, four
suggested dimensions), with original wording throughout, and the
provenance note says so. The template instructs the model that a
code validator checks the tree afterwards — and the code does: the
Sprint 1 validator is the only arbiter, unchanged.

### Deliberation is read-only over engine artifacts

Stages receive rendered text, never live objects; the service writes
only the `skill_deliberations` summary key. A deliberation cannot
change a decomposition, a variable binding, a fitted threshold, or
any simulation result. This is what makes the graft safe to run
against completed runs without re-verifying the numeric core.

## 3. Integration points

- LLM: `OpenAIServiceSkillPort` → `OpenAIService.is_configured("primary")`
  + `generate_json_for_target(target="primary", ...)`. Temperature 0.3
  and `json_object` response format come from the existing adapter.
- MECE: `DecompositionTree` (proposal contract) +
  `validate_decomposition` (verdict) from `services/mece/`; the run
  creation gate in `services/simulation/` is unchanged.
- Fragments read: `configuration.mece`, `configuration.variables`,
  `configuration.hindsight_firewall`, `summary.monte_carlo`,
  `summary.robustness`, `summary.decision_gates`,
  `CalibrationFitRecord` rows (domain-scoped, newest 5).
- Fragment written: `summary.skill_deliberations` (append-only list).
- Service wiring: `get_skill_service` in `api/routes/_deps.py`
  (pre-seedable on `app.state` for tests, same pattern as the other
  services).

## 4. Verification

Full suite: **963 → 1085 passed, 0 failures** (122 new), same command
as Sprints 0–5 with the `NO_PROXY` workaround
(`env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest tests/ -q`).
Sprint 0 smoke re-run on this branch: **PASS**. `mypy` clean on the
new package + routes. No existing test was modified.

New tests (all pass with NO live LLM call — the scripted port serves
32 recorded fixture outputs in `tests/fixtures/skill_outputs/`):

- `tests/unit/test_skill_templates.py` (26): registry pinned at 17
  templates, provenance on every template, slot validation,
  byte-stable rendering for every template, missing-slot errors,
  JSON-only/no-new-numbers instruction on every template.
- `tests/unit/test_skill_contracts.py` (43): every recorded fixture
  parses against its contract; malformed outputs (missing field,
  wrong type, out-of-range score, extra key, empty option set, bad
  verdict, too many CRIT questions, non-object root) all raise
  `SkillContractError`.
- `tests/unit/test_skill_context.py` (12): golden-string rendering
  for every block type, absent-fragment omission, deterministic
  ordering, calibration deltas, unreachable threshold honesty.
- `tests/unit/test_skill_orchestration.py` (23): tally rules (≥2
  distinct lenses, normalization, same-lens-twice), weighted
  direction arithmetic (hand-computed), unanimity detection,
  stage execution (provenance, unavailable, malformed, empty),
  OpenAI port mapping, full strategy-team runs (standard 11 stages,
  deep 17 stages with tournament + loop), full advisory runs
  (standard 13 stages, quick 7 stages, unanimity steelman note,
  veto/unmitigated semantics).
- `tests/unit/test_mece_authoring.py` (6): valid proposal PASSes,
  invalid proposal FAILs with the overlap issue, malformed tree is
  a contract error, dimensions/existing-tree reach the prompt.
- `tests/test_skills_api.py` (12): pipeline endpoints persist +
  list, context reaches prompts, 404/400 gates, 503/502 boundary
  codes with nothing written, MECE proposal endpoints, and the gate
  test below.

### Behavior evidence (fixture run, strategy team, standard mode)

Recorded fixtures drive 11 stages: intake → diagnose → market_map →
bull + lean generators → shortlist (Phased rollout / Full launch /
Partner-led) → synthesis (recommends Phased rollout, in-shortlist) →
panel (assumptions, war-game, execution, premortem). The code tally
finds two must-address flags, each from two independent lenses:
"Demand growth assumption is untested" (assumptions + war-game) and
"Delivery capacity cannot cover launch volume" (execution +
premortem). Deep mode adds the tournament (Phased rollout wins 2–1–0)
and the war-game loop, which stops after 2 quiet rounds
(`two_quiet_rounds`, 2 extra rounds, cap not hit).

### Behavior evidence (fixture run, advisory board, standard mode)

13 stages: CRIT intake → 5 lens positions → forced debate → 5
revisions → chair synthesis. Round 1 equal-weight direction: Phased
rollout 7.2, Partner-led 6.4, Full launch 5.6. Final direction (Round
3 × chair weights): Phased rollout 82/11 ≈ 7.45, top-ranked. The
risk_capital lens raises a runway veto; the chair's verdict is
`validate_first`, so `has_unmitigated_veto` is false and the veto
stays recorded in the contract with its mitigation. A variant run
with verdict `choose` flips `has_unmitigated_veto` to true.

### Behavior evidence (MECE proposal refused by the validator)

`POST /mece/propose` with the invalid fixture returns 200 with
`is_mece: false`, issue kind `overlap`, tags `["capability"]`.
Attaching that exact proposal to `POST /simulation/runs` returns 400
`mece_validation_failed`, and `GET /simulation/runs` returns `[]` —
no row was written. The valid fixture attaches and completes.

### Correction recorded during this sprint

The first version of `render_mece_block` assumed a `verdict` string
on the stored validation fragment; the real `MeceValidationResult`
carries `is_mece` + check records (`node`/`check`/`status`/`detail`)
+ issues. Fixed in commit `bb04d69` before the tests were written
against the corrected shape; the context tests pin the real shape.

## 5. How to run / verify

```bash
env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest tests/unit/test_skill_templates.py tests/unit/test_skill_contracts.py tests/unit/test_skill_context.py tests/unit/test_skill_orchestration.py tests/unit/test_mece_authoring.py tests/test_skills_api.py -q
env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest tests/ -q   # full suite
env -u NO_PROXY -u no_proxy .venv/bin/python docs/sprint0/smoke_e2e.py
```

With a configured LLM key, a live run is:
`POST /runs/{completed_run_id}/skills/strategy-team` with
`{"topic": "...", "mode": "standard"}`. Without a key the same call
returns 503 `skill_llm_unavailable` — by design, not a bug.

## 6. Known limits

- **Live deliberation quality is UNVERIFIED.** No LLM key exists on
  this VM, so no real stage output has ever been seen: prompt quality,
  contract-conformance rates on live models, panel usefulness, and
  the loop-until-done behavior against a real model are all unknown
  until a key exists. The fixtures prove the machinery (rendering,
  validation, tally, persistence), not the deliberation quality.
  This is the sprint's central open item, stated plainly.
- Stages run sequentially (see the agent-teams adaptation, §2): a
  deep strategy-team run makes up to 17 LLM calls in sequence.
  Latency is unmeasured without a key.
- The `primary` LLM target is the only one used; debate_* targets
  are not consulted. Model selection, temperature (0.3), and token
  limits come from the existing adapter and settings.
- `synthesis_recommendation_in_shortlist` is observed, not enforced:
  a synthesis that recommends an off-shortlist option is recorded,
  not refused. Refusing would need a product decision about whether
  the panel or the gate owns that inconsistency.
- Quick-mode advisory runs have no forced debate; the chair sees
  explicit "Not run in this mode" markers. The chair's lens weights
  are LLM output, validated only for shape (1–3 per lens); unknown
  lens keys are ignored, missing lenses default to weight 2.
- Context blocks are text renders of stored fragments: very large
  trees or variable sets are rendered in full (no truncation or
  summarization). Tornado rendering caps at the top 5 rows;
  calibration context caps at the 5 newest fits.
- The weighted direction is a summary of lens scores, never an
  answer; the chair template says so, and the code never acts on
  it. `has_unmitigated_veto` uses the verdict-based definition in
  §1 — it does not check whether the chair's conditions actually
  address the veto's failure path.
- No queueing: deliberations run inline in the request. Long deep
  runs may exceed client timeouts; no timeout/retry policy was added
  (the adapter's own timeout applies per call).
- The MECE authoring aid proposes in one shot; there is no
  revise-until-valid loop. A failing proposal is returned with its
  FAIL verdict for the caller to fix or re-propose.

## 7. Cockpit-UI entry points (next sprint)

The backend for the cockpit UI is complete for the deliberation
surfaces; no new backend work is needed for these views:

- **Deliberation launcher + results**: `POST /runs/{id}/skills/strategy-team`
  and `/advisory-board` (request: topic/decision + mode + options +
  context lines), `GET /runs/{id}/skills/deliberations` (append-only
  history, each record carrying full stage provenance). Render the
  strategy-team result as: shortlist table → synthesis (Pyramid) →
  panel tally with `must_address` flags highlighted → tournament
  bracket (deep) → war-game playbook. Render the advisory result as:
  lens score table → weighted direction → debate disagreements →
  decision contract card (verdict, conditions, go/kill criteria,
  owner, deadline, review date) with vetoes as blocking banners when
  `has_unmitigated_veto` is true.
- **MECE authoring**: `POST /mece/propose` (proposal + verdict in
  one round trip) feeding the existing `POST /mece/validate` and run
  creation gate. The UI should show the proposal's validation issues
  inline and offer re-propose with the failing tree as
  `existing_tree` (the revision path is built; no loop is).
- **Template provenance view**: the registry is importable
  (`list_templates()`); a read-only endpoint was deliberately NOT
  added — the UI can ship the inventory from this report, or a later
  sprint can add `GET /skills/templates` if the cockpit needs it
  live. Template versions in stage records let the UI show exactly
  which prompt version produced each output.
- **Unverified-until-key banner**: the cockpit should surface the
  503 state honestly ("no LLM configured") rather than hiding the
  deliberation surfaces; the API already distinguishes 503
  (unconfigured) from 502 (malformed output).

## 8. Deferred (out of scope, recorded deliberately)

- Cockpit UI (the other Sprint 6 direction; this sprint's §7 is its
  entry point).
- Decision-direction narrative output (pre-mortems as prose, 48-hour
  first steps, LLM narrative/red-team layer): still deferred; needs
  an LLM key + presentation design. The premortem lens output is
  structured data, not the narrative layer.
- Queued ensembles; any change to the numeric core (simulation,
  robustness, calibration math untouched — verified by diff: this
  branch adds files and 15 lines of API wiring only).
- Advisory-board "full" mode; McKinsey parallel waves (see §2);
  revise-until-valid MECE loop; deliberation queueing/timeouts.

## 9. Commits on this branch

- `c3024f6` — versioned skill prompt template library
- `4308f57` — Pydantic output contracts for skill stages
- `38209e1` — engine-artifact context builders
- `9e2c0e9` — skill stage orchestration
- `1684fc1` — MECE authoring aid + skill deliberation service
- `0e9f8ed` — skill deliberation endpoints
- `bb04d69` — fix MECE validation fragment field names in context builder
- `0c5dd2e` — skill graft tests (122 new, no live LLM)
- (this report + backlog update)

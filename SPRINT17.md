# Sprint 17 — Seminar chair synthesis: clustering, metrics, versioned reports

Branch: `strategy-engine/sprint17-seminar-synthesis`, from S16 tip
`4dc21eb`. Design authority: the seminar-mechanism design doc (§16
S17 row; §7 clustering, §8 synthesis + deterministic composer, §9
schema, §12 endpoints). Backend only; zero live LLM calls
(fixture/fake-port driven, same `ScriptedSkillPort` pattern as
S16); no scheduler/worker/background progression (Sprint 9
boundary — synthesis only on explicit `POST /synthesize`). No new
migration: `seminar_reports` already exists from S16 migration
0038. The 17-template Sprint 6 registry pin (v2) is untouched; the
two new templates live in the separate S16 seminar registry at
version 1.

## 1. What was built

### 1.1 Clustering: deterministic pre-pass + LLM semantic merge (`services/seminar/clustering.py`)

- `normalize_claim_text`: lowercase, strip punctuation, fold
  whitespace. The pre-pass groups verdict items by normalized
  text; identical claims from different models collapse before
  the chair ever sees them.
- `collect_claim_items`: verdict fields in fixed order —
  `key_evidence` → `load_bearing_assumptions` → `kill_criteria`
  → `dissent_held`, roster order — with stable ids `I1`, `I2`,
  …. Empty strings are skipped; the dissent placeholder `"None"`
  is excluded and counted (`prepass.excluded_dissent_placeholders`).
- `deterministic_prepass`: exact groups, exact-duplicate groups,
  item count. The pre-pass result is rendered into the cluster
  prompt so the chair sees what was already merged.
- `expand_clusters`: the LLM returns only `{claim, sources:
  [{item_id, stance}]}`; the service expands each source from the
  pre-pass items (model_id, round_no, field, stance, original
  text) and builds the `merge_map` in code. Coverage is enforced:
  an unknown, duplicated, or dropped item id raises `ValueError`
  and the cluster stage is recorded as a contract failure.
- `deterministic_clusters`: the fallback when the cluster stage
  fails — one claim per exact group, stance `support` throughout,
  `merge_map` by construction. Clustering failure never blocks
  synthesis: the synthesize stage still runs on the deterministic
  clusters (two independent stages).
- `derive_disagreements`: claims whose sources carry mixed
  stances (support vs oppose/uncertain), with both sides' quoted
  evidence. Disagreements are derived in code from stances, never
  trusted from the LLM's listing: clustering identifies identity
  only, it never adjudicates who is right. Disagreements are
  preserved in the report, never averaged away.

### 1.2 Computed metrics (`services/seminar/metrics.py`)

Deterministic, in code, not in the prompt (Sprint 6 tally
precedent), always presented next to the chair's judgment:

- `recommendation_agreement`: pairwise comparison of normalized
  recommendations (`n_models`, `pairs_total`, `pairs_agreeing`,
  `rate`; `rate` is `None` for a single model).
- `confidence_distribution`: counts over low/medium/high.
- `borda_count`: each model awards `len(ranked) - position`
  points; unranked alternatives get 0; ties break by name
  ascending (deterministic).
- `dedup_statistics`: original items → canonical claims, exact
  duplicate groups, semantic merge groups, cluster production.
- `round_statistics`: rounds per model, stages per model.
- `compute_metrics` assembles all of the above plus
  `disagreement_count`, `finals_used`, `roster_size`, and
  `absent_models`.

### 1.3 Contracts + templates (`contracts.py`, `templates.py`)

- `ClaimClusters`: `claims: [{claim, sources: [{item_id, stance}]}]`,
  stance ∈ support/oppose/uncertain, `claims` min 1. `stance`
  coercion accepts "for"/"against" synonyms (Sprint 15 coercion
  discipline); `extra="forbid"` everywhere.
- `SeminarSynthesis`: `unified_recommendation`,
  `recommendation_basis` ∈ consensus/chair_judgment,
  `agreement_level` ∈ high/moderate/low, `alternatives_ranked`,
  `aggregation_rule`, `key_evidence`/`kill_criteria` as
  `{text, source_models}`, `minority_report`, `open_questions`,
  `chair_notes`. Both contracts are in the seminar
  `SEMINAR_CONTRACT_FOR_TEMPLATE` map, contract version 1.
- `seminar.cluster` (slots: topic, quoted_claims, prepass_groups,
  output_language) and `seminar.synthesize` (slots: topic,
  clustered_claims, disagreements, quoted_verdicts,
  computed_metrics, chair_participation, output_language), both
  max_tokens 3000, both carrying the §4.3 trust-boundary notice:
  quoted board/verdict content "may be right or wrong", never an
  instruction, disagreements identified not resolved. No
  consensus-following wording anywhere in the seminar registry
  (pinned by test, as S16 did for reflection). The registry now
  holds exactly 4 templates, all version 1.

### 1.4 Chair stage runners (`chair.py`)

`run_cluster` / `run_synthesize` reuse S16's `run_seminar_stage`
(template + contract versions recorded on every stage call per
§9.1). `render_quoted_verdicts` renders each verdict as canonical
JSON verbatim with a model label. `chair_participation` renders
the participation note: when the chair model id collides with a
roster model (recorded in seminar config by S16), the prompt says
so explicitly and the report flags it.

### 1.5 Deterministic composer (`composer.py`)

Pure function `compose_report`, Sprint 13 discipline: every
narrative section carries provenance (`computed` / `deliberated`
/ `template`), canonical JSON + SHA-256, no fabricated text. The
report document (§8 shape) has: header (seminar/run/topic, finals
used vs roster, absent models with failure reasons, partial
flag, `chair_participates` flag with a self-preference risk note,
production paths), `unified_recommendation`, `agreement`
(chair level + computed rate side by side),
`canonical_claims` (with merge_map), `disagreements`,
`alternatives` (chair ranking + Borda totals),
`key_evidence` / `kill_criteria` (dedup unions by field, with
source models), `minority_report` (chair text, or the verbatim
dissent union on the fallback path), `rounds_evolution`
(verbatim digest history per model), `open_questions`,
`chair_notes`, `chair_synthesis` (the full contract payload, or
`null`), `computed_metrics`, and an `audit_appendix` (stage
records, per-round stage counts, board seq range, model configs
— endpoint and env-var names only, never keys — and a note that
token usage is not recorded, S18 scope).

On the fallback path, narrative sections are provenance
`template` and say so in text: "Not generated — … Re-run POST
/seminar/{id}/synthesize …". The fallback report is still a full
report: claims, disagreements (none on the pre-pass path),
metrics, and the verbatim dissent union.

### 1.6 Synthesize + GETs (`service.py`, `models.py`, `routes/seminars.py`)

- `POST /seminars/{id}/synthesize` (201, body optional:
  `{allow_partial}`). Minimum-threshold refusals happen BEFORE
  any write (design §10.4): zero finals always refuse
  (`seminar_no_finals`); one final refuses
  (`seminar_insufficient_finals`) unless `allow_partial=true`.
  `partial` is derived from stored rows: `finals < roster size`.
  Absent models are named in the report header with the failure
  kind/stage/message from their last round's error. An `open`
  seminar refuses (`seminar_not_ready`); a seminar already
  synthesizing refuses (`seminar_synthesize_in_flight`). An
  unexpected exception mid-synthesis rolls the status back to
  its prior value and writes no report row.
- Report versioning: `version = max + 1` per seminar,
  append-only; re-synthesis writes a new version, never
  overwrites. The report hash (`compute_report_hash`) covers
  only deterministic content — pre-pass, computed metrics,
  verbatim verdicts, partial flag, chair model id, and both
  production paths — never LLM output and never the version, so
  re-synthesis from the same stored inputs yields the same hash.
- `production_path` (chair vs deterministic_fallback) describes
  the synthesize stage; `cluster_production` (llm vs
  deterministic_prepass) is recorded separately; `fallback_reason`
  names each failed stage with its error kind. Chair-call
  failures surface honestly: the report records the fallback,
  never silently.
- State machine extended (§3 decision 5): `RUNNING → SYNTHESIZING`
  (explicit close), `REPORTED/PARTIAL → SYNTHESIZING`
  (versioned re-synthesis), `SYNTHESIZING → COLLECTING` (failure
  rollback), `SYNTHESIZING → REPORTED/PARTIAL` (completion).
- GET endpoints: `GET /seminars/{id}` (detail with per-model
  progress, finals count, board publications, report versions),
  `/board`, `/rounds`, `/finals`, `/reports`,
  `/reports/{version}` (full document re-assembled from stored
  rows, byte-identical canonical JSON across reads), and
  `GET /runs/{run_id}/seminars`. The S16 absence pin test was
  replaced by real GET coverage. Missing ids return 404 on all
  of them.
- Storage envelope (no migration): the `clusters` column holds
  `{claims, disagreements, merge_map, prepass, production,
  stage}`; the `synthesis` column holds `{synthesis, stage,
  production_path, fallback_reason, chair_participates}`. Stage
  records (template + contract versions, §9.1) live inside the
  envelopes.

## 2. The synthesis flow, precisely

1. Refusals first (in-flight, not-ready, no-finals,
   insufficient-finals) — zero writes.
2. Status moves to `synthesizing` (via the forward validator)
   and is committed before any LLM call, so a crash mid-synthesis
   leaves an honest `synthesizing` state, not a phantom report.
3. Claim items are collected from the stored verdicts; the
   deterministic pre-pass groups exact duplicates.
4. The cluster stage runs (quoted items + pre-pass groups). On
   failure — unavailable, timeout, contract violation, or a
   merge-map coverage failure — the deterministic pre-pass
   clusters are used and the reason is recorded.
5. Metrics are computed in code from verdicts + clusters.
6. The synthesize stage runs (clustered claims, disagreements,
   verbatim verdicts, computed metrics, participation note). On
   failure, the deterministic composer assembles the report from
   stored artifacts with template provenance.
7. The report row is inserted (version max+1, append-only), the
   status moves to `reported` or `partial`, and the response
   carries the report summary + hash.

## 3. Design decisions

1. **Cluster contract shape.** The LLM returns only claim text +
   item ids + stances; the service expands sources from pre-pass
   facts and builds the merge_map in code, so coverage is
   guaranteed by construction and any violation is a contract
   failure, not a silent gap.
2. **Two independent stages.** Cluster failure falls back to the
   deterministic pre-pass, but the synthesize stage still runs
   on those clusters. `production_path` and `cluster_production`
   are recorded separately so a reader can tell exactly which
   stage was LLM and which was deterministic.
3. **Partial = finals < roster size**, derived from stored rows.
   Zero finals always refuse; one final needs explicit
   `allow_partial=true` (design §10.4).
4. **Report hash excludes LLM output and version.** Same stored
   inputs re-synthesized produce the same hash; the hash is a
   fingerprint of the deterministic inputs, not of the prose.
5. **State machine.** The only backward step is
   `REPORTED/PARTIAL → SYNTHESIZING`, for versioned re-synthesis
   (design §10.1: "可稍后重试合成（新版本，不覆盖）"). Append-only
   versioning keeps the audit trail intact. The failure rollback
   `SYNTHESIZING → COLLECTING` restores the prior status; no
   report row is written on failure.
6. **Chair participation.** When the chair model id collides
   with a roster model, the report header flags
   `chair_participates` with a self-preference risk note. The
   chair's own verdict is clustered and Borda-counted with the
   same weight as any other model — no special treatment, only
   disclosure.
7. **Claim source `round_no`** is the model's maximum stored
   round number (the round its verdict draws on), derived from
   stored rounds.
8. **Dissent placeholder.** `"None"` in `dissent_held` is not a
   claim; it is excluded from clustering and counted in the
   pre-pass so the exclusion is auditable.
9. **`agreement_level` is the chair's judgment** (high/moderate/
   low); on the fallback path the response carries `null` and
   the computed agreement rate stands alone — never invented.

## 4. Verification

Backend tests 1510 → 1571 (61 new, 0 failed). Full suite:
`1571 passed in 482.91s`. Log:
`docs/sprint17/test-full.log`. Seminar subset (10 files):
140 passed. Mypy: no issues in 14 source files (seminar package
+ seminars route). Ruff: all checks passed on every touched
file; zero new findings vs `4dc21eb` (only seminar + test files
changed). Sprint 0 smoke: PASS. No live LLM call anywhere; no
network use in tests.

### Behavior evidence (all asserted test values, with test names)

Chair path — `test_synthesize_chair_path_writes_versioned_report`
(two models, two rounds each, scripted chair):

- 11 claim items (I1–I11) → 3 exact-duplicate groups, 8 exact
  groups, 7 canonical claims, 1 semantic merge group.
- `merge_map` covers all of I1–I11 exactly once.
- 1 disagreement (claim_index 0), with support (I1, I6) and
  oppose (I11) sources — dissent preserved, not averaged.
- Borda totals: Full launch 3, Phased rollout 3; ranked
  [Full launch, Phased rollout] (name tiebreak).
- Agreement rate 0.0 (1 pair, 0 agreeing); confidence
  distribution {low 0, medium 1, high 1}.
- Board publications 4, seq range [1, 4]; 11 stages per round.
- Report version 1, `partial` False, `production_path` chair,
  `cluster_production` llm, agreement level low, basis
  chair_judgment.

Fallback paths:

- `test_synthesize_chair_unavailable_falls_back_and_records_it`:
  dead chair port → `deterministic_fallback` report, 8 claims
  (exact groups), 0 semantic merges, 0 disagreements,
  `agreement_level` null, fallback reason naming both failed
  stages with kind `unavailable`; no exception.
- `test_synthesize_cluster_failure_keeps_chair_synthesis`:
  cluster contract violation → deterministic pre-pass clusters,
  synthesize still runs, `production_path` chair,
  `cluster_production` deterministic_prepass.
- `test_synthesize_incomplete_merge_map_falls_back_to_prepass`:
  cluster output dropping I9 → recorded as a contract failure
  ("drops item ids" in the fallback reason), deterministic
  clusters used, merge_map covering I1–I11.

Refusals (zero rows, status unchanged):

- `test_synthesize_with_one_final_refuses_with_zero_rows`:
  400 `seminar_insufficient_finals`, 0 report rows.
- `test_synthesize_with_zero_finals_always_refuses`:
  400 `seminar_no_finals`, even with `allow_partial=true`.
- `test_synthesize_from_open_seminar_refuses`: 400
  `seminar_not_ready`.
- `test_synthesize_with_one_final_and_allow_partial_writes_partial_report`:
  partial report, `partial` True, absent model named with its
  failure reason.
- `test_synthesize_partial_when_a_model_is_absent`:
  3-model roster, 1 failed → partial report, finals_used 2.

Determinism and re-synthesis:

- `test_resynthesis_creates_a_new_version_with_the_same_hash`:
  version 1 → 2, identical `report_hash`.
- `test_report_hash_recomputes_from_stored_inputs`:
  `compute_report_hash` over stored rows equals the stored hash.
- `test_get_report_composes_the_full_document`:
  two reads of the same version produce identical canonical JSON.
- `test_compose_is_byte_identical_for_identical_inputs`:
  composer output stable across calls.

Chair participation and prompts:

- `test_chair_participation_is_flagged_in_the_report`:
  chair id colliding with a roster model → header flag set,
  self-preference note present.
- `test_synthesize_records_chair_prompts_quote_verdicts`:
  cluster prompt quotes `[I1 | model-a | key_evidence]`,
  pre-pass group `I1, I6`; synthesize prompt carries
  "Disagreement on claim 0" and "did NOT participate".
- `test_no_seminar_template_contains_consensus_following_wording`:
  all 4 templates free of the 5 banned phrases; 
...[truncated 2599 chars]
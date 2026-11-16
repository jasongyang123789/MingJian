# Phase 2 — S-layer wiring, transmission links, dual track, prompts, cockpit

Branch: `strategy-engine/phase2-auto`, from Sprint 16 tip `4dc21eb`.
Nothing pushed. Built in parallel with Sprint 17 (separate worktree,
separate branch, same base) under Ho's 2026-11-16 directives: (a) S-layer
aggregation wired to engine snapshots; (b) income/LPR/raw-materials
transmission links + NEV/ICE dual-track dynamics; (c) cockpit UI for the
automotive pack; (d) the two-subpopulation structure generalized to all
nameplates, with per-nameplate generation schedules replacing Phase 1's
single global transition index; (e) co-occurrence prompts + anomaly flags
— NOT hard rules. This phase closes every limit Phase 1 listed except
dynamics refinement (coefficients remain labeled assumptions; no public
elasticities exist).

Design authority, in order: the Phase 1 report; the auto-domain-pack
design draft (§1 engine interfaces); the auto-model synthesis (Parts
A–D + Ho-answers appendix; §C1 line 242 corrected: fitment rates are
independent penetrations, no product-level sum gate); the
config-co-occurrence verification report INCLUDING appendices 1–3 (all
11 Q1–Q11 rulings, the prompt-system directive, the no-generalization
rule — appendix rulings override the main body wherever they differ).
No LLM call was made anywhere in this phase; no API keys; no network
calls from code or tests. The workbook was not modified. No migration
was needed (no new tables; the split fragment and snapshots already
existed). No seminar code was touched.

## 1. What was built

### 1.1 S-layer wired to engine snapshots (a)

`src/planagent/services/splits/sales_layer.py` (new):

- `extract_production_trajectory(snapshots)` reads the run's stored
  state snapshots and returns the production trajectory (tick →
  `production_volume`), excluding tick 0 (the initial state). It
  refuses loudly on duplicate ticks, missing production values, or an
  empty trajectory — a trajectory that cannot be read is never silently
  replaced by a default.
- `compute_sales_layer(structure, trajectory, oem_production_shares,
  ...)` computes, per tick: the effective split structure at that tick
  (§1.4 schedules applied), OEM production = total production × the
  caller's OEM share, then Phase 1's `aggregate_units` /
  `aggregate_capacity` / `market_capacity_by_oem_product` per
  OEM/product. OEM shares must cover every OEM in the structure and
  sum to 1; the caller supplies them (see §2.3). Own-sales attribution
  has two paths, supplier rows winning over share fallback: rows whose
  supplier id matches `own_supplier_id` attribute their capacity to
  own sales; otherwise `supply_shares` / `default_supply_share` apply.
  Prospects (`customer_status="prospect"`, Ho Q8) always get own sales
  0. With no attribution input at all, own sales is `None` with a
  recorded reason — never a silent zero. `strict_prices` (default
  true) refuses on unpriced slots; with false, unpriced slots are
  skipped and listed in `skipped_unpriced_slots`. Every computation
  carries its `assumptions` list (volume spine, prospect rule,
  schedule semantics, attribution basis).
- Result models: `SalesLayerRow` / `SalesLayerTickTotal` /
  `SalesLayerSummary` / `SalesLayerComputation`.

Endpoints (`src/planagent/api/routes/automotive.py`, new; registered
additively in `api/routes/__init__.py`):

- `GET /runs/{id}/automotive/trajectory` — read-only over stored
  snapshots; any run status; response carries `run_status`. Multiple
  actors per tick must agree on production volume or the read refuses
  with 400. Writes no replay record.
- `POST /runs/{id}/automotive/sales-layer` — requires a COMPLETED
  automotive run with a stored split fragment; body carries
  `oem_production_shares` (sum-to-1, 400
  `automotive_invalid_oem_shares` otherwise) plus the optional
  attribution inputs. Writes zero rows.
- `GET /runs/{id}/automotive/split-structure` — returns the stored
  structure + its validation, so the cockpit can list OEM ids and
  evaluate prompts over the run's own structure.
- Named error codes throughout: `automotive_domain_required`,
  `automotive_run_not_completed`, `automotive_no_split_structure`,
  `automotive_corrupt_split_fragment`, `automotive_no_snapshots`,
  `automotive_corrupt_snapshots`, `automotive_invalid_oem_shares`,
  `automotive_invalid_supply_shares`, `automotive_unpriced_slot`,
  plus the Phase 1 `split_validation_failed` shape.

Automation boundary (Sprint 9) preserved: no scheduler, no worker, no
silent background work. The S-layer is an explicit read/compute over
stored snapshots; loop re-simulation inherits the split fragment
exactly as Phase 1 established, so a re-simulated run's S-layer reads
the new run's own trajectory.

### 1.2 Transmission links + NEV/ICE dual track (b)

Pack (`simulation/domain_packs/automotive/pack.py`): 4 new state
fields, 27 → 31. `nev_production_volume` 137.86 /
`ice_production_volume` 149.94 (sum exactly the 287.8 spine) and
`nev_retail_volume` 94.79 / `ice_retail_volume` 103.11 (sum exactly
the 197.9 retail), at the 47.9% penetration default. `lpr_proxy` and
`material_cost_index` already existed as Phase 1 state fields; this
phase binds template variables to them.

Template (`template_spec.py`): 6 new variables, 24 → 30 — exactly the
Sprint 2 cap (see §2.1): `lpr_proxy`, `material_cost_index`,
`lpr_sensitivity` 0.10, `material_passthrough` 0.30,
`price_sensitivity` 0.20, `margin_material_sensitivity` 0.02. Formulas
8 → 16, drivers 5 → 13. `demand_growth_rate` (F1) is now the
confidence term only; the income/LPR/price terms moved into the retail
driver, which reads current state each tick — this avoids double
counting (F1 is an initial formula; the terms must apply per tick, not
once at run start). New drivers, in order: price (partial adjustment
toward the materials-implied level, speed 0.5 literal), income
(0.05/year ÷ 12 compounding, literal), penetration (+0.002/month,
capped at 1.0, literal), 4 dual-track drivers (spine × penetration),
margin (−sensitivity × (materials − price): price pass-through relieves
the squeeze). The retail driver is now
(1 + g + income term − LPR term − price term − pull-forward drag) ×
the tax level factor (tick 1 only, unchanged). All coefficients are
labeled assumption parameters with evidence grades in code comments;
no public elasticity exists for any of them (synthesis Part A).

Rules (`rules/automotive/default_rules.yaml`): 3 new rules, 10 → 13:
`auto.material_cost_shock` (materials +0.05, margin −0.005, price
+0.01), `auto.rate_cut` (LPR −0.05; a hike still goes through the
lever), `auto.nev_momentum` (penetration +0.01). Scaled effects remain
exactly 1 (`auto.demand_surge`).

### 1.3 Cockpit UI (c)

`frontend-v2`, following the Sprint 7/8/12 patterns (fixed-size
recharts, `useApi`, `RunPicker` + `?run=`, `EmptyState`/`ErrorBanner`,
fetch-mocked tests):

- Route `/cockpit/automotive` + `汽车推演` tab (`App.tsx`,
  `CockpitNav.tsx`).
- `src/pages/Automotive.tsx`: `RunLauncher` (tick count / seed /
  company + optional split-structure JSON → `simulationApi.createRun`
  with `domain_id="automotive"` and the builtin template; malformed
  JSON is an inline error, no POST); `TrajectorySection` (spine,
  retail, NEV/ICE production lines + per-tick table + penetration
  first/last summary); `StructureSection` (stored structure, OEM
  list with customer status, S-layer form with equal-split default
  shares, own-supplier id, default supply share, strict-prices toggle,
  DMS toggle for R12, prompt evaluation); `ExpectationsSection`
  (catalog table). The S-layer form body is keyed by run id, so
  switching runs remounts it — no set-state-in-effect.
- `src/components/cockpit/AutomotiveViews.tsx`: `TrajectoryChart`,
  `SalesLayerTable` (summary cards, un-attributed / skipped-slot
  disclosure, per-tick + detail tables, assumptions fold-out),
  `PromptList` (anomalies in prominent red cards with expected logic
  and likely explanations, skipped expectations folded, prompt-system
  note), `ExpectationCatalogTable`. `automotiveUtils.ts` holds the
  `oemSummaries` helper (separate module: the react-refresh rule
  forbids non-component exports from component files).
- `src/api/engineTypes.ts` + `automotiveApi` in `engine.ts`: the five
  Phase 2 endpoints, typed.
- Frontend 212 → 228 tests; lint + build pass.

### 1.4 Two-subpopulation structure + per-nameplate schedules (d)

The Sagitar pattern — two sub-populations, each with its own volume
weight and its own product/supplier configuration — is the general
shape: a nameplate carries N generations, each with its own share and
its own trims (each trim its own fitments, prices, and supplier
splits). Phase 1's structure already allowed N generations; Phase 2
adds the mechanism that makes the pattern dynamic per nameplate:

- Models (`services/splits/models.py`, all optional, Phase 1 payloads
  unchanged): `NameplateSplit.model_year` + `transition_schedule`
  (`GenerationTransitionSchedule`: outgoing/successor generation ids,
  `start_tick` ≥ 1, `duration_ticks` ≥ 1). `TrimSplit.morphology`
  (ivi_one_box / discrete_host / scdc / central_compute / fused).
  `ProductFitment.solution_code` + `price_basis`
  (discrete / bundle / includes_screen).
- Validator gates (hard, accounting-identity class): schedule
  references must exist, outgoing must be `phase_out`, successor must
  be `ramp`, a schedule requires exactly two generations, same
  generation refused. Issue kinds:
  `transition_schedule_unknown_generation` /
  `transition_schedule_phase_mismatch` /
  `transition_schedule_composition`. New check record
  `transition_schedules`.
- Schedules (`services/splits/schedules.py`, new): progress(t) =
  clamp((t − start_tick + 1) / duration, 0, 1); the outgoing share
  interpolates from its static value to 0, the successor from its
  static value to 1, the sum always 1; before `start_tick` the static
  shares apply. With static (1.0, 0.0) this is exactly Phase 1's
  `generation_mix_at_index`. `structure_with_effective_shares`
  deep-copies (morphology, solution codes, price bases preserved; the
  stored structure is never mutated). The S-layer applies the
  effective structure per tick, so generation mix moves with the
  simulation.
- Phase 1's single global `generation_transition_index` state field is
  left in place (template driver D5 still advances it); per-nameplate
  schedules are the operative mechanism for the split layer. Removing
  the global index is deferred (see §3).

### 1.5 Co-occurrence prompts + anomaly flags (e)

Ho's prompt-system directive (2026-11-16 13:39) governs: every
co-occurrence relationship is probabilistic ('大概率'). The engine
flags and explains; it never refuses and never silently corrects.

- `services/splits/expectations.py` (new): a 22-entry catalog —
  R1–R13, X1–X5, AVM1, BUNDLE1, SCREEN1, EMBED1 — evaluated per trim
  in deterministic order by the pure function
  `evaluate_prompts(structure, dms_mandate_on=None)`. Each `Prompt`
  carries rule id, severity (anomaly | info), path, title, observed,
  expected logic, likely explanations, evidence ref, and scope.
  `PromptReport` counts anomalies/infos and lists evaluated vs
  skipped rules with skip reasons. R11/X1/X2 are catalog-only (always
  skipped with a recorded reason: the structure carries no PHEV
  energy detail / no cross-OEM comparison input / no price-history
  input). Key semantics: R2 camera ladder IFC 5 / 8620 7 / 8650 10
  (2026) or 11 (2027+, {10,11} when the year is unknown) / RHP·NGX 11,
  tolerance ±1 (Q2), +1 observed when a front-view module is present
  (embedded camera); R6/X3/X4 sum the MAXIMUM fitment rate per
  solution code (supplier splits must not double-count); R7 excludes
  the passenger screen; R9 only evaluates rows carrying both 4G and
  5G marks; R13 flags bare P.O rows and lists the decomposition
  catalog; AVM1 is one-directional (AVM ⇒ surround group, not the
  reverse); BUNDLE1 checks the Huawei bundle label and that bundle
  trims carry no P03/P05 rows; SCREEN1 checks the includes_screen
  label on integrated-morphology P01 rows; EMBED1 is an info prompt;
  the known VA3 error is an info prompt and that trim skips R2. NO
  expectation requires P04 to exist (Q10).
- `services/splits/catalog.py` (new): the P.O decomposition catalog —
  15 sub-products (HUD_AR/HUD_W/HUD_P, RADAR count, GATEWAY,
  BODY_DOMAIN count, APA/AVM/UWB flagged assumption, CMS, AMP,
  SMART_ENTRY, STEERING_SWITCH, HVAC_CTRL, ECU_ENGINE),
  `product_line_of`, `is_po_basket`.
- `services/splits/aliases.py` (new): the (code, product-line) alias
  layer (Q4) — no global code classes; §0.2 substring rules with the
  DC mark winning over the CAMMOD mark (NGX:J6M is a DC);
  `classify_solution`, `dc_platform`, `is_huawei_solution`,
  `parse_camera_count` (`*N` sums, binocular 2, trinocular 3, 11-group
  11, uncountable → None), `normalize_code` (keeps 主机:/仪表:
  prefixes).
- `services/splits/morphology.py` (new): morphology labels (5 forms;
  ivi_one_box/fused carry screen_in_p01), exactly 9 registered facts
  (Corolla 2026 ivi_one_box / 2027 discrete_host; Avalon/RAV4/
  Frontlander/Crown-Kluger/Granvia 2026 ivi_one_box; T-Roc/CC 2026
  fused; no fact for CC 2027), OEM/nameplate alias maps (Chinese +
  English), `KNOWN_DATA_ERRORS` (exactly 1: jetta/va3/2026/P05),
  `OEMS_WITHOUT_TBOX = {"jetta"}`. The no-generalization rule (Q9) is
  enforced by construction: morphology is a per-model×year attribute
  and only registered facts are asserted; unregistered combinations
  evaluate no morphology expectation.
- Q1–Q11 mapping: Q1 IVI = one-box with screen → morphology rule R3
  + includes_screen label (C4 locked); Q2 1-camera tolerance, not an
  anomaly; Q3 CDD/CDI = passenger-screen slot (R7/X5 rewritten);
  Q4 (code, product-line) alias keys; Q5 fused morphology; Q6 VA3
  known error; Q7 fitment-rate definition — the Phase 1 validator was
  verified code-correct under it (single-value range checks only) and
  NO product-level sum gate was added; Q8 P.O fully decomposed +
  AVM⇔surround pairing as a prompt; Q9 no generalization (registry
  only); Q10 Jetta P04 = 0 genuine; Q11 Huawei bundle price, never
  compared with discrete ASPs.
- Endpoints: `POST /automotive/prompts/evaluate` (shape validation
  only, 422 — prompts are a diagnostic, not a gate; the sum-to-1
  gates deliberately do NOT run here) and `GET
  /automotive/expectations` (the catalog, including which entries are
  catalog-only).
- Phase 1 hard gates unchanged: sum-to-1 at nameplate / generation /
  trim / supplier levels, the one-host backstop, rate/count
  separation. The prompt engine adds zero refusals anywhere.

### 1.6 Shared-file edits and untouched code

- `src/planagent/api/routes/__init__.py`: one additive router
  registration (S17 does not touch this file — the seminars router was
  already registered at the base).
- Shape-only test updates (counts/sets/order, no weakened behavior
  assertions): `test_automotive_pack.py`, `test_rule_effect_scaling.py`,
  `test_splits.py` (check-set gains `transition_schedules`).
- Frontend shared files: `App.tsx` (import + route), `CockpitNav.tsx`
  (one tab), `engine.ts` / `engineTypes.ts` (additive).
- Untouched: `services/seminar/`, all seminar routes, all S16/S17
  code, all migrations, the workbook, the Phase 1 pack defaults
  (except the F1 split documented in §1.2).

## 2. Decisions needing awareness

1. **The 30-variable cap is a Sprint 2 design pin, not a bug.** The
   template hit exactly 30 variables (the `MAX_VARIABLES=30` pin in
   `services/variables/models.py`, test-pinned). Rather than raise a
   deliberate design limit mid-phase, `income_growth_rate_annual` and
   `nev_penetration_monthly_drift` are documented literals in their
   drivers, following the Phase 1 precedent (literals, promoted to
   variables at calibration). The income LEVEL (`income_index`) and
   the penetration LEVEL (`nev_penetration`) remain sampled levers;
   only the two RATES are literals. Raising the cap is a design
   decision for a later sprint, not a Phase 2 fix.
2. **Schedule semantics are linear, two-generation only.** Progress is
   linear in ticks; a schedule names exactly two generations. A
   three-way transition (two outgoing, one incoming) needs a new
   schedule shape. Static (1.0, 0.0) reproduces Phase 1 exactly, so
   existing structures without schedules behave identically.
3. **S-layer OEM shares are caller-supplied.** No OEM production mix
   is stored anywhere (the 富奥量纲 merged forecast file has not been
   sent); the endpoint requires the caller to pass shares summing to
   1. The cockpit defaults to an equal split and shows the running
   total. When the merged forecast arrives, the mix should become a
   stored, versioned input — not a form default.
4. **Prompt skip semantics are explicit, not silent.** Every rule that
   does not evaluate records a skip reason; catalog-only entries are
   visible in the catalog endpoint with `evaluated: false`. A report
   with zero prompts means "all evaluable expectations held", and the
   UI says so.
5. **Ruff B008 in the new route file matches the repo pattern.**
   `Depends(...)` in argument defaults is flagged 24 times in the
   pre-existing `simulation.py`; the 3 new B008s follow the same
   universal FastAPI pattern and were left as-is. All other new files
   are ruff-clean (the `__all__` sort and one `range` fix were
   applied).
6. **Frontend no-split detection reads the error message.** The
   cockpit distinguishes `automotive_no_split_structure` from genuine
   errors by substring on the ApiError message, because the client
   surfaces the structured code inside the message body. It works and
   is test-pinned, but a structured error shape in the client would be
   cleaner (deferred; the pattern matches how the client exposes
   errors today).

## 3. Limits / deferrals

- Dynamics remain coarse by design: every new coefficient is a labeled
  assumption parameter; no public elasticity exists (synthesis Part
  A). The price-driver speed (0.5), income growth (0.05/year), and
  penetration drift (+0.002/month) are literals (§2.1). Calibration
  (v3) is still ahead.
- The global `generation_transition_index` field and its D5 driver are
  still advanced; only per-nameplate schedules drive the split layer.
  Removing the global index is a cleanup for a later phase.
- Penetration drift is global, not per-nameplate; income is a single
  national index; LPR is a proxy, not a rate curve.
- The morphology registry holds exactly 9 facts; every other
  model×year combination is unasserted by design (Q9). Extending it
  requires per-model verification, not inference.
- The cockpit shows the S-layer as tables, not charts; no real-browser
  rendering was verified (jsdom tests only, per project precedent).
- The one-host backstop product set {P01, P04} is still pending Ho's
  confirmation (carried from Phase 1).
- Deferred elsewhere, unchanged: direction options B/C, polished-text
  verification, S18, Docker, live-LLM quality beyond the first
  observation.

## 4. Verification

- Backend full suite: **1604 passed, 0 failed** in 453.48s
  (`TMPDIR=/dev/shm/pytest-tmp-phase2`, full-suite lock held; log at
  `docs/phase2/test-full.log`). Base at `4dc21eb` was 1510; this phase
  adds 94 tests: `test_phase2_splits.py` (27), `test_phase2_prompts.py`
  (35), `test_phase2_sales_layer.py` (16), `test_automotive_phase2_api.py`
  (16).
- Frontend: **228 passed, 0 failed** across 27 files (base 212; +10
  `AutomotiveViews` tests, +6 `Automotive` page tests). `npm run lint`
  exit 0; `npm run build` exit 0.
- Sprint 0 smoke: **PASS** (`docs/sprint0/smoke_e2e.py`; the refreshed
  `smoke-evidence.json` was reverted per precedent).
- Ruff: all new files clean except 3 B008s in the new route file,
  matching the repo's universal `Depends` pattern (24 pre-existing in
  `simulation.py`); see §2.5.
- No migration was added, so no migration drill applies. No live LLM,
  no network in tests.
- Phase 1 regression subsets re-run green during the build: the 81-test
  splits/automotive subset and the 13-test automotive API subset
  (confidence/tax wiring proofs hold).

## 5. Evidence (asserted test values only)

Every number below is asserted by the named test; all of them passed in
the full-suite run above.

S-layer wiring (the headline acceptance — policy shock → production
change → sales change, automatic):

- `test_sales_layer_end_to_end_shock_moves_production_and_sales`
  (chip_supply_index lever 0.8): shocked production is below baseline
  at every one of 6 ticks; tick-6 shocked production < baseline × 0.7;
  shocked total own sales and total capacity value each < baseline ×
  0.75; the S-layer per-tick production equals the trajectory
  endpoint's values tick for tick; `snapshot_tick_count` 6;
  `own_sales_basis` "supplier_rows".
- `test_compute_single_tick_exact_values` (production 100, tick-1
  schedule mix 0.5/0.5): P01 100 units / capacity 120,000 / own sales
  60,000; P02 40 / 100,000 / 100,000; P05 550 / 66,000; P03 capacity
  80,000; totals capacity 366,000, own sales 306,000.
- `test_compute_schedule_moves_mix_over_ticks`: P02 units move 40 →
  80 across the schedule; P01 own sales move 60,000 → 12,000.
- `test_trajectory_endpoint_reads_stored_snapshots`: 7 points, ticks
  0–6; tick 0 production 287.8, retail 197.9, NEV production 137.86,
  ICE production 149.94, NEV retail 94.79, ICE retail 103.11; two reads
  return the identical body.

Transmission links + dual track:

- `test_dual_track_splits_sum_to_spine_every_tick`: NEV + ICE
  production and NEV + ICE retail each equal the spine every tick;
  penetration 0.479 → 0.491 (0.479 + 6 × 0.002), monotone.
- `test_lpr_easing_moves_retail_up`: LPR lever 0.9 → tick-6 retail >
  baseline × 1.03.
- `test_material_shock_moves_price_up_and_margin_down`: materials
  lever 1.2 → tick-6 price index > 1.04 and above baseline, margin
  below baseline.
- `test_tax_level_factor_exact_at_tick_one`: tick-1 retail ratio
  exactly 0.9375 (rel 1e-6) — the Phase 1 level factor, unchanged by
  the driver rewrite.

Prompts + catalog:

- `test_prompts_evaluate_endpoint`: an R1 anomaly is present for a
  DC-without-cameras trim. `test_expectations_endpoint`: the catalog
  returns 22 entries; R11 `evaluated` is False (catalog-only).
- `test_phase2_prompts.py` (35 tests): every rule's fire / skip /
  silent case is pinned, including the R2 ladder tolerance, the
  supplier-split max-rate sums, the VA3 known-error skip, and
  deterministic evaluation order.

Template/pack shape (pinned counts, not behavior changes):

- 31 pack state fields, 30 template variables, 16 formulas, 13
  drivers, 13 YAML rules, 7 unbound sensitivity ids — asserted in the
  updated `test_automotive_pack.py` / `test_rule_effect_scaling.py`.
- The `transition_schedules` check record is asserted in the updated
  `test_splits.py` check set.

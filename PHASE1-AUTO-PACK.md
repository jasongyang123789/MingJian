# Phase 1 — Automotive domain pack + per-tick drivers + split gates

Branch: `strategy-engine/phase1-auto-pack`, from Sprint 15 tip
`ad92029`. Nothing pushed. This is the FIRST build sprint of
the auto-industry track, built under Ho's 2026-11-16
directives: "做就行" (full-web research + indicator
compilation, then build the decision-impact model); full-chain
skeleton at once, dynamics coarse first then refined; China
market; tick = 1 month; volume spine = OEM PRODUCTION volume
including Audi; the bottom layer is OEM → nameplate →
generation → trim → product → supplier share; industry-average
SIMULATED values authorized for supply share / payment terms /
gross margin / annual-cut execution, explicitly labeled; logic
over results — structural depth (generation transitions,
supplier splits, trim structure, transmission chains) over
numeric precision.

Design authority: `~/workspace/research/strategy-engine/auto-model-synthesis.md`
(Parts B + C + Ho-answers appendix), which supersedes the v1
draft's defaults and granularity; the v1 draft's §1 (engine
interfaces) still applies. No LLM call was made anywhere in
this sprint; no API keys; no network calls from code or tests.
The workbook was not modified. No cockpit UI changes.

Corrected mechanics (verified by reading the code before
building): per-run sampling + lever replacement + formula
evaluation + initial-state override ALREADY existed via
`resolve_run_values`. What was genuinely missing — and what
this sprint builds — is per-tick application of sampled values,
variable-scaled rule effects, and the automotive pack itself.

## 1. What was built

### 1.1 Automotive domain pack (`domain_id="automotive"`)

`src/planagent/simulation/domain_packs/automotive/` (new
package, registered through the existing `discover()` mechanism;
no registry change needed):

- **27 state fields** with synthesis §C1 v2 defaults, each
  default citing its synthesis section in a code comment:
  25 synthesis fields + `cash` (100.0, kept for Monte Carlo
  metric continuity) + `generation_transition_index` (0.0,
  Ho's generation dimension, not in synthesis C1).
  Production volume (287.8), retail (197.9), wholesale
  (246.3), export (59.2) are the 2025 monthly-mean derived
  values; capacity utilization 0.662 (NBS 2026Q3); dealer
  inventory coefficient 1.35 (CADA 2025-09); Tier-1 gross
  margin 0.191 (Desay SV 2025 benchmark); policy tax rate
  0.05 (2026–27 halved rate); DMS mandate 0 (1 from
  2027-01-01 per GB 47955—2026).
- **10 actions** biased to sales strategy: `adjust_price`,
  `increase_incentive`, `cut_production`, `ramp_production`,
  `build_inventory`, `destock`, `shift_mix_nev`,
  `shift_product_mix`, `expand_channel`, `hold_and_monitor`.
- **6 event types**, including `policy_calendar_event` and
  `dms_mandate_switch`, plus `chip_supply_shock`,
  `price_war_escalation`, `generation_changeover`,
  `dealer_inventory_alert`.
- **4 entity types**: `oem`, `dealer`, `tier1_supplier`,
  `nameplate`.
- **3 actor templates** (`oem`, `dealer`, `tier1_supplier`)
  with EMPTY state overrides: inventing per-actor values
  would be fabrication; calibration data decides them later.
- **Default tick count 12** (`default_automotive_ticks` in
  `config/base.py`): an automotive run without `tick_count`
  runs 12 monthly ticks.

Field names align with variable ids: sampling applies only to
id-matched fields, and 21 of the 24 template variables bind to
state fields (the 3 exceptions are formula parameters — see
§1.4). This alignment IS the wiring.

### 1.2 Rules YAML (`rules/automotive/default_rules.yaml`)

10 deterministic rules, priority 70–90, covering the
synthesis §C2 chain links that are rule-expressible:
`auto.chip_shortage` (90), `auto.price_war` (88),
`auto.policy_tax_hike` (85), `auto.subsidy_payback` (84),
`auto.inventory_overhang` (82), `auto.demand_surge` (80),
`auto.dms_mandate` (78), `auto.generation_changeover` (76),
`auto.margin_pressure` (74), `auto.export_hedge` (70).
Keyword-only triggers: `trigger_conditions` are parsed but
NEVER evaluated against state by the engine (their values only
extend the keyword list), so state-gated rules would silently
misbehave. Policy-calendar state (DMS switch etc.) is
lever-driven through the C4 scenario families, not
condition-driven. Effect magnitudes are coarse assumption
parameters (no public elasticities exist — synthesis A9/C5);
direction and mechanism are the Phase 1 deliverable.

The generation-transition rule, `auto.generation_changeover`,
advances `generation_transition_index` by +0.05 when
changeover evidence matches — the required demonstration rule
for the generation dimension.

### 1.3 Per-tick variable drivers

A new formula kind: `FormulaDefinition.tick_driver: bool`
(default `False`). Mechanics:

- `resolve_run_values` SKIPS driver formulas at run start
  (they do not exist yet); `tick_driver_formulas()` reads
  them back from the run's stored bindings.
- Every tick, AFTER `_apply_effects` (including the military
  branch, which automotive runs never take) and BEFORE the
  decision record / snapshot, `evaluate_tick_drivers` runs
  the drivers in list order. The scope is sampled values +
  initial derived values, overlaid with the CURRENT state
  (state wins on id collisions), plus the reserved `tick`
  reference carrying the 1-based tick index. Drivers chain
  within the tick: a later driver sees earlier drivers'
  outputs from the same tick. Each output rounds to 4
  decimals (matching `_apply_effects`). Only outputs whose
  id matches a pack state field overwrite that field.
- Because the driver step runs after rule effects and reads
  the post-rule state, a self-referencing driver TRANSFORMS
  the post-rule state: rule effects and drivers COMPOSE,
  drivers never wipe rule effects out. (Pinned by
  `test_evaluate_tick_drivers_self_reference_reads_current_state`.)
- Runs without driver formulas behave EXACTLY as before:
  the driver step is a no-op over an empty list. Replay
  stability follows: drivers are pure functions of
  (seed-derived sampled values, initial derived values,
  tick index, state), so the Sprint 3 replay mechanism
  reproduces tick-by-tick hashes unchanged.

Validation rules (driver-aware `validate_formulas`):

- A driver may reference sampled ids, earlier formula
  outputs (initial or driver), its OWN output id (= the
  current state value), and `tick`.
- An initial formula may reference only sampled ids and
  earlier INITIAL outputs — never a driver output, never
  itself, never `tick`. Forward references are rejected for
  both kinds.
- `tick` is a RESERVED id: no variable id or formula output
  may use it (`reserved_tick_id`).
- Driver outputs are EXEMPT from the
  `formula_output_collides_with_variable` rule: a driver
  output naming a sampled variable is intentional (the
  sampled value seeds the initial state; the driver evolves
  it per tick). Initial formulas remain bound by the rule.
- A driver needing both an initial and a current value uses
  a separate initial formula to capture the initial value
  (e.g. `pull_forward_stock_initial`).

### 1.4 Variable-scaled rule effects

`RuleEffect.scale_by`: an optional variable/formula id. At
application time the effect value is `base × scope[id]`,
where scope = sampled + initial derived values. A missing id
or a non-finite scope value falls back to factor 1.0 (the
base value applies), documented on `scaled_effect_value`.
The scope threads through `_effects_to_mapping` →
`_aggregate_candidate_effect` → `_rank_action_candidates` →
`_select_action` as defaulted parameters, so fixed-constant
rules work byte-identical to before. Malformed `scale_by`
values in YAML (non-string, empty) fail rule loading loudly
(`_parse_scale_by`), like the existing strict `float(value)`
parse. Only `auto.demand_surge` uses scaling in Phase 1
(production +6.0 × `consumer_confidence_proxy`): the scaling
demonstration.

### 1.5 Automotive variable template (built-in)

`DomainPack` gained three non-abstract default methods —
`template_variables()`, `template_formulas()`,
`template_assumption_data()` — returning empty values, so
corporate/military presets synthesize exactly as before.
`builtin_template` now reads the pack spec, validates the
models, and runs `validate_template` on the synthesized
result: an invalid built-in is a code defect and fails loudly
with `RuntimeError`. The automotive spec lives in
`automotive/template_spec.py` as raw-dict constants; pack
methods return deep copies.

- **24 variables**, each with unit + evidence_ref +
  description. Fixed-distribution variables double as C4
  lever handles (fixed value = pack default). Three
  sensitivity coefficients are variables so they enter
  tornado analysis: `confidence_sensitivity` 0.05,
  `income_sensitivity` 0.05 (both assumption parameters —
  no public elasticities exist), `tax_sensitivity` 1.25
  (the C2 link-2 event anchor: a 20% cost rise on cheap
  segments vs ~25% sales fall; an event observation, NOT a
  structural semi-elasticity). The other coefficients
  (pull-forward decay 2%, drag 0.01, inventory response
  0.1, production-inventory response 0.05, chip response
  0.5, generation ramp 0.05) are formula literals, flagged
  as assumption parameters, to be promoted to variables in
  Phase 2. The 1.2 inventory-band ceiling is NOT an
  assumption: it is the CADA 0.8–1.2 reasonable band (B1).
- **8 formulas** in evaluation order: 3 initial (F1
  `demand_growth_rate`, F2 `demand_level_factor`, F3
  `pull_forward_stock_initial`) + 5 tick drivers (D1
  `pull_forward_stock` decay, D2 `sales_volume_retail`, D3
  `dealer_inventory_coef`, D4 `production_volume`, D5
  `generation_transition_index`). See §2 for the exact
  derivation.
- **The tax effect is a LEVEL effect, applied once at tick
  1 only**: F2 computes `demand_level_factor` from the tax
  rate, and D2 applies it through the first-tick indicator
  `max(0, min(1, 2 - tick))`. It is NEVER in the monthly
  growth rate (that would compound it). Confidence/income
  terms ARE in the growth rate (persistent mechanisms).
  This distinction is structural and is documented in the
  spec comments.
- **Assumption data** (template-bound, replaceable with
  zero code change): `fitment_lookup` holds ONLY the
  published B2 cells as a sparse lookup (L2 by price band,
  cockpit domain controller by price band, city NOA by
  price band, intelligent cabin by energy), each with
  provenance + cell notes; `supply_share_simulated` is
  0.10, a round NEUTRAL PLACEHOLDER, explicitly not an
  estimate, with simulated provenance. Missing lookup
  cells fail loudly at consumption — never interpolated.
- Simulated values carry `simulated:industry-average`
  evidence refs: `annual_cut_rate` triangular(0.03, 0.04,
  0.05), `payment_terms_months` triangular(2, 6, 9),
  `tier1_gross_margin` triangular(0.188, 0.191, 0.20).
  `consumer_confidence_proxy` triangular(0.8, 1.0, 1.2) is
  `assumption:pending-calibration` (no unified series
  exists; the PBOC survey is a proxy). `chip_lead_time_weeks`
  26.2 is the Susquehanna Feb-2022 PEAK anchor, explicitly
  not a normal baseline (current value awaits calibration).

`assumption_data` is a first-class field on `VariableSet`,
`VariableTemplate`, `VariableTemplateCreate`, and
`VariableTemplateUpdate` (`dict[str, Any]`, default `{}`;
`None` = keep on update). `merge_variable_sets` merges it
per top-level key, override wins, nested values replaced
wholesale (never deep-merged). Stored templates persist it
through a new column + migration 0037 (0030 precedent).
`resolve_assumption_data(configuration)` resolves it with
bindings-first, template-snapshot fallback, `{}` default.
The validator treats it as opaque JSON; consumers
(`prior_fitment_rate`, `simulated_supply_share`) validate
strictly at consumption and fail loudly.

### 1.6 Split gates (`services/splits/`, new module)

Pure deterministic validators + run-creation gate, following
the Sprint 1 MECE pattern (refuse-before-compute, 400 with a
distinct code, zero rows written).

Structure: OEM → nameplate → generation (with
`lifecycle_phase`: `ramp` / `mature` / `phase_out`) → trim →
product → supplier share. `energy` (`NEV`/`ICE`) and
`price_band` ride on the nameplate (the two strongest
explanatory variables, synthesis §C1 item 7).
`customer_status` (`existing`/`prospect`) rides on the OEM
(Ho: Dongfeng Honda is a prospect). Fitment kind is explicit:
`rate` ∈ [0, 1] vs `count` ≥ 0 (units per car) — the two are
never confused.

Gates (tolerance 1e-9, synthesis §C1):

- nameplate shares sum to 1 per OEM;
- generation shares sum to 1 per nameplate;
- trim shares sum to 1 per generation;
- supplier shares sum to 1 per model×trim×product slot;
- one-host products (`ONE_HOST_PRODUCTS = {P01, P04}` — a
  Phase 1 design decision, pending Ho's confirmation; P02/P03
  aggregate multiple sub-units, P05 is count-kind, P.O is a
  basket): share-weighted rate fitment ≤ 1. Given the share
  gates + range gates this check is mathematically a
  backstop; it is kept as defense-in-depth because the
  synthesis C1 gate text requires it, and the report states
  this honestly.
- empty OEM/nameplate/generation/trim/product rows refused
  (an empty product row would silently aggregate a trim's
  volume to zero — use P.O as the catch-all); duplicate ids
  refused; negative prices refused.

The gate integrates into `create_simulation_run` AFTER the
MECE and variable gates, BEFORE any row is written. Split
structures are automotive-only: attaching one to another
domain is refused with kind
`split_structure_requires_automotive_domain`. The route
returns 400 `split_validation_failed` with the full
validation result in the dict-detail shape (placed BEFORE
the generic `ValueError` handler — `SplitValidationError`
subclasses `ValueError`). The same catch was added to the
loop re-simulation route. The validated structure is stored
as a `split_structure` fragment in the run configuration
(structure + validation result), so it is part of the run's
hashed identity and is inherited by loop re-simulation (see
§1.8).

Aggregation helpers (pure, validate-first): `aggregate_units`
(OEM PRODUCTION volumes × the share chain × fitment ×
supplier share — the production spine, per Ho's instruction;
retail/wholesale never enter the S-layer), `aggregate_capacity`
(refuses unpriced slots loudly — no partial totals),
`market_capacity_by_oem_product`, and the two SEPARATE S-layer
paths: `own_sales_from_supplier_rows` (sum Ho's own supplier
rows; prospects always 0) and `own_sales_with_share`
(full-market capacity × supply share, per-pair overrides +
default; prospects always 0). `generation_mix_at_index`
implements the two-generation pattern: the `phase_out`
generation holds `1 - index`, the `ramp` generation holds
`index`, always summing to 1; any other lifecycle composition
refuses loudly (per-nameplate schedules are Phase 2).

### 1.7 Engine integration

- `_create_automotive_run`: reuses `_upsert_company`
  (automotive runs take a company subject like corporate),
  stores the split fragment, applies the 12-tick default.
- `_execute_run`: resolves `variable_scope` (sampled +
  initial derived) for rule scaling, reads driver formulas
  from stored bindings, runs the driver step each tick
  (§1.3). `_select_action` receives `scale_scope`.
- `_subject_terms`: the corporate branch now covers
  `("corporate", "automotive")` so evidence matching works
  for automotive runs.
- Automotive fallback action (was: the military branch for
  every non-corporate domain — an automotive run would have
  selected military actions and written military fields):
  `cut_production` when the inventory coefficient exceeds
  1.5, else `hold_and_monitor` with empty effects. Both
  military fallback branches now carry an explicit
  `domain_id != "military"` guard.
- Automotive shock handling in `_derive_shocks` /
  `_apply_external_shock`: `chip_shortage`, `policy_shift`,
  `price_war`, `inventory_build`, `demand_surge`,
  `generation_changeover`, `export_boom` (keyword sets kept
  in sync across both functions).
- Automotive decision policies in
  `services/simulation_branching.py` (6 policies; only the
  1.5 inventory warning line is evidenced, the rest are
  labeled assumption parameters).
- **Report generation**: `ReportService` gained
  `generate_automotive_report` (mirroring the company
  report: same section skeleton, automotive indicator set
  + recommendations, no LLM enhancement — none exists for
  this domain). Without it, automotive run creation failed
  with `Unsupported report domain: automotive`; this was
  found by the first end-to-end smoke, not by reading.

### 1.8 Loop re-simulation inheritance

`_build_resimulation_payload` now inherits the split-structure
fragment (malformed fragment → `loop_corrupt_baseline_fragment`,
mirroring the MECE/variables fragments) and treats automotive
runs as company-subject runs (previously: `loop_unsupported_domain`).
A loop re-simulation of an automotive run therefore preserves
the split structure instead of silently dropping it.

## 2. The per-tick derivation, precisely

For an automotive run bound to the built-in template, seed 7,
tick_count 6 (the shape every test uses):

**Run start** (existing machinery): variables sample from the
seed; levers replace drawn values after the draw is consumed;
initial formulas evaluate in list order over post-lever
sampled values; id-matched values apply to the initial state;
explicit `initial_state` wins over sampled values.

- F1 `demand_growth_rate` =
  `0.05 × (confidence − 1) + 0.05 × (income − 1)`.
- F2 `demand_level_factor` = `1 + 1.25 × (0.05 − tax_rate)`.
- F3 `pull_forward_stock_initial` = `pull_forward_stock`
  (captures the initial stock for the drag denominator).

**Each tick t = 1..6**, in order: external shocks →
`_select_action` (rule → LLM → fallback; rule effects scaled
by `variable_scope`) → `_apply_effects` (additive, 4-decimal
rounding) → **driver step** → decision record → snapshot →
state hash. The driver step evaluates D1–D5 in list order
over scope = sampled + initial derived + current state +
`tick`:

- D1 `pull_forward_stock` = `stock × 0.98` (2%/month decay).
- D2 `sales_volume_retail` = `retail × (1 + g − 0.01 ×
  stock / max(initial_stock, 1)) × (1 + (level − 1) ×
  max(0, min(1, 2 − tick)))`, where `g` = F1, `level` = F2,
  `stock` = this tick's D1 output, `initial_stock` = F3.
  The last factor is 1.0 except at tick 1, where it equals
  the level factor: the tax effect lands ONCE.
- D3 `dealer_inventory_coef` = `coef + 0.1 × (wholesale −
  retail) / max(retail, 1)`, reading this tick's D2 retail.
- D4 `production_volume` = `production × (1 − 0.05 × (coef −
  1.2)) × (1 + 0.5 × (chip − 1))`, reading this tick's D3
  coefficient. The 1.2 ceiling is the CADA reasonable band.
- D5 `generation_transition_index` = `min(index + 0.05, 1)`.

Only outputs matching pack state fields are written back;
all five do. The whole derivation is a pure function of
(seed, tick, state) — replay reproduces every tick hash.

Observed trajectory (seed 7, builtin template, no claims —
from the verification smoke): retail 197.90 → 184.88,
production 287.80 → 266.93, inventory 1.3500 → 1.5275,
pull-forward stock 1150.00 → 1018.72, transition index
0.00 → 0.30 over 6 ticks. The pull-forward drag dominates
at baseline confidence: this is the 2026 policy-cliff
mechanism, coarse but directionally the synthesis story.

## 3. Design decisions

- **Driver mechanism = flagged formulas**, not a new
  subsystem: the formula graph already had validation,
  evaluation order, and lever propagation. One boolean +
  one evaluator + scope rules reuses all of it.
- **Driver step AFTER rule effects** (not before): rules
  act on the state, drivers evolve the post-rule state.
  The alternative (drivers first) would let rule effects
  overwrite driver outputs within the tick; the chosen
  order composes them.
- **No new determinism-fragment keys**: driver outputs are
  already auditable via stored bindings + snapshots + state
  hashes. Diff kept minimal.
- **Scaling falls back to 1.0** on a missing/non-finite
  scope id, rather than refusing: a rule file shared across
  runs with different bindings must degrade to its base
  value, and the fallback is documented on the function.
- **One-host rule** (§1.6): kept as defense-in-depth
  despite being mathematically implied by the other gates.
- **No run calendar in Phase 1**: policy-calendar state is
  lever-driven (C4 families), never rule-`conditions`
  (which the engine does not evaluate against state).
- **Generation transition is ONE global index** in Phase 1
  (`generation_transition_index` + D5 + the changeover
  rule + `generation_mix_at_index`), not per-nameplate
  schedules. The split STRUCTURE carries the full
  generation layer per nameplate; the DYNAMIC schedule per
  nameplate is Phase 2.
- **S-layer aggregation is NOT engine-wired in Phase 1**:
  the helpers are pure functions over a validated structure
  + production volumes. Wiring them to run snapshots (so a
  run's production trajectory feeds capacity directly) is
  Phase 2. The report does not claim otherwise.
- **No cockpit UI**: out of scope for Phase 1 by the brief.
- **Sub-product variants** (e.g. 4G vs 5G within P04) are
  NOT modeled in Phase 1: the one-host check is at product
  level. A variant dimension is Phase 2.

## 4. Verification

- Full backend suite: **1430 passed / 0 failed** in 427.10s
  (baseline 1349 + 81 new: 22 tick-driver + 10 rule-scaling
  + 26 splits + 10 pack/template + 13 API; collection count
  verified: 81 tests collected across the five new files).
  Log: `docs/phase1-auto-pack/test-full.log` (force-added
  past the `*.log` ignore, per Sprint 15 precedent). Note:
  the first full run reported 1425 passed / 5 failed — all
  five were diagnosed as intended-shape consequences of
  this sprint, fixed, and the re-run passed fully: (1–2)
  the two golden serialization fixtures gained the new
  default-valued fields (`assumption_data: {}` on the set,
  `tick_driver: false` on each formula — diff verified to
  contain ONLY those additions); (3) the
  `test_unsupported_domain_raises` stand-in payload gained
  `split_structure=None` (Sprint 1/2 precedent); (4–5) the
  two template-list assertions gained `builtin:automotive`
  in the pinned built-in order. No disk-full re-run was
  needed (`/tmp/pytest-of-root` cleared before each run).
- `mypy` on the 26 changed/new source files: clean, no
  issues.
- `ruff check`: ZERO new findings vs the branch point. New
  files are clean (5 `TRY004` sites in `splits/aggregation.py`
  carry targeted `noqa` with rationale: malformed
  caller-supplied data is a `ValueError` by module
  contract). Modified files were compared per-file against
  a pristine `ad92029` worktree: finding counts identical
  in every file (e.g. `routes/simulation.py` 25 = 24 B008 +
  1 I001; `domain/models.py` 35), all pre-existing and left
  untouched. `ruff format`: 7 new files formatted;
  `impact.py` + `presets.py` formatted (clean at HEAD, drift
  was this sprint's); `domain/models.py` format drift is
  pre-existing (Sprint 14 region) and untouched.
- Sprint 0 smoke re-run: **PASS**; the refreshed
  `smoke-evidence.json` was reverted per precedent.
- Migration 0037 drill on a scratch DB: upgrade to 0036
  (column absent) → upgrade head (column present) →
  downgrade to 0036 (column absent) → upgrade head again
  (column present); `alembic current` reports
  `0037_variable_template_assumption_data (head)`.
- Frontend: untouched (no frontend file changed, no
  re-run).

### Behavior evidence (all asserted test values, with test names)

Wiring proof (`tests/test_automotive_api.py`):

- `test_wiring_proof_confidence_moves_retail_p50`: 50-trial
  ensembles, seed 11, metric `sales_volume_retail`, 6 ticks.
  Confidence mode 1.0 → retail P50 **186.87** (P10 180.96 /
  P90 192.86); mode 1.2 → P50 **191.52** (P10 183.03 / P90
  197.19); ratio **1.0248 (+2.48%)**, asserting `> 1.02`.
  (The triangular mean moves 1.0 → 1.0667, adding ~0.0033
  to the monthly growth rate — the observed +2.48% matches
  the mechanism; the report §2 derivation states it
  exactly.)
- `test_same_seed_byte_identical_rerun`: two identical runs
  (pinned `decision_time`) produce identical snapshot lists,
  identical `state_hashes`, identical `sampled_values`, and
  identical `input_hash`.
- `test_policy_cliff_lever_lowers_retail_p50`: the 10% tax
  lever cuts the strategy-arm P50 186.87 → **175.19**, ratio
  **exactly 0.9375** = the level factor `1 + 1.25 × (0.05 −
  0.10)`, applied once.
- `test_automotive_run_state_fields_and_drivers`: tick-0
  state carries pack defaults (production 287.8, retail
  197.9, inventory 1.35, transition index 0.0); each tick
  the transition index is exactly `0.05 × tick`, the
  pull-forward stock is exactly `1150 × 0.98^tick`, retail
  strictly falls, inventory strictly rises, production
  strictly falls.
- `test_rule_trigger_and_scaled_effect`: after ingest +
  review-acceptance of a demand-surge claim, `matched_rules`
  contains `auto.demand_surge`; the tick-1 decision record's
  expected production effect is `6.0 × 0.9609553391057687`
  (the sampled confidence) = 5.7657; on every surge tick
  the production/inventory effect ratio equals
  `(6.0 × confidence) / −0.03`, pinning scaling under the
  pre-existing escalation multiplier.
- `test_replay_matches_tick_by_tick`: replay `match` is
  `True`, `first_diverging_tick` is `None`, replay snapshots
  equal original snapshots.
- `test_generation_transition_in_snapshots`: the
  phase_out/ramp mix sums to 1.0 at every tick; outgoing
  falls 1.0 → 0.7, successor rises 0.0 → 0.3 over 6 ticks.
- `test_split_gate_refuses_f02_and_writes_nothing`: the
  F02 structure (supplier shares 1.0 + 1.0) → 400
  `split_validation_failed` with a `supplier_shares_sum`
  issue; `GET /simulation/runs` returns `[]`.
- `test_split_gate_rejects_non_automotive_domain`: a
  corporate run with a split structure → 400 with kind
  `split_structure_requires_automotive_domain`; no rows.
- `test_split_structure_stored_in_input_hash`: runs
  differing only in the split fragment have different
  `input_hash`; identical split runs share it.
- `test_lookup_replaceable_via_stored_template` /
  `test_lookup_replaceable_via_inline_variable_set`: a
  replaced `l2_by_price_band` `<10` cell (0.5 via stored
  template, 0.25 via inline set) is what
  `prior_fitment_rate` reads from the run's stored bindings;
  the merge keeps `supply_share_simulated` 0.10 untouched.
- `test_automotive_run_defaults_to_twelve_ticks`: no
  `tick_count` → 12 ticks, 13 snapshots.

Tick drivers (`tests/test_tick_drivers.py`, 22 tests):

- `test_driver_may_reference_its_own_output` /
  `test_initial_formula_may_not_reference_itself` /
  `test_driver_may_reference_tick` /
  `test_initial_formula_may_not_reference_tick` /
  `test_initial_formula_may_not_reference_driver_output` /
  `test_driver_may_reference_earlier_driver_output` /
  `test_forward_reference_rejected_for_drivers`: the scope
  rules of §1.3, each pinned by kind
  (`formula_unknown_ref`).
- `test_driver_output_colliding_with_sampled_id_is_exempt`
  vs `test_initial_output_colliding_with_sampled_id_still_rejected`
  (`formula_output_collides_with_variable`).
- `test_reserved_tick_output_rejected_for_both_kinds` /
  `test_tick_variable_id_rejected_by_set_validator`
  (`reserved_tick_id`).
- `test_evaluate_tick_drivers_self_reference_reads_current_state`:
  sampled 100, post-rule state 50, ×0.9 driver → 45.0.
- `test_evaluate_tick_drivers_chain_within_tick`: retail
  100 → 90, inventory 1 + 90 = 91 in one tick.
- `test_evaluate_tick_drivers_first_tick_indicator`:
  `max(0, min(1, 2 − tick))` = 1.0 at tick 1, 0.0 at ticks
  2 and 12.
- `test_resolve_run_values_skips_drivers`: sampled
  `{retail: 100.0}`, derived `{growth: 0.05}` — no driver
  output at run start.

Rule scaling (`tests/test_rule_effect_scaling.py`, 10 tests):

- `test_scaled_effect_multiplies_by_scope_value`: 6.0 × 0.5
  = 3.0, 6.0 × 1.2 = 7.2; missing/non-finite ids fall back
  to 6.0 (two more tests).
- `test_yaml_scale_by_malformed_fails_loudly`: `""`, `"   "`,
  `42`, `["x"]` all raise `ValueError` at load.
- `test_automotive_rules_file_shape`: 10 rules with the
  pinned id set; no `trigger_conditions`; exactly one
  scaled effect (`auto.demand_surge`, production 6.0 ×
  `consumer_confidence_proxy`); the changeover rule targets
  `generation_transition_index` +0.05.

Splits (`tests/test_splits.py`, 26 tests):

- `test_f02_regression_supplier_shares_summing_to_two_refused`
  vs `test_valid_supplier_split_01_09_passes`;
  `test_sagitar_two_subpopulations_pass` (0.6/0.4 generations
  with flipped 0.1/0.9 splits);
  `test_generation_transition_structure_passes`.
- Sum gates: `nameplate_shares_sum`, `generation_shares_sum`,
  `trim_shares_sum`, `supplier_shares_sum` — one test each.
- `test_one_host_backstop_fires`: 0.6/0.6 shares with full
  fitment fires both `supplier_shares_sum` and
  `one_host_fitment_exceeded`.
- `test_aggregate_units_production_spine_math`: volume 100 →
  slot units 2.4 / 21.6 / 5.6 / 50.4, total 80.0.
- `test_own_sales_with_share_and_prospect_zero`: prospect
  market capacity 4000.0 computed, prospect own sales 0.0
  with default share 0.10; override 0.5 → 4000.0 for the
  existing OEM.
- `test_generation_mix_at_index`: index 0.0 → {1.0, 0.0};
  0.3 → {0.7, 0.3}; 1.0 → {0.0, 1.0}; always sums to 1.0.
- `test_prior_fitment_rate_lookup_and_missing_cell` /
  `test_simulated_supply_share`: loud failure on every
  missing/malformed shape.

Pack/template (`tests/test_automotive_pack.py`, 10 tests):

- `test_pack_registered_and_state_fields`: 27 fields;
  production 287.8, retail 197.9, wholesale 246.3, export
  59.2, utilization 0.662, inventory 1.35, cash 100.0,
  transition index 0.0, DMS 0.0, tax 0.05, margin 0.191.
- `test_template_spec_counts_and_driver_flags`: 24
  variables, 8 formulas, 5 drivers in pinned order; every
  variable has unit + evidence_ref; exactly the 3
  sensitivity ids are unbound to state fields.
- `test_builtin_automotive_template_validates` /
  `test_builtin_corporate_template_unchanged` (0 variables,
  0 formulas, empty assumption data).
- `test_template_assumption_data_lookup_cells`: L2 <10 =
  0.111, 40–60 = 0.901; domain controller >20 = 0.864;
  city NOA 25–30 = 0.57; intelligent cabin NEV 0.90 / ICE
  0.633; simulated share 0.10 with simulated provenance;
  pack copies are mutation-isolated.
- `test_resolve_assumption_data_bindings_win` /
  `..._template_snapshot_fallback` / `..._empty_when_absent`.

## 5. How to run / verify

```bash
cd ~/workspace/mingjian-base
git checkout strategy-engine/phase1-auto-pack
env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest \
  tests/test_tick_drivers.py tests/test_rule_effect_scaling.py \
  tests/test_splits.py tests/test_automotive_pack.py \
  tests/test_automotive_api.py -q
# Full backend suite:
env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest -q
# Sprint 0 smoke (revert the evidence file afterwards):
env -u NO_PROXY -u no_proxy .venv/bin/python docs/sprint0/smoke_e2e.py
git checkout -- docs/sprint0/smoke-evidence.json
# Migration drill (scratch DB):
PLANAGENT_DATABASE_URL="sqlite+aiosqlite:////tmp/phase1-mig.db" \
  .venv/bin/python -m alembic upgrade 0036_direction_mappings
PLANAGENT_DATABASE_URL="sqlite+aiosqlite:////tmp/phase1-mig.db" \
  .venv/bin/python -m alembic upgrade head   # 0037
PLANAGENT_DATABASE_URL="sqlite+aiosqlite:////tmp/phase1-mig.db" \
  .venv/bin/python -m alembic downgrade 0036_direction_mappings
PLANAGENT_DATABASE_URL="sqlite+aiosqlite:////tmp/phase1-mig.db" \
  .venv/bin/python -m alembic upgrade head   # re-up
```

## 6. Known limits

- Dynamics are COARSE by design (Ho: coarse first, then
  refined). All transmission coefficients except the three
  sensitivity variables are formula literals; no public
  elasticities exist anywhere (synthesis A9). The tax anchor
  (1.25) is an event observation, not a structural estimate.
  Magnitudes are sensitivity-analysis inputs, not forecasts.
- The income / LPR / raw-materials links of the 12-link
  chain are NOT in the drivers: `income_index` enters only
  through F1; `lpr_proxy` and `material_cost_index` are
  state fields with no driver and no rule in Phase 1. The
  NEV/ICE dual-track dynamics are not modeled (energy is a
  split-structure attribute, not a state dynamic).
- Generation transition is one global index (§3); the
  changeover rule fires on evidence keywords, not on a
  per-nameplate calendar.
- The S-layer is not engine-wired (§3); capacity numbers
  come from the pure helpers, not from run output.
- Rule `trigger_conditions` remain unevaluated engine-wide
  (pre-existing); automotive rules deliberately avoid them.
- The repeated-rule escalation multiplier (×1.15, ×1.30
  capped — pre-existing engine behavior, discovered while
  writing the scaled-effect test) applies to scaled and
  fixed effects alike; the scaled-effect test pins the
  tick-1 value and the escalation-invariant ratio.
- `input_hash` includes the hindsight-firewall decision
  time, which defaults to creation time (pre-existing
  Sprint 3/5 behavior): two identical payloads created at
  different instants have different input hashes. Tests
  that compare hashes pin `decision_time`.
- The one-host product set {P01, P04} is a Phase 1 design
  decision pending Ho's confirmation.
- `ONE_HOST_PRODUCTS`, the 0.10 simulated supply share, and
  the policy thresholds (except the 1.5 inventory line) are
  assumption parameters awaiting Ho's real data / decisions.
- Docker stack, Postgres/Redis, real-browser rendering,
  and live-LLM paths remain unverified (standing limits).

## 7. Cockpit check

No frontend file changed; no frontend re-run. The cockpit
has no automotive views (Phase 1 scope: backend + pack +
template + tests only).

## 8. Deferred (out of scope, recorded deliberately)

- Per-nameplate generation schedules + run calendar.
- Promoting the literal coefficients to variables (tornado
  analysis over all of them).
- Income / LPR / raw-materials transmission links; NEV/ICE
  dual-track dynamics.
- S-layer engine wiring (run snapshots → capacity).
- Sub-product variant dimension (4G/5G within P04, etc.).
- Cockpit UI for automotive runs, split-structure editing,
  and stored-template lookup editing.
- Direction-as-variable-overrides (option B) and
  LLM-proposed directions (option C) — standing deferrals.
- Calibration of the template against real internal data
  (Ho's trim-split file + internal calibration file, both
  still to arrive; simulated values stand in, labeled).

## 9. Commits on this branch

- `3b1eaf2` — tick-driver formulas + variable-scaled rule effects
- `1e3e1e7` — automotive domain pack + built-in template +
  assumption-data persistence (migration 0037)
- `239b994` — split gates + automotive engine integration + report
- `7bd7921` — pre-existing test updates for the new model shape
- (this commit) — Phase 1 report, backlog update, verification log

## 10. What was NOT verified

- Live-LLM deliberation on automotive runs (no LLM call in
  this sprint by design); skill-template quality for
  automotive content (templates are domain-generic).
- Real-backend integration over HTTP for the new endpoints
  surface (tests use TestClient, as in prior sprints).
- Docker / Postgres / Redis behavior of the new code.
- The 180s-timeout deliberation retest running concurrently
  in `~/workspace/mingjian-delib` was not touched and is
  unaffected by this branch.

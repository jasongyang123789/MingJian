# S-layer real splits — workbook splits + stored OEM shares

Branch: `strategy-engine/s-layer-real-splits`, from
`strategy-engine/sprint20-cockpit-seminar` @ `23aafb7`. Nothing
merged, nothing pushed, `BACKLOG.md` untouched. Ho approved the work
with data ready: (a) S-layer OEM shares become STORED run inputs
instead of caller-supplied values, and (b) the simulated splits are
replaced with the REAL workbook splits. Workbook V8.5 governs
throughout (Ho 2026-11-17); screenshot A is a secondary Jan–Sep
snapshot and no screenshot value is used anywhere.

What landed: a workbook-derived split structure (5 OEMs, 92
nameplates, 268 rows) whose aggregated capacity reproduces the
workbook's Hongqi totals exactly; a stored OEM mix validated by the
run-creation gate, carried in the run fragment, inherited by
re-simulation, and used by the sales-layer endpoint when the request
body omits shares; and one semantic refinement the real data forced
— the supplier-share gate now groups rows by SOLUTION slot
(product + solution code), with the one-host backstop staying
product-level. Two prompt-engine corrections the real labels
exposed (supplier-share-weighted camera totals, segment-aware
camera-count parsing) are included, each with its own test. No LLM
call was made anywhere; everything is deterministic tables +
arithmetic.

## 1. What was built

### Data tables (`services/splits/real_data.py`, new, generated)

Generated 2026-11-18 from the extraction CSVs, never hand-typed
(the generator output was reviewed row-class by row-class before
splicing; the module docstring records the filter):

- `HONGQI_WORKBOOK_ROWS`: 152 rows — the 181 extract entries minus
  15 screenshot-only/duplicate rows (including the P03 duplicate
  display rows, which would overstate P03 by 54,089,631) minus 14
  rows with an empty workbook fitment or an `NA` solution. The HS7
  PHEV P04 row (empty solution name, real fitment/supplier/price)
  is KEPT as an unnamed solution.
- `FORECAST_2026_ROWS`: 110 forecast data rows (blank cells `None`,
  summing as 0 per the extraction report).
- `JAN_OCT_VOLUMES`: 27 Hongqi Jan–Oct volumes totaling 213,992
  (国悦 QM7 at 487 — its capacity lines use 国悦's shared volume
  cell, proven by cap_wb; HS9 PHEV at 0).

### Builder (`services/splits/real_structure.py`, new, pure)

`build_real_structure()` returns the full 5-OEM structure;
`build_hongqi_structure(shares_source=...)` returns the Hongqi-only
structure on either the `forecast_2026` or the `jan_oct_actuals`
share base; `real_oem_shares()` / `REAL_OEM_SHARES_2026` compute
the stored 2026 OEM mix from the forecast tables. Transformation
rules T1–T8 and labeled assumptions A1–A7 are documented in the
module docstring; every rule is enforced by a loud assertion (a
violated rule refuses to build rather than guessing). The builder
asserts all five forecast market subtotals (979,925 / 300,236 /
637,097 / 103,698 / 280,259) and the Hongqi model-set identity
between the two extracts (27 = 27 after the two explicit name
mappings).

Trim derivation (T1): both `低配`/`高配` prefixes → two trims with
shares from the split rows' fitments (P02/P05 agreement asserted —
all nine split models agree exactly); a lone split label at fitment
1.0 (E-HS9, HQ9 GAS) is a naming artifact → single trim; a lone
partial label refuses. Within a split trim the row fitment becomes
1.0 (the trim IS the sub-population); whole-model rows repeat in
every trim. Multi-supplier `A/B` cells (16, all P05) split 0.5/0.5
(T3, labeled assumption); `/` suppliers kept verbatim. Only the
P-H9 P01 华为 row is `bundle` (T7, Ho Q11). Energy from name
markers, HEV → ICE per the Chinese 新能源 definition, unmarked →
ICE labeled assumption (T8). Every nameplate: one `current`
generation, `price_band` `"unknown"`, `model_year` 2026, morphology
unset (T5/T6/A2).

Placeholders (A1): 64 non-Hongqi forecast models + HS9 PHEV + one
Dongfeng Honda placeholder carry a single P.O row (fitment 0.0,
supplier `UNKNOWN`, price 0.0) — zero units, zero capacity, R13
flag. No fitment, price, or supplier is invented for them.

### Stored OEM shares (`services/splits/models.py`, `domain/api.py`, `services/simulation/engine.py`)

- `OemProductionShares{shares, source, as_of?, notes?}`
  (`extra="forbid"`): shape rules in the model (non-empty map,
  per-value [0, 1], non-empty provenance source); coverage + sum
  rules in `validator.validate_oem_shares` / `oem_share_issues`,
  shared with the S-layer's `_validate_shares` so the two paths
  cannot disagree (messages identical to Phase 2, preserving the
  route's error-code mapping).
- `SimulationRunCreate.oem_production_shares`: optional. The
  creation gate refuses shares without a structure
  (`oem_shares_require_split_structure`) and shares that fail
  coverage/sum — before any row is written, mirroring the split
  gate. The fragment stores the shares beside the structure, so
  the Sprint 3 input hash covers them (different mix = different
  run, correctly).
- Living loop (`living_loop.py`): `_build_resimulation_payload`
  inherits the stored shares wholesale with the structure;
  malformed stored shares refuse (`loop_corrupt_baseline_fragment`)
  rather than dropping the mix silently.

### Route + S-layer (`api/routes/automotive.py`, `services/splits/sales_layer.py`)

- `POST /runs/{id}/automotive/sales-layer`: `oem_production_shares`
  is now optional. Resolution: explicit body > stored shares >
  400 `automotive_oem_shares_required`. A body override affects
  only that computation — it never rewrites the stored input.
- `compute_sales_layer` gains `shares_source` (default
  `"caller-supplied"`, preserving the Phase 2 assumption string
  verbatim); the route passes `stored input <source> (<as_of>)`
  for stored shares, so the assumptions list records provenance.
- `GET /runs/{id}/automotive/split-structure` now also returns the
  stored shares (`oem_production_shares`, `null` when absent).

### Solution slots (`services/splits/validator.py`, `models.py` docstring)

The supplier-share sum gate and the duplicate-row gate group rows
by (product, solution code). The one-host backstop stays
product-level (weighted sum across all solutions of P01/P04 in the
trim). Uncoded rows group into one slot per product, so Phase 1
structures without solution codes validate exactly as before.
Why: the real data is unrepresentable under per-product slots —
Hongqi H5 carries two P03 solutions from the SAME supplier at full
fitment (duplicate gate refuses), E-H7 carries two P03 solutions
from DIFFERENT suppliers (sum gate halves them). See §2.

### Prompt-engine corrections (`services/splits/expectations.py`, `services/splits/aliases.py`)

- `_p05_total` weights rows by supplier share, so a camera group
  split across two suppliers counts once, not twice (16 real P05
  splits). Behavior-preserving for all existing fixtures (all
  shares 1.0).
- `parse_camera_count` parses per segment (marker factor × `*N`
  multiplier): `"前视三目摄像头*1"` → 3 (was 1),
  `"环视摄像头*4 前视双目摄像头*1 后视摄像头*1"` → 7. The old
  parser honored 双目/三目 only when no multiplier existed
  anywhere; the real labels carry both. All nine pinned cases
  still pass; the corrected parses align exactly with the R2
  ladder (7/10/11).

## 2. Design decisions

### Solution slots keep every hard gate hard

The refinement changes the SLOT DEFINITION, not the gate
strength: sum-to-1 still enforced (per solution, strictly more
precise), one-host still ≤ 1 (product-level, unchanged
arithmetic), rate/count separation untouched. Two existing
fixtures encoded the superseded per-product slot and were updated
with intent preserved (see §4): the Q7 four-solution fixture
(0.25 → 1.0 shares — the old shares understated every solution's
units 4×) and the R6 overlap fixture (0.5 → 1.0). No other
existing test changed behavior.

### Stored shares: creation-time + inheritance, no PATCH endpoint

Shares are run INPUTS, so they attach at creation beside the
structure they cover and inherit through re-simulation. A PATCH
endpoint for existing runs was deliberately NOT built: no
production runs depend on the S-layer yet, and the creation-time
path covers the lifecycle. Follow-up if the cockpit needs it (§6).

### The modeled-set denominator is provenance, not a footnote

The stored mix sums over the modeled FAW set only (1,917,258 =
899,054 + 80,871 + 300,236 + 637,097). 一汽奔腾 (103,698) and
一汽解放 (280,259) are excluded — no workbook trim sheets — and
the exclusion is recorded in the shares' `notes`, in the module
docstring, and here. The engine total is therefore interpreted
as modeled-set production. Jetta splits out of 一汽大众 by name
(8 models, 80,871); Audi stays in FAW-VW (Ho: spine includes
Audi). Dongfeng Honda: prospect, 0.0, no forecast volume.

### Reconciliation base: Jan–Oct actuals, corrected arithmetic

Nameplate shares default to the 2026 forecast (the forward mix).
Reconciliation uses the Jan–Oct actual base (213,992) because the
workbook's capacity totals are Jan–Oct arithmetic. P01 reconciles
to the CORRECTED total 400,940,700 — the structure reproduces
correct volume × fitment × price arithmetic, not the workbook's
displayed G53 bug cell. The `capacity_recomputed` extract column
was not used (it mixes screenshot volumes for shared-pool
models).

### Judgment calls, each surfaced by the prompt system

- P-H9 P02 华为 stays `discrete` (Q11's bundle resolution names
  the P01 row; the workbook counts P02 as an additive line). The
  BUNDLE1 prompt flags it — the judgment is visible, not buried.
- HEV → ICE (Chinese 新能源 definition). Unmarked models → ICE
  (labeled assumption, placeholder nameplates only, aggregation
  never reads energy).
- Equal 0.5/0.5 supplier splits (workbook gives no ratio).
- 国耀/国礼 name mapping is explicit per model, never fuzzy.

### What was deliberately NOT built

No cockpit UI change (the equal-split form default is now
overridable by stored shares; the form follow-up is §6). No
generation-transition schedules (no generation data in the
extracts). No morphology inference. No VW/Toyota/Jetta trim
extraction (no data — placeholders instead, never Hongqi patterns
generalized: Q9).

## 3. Integration points

- Run fragment shape: `configuration["split_structure"]` gains an
  optional `oem_production_shares` member beside `structure` /
  `validation`. Old fragments (no shares) read as `null` shares;
  the sales-layer endpoint then requires body shares, as before.
- Determinism: shares enter the Sprint 3 input hash via the
  fragment (no hash-code change; verified by construction — the
  hash covers the whole configuration dict).
- S-layer precedence: body shares > stored shares > refusal. The
  computation itself is unchanged (same aggregation, same gates).
- Prompt evaluation over the full real structure: 81 prompts
  (R13 ×66 = the placeholders; EMBED1 ×11 info; BUNDLE1 ×2, both
  P-H9; R1 ×1, the HS6 低配 data gap; R2 ×1, the genuine H9
  IFC/11-camera tension). Morphology rules skip all 101 trims
  (morphology unset). Prompts never refuse — the three
  anomaly-class flags are exactly the judgment calls and data gaps
  a reviewer should see.

## 4. Verification

New tests: 28 (11 in `tests/test_splits_solution_slots.py`, 17 in
`tests/test_s_layer_real_splits.py`). Targeted subsets run, all
green: the 2 new files (28) + `test_phase2_splits.py` (28) +
`test_splits.py` / `test_phase2_sales_layer.py` /
`test_phase2_prompts.py` / `test_automotive_api.py` /
`test_automotive_phase2_api.py` / `test_loops_api.py` (119) +
`test_mece_api.py` / `test_phase2_simulation_api.py` /
`test_simulation_action_selection.py` /
`test_variable_templates_api.py` (30) = 205 tests, 0 failures.
Lint: `ruff check` on all touched files reports exactly the 6
pre-existing errors (3× B008 route defaults, I001 + UP037 in
`domain/api.py`, I001 in `engine.py`, all confirmed present at
baseline via `git stash`); zero new findings. No full suite was
run (protocol: flock helper + ≥750M /dev/shm gate + ~10-minute
window, with other agents running concurrently) — a full-suite
re-proof is the merger's gate, not claimed here.

### Behavior evidence (all asserted test values, with test names)

| Claim | Value | Test |
|---|---|---|
| Real structure validates; OEM order + nameplate counts | 5 OEMs; 27/37/8/19/1 = 92; `5 OEM(s), 252 slot(s), 268 row(s)`; per-OEM share sums 1.0 | `test_real_structure_validates_and_counts` |
| H5 split trims; within-trim P02 fitment; P01 repetition | 低配 0.7 / 高配 0.3; P02 fitment 1.0 in-trim; P01 8155 in both | `test_real_structure_hongqi_trim_splits` |
| HS6 zero-share trim kept; lone-label artifacts single-trim | HS6 0.0/1.0; E-HS9 + HQ9 GAS single `全车型` | `test_real_structure_hongqi_trim_splits` |
| Pinned workbook values | 8620/富赛/3164.39; J3 IFC `/`/400; E-H7 8155+8397 @0.5; H9 扶手屏 0.2/712; P-H9 bundle 6000, no P04/P05; HS7 PHEV P04 unnamed 540; P05 splits 0.5/0.5 | `test_real_structure_pinned_workbook_values` |
| Placeholders: count + zero contribution + prospect | 66; P.O/0.0/`UNKNOWN`/0.0; HS9 share 0.0; DFH prospect + `待开发车型` | `test_real_structure_placeholders_contribute_zero` |
| Energy / bands / generations | E-QM5 NEV, H5 ICE, 锐放 HEV ICE, Q4 e-tron NEV; all bands `unknown`, year 2026, single `current`/`mature`, morphology `None` | `test_real_structure_energy_bands_and_generations` |
| Jan–Oct base | 27 models; total 213,992; QM7 487; HS9 0 | `test_jan_oct_volumes_base` |
| Reconciliation vs workbook R64 | P01 400,940,700.0; P02 292,627,657.695; P03 260,430,343.2; P04 86,578,384.0; P05 131,743,360.0 (abs tol 0.01, float-summation noise); P.O 0.0 | `test_jan_oct_reconciliation_matches_workbook_totals` |
| Unknown share base refuses | `ValueError: Unknown shares_source` | `test_build_hongqi_structure_rejects_unknown_source` |
| Prompt evaluation on the real structure | Report returned; R13 flags present; BUNDLE1 flag on a P-H9 path | `test_real_structure_prompts_evaluate_without_refusal` |
| Stored mix values + provenance | faw-vw 899054/1917258; jetta 80871/1917258; hongqi 300236/1917258; faw-toyota 637097/1917258; DFH 0.0; sum 1.0; source `faw_volume_forecast_2026`, as_of `2026`; notes name the modeled set + exclusions; `validate_oem_shares == []` | `test_real_oem_shares_values_and_provenance` |
| Creation stores shares; GET returns them | Shares + source + as_of round-trip | `test_run_creation_stores_oem_shares` |
| Creation refuses bad shares, writes nothing | Sum 0.9 → 400 `split_validation_failed` + `oem_shares_sum`; shares-without-structure → `oem_shares_require_split_structure`; run list empty | `test_run_creation_refuses_bad_shares_and_writes_nothing` |
| S-layer uses stored shares when body omits them | Same summary + rows as the explicit-body call; assumption names `stored input test-fixture (2026)` | `test_sales_layer_uses_stored_shares_when_body_omits_them` |
| Body shares override stored | Assumption says `caller-supplied`; per-OEM tick-1 capacities differ | `test_sales_layer_body_shares_override_stored` |
| No shares anywhere refuses | 400 `automotive_oem_shares_required` | `test_sales_layer_without_any_shares_refuses` |
| Living loop inherits stored shares | Rebuilt payload carries the shares + structure | `test_living_loop_inherits_stored_shares` |
| Full real structure end-to-end via API | 92 nameplates round-trip; S-layer 200 from stored shares alone; `oem_count` 5; capacity > 0; `supplier_rows` basis | `test_real_structure_end_to_end_via_api` |
| Two solutions, same supplier / different suppliers | Both validate | `test_two_solutions_same_supplier_validate`, `test_two_solutions_different_suppliers_validate` |
| Same-solution split: 0.6+0.3 refuses, 0.9+0.1 validates | `supplier_shares_sum` / valid | `test_same_solution_supplier_split_must_sum_to_one`, `test_same_solution_supplier_split_valid` |
| Duplicate supplier+same solution refuses | `duplicate_supplier_slot` | `test_duplicate_supplier_same_solution_refused` |
| Uncoded rows group per product (Phase 1 preserved) | 1.0+1.0 refuses; 0.5+0.5 validates | `test_uncoded_rows_group_per_product` |
| One-host backstop spans solutions | 1.0+1.0 → `one_host_fitment_exceeded`; 0.5+0.5 validates | `test_one_host_backstop_spans_solutions` |
| Split P05 counts once in the R2 ladder (rate + count) | No R2 flag in either variant | `test_p05_supplier_split_counts_once_in_ladder`, `test_p05_count_split_counts_once_in_ladder` |
| Share model + gate: bad values, exact coverage, prospect 0 | `ValidationError` ×3; `[]` / unknown+missing / `oem_shares_sum` / prospect-zero `[]` | `test_oem_shares_model_rejects_bad_values`, `test_validate_oem_shares_accepts_exact_coverage` |
| Camera-count parsing incl. real labels | 7 / 10 / 11 for the three real group labels; all 9 pinned cases unchanged | `test_parse_camera_count` (extended) |
| Q7 + R6 fixtures under solution slots | Rates summing to 1.2 validate; overlap stays prompt-not-refusal | `test_fitment_rates_need_not_sum_to_one`, `test_r6_overlap_is_a_prompt_not_a_refusal` (fixtures updated, intent preserved) |

## 5. How to run / verify

```bash
# New + directly affected subsets (dynamic TMPDIR per AGENTS.md protocol)
TMPDIR=/dev/shm/pytest-tmp-slayer env -u NO_PROXY -u no_proxy \
  .venv/bin/python -m pytest tests/test_splits_solution_slots.py \
  tests/test_s_layer_real_splits.py tests/test_phase2_splits.py \
  tests/test_splits.py tests/test_phase2_sales_layer.py \
  tests/test_phase2_prompts.py tests/test_automotive_api.py \
  tests/test_automotive_phase2_api.py tests/test_loops_api.py -q
# Lint (new/changed files; expect only the 6 pre-existing findings)
.venv/bin/python -m ruff check src/planagent/services/splits/ \
  src/planagent/services/simulation/engine.py \
  src/planagent/services/simulation/living_loop.py \
  src/planagent/domain/api.py src/planagent/api/routes/automotive.py \
  tests/test_splits_solution_slots.py tests/test_s_layer_real_splits.py
# Rebuild + reconcile by hand
.venv/bin/python -c "
from planagent.services.splits import build_hongqi_structure, aggregate_units, aggregate_capacity
s = build_hongqi_structure(shares_source='jan_oct_actuals')
print({p: round(sum(r['capacity'] for r in aggregate_capacity(aggregate_units(s, {'hongqi': 213992.0})) if r['product_id'] == p), 3) for p in ('P01','P02','P03','P04','P05')})"
```

## 6. Follow-ups / known gaps (not built here)

1. **Cockpit**: the automotive S-layer form still defaults to
   equal-split shares. It should offer "use stored shares" now
   that runs can carry them (and surface the stored mix on the
   split-structure view). Backend-ready; no API change needed.
2. **PATCH endpoint for shares** on existing runs, if the cockpit
   flow needs attach-after-creation (§2).
3. **VW/Toyota/Jetta trim extraction**: 64 placeholder nameplates
   await real workbook extraction, per model, per the Q9 rule —
   including generation-transition schedules (T-Roc/CC) and
   morphology facts. The placeholder shape makes the replacement
   mechanical (swap the trim tree, keep the shares).
4. **Price bands + energy verification**: `price_band` is
   `unknown` everywhere; unmarked-model ICE defaults need
   per-model verification against the forecast's product data.
5. **The H9 R2 flag** (J3 IFC + 11 cameras vs ladder 5±1) and the
   **P-H9 P02 bundle judgment** are live prompt findings for Ho's
   review, not defects: the prompt system surfaces them; it does
   not resolve them.
6. **Full-suite re-proof** at merge time (see §4).

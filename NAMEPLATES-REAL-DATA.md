# Nameplates: real data for the 64 placeholder nameplates

Track 2, 2026-11-19. Branch `fix/nameplates-real-data`, base `83bb09f`
(tip of `fix/backtest-improvements`). No merge, no push.

## Result

- **Placeholders: 66 → 19.** 47 replaced with real workbook trim trees:
  22 FAW-VW + 8 Jetta + 16 FAW-Toyota members + 1 extra Dongfeng Honda
  nameplate (DFH had 1 placeholder; it now has 7 real nameplates).
- **Nameplates: 92 → 98** (27 Hongqi + 37 FAW-VW + 8 Jetta + 19
  FAW-Toyota + 7 Dongfeng Honda). Structure detail:
  `5 OEM(s), 523 slot(s), 560 row(s)` (was `252 slot(s), 268 row(s)`).
- **Remaining 19 placeholders** (labeled, never invented):
  - 15 FAW-VW: every Audi / Audi e-tron forecast model — no sheet rows
    at all (`Audi A3 Sportback`, `Audi A4L`, `Audi A5L（B10）`,
    `Audi A6L（C9）`, `Audi Q3`, `Audi Q5L NF`, `Audi A3 Limousine`,
    `Audi Q2L`, `Audi Q3 Sportback PA`, `Audi Q5 Sportback`,
    `E6L Limousine`, `Q6L e-tron  LWB`, `Q6L e-tron  SB`, `A4 e-tron`,
    `Q4 e-tron`). The 一汽大众-2026 sheet covers only the VW brand.
  - 3 FAW-Toyota: `兰德酷路泽`, `考斯特`, `960D PHEV` — no sheet rows.
  - HS9 PHEV: forecast-only, zero 2026 volume, no Hongqi-sheet rows.
- **Dongfeng Honda is no longer a placeholder.** Its 7 sheet models
  carry real trim trees on sheet-volume shares (A9); the OEM share
  stays 0.0 (prospect), so its S-layer sales stay 0.

## Source

Governing workbook V8.5
(`~/workspace/user/files/-20261110_-_____-_V8.5.xlsx`, 20 sheets).
The four 2026 OEM sheets were extracted with
`~/workspace/research/strategy-engine/extract-oem-2026.py`
(reproducible; openpyxl `data_only=True` + full load + single forward
snapshot) into `oem-2026-extract.csv` (348 entries → 295 included
rows). The 修正版 copy differs only in formula-cached capacity/volume
cells — every solution/fitment/supplier/price input cell identical —
so extraction uses the original V8.5.

New tables in `src/planagent/services/splits/real_data.py`
(same 8-tuple shape as `HONGQI_WORKBOOK_ROWS`):
`VW_WORKBOOK_ROWS` 175, `JETTA_WORKBOOK_ROWS` 33,
`TOYOTA_WORKBOOK_ROWS` 45, `DFH_WORKBOOK_ROWS` 42, plus
`SHEET_JAN_OCT_VOLUMES` (the per-sheet Jan-Oct volume base).

Row filter (mirrors the Hongqi filter, plus sheet-specific exclusions,
each recorded with a reason in the extract CSV):
- `NA` / `NA EOP` solutions (31) — no product data. Jetta P04 is NA
  on every row: Jetta genuinely has no T-BOX (Ho Q10).
- Empty fitment (2): New ID.4 R89 P05 (capacity 0) and Jetta J03 P02
  `NGX:J6M` (supplier `TBD`, no fitment/price).
- Jetta VA3 P05 11-camera group (Ho Q6 misfill; the VA7 `1M*1` row is
  the correct pattern). The 2027 sheet corroborates: VA3 shows the
  `1M*1` 0.8 pattern there.
- 揽镜 PA R80 P02 RHP (F03 copy-slip: identical to R76 in all fields).
- KEPT: six VW P03 rows at fitment 0.0 (the workbook says zero, like
  HS6's zero-share trim); Jetta M6's 11-camera row (inspected
  individually per Q9 — new J01 platform, full P02/P03/P05 set,
  persists in 2027).

## Transformation rules (extend T1–T8)

- **T9 Instrument re-homing.** VW/Toyota/DFH sheets put 仪表 in the
  P01 column; the locked definition says P03 = display incl. 仪表
  (Ho 2026-11-16, F14). Every P01 row naming an instrument is moved
  to P03, fitment/supplier/price unchanged. Capacity-neutral across
  P01+P03; required by the one-host backstop (left in P01, the
  instrument rows would push P01 over 1.0 on most models).
- **T10 Same-solution multi-row supplier splits**, distinguished by
  the fitments, never guessed. Case A (unequal fitments are the
  suppliers' shares; slot = sum; share = fitment/sum; sum > 1
  refuses): Toyota 仪表/SA8155P groups, all summing to exactly 1.0.
  Case B (equal fitments repeat the slot rate; equal supplier split,
  labeled assumption A7): Jetta `1M*1` 0.8/0.8, DFH `前视+环视`
  0.5/0.5. A repeated (product, solution, supplier) pair refuses.
  Either case preserves the one-host weighted sum.
- **T11 Row-group partitions.** 速腾's two row-groups are two
  sub-population trims (`子人群1` / `子人群2`); 探歌's two row-groups
  are two generations (`prev`/`phase_out` / `current`/`ramp`) — the
  agreed F02 readings. Group weights 0.5/0.5 are LABELED assumptions
  (A7): the workbook gives no weights; the 2027 sheet (single merged
  速腾 group; 探歌 8155-only) corroborates the grouping but supplies
  no 2026 weights. No transition schedule for 探歌 (no timing data).
- **T12 Toyota families.** The sheet lists 8 family models; the
  forecast splits them into 19 powertrain variants. Each family trim
  tree applies verbatim to every member (explicit map, never fuzzy).
  BZ5 has sheet rows but no forecast row: sheet-only, not a
  nameplate.

New labeled assumptions: A7 extended (equal 0.5/0.5 splits wherever
the workbook gives no ratio), A8 (Toyota family trees verbatim), A9
(DFH nameplate shares from sheet Jan-Oct volumes — its only volume
source), A10 (sheet-vs-forecast volume conflicts reported, never
resolved by adjusting either side).

## Reconciliation (the proof)

`build_sheet_structure(oem_id)` builds the single-OEM structure on
the sheet Jan-Oct volume base; aggregated capacity reproduces the
corrected workbook totals exactly (abs tol 0.01). The targets were
computed by an independent re-implementation of the builder rules
(`generate-oem-2026-tables.py`), so the test pins the builder against
a second implementation, not against itself.

| OEM | base volume | P01 | P02 | P03 | P04 | P05 |
|---|---|---|---|---|---|---|
| faw-vw | 466,868.16 | 660,824,539.73 | 266,767,704.00 | 411,044,298.32 | 280,984,880.00 | 150,197,353.75 |
| jetta | 64,468 | 57,606,892.88 | 1,994,552.00 | 12,765,580.00 | 0.00 | 3,154,490.40 |
| faw-toyota | 510,277 | 1,251,331,300.00 | 7,782,740.00 | 482,098,475.00 | 405,009,600.00 | 189,595,600.00 |
| dongfeng-honda | 160,034.44 | 240,051,666.67 | 0.00 | 232,049,944.44 | 86,962,166.67 | 36,007,750.00 |

All 20 totals match with diff ±0.00. The corrected totals decompose
exactly against the displayed sheet totals (see the generator's
delta accounting): 速腾/探歌 halving, 仪表 P01↔P03 shifts
(VW ±75,521,291.20; Toyota ±461,838,875.00; DFH ±128,027,555.56),
Case B halving (Jetta P05 −1,568,102; DFH P05 halved from 72,015,500),
the 揽镜 dup (−1,605,450), the VA3 misfill (−358,784).

## Sheet-vs-forecast volume conflicts (reported, unresolved)

- 探岳 family mix: sheet Jan-Oct 20/10/70 vs forecast full-year
  63/2/34 (Nov–Dec would need ~12x the PA monthly rate).
- New ID.4's sheet volume is `1888×0.7` (ID.4's forecast) while the
  forecast also carries a separate New ID.4 line (10,905).
- ID.AURA sheet Jan-Oct volume (3,815.56) exceeds its full-year
  forecast (2,032).
- 速腾 and 速腾 S share one sheet volume cell (52,613; review F17 —
  unresolvable from the workbook).
- Review F17's "592,280 去重后" VW volume total overcounts: the true
  deduped sheet total is 466,868.16 (F17 counted `(N%)`-suffixed rows
  and plain continuation rows as distinct models).

Shares always come from the forecast; trim trees always from the
sheets. The reconciliation base uses sheet volumes, so the sheet's
own arithmetic still reconciles exactly.

## Code

- `src/planagent/services/splits/real_data.py`: four new row tables
  + `SHEET_JAN_OCT_VOLUMES` (docstring documents the filter).
- `src/planagent/services/splits/real_structure.py`: T9–T12,
  A7–A10, `_rehome_instrument`, `_slot_fitments`, `_generic_trims`,
  `_generic_generations`, `_mapped_oem`, `_toyota_oem`,
  `_toyota_sheet_oem`, `_dfh_oem`, `build_sheet_structure(oem_id)`.
  `build_real_structure()` now wires all five OEMs. Every coverage
  mismatch refuses loudly (unknown row-group structure, lone
  generation tag, unmapped/unexpected models, duplicate
  (product, solution, supplier)).
- `src/planagent/services/splits/__init__.py`: exports
  `build_sheet_structure`.
- Tests: `tests/test_s_layer_nameplates_real_data.py` (new, 14 tests:
  pinned values, coverage/refusals, 4 parametrized reconciliations);
  `tests/test_s_layer_real_splits.py` updated (counts 92→98, detail
  string, placeholder set 66→19 with the exact list, DFH's 7 real
  nameplates, 探歌's two generations, e2e 92→98).

## Verification

- Targeted: `tests/test_s_layer_real_splits.py` +
  `tests/test_s_layer_nameplates_real_data.py` — 35 passed.
- `ruff check` on all touched files — clean (zero new findings).
- Full suite: **2113 passed in 650.34s (0:10:50)**, exit 0, under
  `full-run-lock.sh` (TMPDIR `/dev/shm/pytest-tmp-nameplates`,
  794M free pre-start gate passed, single-process). Two attempts:
  the first was killed by a VM reboot at 08:00 (SIGTERM, no output);
  the second timed out after 3600s waiting for the lock (seven
  parallel track agents were queuing full suites that morning); the
  third attempt, `--wait 7200`, acquired the lock and ran green.

## Limits / follow-ups

- **Morphology registry keys don't fire for forecast-named Toyota
  nameplates.** Registry facts exist (Toyota families → `ivi_one_box`
  2026; T-Roc/CC → `fused` 2026) but the prompt engine consults the
  registry only when `trim.morphology` is set, and registry keys
  (sheet family names) don't match forecast names (e.g. `卡罗拉 Long
  HEV` ≠ `corolla`). All new trims leave `morphology` unset (T6
  extended). Needs a name-normalization layer or per-nameplate
  morphology assignment — a separate track.
- **DFH P05 Case A vs B is genuinely ambiguous** (0.5/0.5 could be
  shares of a 1.0 slot). Case B chosen for cross-sheet consistency
  with Jetta's proven convention (same workbook/team/pattern). DFH's
  OEM share is 0.0 so it affects no computed result — but Ho's team
  should confirm which convention the DFH sheet uses.
- **速腾/探歌 50/50 weights are labeled assumptions** awaiting Ho's
  confirmation; no source in the workbook or forecast supplies them.
- **BZ5** (sheet volume 4,015, no forecast row) is sheet-only; needs
  Ho's team to confirm whether it's a 2027 model or a forecast
  omission.
- **Audi/e-tron (15) + 兰德酷路泽/考斯特/960D PHEV (3)** have no
  workbook rows at all: they stay placeholders until Ho's team
  supplies their sheets.

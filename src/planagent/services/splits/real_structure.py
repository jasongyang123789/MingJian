"""Real workbook split structure + stored OEM shares (S-layer real splits).

Builds the MECE bottom-layer structure from the workbook-derived
tables in :mod:`real_data` — the Hongqi model x trim x product splits
(152 workbook rows) and the FAW-dimension 2026 volume forecast (110
model rows) — replacing the simulated splits Phase 1/2 used as
placeholders. Workbook V8.5 governs throughout (Ho 2026-11-17).

Transformation rules (each enforced by loud assertions in the
builder; a violated rule refuses to build rather than guessing):

- T1 Trim derivation. A model whose P02/P05 rows carry BOTH the
  ``低配`` and ``高配`` solution prefixes has exactly those two
  trims; the trim shares ARE the split rows' fitments, and every
  split row for a label must agree (P02/P05 consistency — all nine
  split models agree exactly). Within a split trim the row's fitment
  becomes 1.0: the trim IS the sub-population. A LONE split label
  whose rows all carry fitment 1.0 (E-HS9, HQ9 GAS: a single P05 row
  labeled ``低配：`` covering the whole model) is a naming artifact,
  not a split: single trim, prefix stripped. A lone label with any
  partial fitment refuses to build — a partial sub-population with
  no counterpart is ambiguous. All other rows (``全车型``,
  ``单一``, ``row_group`` labels — the row-group labels are screenshot
  layout, not workbook trim information) apply model-wide and repeat
  in every trim with their workbook fitment.
- T2 Solution codes. The ``低配：``/``高配：`` prefix is the trim
  label, not part of the solution: it is stripped from the code (the
  trim already carries it). All other solution text is verbatim,
  including full-width digits and the literal ``\\n`` in the 4G+5G
  P04 labels. An empty solution (HS7 PHEV P04) becomes
  ``solution_code=None``.
- T3 Multi-supplier cells. ``"A/B"`` supplier cells (16, all P05)
  split into two rows of the same solution, same fitment, same
  price, with supplier shares 0.5/0.5 — a LABELED assumption (the
  workbook gives no ratio). A cell with more than two suppliers
  refuses to build. The ``"/"`` supplier mark (J3/安霸 IFC rows) is
  kept verbatim: the workbook names no supplier there.
- T4 Fitment kinds. Every workbook fitment is a rate (Q7: an
  independent penetration); P05 rows are rate-kind group rows whose
  camera count lives in the solution code (parsed by the prompt
  engine). No count-kind rows exist in the real structure.
- T5 Generations. The extracts carry no generation dimension, so
  every nameplate has one ``"current"`` generation (``mature``, share
  1.0) and no transition schedule. Generation-transition modeling
  (T-Roc/CC) stays a per-model exercise for the VW extraction.
- T6 Morphology. No morphology evidence exists for Hongqi in the
  extracts, so morphology is left unset (never inferred). The
  morphology prompts skip unset trims.
- T7 Price basis. Only the P-H9 P01 华为 row is ``"bundle"`` (Ho
  Q11: the Huawei full-solution bundle price, screen + cameras
  included — it is also why P-H9 carries no P05 row). Every other
  row is ``"discrete"``. The P-H9 P02 华为 row stays discrete: the
  workbook counts it as a separate additive capacity line, and Q11's
  bundle resolution names the P01 row specifically.
- T8 Energy. BEV/PHEV/REEV/``e-tron``/``ID.``/``BZ`` markers mean
  NEV. HEV means ICE: under the Chinese 新能源 definition HEV is not
  a new-energy vehicle. Unmarked models default to ICE — a LABELED
  assumption (the forecast carries no energy column); every unmarked
  model is a placeholder nameplate whose energy affects nothing
  (aggregation never reads it), and the assumption is listed for
  per-model verification, never generalized silently.

- T9 Instrument re-homing. The VW/Toyota/DFH sheets list the instrument
  cluster (仪表) in the P01 column, but the locked product-line
  definition says P03 = display (incl. instrument; Ho 2026-11-16, F14).
  Every P01 row whose solution names an instrument (``仪表`` in the
  solution text) is re-homed to P03 with fitment/supplier/price
  unchanged. The move is capacity-neutral across P01+P03 and is what
  the one-host backstop requires: left in P01, the instrument rows
  would push the P01 weighted fitment over 1.0 on most VW/Toyota/DFH
  models. Hongqi/Jetta need no re-homing (their instruments are
  already P03).
- T10 Same-solution multi-row supplier splits. Two workbook
  conventions exist for one solution carried by two suppliers, and
  the builder distinguishes them by the fitments (never by guessing):
  (Case A) UNEQUAL fitments are the suppliers' shares of the slot —
  the slot fitment is their sum and each supplier's share is its
  fitment over the sum (Toyota 仪表/SA8155P groups, all summing to
  exactly 1.0); a sum over 1.0 refuses. (Case B) EQUAL fitments repeat
  the slot rate on each row — the slot fitment is the repeated rate
  and the suppliers split it equally (Jetta 1M*1 0.8/0.8, DFH
  前视+环视 0.5/0.5; the equal split is labeled assumption A7). A
  repeated (product, solution, supplier) pair refuses: the 揽镜 PA
  R80 RHP row is excluded at generation as an F03 copy-slip duplicate
  (see :mod:`real_data`), never merged. Either case preserves the
  one-host weighted sum.
- T11 Row-group partitions. 速腾's two row-groups (R4–R7 / R8–R11)
  are two sub-populations (trims ``子人群1`` / ``子人群2``) and 探歌's
  two row-groups (R26 / R27–R30) are two generations (``prev``,
  ``phase_out`` / ``current``, ``ramp``) — the agreed F02 readings
  (synthesis §C1: Sagitar pairs are sub-populations with weights;
  T-Roc is a generation transition). Within a group, every row belongs
  to that group only (the 仪表 rows repeat per group, one copy each);
  rows with no group label apply model-wide. The group weights are
  0.5/0.5 — a LABELED assumption (A7): the workbook gives no weights,
  and neither the 2027 sheet (single merged 速腾 group) nor the
  forecast supplies them. No transition schedule is attached to 探歌:
  the workbook gives no start/duration, so the static 50/50 snapshot
  stands until Ho's team supplies timing.
- T12 Toyota families. The 一汽丰田-2026 sheet lists 8 family models
  (卡罗拉, 亚洲龙, 锐放, 荣放, 皇冠陆放, 格瑞维亚 HEV, BZ3, BZ5)
  while the forecast splits them into 19 powertrain variants. Each
  family trim tree applies to every member forecast model (explicit
  map ``_TOYOTA_FAMILY_MAP``, never fuzzy). BZ5 has sheet rows but no
  forecast row: it is sheet-only, not a nameplate. The three forecast
  models with no sheet rows stay placeholders (A1).

Labeled simulated values (explicitly labeled, replaceable — Ho's
internal-calibration ruling) remain where real data is absent:

- A1 Placeholder nameplates: the 15 forecast FAW-VW models with no
  sheet rows (all Audi + Audi e-tron lines — see ``_VW_UNSOURCED``),
  the 3 forecast FAW-Toyota models with no sheet rows (兰德酷路泽,
  考斯特, 960D PHEV — see ``_TOYOTA_UNSOURCED``), and HS9 PHEV
  (forecast-only, zero 2026 volume, no Hongqi-sheet rows) carry a
  single trim with one P.O row (fitment 0.0, supplier ``"UNKNOWN"``,
  price 0.0): zero units, zero capacity, and an R13 prompt flagging
  the un-decomposed basket. No fitment, price, or supplier is invented
  for them. Dongfeng Honda is NO LONGER a placeholder: its 7 sheet
  models carry real trim trees (A9); only its OEM share stays 0.0.
- A2 ``price_band`` is ``"unknown"`` for every nameplate: neither
  extract carries price bands.
- A3 The OEM mix (see :func:`real_oem_shares`) sums over the MODELED
  FAW set only: 一汽奔腾 (103,698) and 一汽解放 (280,259) are
  excluded — they have no workbook trim sheets — and the denominator
  is recorded in the shares' provenance notes. The engine's total
  production is therefore interpreted as modeled-set production.
- A4 Jetta is split out of the 一汽大众 forecast market by nameplate
  name (``Jetta*`` / ``捷达*``, 8 models): the workbook's 捷达 sheet
  is a separate OEM. Everything else in the market — including Audi —
  stays FAW-VW (Ho: volume spine includes Audi).
- A5 Dongfeng Honda is a prospect with share 0.0 (no forecast
  volume); its S-layer own sales stay 0 by the customer-status flag,
  per the Q8/prospect ruling. Its 7 nameplates now carry REAL trim
  trees from the 东风本田-2026 sheet (A9) — the prospect flag, not a
  placeholder, is what keeps its sales at zero.
- A6 The two Hongqi forecast/trim-split name mismatches are mapped
  explicitly (never fuzzy-matched): forecast ``国耀 GAS（N117）`` and
  ``国礼 GAS（V501）`` are the trim-split ``国耀 GAS（C817-01）`` and
  ``国礼 GAS（C872-10）`` (same model names, different internal
  codes). The builder asserts the mapped model sets are identical.
- A7 Equal 0.5/0.5 splits wherever the workbook gives no ratio are
  the only numeric assumptions in the real rows (plus the ICE default
  in T8); all are labeled here and in the report, and all are
  replaceable without touching the transformation rules: the T3 A/B
  supplier cells (Hongqi), the Case B repeated-rate rows (T10: Jetta
  1M*1, DFH 前视+环视), the 速腾 trim weights and the 探歌 generation
  shares (T11).
- A8 Toyota family trees (T12): the sheet gives one configuration per
  family; no per-variant (GAS/HEV/BEV) split exists in the workbook,
  so each member forecast model carries the family tree verbatim. If
  Ho's team supplies per-variant splits, the map is replaced by
  per-model rows.
- A9 Dongfeng Honda nameplate shares come from the sheet's Jan-Oct
  volumes (the only DFH volume source; no forecast row exists), so the
  7 DFH nameplates sum to 1.0 within the OEM. The OEM share stays
  0.0 (A5) — the shares affect no run's capacity.
- A10 Sheet-vs-forecast volume conflicts are REPORTED, never resolved
  by adjusting either side: nameplate shares always come from the
  forecast, trim trees always from the sheets. Known conflicts: the
  探岳 family mix (sheet Jan-Oct 20/10/70 vs forecast full-year
  63/2/34 — Nov–Dec would need 12x the PA monthly rate); New ID.4's
  sheet volume is 1888x0.7 (ID.4's forecast) while the forecast also
  carries a separate New ID.4 line (10,905); ID.AURA's sheet Jan-Oct
  volume (3,815.56) exceeds its full-year forecast (2,032); 速腾 and
  速腾 S share one sheet volume cell (52,613, F17 — unresolvable from
  the workbook). The reconciliation base uses sheet volumes, so the
  sheet's own arithmetic still reconciles exactly (see
  :func:`build_sheet_structure`).

Per-model inspections (Q9: no single-case rule generalized — each
model below was inspected individually; the full list is in
S-LAYER-REAL-SPLITS.md):

- E-H7: two P01 solutions (8155 0.5 + 8397 0.5, same supplier) in
  one trim — valid under solution slots, one-host weighted sum
  exactly 1.0. The 8397 row's workbook DISPLAYED capacity (4,750,125)
  is the known G53 copy-slip; the structure reproduces the correct
  arithmetic (429 x 0.5 x 7950 = 1,705,275).
- HS6 PHEV: the 低配 trim has share 0.0 (P02 fitment 0) and is KEPT:
  the workbook says zero, and a zero-share trim contributes zero
  while preserving the record.
- H9 / P-H9 / 国悦 / 国悦 QM7: the screenshot's shared pools do not
  exist workbook-side (H9 3373, P-H9 1100, 国悦 487, QM7's lines use
  the shared 487 cell — see :mod:`real_data`).
- 国悦 has no workbook P01 row; 国悦 QM7 has only a P03 row; P-H9
  has no P04 row. Absent rows stay absent (never filled from other
  models, never assumed fused).
- 速腾: two row-groups with mirrored host mixes (X9HP 0.1/8155 0.9
  vs 0.9/0.1) and different P02/P03/P05 sets — two sub-population
  trims at 0.5/0.5 (T11/A7). The 2027 sheet merges them into one
  group (group 1's host mix), which corroborates the grouping but
  supplies no 2026 weights.
- 探歌: X9HP 1.0 vs 8155 1.0 sharing one volume — two generations
  at 0.5/0.5 (T11/A7); the 2027 sheet carries only the 8155
  generation (volume 0 — the model ends after 2026, forecast
  2027–2031 all 0; its successor is the A SUV, forecast from 2027).
- 揽镜 PA: the R80 P02 RHP row repeats R76 identically and is dropped
  as an F03 copy-slip duplicate (see :mod:`real_data`); every other
  VW model carries exactly one RHP row at 0.3.
- Jetta VA3: the 11-camera P05 group is EXCLUDED (Ho Q6 misfill);
  VA3 keeps P01 only. Jetta M6 keeps its identical 11-camera row:
  M6 is the new J01 platform with a full P02/P03/P05 set, and the row
  persists in the 2027 sheet — inspected individually per Q9, not
  generalized from VA3. Jetta J03's P02 NGX:J6M row is excluded
  (supplier TBD, no fitment/price). Jetta has no P04 rows anywhere
  (Ho Q10: genuinely no T-BOX).
- Toyota: the sheet's single-supplier P05 rows (摄像头环视 0.6–1.0)
  and the Case A host/instrument splits (锐放 SA8155P 0.01/0.99) are
  verbatim; 卡罗拉/亚洲龙/锐放/荣放/皇冠陆放/格瑞维亚 carry NO P02
  rows (absent stays absent). BZ5 is sheet-only (no forecast row).
- Dongfeng Honda: every model carries the same shape (8155 1.0 +
  8.8仪表 1.0 + 中控 1.0 + 4G/5G 1.0 + 前视+环视 0.5/0.5 dual-supplier);
  the P05 dual rows are Case B (T10/A7) — the sheet double-counts
  those slots and the structure corrects P05 to half the displayed
  total. DFH volumes are 9→10-month extrapolations (A7 in the review).
- ID.4（30%） has no P01 rows (its host lives in the New ID.4 block);
  absent stays absent. B NB（CSP）/B SUV（CSP）/C-CUV/A SUV carry
  real trees at forecast share 0.0 (2026 volume 0).
"""

from __future__ import annotations

from .models import (
    GenerationSplit,
    NameplateSplit,
    OemProductionShares,
    OemSplit,
    ProductFitment,
    SplitStructure,
    TrimSplit,
)
from .real_data import (
    DFH_WORKBOOK_ROWS,
    FORECAST_2026_ROWS,
    HONGQI_WORKBOOK_ROWS,
    JAN_OCT_VOLUMES,
    JETTA_WORKBOOK_ROWS,
    SHEET_JAN_OCT_VOLUMES,
    TOYOTA_WORKBOOK_ROWS,
    VW_WORKBOOK_ROWS,
)

#: The model year this structure describes (forecast year = workbook year).
REAL_STRUCTURE_YEAR = 2026

#: OEM ids in workbook-sheet order.
OEM_HONGQI = "hongqi"
OEM_FAW_VW = "faw-vw"
OEM_JETTA = "jetta"
OEM_FAW_TOYOTA = "faw-toyota"
OEM_DONGFENG_HONDA = "dongfeng-honda"

#: Trim-split ids keyed to their forecast names (A6). The forecast
#: uses different internal codes for 国耀/国礼; the mapping is
#: explicit, one entry per model, never fuzzy.
_TRIM_SPLIT_TO_FORECAST = {
    "国耀 GAS（C817-01）": "国耀 GAS（N117）",
    "国礼 GAS（C872-10）": "国礼 GAS（V501）",
}

#: Forecast market subtotals the builder asserts (extraction-report
#: §3; every subtotal reconciled with diff 0).
_MARKET_TOTALS_2026 = {
    "一汽大众": 979925,
    "一汽红旗": 300236,
    "一汽丰田": 637097,
    "一汽奔腾": 103698,
}
_JIEFANG_TOTAL_2026 = 280259

#: Markets outside the modeled set (A3): no workbook trim sheets.
_EXCLUDED_MARKETS = {"一汽奔腾"}

#: Rows whose price basis is the Huawei full-solution bundle (T7):
#: (model, product, solution code after prefix stripping).
_BUNDLE_ROWS = {("P-H9 PHEV（P601/E702）", "P01", "华为")}

#: Name markers that mean NEV (T8). HEV is deliberately absent: under
#: the Chinese 新能源 definition HEV is not a new-energy vehicle.
_NEV_MARKERS = ("BEV", "PHEV", "REEV", "e-tron", "ID.", "BZ")

#: Toyota sheet families -> forecast member models (T12/A8). Explicit,
#: one entry per family; the builder refuses any forecast model that
#: maps to no family and any family with no sheet rows. BZ5 has sheet
#: rows but no forecast row: sheet-only, not a nameplate.
_TOYOTA_FAMILY_MAP = {
    "卡罗拉": ["卡罗拉 Long HEV", "卡罗拉 GAS 1.2T", "卡罗拉 Long GAS"],
    "亚洲龙": ["亚洲龙 GAS", "亚洲龙 HEV 2.0L", "亚洲龙 HEV 2.5L"],
    "锐放": ["卡罗拉锐放 GAS", "卡罗拉锐放 HEV"],
    "荣放": ["荣放 GAS", "荣放 HEV 2.5L", "荣放 HEV  2.0L"],
    "皇冠陆放": ["皇冠陆放 GAS", "皇冠陆放 HEV"],
    "格瑞维亚 HEV": ["格瑞维亚 HEV"],
    "BZ3": ["BZ3 BEV", "BZ3C BEV"],
}

#: Forecast models with no workbook sheet rows (A1): labeled
#: placeholders, never filled from other models.
_VW_UNSOURCED = frozenset(
    {
        "Audi A3 Sportback",
        "Audi A4L",
        "Audi A5L（B10）",
        "Audi A6L（C9）",
        "Audi Q3",
        "Audi Q5L NF",
        "Audi A3 Limousine",
        "Audi Q2L",
        "Audi Q3 Sportback PA",
        "Audi Q5 Sportback",
        "E6L Limousine",
        "Q6L e-tron  LWB",
        "Q6L e-tron  SB",
        "A4 e-tron",
        "Q4 e-tron",
    }
)
_TOYOTA_UNSOURCED = frozenset({"兰德酷路泽", "考斯特", "960D PHEV"})

#: Equal split where the workbook gives no ratio (A7): sub-population
#: trims, generation shares, and Case B supplier splits.
_EQUAL_GROUP_SHARE = 0.5

#: Split-trim labels (T1).
_SPLIT_LABELS = ("低配", "高配")


def _energy_for(model: str) -> str:
    """NEV/ICE from the model name's energy markers (T8)."""

    if any(marker in model for marker in _NEV_MARKERS):
        return "NEV"
    return "ICE"


def _is_jetta(model: str) -> bool:
    """Jetta nameplates inside the 一汽大众 forecast market (A4)."""

    return model.startswith(("Jetta", "捷达"))


def _forecast_volumes_by_oem() -> dict[str, dict[str, int]]:
    """2026 forecast volumes per modeled OEM id, in forecast row order.

    Asserts every market subtotal against the extraction report, splits
    Jetta out of 一汽大众 by name, maps the two Hongqi forecast names
    to their trim-split ids, and drops the excluded markets. Blank
    cells count as 0.
    """

    markets: dict[str, dict[str, int]] = {}
    for market, model, volume in FORECAST_2026_ROWS:
        key = market.strip()
        markets.setdefault(key, {})[model] = int(volume or 0)
    for market, total in _MARKET_TOTALS_2026.items():
        actual = sum(markets[market].values())
        if actual != total:
            raise ValueError(
                f"Forecast market {market!r} sums to {actual}, not {total}; "
                "the extract and the builder disagree — refusing to build."
            )
    jiefang = sum(
        sum(rows.values()) for name, rows in markets.items() if name.startswith("解放")
    )
    if jiefang != _JIEFANG_TOTAL_2026:
        raise ValueError(
            f"Forecast 解放 markets sum to {jiefang}, not {_JIEFANG_TOTAL_2026}."
        )
    forecast_to_trim_split = {v: k for k, v in _TRIM_SPLIT_TO_FORECAST.items()}
    volumes: dict[str, dict[str, int]] = {
        OEM_FAW_VW: {},
        OEM_JETTA: {},
        OEM_HONGQI: {},
        OEM_FAW_TOYOTA: {},
    }
    for model, volume in markets["一汽大众"].items():
        target = OEM_JETTA if _is_jetta(model) else OEM_FAW_VW
        volumes[target][model] = volume
    for model, volume in markets["一汽红旗"].items():
        volumes[OEM_HONGQI][forecast_to_trim_split.get(model, model)] = volume
    for model, volume in markets["一汽丰田"].items():
        volumes[OEM_FAW_TOYOTA][model] = volume
    return volumes


def _shares_from_volumes(volumes: dict[str, int]) -> dict[str, float]:
    """Volume shares within one OEM (sum 1 up to float rounding)."""

    total = sum(volumes.values())
    if total <= 0:
        raise ValueError("Volume base is empty; shares are undefined.")
    return {name: volume / total for name, volume in volumes.items()}


def _strip_trim_prefix(solution: str) -> str | None:
    """The solution code: trim prefix stripped, whitespace trimmed (T2)."""

    code = solution.strip()
    for prefix in ("低配：", "高配："):
        if code.startswith(prefix):
            code = code[len(prefix) :].strip()
    return code or None


def _supplier_splits(supplier_cell: str, model: str, product: str) -> list[tuple[str, float]]:
    """Supplier rows for one workbook supplier cell (T3).

    One supplier -> share 1.0. Two suppliers (``"A/B"``) -> 0.5/0.5,
    a labeled assumption (the workbook gives no ratio). More than two
    refuses: no such cell exists in the extract, and inventing a
    three-way rule would be a generalization. ``"/"`` is kept verbatim.
    """

    cell = supplier_cell.strip()
    if cell == "/":
        return [("/", 1.0)]
    suppliers = [part.strip() for part in cell.split("/")]
    if len(suppliers) == 1:
        return [(suppliers[0], 1.0)]
    if len(suppliers) == 2:
        return [(suppliers[0], 0.5), (suppliers[1], 0.5)]
    raise ValueError(
        f"Model {model!r} product {product!r}: supplier cell {supplier_cell!r} "
        f"names {len(suppliers)} suppliers; no split rule exists."
    )


def _hongqi_trims(model: str, rows: list[tuple]) -> list[TrimSplit]:
    """Trim tree for one Hongqi model from its workbook rows (T1/T2/T3/T4)."""

    split_rows = [
        row for row in rows if row[3] == "solution_prefix" and row[2] in _SPLIT_LABELS
    ]
    split_labels = {row[2] for row in split_rows}
    has_split = split_labels == set(_SPLIT_LABELS)
    if split_labels and not has_split:
        # Lone split label: a naming artifact only when every such row
        # covers the whole model (fitment 1.0); a partial lone split
        # is ambiguous and refuses.
        lone_fits = {float(row[5]) for row in split_rows}
        if lone_fits != {1.0}:
            raise ValueError(
                f"Model {model!r} has a lone trim label {sorted(split_labels)} "
                f"with partial fitments {sorted(lone_fits)}; no counterpart "
                "trim exists to complete the split."
            )
    if not has_split:
        trim_specs = [("全车型", 1.0)]
    else:
        shares: dict[str, float] = {}
        for label in _SPLIT_LABELS:
            fits = {float(row[5]) for row in split_rows if row[2] == label}
            if len(fits) != 1:
                raise ValueError(
                    f"Model {model!r} trim {label!r}: split fitments disagree: "
                    f"{sorted(fits)} (P02/P05 splits must agree)."
                )
            shares[label] = fits.pop()
        if abs(sum(shares.values()) - 1.0) > 1e-9:
            raise ValueError(
                f"Model {model!r}: trim shares sum to {sum(shares.values())}, not 1."
            )
        trim_specs = [(label, shares[label]) for label in _SPLIT_LABELS]
    trims: list[TrimSplit] = []
    for trim_id, trim_share in trim_specs:
        fitments: list[ProductFitment] = []
        for (_m, product, label, source, solution, fitment, supplier, price) in rows:
            is_split_row = (
                has_split and source == "solution_prefix" and label in _SPLIT_LABELS
            )
            if is_split_row:
                if label != trim_id:
                    continue
                within_fitment = 1.0
            else:
                within_fitment = float(fitment)
            code = _strip_trim_prefix(str(solution))
            price_basis = (
                "bundle"
                if (model, product, code) in _BUNDLE_ROWS
                else "discrete"
            )
            for supplier_id, supplier_share in _supplier_splits(
                str(supplier), model, product
            ):
                fitments.append(
                    ProductFitment(
                        product_id=product,
                        fitment_kind="rate",
                        fitment=within_fitment,
                        supplier_id=supplier_id,
                        supplier_share=supplier_share,
                        price=float(price),
                        solution_code=code,
                        price_basis=price_basis,
                    )
                )
        trims.append(TrimSplit(trim_id=trim_id, share=trim_share, fitments=fitments))
    return trims


def _placeholder_nameplate(
    nameplate_id: str, share: float, energy: str | None = None
) -> NameplateSplit:
    """A labeled-simulated nameplate (A1): one zero-contribution P.O row."""

    return NameplateSplit(
        nameplate_id=nameplate_id,
        energy=energy if energy is not None else _energy_for(nameplate_id),
        price_band="unknown",
        share=share,
        model_year=REAL_STRUCTURE_YEAR,
        generations=[
            GenerationSplit(
                generation_id="current",
                lifecycle_phase="mature",
                share=1.0,
                trims=[
                    TrimSplit(
                        trim_id="全车型",
                        share=1.0,
                        fitments=[
                            ProductFitment(
                                product_id="P.O",
                                fitment_kind="rate",
                                fitment=0.0,
                                supplier_id="UNKNOWN",
                                supplier_share=1.0,
                                price=0.0,
                            )
                        ],
                    )
                ],
            )
        ],
    )


def _hongqi_oem(volumes: dict[str, int]) -> OemSplit:
    """The Hongqi OEM: real trim trees where rows exist, placeholders else."""

    rows_by_model: dict[str, list[tuple]] = {}
    for row in HONGQI_WORKBOOK_ROWS:
        rows_by_model.setdefault(row[0], []).append(row)
    shares = _shares_from_volumes(volumes)
    nameplates: list[NameplateSplit] = []
    for nameplate_id, share in shares.items():
        rows = rows_by_model.get(nameplate_id)
        if rows is None:
            nameplates.append(_placeholder_nameplate(nameplate_id, share))
            continue
        nameplates.append(
            NameplateSplit(
                nameplate_id=nameplate_id,
                energy=_energy_for(nameplate_id),
                price_band="unknown",
                share=share,
                model_year=REAL_STRUCTURE_YEAR,
                generations=[
                    GenerationSplit(
                        generation_id="current",
                        lifecycle_phase="mature",
                        share=1.0,
                        trims=_hongqi_trims(nameplate_id, rows),
                    )
                ],
            )
        )
    return OemSplit(oem_id=OEM_HONGQI, customer_status="existing", nameplates=nameplates)


def _rehome_instrument(product: str, solution: str | None) -> str:
    """T9: 仪表 rows in the P01 column belong to P03."""

    if product == "P01" and solution and "仪表" in solution:
        return "P03"
    return product


def _slot_fitments(rows: list[tuple]) -> list[ProductFitment]:
    """ProductFitment list for one trim from its raw rows (T9/T10).

    ``rows`` are (model, product, trim_label, trim_source, solution,
    fitment, supplier, price) tuples already filtered to one trim (and
    one generation). Same-(product, solution) rows are merged per T10:
    unequal fitments are the suppliers' shares of the slot (Case A),
    equal fitments repeat the slot rate with an equal supplier split
    (Case B, A7). A repeated (product, solution, supplier) pair
    refuses — the builder never silently drops a duplicate.
    """

    groups: dict[tuple[str, str], list[tuple[float, str, float]]] = {}
    order: list[tuple[str, str]] = []
    for _model, product, _label, _source, solution, fitment, supplier, price in rows:
        product = _rehome_instrument(product, solution)
        key = (product, (solution or "").strip())
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((float(fitment), str(supplier), float(price)))
    fitments: list[ProductFitment] = []
    for product, solution in order:
        grows = groups[(product, solution)]
        if len({supplier for _fit, supplier, _price in grows}) != len(grows):
            raise ValueError(
                f"Duplicate (product, solution, supplier) in one trim: "
                f"{product} {solution!r} — refusing to build."
            )
        if len(grows) == 1:
            fitment, supplier, price = grows[0]
            fitments.append(
                ProductFitment(
                    product_id=product,
                    fitment_kind="rate",
                    fitment=fitment,
                    supplier_id=supplier,
                    supplier_share=1.0,
                    price=price,
                    solution_code=solution or None,
                    price_basis="discrete",
                )
            )
            continue
        fits = [grow[0] for grow in grows]
        if len(set(fits)) == 1:
            # Case B: the fitments repeat the slot rate.
            for fitment, supplier, price in grows:
                fitments.append(
                    ProductFitment(
                        product_id=product,
                        fitment_kind="rate",
                        fitment=fitment,
                        supplier_id=supplier,
                        supplier_share=1.0 / len(grows),
                        price=price,
                        solution_code=solution or None,
                        price_basis="discrete",
                    )
                )
            continue
        # Case A: the fitments ARE the suppliers' shares of the slot.
        total = sum(fits)
        if total > 1.0 + 1e-9:
            raise ValueError(
                f"Supplier-split fitments sum to {total} (> 1) for "
                f"{product} {solution!r} — refusing to build."
            )
        for fitment, supplier, price in grows:
            fitments.append(
                ProductFitment(
                    product_id=product,
                    fitment_kind="rate",
                    fitment=total,
                    supplier_id=supplier,
                    supplier_share=fitment / total,
                    price=price,
                    solution_code=solution or None,
                    price_basis="discrete",
                )
            )
    return fitments


def _generic_trims(model: str, rows: list[tuple]) -> list[TrimSplit]:
    """Trim tree for one non-Hongqi model from its workbook rows (T11).

    Rows labeled ``子人群1`` / ``子人群2`` (source ``row_group``) form
    two trims at 0.5/0.5 (A7); rows with no group label apply
    model-wide (within the generation) in a single ``全车型`` trim.
    Any other row-group structure refuses — the builder does not guess
    partitions.
    """

    grouped: dict[str, list[tuple]] = {}
    whole: list[tuple] = []
    for row in rows:
        label, source = row[2], row[3]
        if source == "row_group":
            grouped.setdefault(label, []).append(row)
        elif source in ("default", "generation_prev", "generation_current"):
            whole.append(row)
        else:
            raise ValueError(
                f"Unexpected trim source {source!r} for {model!r} — "
                "refusing to build."
            )
    if not grouped:
        return [
            TrimSplit(
                trim_id="全车型",
                share=1.0,
                fitments=_slot_fitments(whole),
            )
        ]
    if whole:
        raise ValueError(
            f"{model!r} mixes whole-model rows with row-group rows — "
            "refusing to build."
        )
    if set(grouped) != {"子人群1", "子人群2"}:
        raise ValueError(
            f"{model!r} has unexpected row groups {sorted(grouped)} — "
            "refusing to build."
        )
    return [
        TrimSplit(
            trim_id=label,
            share=_EQUAL_GROUP_SHARE,
            fitments=_slot_fitments(grouped[label]),
        )
        for label in ("子人群1", "子人群2")
    ]


def _generic_generations(model: str, rows: list[tuple]) -> list[GenerationSplit]:
    """Generation tree for one non-Hongqi model from its rows (T11).

    Rows tagged ``generation_prev`` / ``generation_current`` form two
    generations (``prev``/``phase_out`` and ``current``/``ramp``) at
    0.5/0.5 (A7); untagged rows form a single ``current``/``mature``
    generation. A lone generation tag refuses.
    """

    prev = [row for row in rows if row[3] == "generation_prev"]
    current = [row for row in rows if row[3] == "generation_current"]
    whole = [row for row in rows if row[3] in ("default", "row_group")]
    if prev and current:
        if whole:
            raise ValueError(
                f"{model!r} mixes generation rows with untagged rows — "
                "refusing to build."
            )
        return [
            GenerationSplit(
                generation_id="prev",
                lifecycle_phase="phase_out",
                share=_EQUAL_GROUP_SHARE,
                trims=_generic_trims(model, prev),
            ),
            GenerationSplit(
                generation_id="current",
                lifecycle_phase="ramp",
                share=_EQUAL_GROUP_SHARE,
                trims=_generic_trims(model, current),
            ),
        ]
    if prev or current:
        raise ValueError(
            f"{model!r} has a lone generation tag — refusing to build."
        )
    return [
        GenerationSplit(
            generation_id="current",
            lifecycle_phase="mature",
            share=1.0,
            trims=_generic_trims(model, whole),
        )
    ]


def _rows_by_model(rows: list[tuple]) -> dict[str, list[tuple]]:
    """Group workbook rows by their sheet model name."""

    grouped: dict[str, list[tuple]] = {}
    for row in rows:
        grouped.setdefault(row[0], []).append(row)
    return grouped


def _nameplate_from_rows(
    nameplate_id: str, share: float, rows: list[tuple]
) -> NameplateSplit:
    """One real nameplate from its workbook rows (T9–T11)."""

    return NameplateSplit(
        nameplate_id=nameplate_id,
        energy=_energy_for(nameplate_id),
        price_band="unknown",
        share=share,
        model_year=REAL_STRUCTURE_YEAR,
        generations=_generic_generations(nameplate_id, rows),
    )


def _mapped_oem(
    oem_id: str,
    volumes: dict[str, int],
    rows_by_model: dict[str, list[tuple]],
    *,
    unsourced: frozenset[str] = frozenset(),
    customer_status: str = "existing",
) -> OemSplit:
    """An OEM whose models map 1:1 to sheet models (VW/Jetta/DFH).

    Every volume model must have sheet rows or be in ``unsourced``
    (placeholder, A1); every sheet model must have a volume. Either
    mismatch refuses.
    """

    mapped = set(rows_by_model)
    unmapped = set(volumes) - mapped
    if unmapped != set(unsourced):
        raise ValueError(
            f"{oem_id}: volume models without sheet rows "
            f"{sorted(unmapped)} != expected unsourced {sorted(unsourced)} "
            "— refusing to build."
        )
    if mapped - set(volumes):
        raise ValueError(
            f"{oem_id}: sheet models without volumes "
            f"{sorted(mapped - set(volumes))} — refusing to build."
        )
    shares = _shares_from_volumes(volumes)
    nameplates: list[NameplateSplit] = []
    for nameplate_id, share in shares.items():
        rows = rows_by_model.get(nameplate_id)
        if rows is None:
            nameplates.append(_placeholder_nameplate(nameplate_id, share))
            continue
        nameplates.append(
            _nameplate_from_rows(nameplate_id, share, rows)
        )
    return OemSplit(
        oem_id=oem_id,
        customer_status=customer_status,  # type: ignore[arg-type]
        nameplates=nameplates,
    )


def _toyota_oem(volumes: dict[str, int]) -> OemSplit:
    """The FAW-Toyota OEM: family trim trees per forecast member (T12).

    Every forecast model must map to exactly one sheet family or be in
    ``_TOYOTA_UNSOURCED`` (placeholder, A1); every family must have
    sheet rows; every member of the map must be a forecast model.
    """

    rows_by_family = _rows_by_model(TOYOTA_WORKBOOK_ROWS)
    family_of: dict[str, str] = {}
    for family, members in _TOYOTA_FAMILY_MAP.items():
        for member in members:
            if member in family_of:
                raise ValueError(
                    f"Toyota member {member!r} is in two families — "
                    "refusing to build."
                )
            family_of[member] = family
    if set(family_of) - set(volumes):
        raise ValueError(
            "Toyota family-map members without forecast volumes "
            f"{sorted(set(family_of) - set(volumes))} — refusing to build."
        )
    if set(rows_by_family) - set(_TOYOTA_FAMILY_MAP) - {"BZ5"}:
        raise ValueError(
            "Toyota sheet families outside the map "
            f"{sorted(set(rows_by_family) - set(_TOYOTA_FAMILY_MAP) - {'BZ5'})} "
            "— refusing to build."
        )
    unmapped = set(volumes) - set(family_of)
    if unmapped != set(_TOYOTA_UNSOURCED):
        raise ValueError(
            f"Toyota volume models without a family {sorted(unmapped)} != "
            f"expected unsourced {sorted(_TOYOTA_UNSOURCED)} — refusing."
        )
    shares = _shares_from_volumes(volumes)
    nameplates: list[NameplateSplit] = []
    for nameplate_id, share in shares.items():
        family = family_of.get(nameplate_id)
        if family is None:
            nameplates.append(_placeholder_nameplate(nameplate_id, share))
            continue
        nameplates.append(
            _nameplate_from_rows(nameplate_id, share, rows_by_family[family])
        )
    return OemSplit(
        oem_id=OEM_FAW_TOYOTA, customer_status="existing", nameplates=nameplates
    )


def _toyota_sheet_oem(volumes: dict[str, float]) -> OemSplit:
    """The FAW-Toyota OEM on the sheet-volume base (reconciliation).

    Nameplates are the sheet families themselves (BZ5 included — its
    rows are part of the sheet's totals), each carrying its family
    tree at its sheet-volume share.
    """

    rows_by_family = _rows_by_model(TOYOTA_WORKBOOK_ROWS)
    if set(volumes) != set(rows_by_family):
        raise ValueError(
            "Toyota sheet-volume families disagree with the sheet rows: "
            f"{sorted(set(volumes) ^ set(rows_by_family))} — refusing."
        )
    shares = _shares_from_volumes(volumes)
    return OemSplit(
        oem_id=OEM_FAW_TOYOTA,
        customer_status="existing",
        nameplates=[
            _nameplate_from_rows(family, share, rows_by_family[family])
            for family, share in shares.items()
        ],
    )


def _dfh_oem() -> OemSplit:
    """The Dongfeng Honda OEM: real trim trees, sheet-volume shares (A9).

    Dongfeng Honda has no forecast volume (A5): the sheet's Jan-Oct
    volumes are its only volume source, so the 7 nameplates sum to 1.0
    within the OEM while the OEM share stays 0.0.
    """

    volumes = dict(SHEET_JAN_OCT_VOLUMES[OEM_DONGFENG_HONDA])
    return _mapped_oem(
        OEM_DONGFENG_HONDA,
        volumes,
        _rows_by_model(DFH_WORKBOOK_ROWS),
        customer_status="prospect",
    )


def build_real_structure() -> SplitStructure:
    """The full real split structure: 5 OEMs, 2026 forecast shares.

    Hongqi, FAW-VW, Jetta, and FAW-Toyota carry real workbook trim
    trees where the sheets have rows (A1 lists the 19 forecast models
    that stay placeholders); Dongfeng Honda carries real trim trees on
    sheet-volume shares with a 0.0 OEM share (A5/A9).
    """

    volumes = _forecast_volumes_by_oem()
    hongqi_ids = set(volumes[OEM_HONGQI])
    if hongqi_ids != set(JAN_OCT_VOLUMES):
        raise ValueError(
            "Hongqi model sets disagree between the forecast and the "
            f"trim-split extracts: {sorted(hongqi_ids ^ set(JAN_OCT_VOLUMES))}."
        )
    return SplitStructure(
        oems=[
            _hongqi_oem(volumes[OEM_HONGQI]),
            _mapped_oem(
                OEM_FAW_VW,
                volumes[OEM_FAW_VW],
                _rows_by_model(VW_WORKBOOK_ROWS),
                unsourced=_VW_UNSOURCED,
            ),
            _mapped_oem(
                OEM_JETTA,
                volumes[OEM_JETTA],
                _rows_by_model(JETTA_WORKBOOK_ROWS),
            ),
            _toyota_oem(volumes[OEM_FAW_TOYOTA]),
            _dfh_oem(),
        ]
    )


def build_sheet_structure(oem_id: str) -> SplitStructure:
    """The single-OEM structure on the sheet Jan-Oct volume base.

    The reconciliation view: nameplate shares come from the sheet's
    own Jan-Oct volumes (``SHEET_JAN_OCT_VOLUMES``), so the
    structure's capacity reproduces the workbook's sheet totals
    exactly (after the T9/T10/T11 corrections — see
    :mod:`real_data`). Hongqi delegates to
    :func:`build_hongqi_structure` (``"jan_oct_actuals"``); Toyota
    nameplates are the sheet families themselves (BZ5 included).
    """

    if oem_id == OEM_HONGQI:
        return build_hongqi_structure(shares_source="jan_oct_actuals")
    if oem_id == OEM_FAW_VW:
        return SplitStructure(
            oems=[
                _mapped_oem(
                    OEM_FAW_VW,
                    dict(SHEET_JAN_OCT_VOLUMES[OEM_FAW_VW]),
                    _rows_by_model(VW_WORKBOOK_ROWS),
                )
            ]
        )
    if oem_id == OEM_JETTA:
        return SplitStructure(
            oems=[
                _mapped_oem(
                    OEM_JETTA,
                    dict(SHEET_JAN_OCT_VOLUMES[OEM_JETTA]),
                    _rows_by_model(JETTA_WORKBOOK_ROWS),
                )
            ]
        )
    if oem_id == OEM_FAW_TOYOTA:
        return SplitStructure(
            oems=[
                _toyota_sheet_oem(dict(SHEET_JAN_OCT_VOLUMES[OEM_FAW_TOYOTA]))
            ]
        )
    if oem_id == OEM_DONGFENG_HONDA:
        return SplitStructure(oems=[_dfh_oem()])
    raise ValueError(
        f"Unknown oem_id {oem_id!r}; expected one of "
        f"{OEM_HONGQI}, {OEM_FAW_VW}, {OEM_JETTA}, {OEM_FAW_TOYOTA}, "
        f"{OEM_DONGFENG_HONDA}."
    )


def build_hongqi_structure(*, shares_source: str = "forecast_2026") -> SplitStructure:
    """The Hongqi-only structure, for reconciliation and focused analysis.

    ``shares_source="forecast_2026"`` (default) uses the 2026 forecast
    mix; ``"jan_oct_actuals"`` uses the Jan-Oct actual volumes, which
    is the base the workbook's capacity totals reconcile against (see
    :mod:`real_data`). Any other value refuses loudly.
    """

    if shares_source == "forecast_2026":
        volumes = _forecast_volumes_by_oem()[OEM_HONGQI]
    elif shares_source == "jan_oct_actuals":
        volumes = dict(JAN_OCT_VOLUMES)
    else:
        raise ValueError(
            f"Unknown shares_source {shares_source!r}; "
            "expected 'forecast_2026' or 'jan_oct_actuals'."
        )
    return SplitStructure(oems=[_hongqi_oem(volumes)])


def real_oem_shares() -> OemProductionShares:
    """The stored 2026 OEM mix over the modeled FAW set (A3/A4/A5)."""

    volumes = _forecast_volumes_by_oem()
    totals = {oem_id: sum(rows.values()) for oem_id, rows in volumes.items()}
    modeled_total = sum(totals.values())
    shares = {
        oem_id: total / modeled_total for oem_id, total in totals.items()
    }
    shares[OEM_DONGFENG_HONDA] = 0.0
    return OemProductionShares(
        shares=shares,
        source="faw_volume_forecast_2026",
        as_of="2026",
        notes=(
            "Shares of the MODELED FAW set only (2026 forecast volumes, "
            f"total {modeled_total:,}); 一汽奔腾 (103,698) and 一汽解放 "
            "(280,259) are excluded — no workbook trim sheets — so the "
            "engine total is interpreted as modeled-set production. "
            "Jetta models split out of the 一汽大众 market by name; Audi "
            "stays in FAW-VW. Dongfeng Honda is a prospect with no "
            "forecast volume (0.0)."
        ),
    )


#: The stored 2026 OEM mix, computed once from the forecast tables.
REAL_OEM_SHARES_2026 = real_oem_shares()

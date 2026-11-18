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

Labeled simulated values (explicitly labeled, replaceable — Ho's
internal-calibration ruling) remain where real data is absent:

- A1 Placeholder nameplates: every non-Hongqi forecast model (64),
  HS9 PHEV (forecast-only, zero 2026 volume), and one Dongfeng Honda
  placeholder carry a single trim with one P.O row (fitment 0.0,
  supplier ``"UNKNOWN"``, price 0.0): zero units, zero capacity, and
  an R13 prompt flagging the un-decomposed basket. No fitment, price,
  or supplier is invented for them.
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
  volume) and a placeholder nameplate; its S-layer own sales stay 0
  by the customer-status flag, per the Q8/prospect ruling.
- A6 The two Hongqi forecast/trim-split name mismatches are mapped
  explicitly (never fuzzy-matched): forecast ``国耀 GAS（N117）`` and
  ``国礼 GAS（V501）`` are the trim-split ``国耀 GAS（C817-01）`` and
  ``国礼 GAS（C872-10）`` (same model names, different internal
  codes). The builder asserts the mapped model sets are identical.
- A7 Equal 0.5/0.5 supplier splits (T3) and the ICE default (T8)
  are the only numeric assumptions in the real rows; both are
  labeled here and in the report, and both are replaceable without
  touching the transformation rules.

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
from .real_data import FORECAST_2026_ROWS, HONGQI_WORKBOOK_ROWS, JAN_OCT_VOLUMES

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

#: The Dongfeng Honda placeholder nameplate id (A5).
_DONGFENG_PLACEHOLDER_NAMEPLATE = "待开发车型"

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


def _placeholder_oem(
    oem_id: str, customer_status: str, volumes: dict[str, int]
) -> OemSplit:
    """An OEM whose nameplates are all labeled-simulated placeholders."""

    shares = _shares_from_volumes(volumes)
    return OemSplit(
        oem_id=oem_id,
        customer_status=customer_status,  # type: ignore[arg-type]
        nameplates=[
            _placeholder_nameplate(nameplate_id, share)
            for nameplate_id, share in shares.items()
        ],
    )


def build_real_structure() -> SplitStructure:
    """The full real split structure: 5 OEMs, 2026 forecast shares.

    Hongqi carries the real workbook trim trees; FAW-VW, Jetta, and
    FAW-Toyota carry real forecast nameplate shares with placeholder
    trim detail (A1); Dongfeng Honda is the zero-share prospect (A5).
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
            _placeholder_oem(OEM_FAW_VW, "existing", volumes[OEM_FAW_VW]),
            _placeholder_oem(OEM_JETTA, "existing", volumes[OEM_JETTA]),
            _placeholder_oem(OEM_FAW_TOYOTA, "existing", volumes[OEM_FAW_TOYOTA]),
            OemSplit(
                oem_id=OEM_DONGFENG_HONDA,
                customer_status="prospect",
                nameplates=[
                    _placeholder_nameplate(
                        _DONGFENG_PLACEHOLDER_NAMEPLATE, 1.0, energy="ICE"
                    )
                ],
            ),
        ]
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

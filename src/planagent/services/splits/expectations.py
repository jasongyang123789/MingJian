"""Co-occurrence prompt engine (Phase 2, Ho's prompt-system directive).

Ho 2026-11-16 13:39: ALL co-occurrence relationships are probabilistic
('大概率'), never hard rules. This module encodes the verification
report's R1–R13 / X1–X5 expectation model plus the AVM pairing (Ho
Q8) as PROMPTS: when input data violates normal logic, outputs
PROMINENTLY flag the anomaly and explain what the normal logic
should be, plus likely explanations (data gap / morphology
transition / genuine exception). It NEVER refuses and NEVER silently
corrects. The Phase 1 accounting-identity gates (sum-to-1 shares,
one-host backstop, rate/count separation) stay hard in the validator
— this module is advisory-only and runs on validated structures.

No-generalization rule (Ho Q9): every expectation's scope is stated
per model / per (OEM, nameplate, year) and verified individually;
the Corolla-2027 switch stays a Corolla-only registry fact.

Evaluation is at the CONFIGURATION (trim / sub-population) layer:
block-level co-occurrence is an upper bound, so prompts fire per
trim, the level at which one vehicle's fitment combination is
observed. One solution per function is the normal case behind the
substitution prompts, never a universal rule: P-HUD coexists with
W-HUD/AR-HUD on the same vehicle (Ho 2026-11-17 ruling), and
fitment rates are independent penetrations (Ho Q7). Checks that
cannot be evaluated (no solution codes, uncountable camera labels,
no registry fact, PHEV detail absent) are recorded in ``skipped``
with the reason — never silently dropped, never assumed.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .aliases import classify_solution, dc_platform, is_huawei_solution, parse_camera_count
from .catalog import PO_SUBPRODUCTS, is_po_basket, product_line_of
from .models import SplitStructure, TrimSplit
from .morphology import lookup_known_data_error, lookup_morphology_fact

#: Normal tolerance for camera-ladder comparisons (Ho Q2: a 1-camera
#: difference from the embedded front-view module is normal tolerance,
#: not an anomaly).
LADDER_TOLERANCE = 1

#: Camera-ladder tiers: driving-compute platform -> expected total
#: camera count (P05 rows + 1 embedded when the platform is a
#: front-view module). The 8650 tier is year-dependent (2026: 10,
#: 2027+: 11) per the verification report §1.1 (corrected count).
_LADDER: dict[str, int] = {"ifc": 5, "8620": 7, "rhp": 11, "ngx": 11}


def _ladder_expected(platform: str, model_year: int | None) -> set[int] | None:
    if platform == "8650":
        if model_year is None:
            return {10, 11}
        return {11} if model_year >= 2027 else {10}
    if platform in _LADDER:
        return {_LADDER[platform]}
    return None


class Prompt(BaseModel):
    """One co-occurrence prompt: an anomaly flag or an advisory note."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    severity: str = Field(pattern="^(anomaly|info)$")
    path: str
    title: str
    observed: str
    expected_logic: str
    likely_explanations: list[str] = Field(default_factory=list)
    evidence_ref: str
    scope: str


class SkipRecord(BaseModel):
    """One expectation that could not be evaluated, with the reason."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    path: str
    reason: str


class PromptReport(BaseModel):
    """The full prompt evaluation of one split structure."""

    model_config = ConfigDict(extra="forbid")

    prompts: list[Prompt] = Field(default_factory=list)
    skipped: list[SkipRecord] = Field(default_factory=list)
    anomaly_count: int = 0
    info_count: int = 0
    rules_evaluated: list[str] = Field(default_factory=list)
    rules_skipped: list[str] = Field(default_factory=list)


#: The expectation catalog: every rule, its normal logic, strength,
#: scope, evidence, and whether this module evaluates it. Catalog-only
#: entries (R11, X1, X2) are documented here and always skipped with
#: the stated reason — they are never silently absent.
EXPECTATION_CATALOG: list[dict[str, str | bool]] = [
    {
        "id": "R1",
        "title": "Driving domain controller implies cameras",
        "normal_logic": "A trim with a driving domain controller (P02 DC) carries camera rows (P05).",
        "strength": "63/64 DC blocks (the sole exception is the Huawei bundle, Ho Q11)",
        "scope": "All OEMs; bundle trims excluded (cameras included in the bundle price)",
        "evidence_ref": "verification report §1.1 (H1 VERIFIED)",
        "evaluated": True,
    },
    {
        "id": "R2",
        "title": "Camera-count ladder by driving-compute platform",
        "normal_logic": "Total cameras scale with the platform: IFC/front-view module 5, 8620 7, 8650 10 (2026) / 11 (2027+), RHP/NGX 11 (incl. 1 embedded front camera for modules).",
        "strength": "35/35 prefix pairs (Hongqi); 5V/7V/11V tiers match public evidence",
        "scope": "Hongqi-verified; applied per trim wherever platform + countable P05 labels exist; ±1 tolerance (Ho Q2)",
        "evidence_ref": "verification report §1.1 (H1 ladder, corrected 8650-2026 count 10)",
        "evaluated": True,
    },
    {
        "id": "R3",
        "title": "Integrated morphology implies no separate central screen",
        "normal_logic": "IVI one-box / fused trims have no separate P03 central row (the screen lives in P01).",
        "strength": "Toyota one-box 11/11 blocks; VW fused blocks per Ho Q5",
        "scope": "Trims with morphology ivi_one_box / fused",
        "evidence_ref": "verification report §1.2 (H2) + Ho Q1/Q5",
        "evaluated": True,
    },
    {
        "id": "R4",
        "title": "Discrete host implies a central screen",
        "normal_logic": "A discrete-host trim with a cockpit host carries a P03 central screen row.",
        "strength": "115/140 host blocks overall; 109/123 excluding Toyota one-box; Hongqi 98%, Honda 93%",
        "scope": "Trims with morphology discrete_host",
        "evidence_ref": "verification report §1.3 (H3 VERIFIED, OEM-conditioned)",
        "evaluated": True,
    },
    {
        "id": "R5",
        "title": "Morphology consistency with verified registry facts",
        "normal_logic": "A trim's morphology matches the individually verified (OEM, nameplate, year) registry fact when one exists.",
        "strength": "Registry facts only; no generalization across models (Ho Q9)",
        "scope": "Trims whose (OEM, nameplate, year) has a registry fact",
        "evidence_ref": "services/splits/morphology.py (Ho Q1/Q5/Q9)",
        "evaluated": True,
    },
    {
        "id": "R6",
        "title": "Within-class P02 substitution (overlap is a prompt)",
        "normal_logic": "Within one function class (DC / front-view module), distinct solutions substitute: their rates normally sum to <= 1 per trim.",
        "strength": "Class-level pattern; VW-2027 four-solution blocks summing 1.2 are legitimate independent penetrations (Ho Q7) — overlap prompts explain this, never refuse",
        "scope": "Trims with classified P02 rows carrying solution codes",
        "evidence_ref": "verification report §3 (R6) + Ho Q7 fitment definition",
        "evaluated": True,
    },
    {
        "id": "R7",
        "title": "Central-slot substitution (passenger screens excluded)",
        "normal_logic": "ABT central-display variants substitute within the central slot: their rates normally sum to <= 1. CDD/CDI passenger screens coexist and are excluded (Ho Q3).",
        "strength": "VW-2027 ABT+CDD sums 1.1–1.2 are legitimate coexistence",
        "scope": "Trims with classified P03 central rows",
        "evidence_ref": "verification report §3 (R7, rewritten per Ho Q3)",
        "evaluated": True,
    },
    {
        "id": "R8",
        "title": "Instrument rows belong to P03",
        "normal_logic": "Instrument rows are booked under P03 (screens), never under P01 (Ho Q3 2026-11-16: instrument counts in P03).",
        "strength": "Confirmed classification ruling",
        "scope": "All P01 rows classified as instrument",
        "evidence_ref": "Ho Q3 ruling + verification report §2.3/F14",
        "evaluated": True,
    },
    {
        "id": "R9",
        "title": "4G/5G variant substitution",
        "normal_logic": "4G and 5G comm-terminal variants substitute: their rates normally sum to <= 1 per trim (one terminal per car).",
        "strength": "P04 slot: one terminal per vehicle; variant maxima are read as distinct-variant fitments",
        "scope": "Trims with both 4G and 5G variant labels",
        "evidence_ref": "verification report §3 (R9)",
        "evaluated": True,
    },
    {
        "id": "R10",
        "title": "High camera count implies driving compute",
        "normal_logic": "A trim with >= 7 cameras usually carries driving compute (DC or module) in P02.",
        "strength": "0.94 block-level co-occurrence; parking-only surround groups are legitimate exceptions",
        "scope": "Trims with countable P05 totals >= 7",
        "evidence_ref": "verification report §3 (R10)",
        "evaluated": True,
    },
    {
        "id": "R11",
        "title": "PHEV energy detail implies a battery-pack domain",
        "normal_logic": "PHEV nameplates carry a battery-pack domain row (catalog-only: energy detail is not carried by the structure).",
        "strength": "Not evaluable",
        "scope": "None (structure energy is NEV/ICE only)",
        "evidence_ref": "verification report §3 (R11)",
        "evaluated": False,
    },
    {
        "id": "R12",
        "title": "DMS mandate adds one cabin camera",
        "normal_logic": "With the DMS mandate on (GB 47955-2026, from 2027-01-01), camera totals include +1 cabin (DMS/OMS) camera.",
        "strength": "Regulatory (mandatory standard)",
        "scope": "Runs with dms_mandate_on context",
        "evidence_ref": "verification report §3 (R12) + synthesis §B",
        "evaluated": True,
    },
    {
        "id": "R13",
        "title": "P.O is decomposed, never a basket row",
        "normal_logic": "P.O sub-products (HUD/radar/gateway/body-domain/APA/AVM/UWB/...) are carried as their own rows; a bare P.O basket row is flagged for decomposition.",
        "strength": "Structural ruling (Ho Q8)",
        "scope": "All trims",
        "evidence_ref": "Ho Q8 ruling + services/splits/catalog.py",
        "evaluated": True,
    },
    {
        "id": "X1",
        "title": "IVI one-box excludes a separate cockpit domain controller",
        "normal_logic": "One morphology per vehicle: a one-box trim has no separate SCDC row (enforced structurally — morphology is a single field).",
        "strength": "Catalog-only",
        "scope": "None (structural)",
        "evidence_ref": "verification report §3 (X1)",
        "evaluated": False,
    },
    {
        "id": "X2",
        "title": "One-box and discrete host are mutually exclusive",
        "normal_logic": "A trim has exactly one morphology (enforced structurally — morphology is a single field).",
        "strength": "Catalog-only",
        "scope": "None (structural)",
        "evidence_ref": "verification report §3 (X2)",
        "evaluated": False,
    },
    {
        "id": "X3",
        "title": "DC + front-view module overlap",
        "normal_logic": "DC and front-view module are different compute tiers; both in one trim suggests merged sub-populations (evaluated jointly with R6).",
        "strength": "Prompt only",
        "scope": "Trims with both DC and module rows",
        "evidence_ref": "verification report §3 (X3)",
        "evaluated": True,
    },
    {
        "id": "X4",
        "title": "Two domain controllers in one trim",
        "normal_logic": "One driving domain controller per trim; two distinct DC solutions suggests merged sub-populations (evaluated jointly with R6).",
        "strength": "Prompt only",
        "scope": "Trims with >= 2 distinct DC solutions",
        "evidence_ref": "verification report §3 (X4)",
        "evaluated": True,
    },
    {
        "id": "X5",
        "title": "ABT variants substitute within the central slot only",
        "normal_logic": "ABT variants substitute with each other, never with passenger screens (evaluated jointly with R7).",
        "strength": "Prompt only",
        "scope": "Trims with >= 2 distinct ABT variants",
        "evidence_ref": "verification report §3 (X5, rewritten per Ho Q3)",
        "evaluated": True,
    },
    {
        "id": "AVM1",
        "title": "AVM implies a surround-view camera group",
        "normal_logic": "A trim with AVM carries a surround-view camera group in P05. The reverse does not hold: a surround group does not imply AVM.",
        "strength": "Structural pairing (Ho Q8)",
        "scope": "Trims with AVM rows",
        "evidence_ref": "Ho Q8 ruling",
        "evaluated": True,
    },
    {
        "id": "BUNDLE1",
        "title": "Huawei rows are bundle-priced, never compared with discrete ASPs",
        "normal_logic": "Huawei full-solution rows carry price_basis 'bundle' (screen + cameras included) and bundle trims carry no separate P03/P05 rows.",
        "strength": "Confirmed classification ruling",
        "scope": "All trims with Huawei rows / bundle-priced rows",
        "evidence_ref": "Ho Q11 ruling",
        "evaluated": True,
    },
    {
        "id": "SCREEN1",
        "title": "One-box / fused P01 ASP includes the screen",
        "normal_logic": "P01 ASPs on integrated-morphology trims are labeled price_basis 'includes_screen'; they are never compared with discrete host ASPs.",
        "strength": "Confirmed classification ruling",
        "scope": "Trims with morphology ivi_one_box / fused",
        "evidence_ref": "Ho Q1/C4 ruling",
        "evaluated": True,
    },
    {
        "id": "EMBED1",
        "title": "Front-view modules embed one camera (accounting note)",
        "normal_logic": "MFK/IFC front-view modules embed 1 camera: totals are annotated incl./excl. the embedded unit; a 1-camera difference is normal tolerance (Ho Q2), never an anomaly.",
        "strength": "Accounting convention",
        "scope": "Trims with front-view module rows",
        "evidence_ref": "verification report §5 + Ho Q2",
        "evaluated": True,
    },
]


def expectation_catalog() -> list[dict[str, str | bool]]:
    """The expectation catalog (for API/UI display)."""

    return [dict(entry) for entry in EXPECTATION_CATALOG]


def _rows_by_line(trim: TrimSplit) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for row in trim.fitments:
        line = product_line_of(row.product_id)
        if line is None:
            continue
        grouped.setdefault(line, []).append(row)
    return grouped


def _max_rate_by_solution(rows: list) -> dict[str, float]:
    """Max rate fitment per distinct solution code.

    Supplier splits repeat the slot's fitment across supplier rows;
    the per-solution maximum is the slot penetration, and summing
    across supplier rows would double-count.
    """

    maxima: dict[str, float] = {}
    for row in rows:
        if row.fitment_kind != "rate":
            continue
        code = (row.solution_code or "").strip()
        if not code:
            continue
        maxima[code] = max(maxima.get(code, 0.0), row.fitment)
    return maxima


def _p05_total(trim: TrimSplit, rows_by_line: dict[str, list]) -> tuple[float | None, bool]:
    """The trim's total camera count, or ``None`` when uncountable.

    Count-kind rows contribute their fitment; rate-kind rows contribute
    the group size parsed from their label. Both are weighted by
    supplier share, so a camera group split across two suppliers (two
    rows, one solution) counts once, not twice — the real workbook
    splits carry 16 such P05 splits. Returns ``(total, False)``
    when every P05 row is countable, ``(None, True)`` when any row
    cannot be counted (the ladder check must skip, not guess).
    """

    total = 0.0
    for row in rows_by_line.get("P05", []):
        if row.fitment_kind == "count":
            total += row.fitment * row.supplier_share
        else:
            parsed = parse_camera_count(row.solution_code)
            if parsed is None:
                return None, True
            total += parsed * row.supplier_share
    return total, False


def evaluate_prompts(
    structure: SplitStructure, *, dms_mandate_on: bool | None = None
) -> PromptReport:
    """Evaluate every co-occurrence expectation over a split structure.

    Pure function: no I/O, no refusal, no correction. Prompts are
    emitted in deterministic order (tree order, fixed rule order).
    """

    prompts: list[Prompt] = []
    skipped: list[SkipRecord] = []
    evaluated: set[str] = set()

    def flag(
        rule_id: str,
        severity: str,
        path: str,
        title: str,
        observed: str,
        expected_logic: str,
        likely_explanations: list[str],
        evidence_ref: str,
        scope: str,
    ) -> None:
        prompts.append(
            Prompt(
                rule_id=rule_id,
                severity=severity,
                path=path,
                title=title,
                observed=observed,
                expected_logic=expected_logic,
                likely_explanations=likely_explanations,
                evidence_ref=evidence_ref,
                scope=scope,
            )
        )
        evaluated.add(rule_id)

    def skip(rule_id: str, path: str, reason: str) -> None:
        skipped.append(SkipRecord(rule_id=rule_id, path=path, reason=reason))

    # Structure-level catalog-only entries: always recorded as skipped.
    skip("R11", "", "PHEV energy detail is not carried by the structure (energy is NEV/ICE only).")
    skip("X1", "", "Enforced structurally: morphology is a single field per trim.")
    skip("X2", "", "Enforced structurally: morphology is a single field per trim.")

    if dms_mandate_on is True:
        flag(
            "R12",
            "info",
            "",
            "DMS mandate on: expect +1 cabin camera",
            "dms_mandate_on is true for this evaluation.",
            "With the DMS mandate on (GB 47955-2026, from 2027-01-01), camera totals include +1 cabin (DMS/OMS) camera; workbook-caliber P05 totals include DMS/OMS.",
            ["The mandate switch is on for this run; totals already include the cabin camera."],
            "verification report §3 (R12) + synthesis §B",
            "structure",
        )
        evaluated.add("R12")
    else:
        skip("R12", "", "No run context supplied or the DMS mandate is off.")

    for oi, oem in enumerate(structure.oems):
        for pi, nameplate in enumerate(oem.nameplates):
            for gi, generation in enumerate(nameplate.generations):
                for ti, trim in enumerate(generation.trims):
                    path = (
                        f"oem[{oi}]/nameplates[{pi}]/generations[{gi}]/trims[{ti}]"
                        f" ({oem.oem_id}/{nameplate.nameplate_id}/{generation.generation_id}/{trim.trim_id})"
                    )
                    _evaluate_trim(
                        trim,
                        path,
                        oem.oem_id,
                        nameplate.nameplate_id,
                        nameplate.model_year,
                        flag,
                        skip,
                        evaluated,
                    )

    return PromptReport(
        prompts=prompts,
        skipped=skipped,
        anomaly_count=sum(1 for prompt in prompts if prompt.severity == "anomaly"),
        info_count=sum(1 for prompt in prompts if prompt.severity == "info"),
        rules_evaluated=sorted(evaluated),
        rules_skipped=sorted({record.rule_id for record in skipped}),
    )


def _evaluate_trim(
    trim: TrimSplit,
    path: str,
    oem_id: str,
    nameplate_id: str,
    model_year: int | None,
    flag,
    skip,
    evaluated: set[str],
) -> None:
    rows_by_line = _rows_by_line(trim)
    p02_rows = rows_by_line.get("P02", [])
    p03_rows = rows_by_line.get("P03", [])
    p05_rows = rows_by_line.get("P05", [])
    p01_rows = rows_by_line.get("P01", [])

    p02_classes = [(row, classify_solution(row.solution_code, "P02")) for row in p02_rows]
    dc_rows = [row for row, cls in p02_classes if cls is not None and cls.solution_class == "dc"]
    cammod_rows = [
        row for row, cls in p02_classes if cls is not None and cls.solution_class == "cammod"
    ]
    unclassified_p02 = [row for row, cls in p02_classes if cls is None and row.solution_code]
    bundle_trim = any(row.price_basis == "bundle" for row in trim.fitments) or any(
        is_huawei_solution(row.solution_code) for row in trim.fitments
    )

    # Known data errors: flagged as info, excluded from ladder stats.
    known_error = lookup_known_data_error(oem_id, nameplate_id, model_year, "P05")
    if known_error is not None and p05_rows:
        flag(
            "KNOWN_ERROR",
            "info",
            path,
            "Known data error (flagged, not corrected)",
            f"P05 rows on this trim match the registered known data error: {known_error.description}",
            "The correct pattern is the VA7 row (paired host/screen rates + one cheap single camera).",
            ["Known misfill (Ho Q6); excluded from ladder/co-occurrence statistics."],
            "Ho Q6 ruling + services/splits/morphology.py",
            f"{oem_id}/{nameplate_id}/{model_year}",
        )
        evaluated.add("KNOWN_ERROR")

    # R1: DC implies cameras.
    active_dc = [row for row in dc_rows if row.fitment > 0]
    if active_dc and not p05_rows:
        if bundle_trim:
            skip("R1", path, "Bundle trim: cameras are included in the bundle price (Ho Q11).")
        else:
            flag(
                "R1",
                "anomaly",
                path,
                "Driving domain controller without cameras",
                f"P02 domain-controller rows present ({len(active_dc)}), no P05 camera rows.",
                "A trim with a driving domain controller normally carries camera rows (63/64 DC blocks in the workbook).",
                ["Data gap: P05 rows missing for this trim.", "Genuine exception (1/64 in the workbook)."],
                "verification report §1.1 (H1 VERIFIED)",
                "all OEMs",
            )
    elif active_dc:
        evaluated.add("R1")

    # R2: camera-count ladder.
    if known_error is not None and p05_rows:
        skip("R2", path, "Known data error: trim excluded from ladder statistics (Ho Q6).")
    else:
        total, uncountable = _p05_total(trim, rows_by_line)
        if uncountable:
            if p05_rows and (dc_rows or cammod_rows):
                skip("R2", path, "P05 labels carry no countable group size; ladder not evaluated.")
        elif p05_rows and (dc_rows or cammod_rows):
            embedded = 1 if cammod_rows else 0
            observed = total + embedded
            for row in dc_rows + cammod_rows:
                platform = dc_platform(row.solution_code)
                if platform is None:
                    continue
                expected = _ladder_expected(platform, model_year)
                if expected is None:
                    skip(
                        "R2",
                        path,
                        f"No ladder tier for platform {platform!r}; ladder not evaluated for this row.",
                    )
                    continue
                evaluated.add("R2")
                if all(abs(observed - value) > LADDER_TOLERANCE for value in expected):
                    expected_text = " or ".join(str(value) for value in sorted(expected))
                    flag(
                        "R2",
                        "anomaly",
                        path,
                        "Camera count off the platform ladder",
                        f"Platform {platform} (row {row.solution_code!r}) with total {observed:g} cameras "
                        f"(P05 {total:g} + {embedded} embedded), expected {expected_text} ± {LADDER_TOLERANCE}.",
                        "Camera totals scale with the driving-compute platform: IFC/module 5, 8620 7, 8650 10 (2026)/11 (2027+), RHP/NGX 11.",
                        [
                            "Data gap: P05 group size mislabeled or missing.",
                            "Morphology/trim transition: the trim mixes sub-populations with different platforms.",
                            "Genuine exception: a lower camera count on a high platform is possible but unusual.",
                        ],
                        "verification report §1.1 (H1 ladder, corrected 8650-2026 count 10)",
                        "Hongqi-verified; applied per trim where countable",
                    )

    # R3/R4/R5: morphology expectations.
    morphology = trim.morphology
    central_rows = [
        row
        for row in p03_rows
        if (cls := classify_solution(row.solution_code, "P03")) is not None
        and cls.solution_class == "central"
    ]
    host_rows = [
        row
        for row in p01_rows
        if (cls := classify_solution(row.solution_code, "P01")) is not None
        and cls.solution_class == "host"
    ]
    if morphology in ("ivi_one_box", "fused"):
        evaluated.add("R3")
        if central_rows:
            flag(
                "R3",
                "anomaly",
                path,
                "Integrated morphology with a separate central screen",
                f"Morphology {morphology!r} with {len(central_rows)} P03 central row(s).",
                "IVI one-box / fused trims have no separate P03 central row: the screen lives inside P01.",
                [
                    "Morphology mislabeled: the trim may be a discrete-host trim.",
                    "Data gap: stray P03 rows carried over from another trim.",
                    "Morphology transition: the trim spans the switch year.",
                ],
                "verification report §1.2 (H2) + Ho Q1/Q5",
                f"morphology {morphology}",
            )
    elif morphology == "discrete_host":
        evaluated.add("R4")
        if host_rows and not central_rows:
            flag(
                "R4",
                "anomaly",
                path,
                "Discrete host without a central screen",
                "Discrete-host trim with P01 host rows and no P03 central row.",
                "A discrete-host trim normally carries an independent P03 central screen (89% of non-one-box host blocks).",
                [
                    "Data gap: the P03 row is missing for this trim.",
                    "Morphology mislabeled: the trim may be a fused/one-box trim.",
                    "Genuine exception (11% of non-one-box host blocks have no central row).",
                ],
                "verification report §1.3 (H3 VERIFIED, OEM-conditioned)",
                "morphology discrete_host",
            )
    elif morphology is None:
        skip("R3", path, "No morphology on the trim; integrated-form expectations not evaluated.")
        skip("R4", path, "No morphology on the trim; discrete-host expectations not evaluated.")
    else:
        skip(
            "R3",
            path,
            f"Morphology is {morphology}; integrated-form expectations do not apply.",
        )
        skip(
            "R4",
            path,
            f"Morphology is {morphology}; discrete-host expectations do not apply.",
        )

    if morphology is not None:
        fact = lookup_morphology_fact(oem_id, nameplate_id, model_year)
        if fact is None:
            skip(
                "R5",
                path,
                "No verified registry fact for this (OEM, nameplate, year); no generalization (Ho Q9).",
            )
        elif fact.morphology != morphology:
            evaluated.add("R5")
            flag(
                "R5",
                "anomaly",
                path,
                "Morphology contradicts the verified registry fact",
                f"Trim morphology {morphology!r} but the registry fact for "
                f"{oem_id}/{nameplate_id}/{model_year} is {fact.morphology!r}.",
                "The trim's morphology matches the individually verified (OEM, nameplate, year) fact.",
                [
                    "Morphology mislabeled on this trim.",
                    "The registry fact is stale (a later switch was verified for this model).",
                ],
                fact.evidence,
                f"{oem_id}/{nameplate_id}/{model_year}",
            )
        else:
            evaluated.add("R5")
    else:
        skip("R5", path, "No morphology on the trim.")

    # R6/X3/X4: within-class P02 overlap (prompt only; Ho Q7).
    if unclassified_p02:
        skip("R6", path, "P02 rows with unclassifiable solution codes; overlap not evaluated.")
    elif p02_rows:
        evaluated.add("R6")
        for solution_class, label in (("dc", "domain controller"), ("cammod", "front-view module")):
            class_rows = [
                row
                for row, cls in p02_classes
                if cls is not None and cls.solution_class == solution_class
            ]
            maxima = _max_rate_by_solution(class_rows)
            total_rate = sum(maxima.values())
            if len(maxima) >= 2 and total_rate > 1.0 + 1e-9:
                flag(
                    "R6",
                    "anomaly",
                    path,
                    f"Same-function {label} solutions overlap",
                    f"{len(maxima)} distinct {label} solutions with rates summing to {total_rate:.3f} (> 1).",
                    f"Within one function class, distinct {label} solutions normally substitute: rates sum to <= 1 per trim.",
                    [
                        "Merged sub-populations: the trim mixes configurations that should be separate trims.",
                        "Legitimate independent penetrations (Ho Q7): each solution independently fits a share of the trim's volume.",
                    ],
                    "verification report §3 (R6) + Ho Q7 fitment definition",
                    "per trim",
                )
        dc_codes = {row.solution_code for row in dc_rows if row.solution_code}
        if dc_rows and cammod_rows:
            evaluated.add("X3")
            flag(
                "X3",
                "anomaly",
                path,
                "Domain controller + front-view module in one trim",
                "Both a driving domain controller and a front-view module are present.",
                "DC and front-view module are different compute tiers; one trim normally carries one.",
                ["Merged sub-populations with different compute tiers.", "Transition trim spanning a platform switch."],
                "verification report §3 (X3)",
                "per trim",
            )
        if len(dc_codes) >= 2:
            evaluated.add("X4")
            flag(
                "X4",
                "anomaly",
                path,
                "Two domain-controller solutions in one trim",
                f"Distinct DC solutions: {sorted(dc_codes)}.",
                "One driving domain controller per trim; two distinct solutions suggests merged sub-populations.",
                ["Merged sub-populations.", "Legitimate independent penetrations (Ho Q7) — verify per trim."],
                "verification report §3 (X4)",
                "per trim",
            )

    # R7/X5: central-slot substitution; passenger screens excluded (Ho Q3).
    central_maxima = _max_rate_by_solution(central_rows)
    if central_rows:
        evaluated.add("R7")
        central_total = sum(central_maxima.values())
        if len(central_maxima) >= 2 and central_total > 1.0 + 1e-9:
            flag(
                "R7",
                "anomaly",
                path,
                "Central-display variants overlap",
                f"{len(central_maxima)} distinct central variants with rates summing to {central_total:.3f} (> 1).",
                "ABT central-display variants substitute within the central slot: rates sum to <= 1. Passenger screens (CDD/CDI) coexist and are excluded from this sum.",
                [
                    "Merged sub-populations with different central screens.",
                    "Legitimate independent penetrations (Ho Q7) — verify per trim.",
                ],
                "verification report §3 (R7, rewritten per Ho Q3)",
                "per trim",
            )
        if len(central_maxima) >= 2:
            evaluated.add("X5")

    # R8: instrument rows booked under P01.
    for row in p01_rows:
        cls = classify_solution(row.solution_code, "P01")
        if cls is not None and cls.solution_class == "instrument":
            evaluated.add("R8")
            flag(
                "R8",
                "anomaly",
                path,
                "Instrument row booked under P01",
                f"P01 row {row.solution_code!r} is an instrument row.",
                "Instrument rows belong to P03 (screens), never to P01 (Ho: instrument counts in P03).",
                ["Row mis-booked: move it to the P03 block with the same rate and price."],
                "Ho Q3 ruling + verification report §2.3/F14",
                "all OEMs",
            )

    # R9: 4G/5G variant substitution.
    p04_rows = rows_by_line.get("P04", [])
    variant_maxima: dict[str, float] = {}
    for row in p04_rows:
        cls = classify_solution(row.solution_code, "P04")
        if cls is None or cls.solution_class not in ("terminal_4g", "terminal_5g"):
            continue
        if row.fitment_kind == "rate":
            variant_maxima[cls.solution_class] = max(
                variant_maxima.get(cls.solution_class, 0.0), row.fitment
            )
    if len(variant_maxima) == 2:
        evaluated.add("R9")
        variant_total = sum(variant_maxima.values())
        if variant_total > 1.0 + 1e-9:
            flag(
                "R9",
                "anomaly",
                path,
                "4G/5G variants overlap",
                f"4G rate {variant_maxima['terminal_4g']:.3f} + 5G rate {variant_maxima['terminal_5g']:.3f} = {variant_total:.3f} (> 1).",
                "4G and 5G comm-terminal variants substitute: one terminal per car, rates sum to <= 1.",
                ["Merged sub-populations with different terminal generations.", "Variant rates double-counted."],
                "verification report §3 (R9)",
                "per trim",
            )

    # R10: high camera count implies driving compute.
    total, uncountable = _p05_total(trim, rows_by_line)
    if uncountable:
        if p05_rows:
            skip("R10", path, "P05 labels carry no countable group size.")
    elif total is not None and total >= 7 and not dc_rows and not cammod_rows:
        evaluated.add("R10")
        flag(
            "R10",
            "anomaly",
            path,
            "High camera count without driving compute",
            f"Total {total:g} cameras with no P02 driving-compute rows.",
            "Trims with >= 7 cameras usually carry driving compute (0.94 block-level co-occurrence).",
            [
                "Data gap: P02 rows missing for this trim.",
                "Parking-only surround group: a legitimate exception (surround cameras without a DC).",
            ],
            "verification report §3 (R10)",
            "per trim",
        )
    elif total is not None:
        evaluated.add("R10")

    # R13: bare P.O basket rows.
    for row in trim.fitments:
        if is_po_basket(row.product_id):
            evaluated.add("R13")
            flag(
                "R13",
                "anomaly",
                path,
                "Undecomposed P.O basket row",
                f"Bare P.O row (solution {row.solution_code!r}).",
                "P.O is decomposed to the finest granularity: HUD/radar/gateway/body-domain/APA/AVM/UWB each carry their own row (catalog: "
                + ", ".join(sorted(PO_SUBPRODUCTS))
                + ").",
                ["Legacy basket row not yet decomposed; split it into catalog sub-product rows."],
                "Ho Q8 ruling + services/splits/catalog.py",
                "all OEMs",
            )

    # AVM1: AVM implies a surround-view group (reverse does not hold).
    avm_rows = [
        row
        for row in trim.fitments
        if (row.product_id == "AVM" or (row.solution_code or "").upper().find("AVM") >= 0)
        and row.fitment > 0
    ]
    if avm_rows:
        evaluated.add("AVM1")
        surround = [
            row
            for row in p05_rows
            if (cls := classify_solution(row.solution_code, "P05")) is not None
            and cls.solution_class == "surround_group"
        ]
        countable_surround = total is not None and total >= 4
        if not surround and not countable_surround:
            flag(
                "AVM1",
                "anomaly",
                path,
                "AVM without a surround-view camera group",
                "AVM rows present with no surround-view camera group in P05.",
                "A trim with AVM carries a surround-view camera group; the reverse does not hold (a surround group does not imply AVM).",
                ["Data gap: the P05 surround-group row is missing.", "AVM row mislabeled."],
                "Ho Q8 ruling",
                "per trim",
            )

    # BUNDLE1: Huawei bundle labeling + no separate P03/P05 rows.
    for row in trim.fitments:
        if is_huawei_solution(row.solution_code) and row.price_basis != "bundle":
            evaluated.add("BUNDLE1")
            flag(
                "BUNDLE1",
                "anomaly",
                path,
                "Huawei row not labeled bundle price",
                f"Huawei row {row.solution_code!r} carries price_basis {row.price_basis!r}.",
                "Huawei full-solution rows carry price_basis 'bundle' (screen + cameras included) and are never compared with discrete ASPs.",
                ["Label missing: set price_basis to 'bundle' on this row."],
                "Ho Q11 ruling",
                "all OEMs",
            )
    if bundle_trim and (p03_rows or p05_rows):
        evaluated.add("BUNDLE1")
        lines = sorted({*({"P03"} if p03_rows else set()), *({"P05"} if p05_rows else set())})
        flag(
            "BUNDLE1",
            "anomaly",
            path,
            "Bundle trim carries separate P03/P05 rows",
            f"Bundle-priced trim with separate rows in {', '.join(lines)}.",
            "Bundle trims carry no separate P03/P05 rows: the screen and cameras are included in the bundle price.",
            ["Double-count risk: remove the separate rows or un-bundle the trim."],
            "Ho Q11 ruling",
            "per trim",
        )

    # SCREEN1: one-box/fused P01 ASP includes the screen.
    if morphology in ("ivi_one_box", "fused"):
        for row in p01_rows:
            if row.price_basis == "discrete":
                evaluated.add("SCREEN1")
                flag(
                    "SCREEN1",
                    "anomaly",
                    path,
                    "Integrated-morphology P01 ASP not labeled as including the screen",
                    f"P01 row {row.solution_code!r} carries price_basis 'discrete' on a {morphology} trim.",
                    "P01 ASPs on integrated-morphology trims include the screen and carry price_basis 'includes_screen'; they are never compared with discrete host ASPs.",
                    ["Label missing: set price_basis to 'includes_screen' on this row."],
                    "Ho Q1/C4 ruling",
                    f"morphology {morphology}",
                )

    # EMBED1: embedded-camera accounting note.
    if cammod_rows:
        evaluated.add("EMBED1")
        flag(
            "EMBED1",
            "info",
            path,
            "Front-view module embeds one camera",
            f"{len(cammod_rows)} front-view module row(s) present; camera totals include +1 embedded unit.",
            "MFK/IFC front-view modules embed 1 camera: totals are annotated incl./excl. the embedded unit; a 1-camera difference is normal tolerance, never an anomaly.",
            ["Accounting convention (Ho Q2); no action needed."],
            "verification report §5 + Ho Q2",
            "per trim",
        )

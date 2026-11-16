"""Morphology registry + known-data-error registry (Phase 2).

Morphology is a MODEL x YEAR attribute (Ho Q1/Q5/Q9): the same
nameplate can switch form across years (Corolla 2027), and a form
observed on one model NEVER generalizes to others (Ho Q9: no
single-case rule is ever promoted). This module therefore holds
only individually verified (OEM, nameplate, year) facts, matched
EXACTLY (modulo the small explicit id-alias maps below — no fuzzy
matching). A structure whose ids match no fact yields no morphology
expectation; the evaluator records the skip honestly.

Known data errors are likewise scoped facts: the Jetta VA3 11-camera
row (Ho Q6) is flagged as a known error and excluded from ladder
statistics wherever it appears, never silently corrected.

OEM id aliases cover the workbook's sheet names in both languages;
nameplate aliases cover the latin/Chinese name pairs used in the
workbook. Anything outside these maps matches only on its exact
normalized id.
"""

from __future__ import annotations

MORPHOLOGY_LABELS: dict[str, dict[str, str | bool]] = {
    "ivi_one_box": {
        "label": "IVI one-box (with screen)",
        "screen_in_p01": True,
        "description": "Host + screen in one box (P01 definition: '带 SoC 和屏幕的一体机'); no separate P03 central row.",
    },
    "discrete_host": {
        "label": "Discrete host",
        "screen_in_p01": False,
        "description": "Separate host + independent P03 central screen; the split form.",
    },
    "scdc": {
        "label": "Smart cockpit domain controller",
        "screen_in_p01": False,
        "description": "Cockpit domain controller driving independent screens (one chip, multiple screens).",
    },
    "central_compute": {
        "label": "Central compute",
        "screen_in_p01": False,
        "description": "Cross-domain central compute absorbing cockpit + driving compute.",
    },
    "fused": {
        "label": "Fused form (screen inside the cockpit)",
        "screen_in_p01": True,
        "description": "Screen fused into the cockpit/P01 (VW T-Roc/CC 2026, Ho Q5); no separate P03 row, not a data gap.",
    },
}

_OEM_ALIASES = {
    "hongqi": "hongqi",
    "红旗": "hongqi",
    "faw-hongqi": "hongqi",
    "faw-vw": "faw-vw",
    "一汽大众": "faw-vw",
    "faw-vw-jetta": "faw-vw",
    "jetta": "jetta",
    "捷达": "jetta",
    "faw-toyota": "faw-toyota",
    "一汽丰田": "faw-toyota",
    "toyota": "faw-toyota",
    "丰田": "faw-toyota",
    "dongfeng-honda": "dongfeng-honda",
    "东风本田": "dongfeng-honda",
    "honda": "dongfeng-honda",
    "本田": "dongfeng-honda",
}

_NAMEPLATE_ALIASES = {
    "corolla": "corolla",
    "卡罗拉": "corolla",
    "t-roc": "t-roc",
    "troc": "t-roc",
    "探歌": "t-roc",
    "cc": "cc",
    "avalon": "avalon",
    "亚洲龙": "avalon",
    "rav4": "rav4",
    "荣放": "rav4",
    "frontlander": "frontlander",
    "锐放": "frontlander",
    "crownkluger": "crown-kluger",
    "crown-kluger": "crown-kluger",
    "皇冠陆放": "crown-kluger",
    "granvia": "granvia",
    "格瑞维亚": "granvia",
    "va3": "va3",
    "va7": "va7",
}


def normalize_oem_id(oem_id: str) -> str:
    """Normalize an OEM id for registry lookup (alias map + lowercase)."""

    key = oem_id.strip().lower()
    return _OEM_ALIASES.get(key, key)


def normalize_nameplate_id(nameplate_id: str) -> str:
    """Normalize a nameplate id for registry lookup (alias map + lowercase)."""

    key = nameplate_id.strip().lower()
    return _NAMEPLATE_ALIASES.get(key, key)


class MorphologyFact:
    """One verified (OEM, nameplate, year) -> morphology fact."""

    def __init__(
        self, oem_id: str, nameplate_id: str, model_year: int, morphology: str, evidence: str
    ) -> None:
        self.oem_id = oem_id
        self.nameplate_id = nameplate_id
        self.model_year = model_year
        self.morphology = morphology
        self.evidence = evidence


#: Individually verified morphology facts. Scope is EXACTLY the
#: (OEM, nameplate, year) triple — nothing here generalizes (Ho Q9).
MORPHOLOGY_FACTS: list[MorphologyFact] = [
    MorphologyFact(
        "faw-toyota", "corolla", 2026, "ivi_one_box", "report §1.2: Corolla 2026 one-box (P01 host + instrument, zero P03 central rows)"
    ),
    MorphologyFact(
        "faw-toyota",
        "corolla",
        2027,
        "discrete_host",
        "Ho Q9 (2026-11-16): Corolla 2027 switches to discrete (SA8255P + independent P03); INDIVIDUAL CASE ONLY, never generalized",
    ),
    MorphologyFact(
        "faw-toyota", "avalon", 2026, "ivi_one_box", "report §1.2: Toyota 2026 fuel blocks one-box"
    ),
    MorphologyFact(
        "faw-toyota", "rav4", 2026, "ivi_one_box", "report §1.2: Toyota 2026 fuel blocks one-box"
    ),
    MorphologyFact(
        "faw-toyota",
        "frontlander",
        2026,
        "ivi_one_box",
        "report §1.2: Toyota 2026 fuel blocks one-box",
    ),
    MorphologyFact(
        "faw-toyota",
        "crown-kluger",
        2026,
        "ivi_one_box",
        "report §1.2: Toyota 2026 fuel blocks one-box",
    ),
    MorphologyFact(
        "faw-toyota", "granvia", 2026, "ivi_one_box", "report §1.2: Toyota 2026 fuel blocks one-box"
    ),
    MorphologyFact(
        "faw-vw", "t-roc", 2026, "fused", "Ho Q5 (2026-11-16): VW-2026 T-Roc no-P03 blocks are the fused form"
    ),
    MorphologyFact(
        "faw-vw", "cc", 2026, "fused", "Ho Q5 (2026-11-16): VW-2026 CC no-P03 blocks are the fused form"
    ),
]


def lookup_morphology_fact(
    oem_id: str, nameplate_id: str, model_year: int | None
) -> MorphologyFact | None:
    """The verified morphology fact for a triple, or ``None``.

    ``None`` means "no verified fact" — the evaluator must skip the
    morphology-consistency check, never assume a form.
    """

    if model_year is None:
        return None
    oem = normalize_oem_id(oem_id)
    plate = normalize_nameplate_id(nameplate_id)
    for fact in MORPHOLOGY_FACTS:
        if fact.oem_id == oem and fact.nameplate_id == plate and fact.model_year == model_year:
            return fact
    return None


class KnownDataError:
    """One scoped known data error (flagged, never silently corrected)."""

    def __init__(
        self,
        oem_id: str,
        nameplate_id: str,
        model_year: int,
        product_id: str,
        description: str,
        disposition: str,
    ) -> None:
        self.oem_id = oem_id
        self.nameplate_id = nameplate_id
        self.model_year = model_year
        self.product_id = product_id
        self.description = description
        self.disposition = disposition


#: Known workbook data errors, scoped exactly (Ho Q6).
KNOWN_DATA_ERRORS: list[KnownDataError] = [
    KnownDataError(
        "jetta",
        "va3",
        2026,
        "P05",
        "11-camera group at rate 0.1, CNY 160, with no P02/P03/P04 rows — misfilled (Ho Q6). "
        "Correct pattern is the VA7 row: paired host/screen rates + one cheap single camera.",
        "Flag as a known data error; exclude from camera-ladder and co-occurrence statistics.",
    )
]


def lookup_known_data_error(
    oem_id: str, nameplate_id: str, model_year: int | None, product_id: str
) -> KnownDataError | None:
    """The known data error for a scoped row, or ``None``."""

    if model_year is None:
        return None
    oem = normalize_oem_id(oem_id)
    plate = normalize_nameplate_id(nameplate_id)
    for error in KNOWN_DATA_ERRORS:
        if (
            error.oem_id == oem
            and error.nameplate_id == plate
            and error.model_year == model_year
            and error.product_id == product_id
        ):
            return error
    return None


#: OEMs whose missing P04 is a verified genuine fact (Ho Q10: Jetta
#: genuinely has no T-BOX). No expectation ever requires P04 presence
#: for these OEMs, and no market-average T-BOX fitment is ever applied
#: to them — P04 uses per-OEM fitment only.
OEMS_WITHOUT_TBOX = frozenset({"jetta"})

"""Solution-code alias layer (Phase 2, Ho Q4 ruling).

Ho 2026-11-16: classify by PRODUCT-LINE block, not by code expansion.
The same chip has different identities in different blocks: SA8650 in
P01 is a cockpit domain controller, in P02 an ADAS controller
assembly. This module therefore keys every classification by the
``(code, product-line)`` pair and assigns NO global code class.

Classification combines:

1. an explicit alias table for the workbook's solution vocabulary
   (verification report §2.1/§2.2, original labels preserved), and
2. the report §0.2 substring rules (MFK/IFC -> front-view module;
   RHP/NGX/8650/8620/IDU -> domain controller; ABT -> central
   display; CDD/CDI -> passenger display per Ho Q3), applied in the
   report's order (DC markers before CAMMOD markers: NGX:J6M is a
   domain controller by price + pairing, not a bare J6M module).

Unknown codes classify to ``None``: the prompt engine skips checks
that need a class rather than inferring one. Code expansions
(full names / platform attributions) are deliberately NOT recorded
(Ho Q4: no longer needed).

Camera-count parsing (:func:`parse_camera_count`) reads the group
size out of P05 solution labels (``*N`` multipliers, binocular = 2,
trinocular = 3, the 11-camera group). Labels without a countable
size return ``None`` (Toyota/Honda groups); the ladder check skips
them and records the skip.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SolutionClass:
    """A classified solution: its class within its product line."""

    solution_class: str
    role: str
    evidence: str


def normalize_code(code: str) -> str:
    """Normalize a solution label for alias lookup.

    Full-width colons become ``:``, whitespace is removed, and the
    label is uppercased. The ``主机:``/``仪表:`` prefixes are KEPT:
    for VW labels the prefix is the classifier.
    """

    return re.sub(r"\s+", "", code.replace("：", ":")).upper()


# Explicit aliases: (normalized code, product line) -> class.
# Covers the §2.1 vocabulary that substring rules would miss or
# misclassify. Labels are the workbook's own (see §2.1 tables).
_ALIASES: dict[tuple[str, str], SolutionClass] = {
    ("8155", "P01"): SolutionClass("host", "cockpit host SoC", "report §2.2: SA8155P cockpit SoC"),
    ("SA8155P", "P01"): SolutionClass("host", "cockpit host SoC", "report §2.2: SA8155P cockpit SoC"),
    ("8295", "P01"): SolutionClass("host", "cockpit host SoC", "report §2.2: SA8295P cockpit SoC"),
    ("SA8295P", "P01"): SolutionClass("host", "cockpit host SoC", "report §2.2: SA8295P cockpit SoC"),
    ("SA8255P", "P01"): SolutionClass("host", "cockpit host SoC", "report §2.2: SA8255P cockpit SoC"),
    ("8676", "P01"): SolutionClass("host", "cockpit host SoC", "report §2.1: VW host code"),
    ("8397", "P01"): SolutionClass("host", "cockpit host SoC", "report §2.1: Hongqi host code"),
    ("8538", "P01"): SolutionClass("host", "cockpit host SoC", "report §2.1: Jetta host code"),
    ("X9HP", "P01"): SolutionClass("host", "cockpit host SoC", "report §2.2: SemiDrive X9 cockpit SoC"),
    ("X9SP", "P01"): SolutionClass("host", "cockpit host SoC", "report §2.2: SemiDrive X9 cockpit SoC"),
    ("E04", "P01"): SolutionClass("host", "cockpit host SoC", "report §2.2: SemiDrive cockpit chip"),
    ("AC8015", "P01"): SolutionClass("host", "cockpit host SoC", "report §2.2: AutoChips cockpit SoC"),
    ("AC8025", "P01"): SolutionClass("host", "cockpit host SoC", "report §2.2: AutoChips cockpit SoC"),
    ("RCARM3", "P01"): SolutionClass("host", "cockpit host SoC", "report §2.2: Renesas R-Car M3"),
    ("R-CARM3", "P01"): SolutionClass("host", "cockpit host SoC", "report §2.2: Renesas R-Car M3"),
    ("瑞萨H3", "P01"): SolutionClass("host", "cockpit host SoC", "report §2.2: Renesas R-Car H3"),
    ("瑞萨", "P01"): SolutionClass("host", "cockpit host SoC", "report §2.1: Hongqi host code"),
    ("SPHE8368", "P01"): SolutionClass("host", "cockpit host SoC", "report §2.2: low-end cockpit SoC (grade D)"),
    ("三星V7", "P01"): SolutionClass("host", "cockpit host SoC", "report §2.1: VW host code"),
    ("IDU+DCM", "P02"): SolutionClass("dc", "driving domain controller", "report §2.2: BYD-supplied, DC by price"),
    ("智驾", "P02"): SolutionClass("dc", "driving domain controller", "report §2.1: Toyota P02 label"),
    ("J3", "P02"): SolutionClass("cammod", "front-view integrated module", "report §0.2: bare J3 is CAMMOD"),
    ("J6M", "P02"): SolutionClass("cammod", "front-view integrated module", "report §0.2: bare J6M is CAMMOD"),
    ("J6H", "P02"): SolutionClass("cammod", "front-view integrated module", "report §0.2: bare J6H is CAMMOD"),
    ("KBT8", "P03"): SolutionClass("other_screen", "other display", "report §2.1: VW display code"),
    ("RSE21.4", "P03"): SolutionClass("other_screen", "rear-seat entertainment", "report §2.1: VW display code"),
    ("SSL/SSR6", "P03"): SolutionClass("other_screen", "other display", "report §2.1: VW display code"),
    ("ISM", "P03"): SolutionClass("other_screen", "other display", "report §2.1: VW display code"),
    ("CONMOD", "P04"): SolutionClass("terminal", "connectivity module", "report §2.2: VW comm module"),
    ("OCU3", "P04"): SolutionClass("terminal", "online connectivity unit", "report §2.2: VW OCU"),
    ("OCU4", "P04"): SolutionClass("terminal", "online connectivity unit", "report §2.2: VW OCU"),
}

_DC_MARKERS = ("RHP", "NGX", "8650", "8620", "IDU", "智驾")
_CAMMOD_MARKERS = ("MFK", "IFC", "J3", "J6M", "J6H")


def classify_solution(solution_code: str | None, product_line: str) -> SolutionClass | None:
    """Classify a solution label within its product-line block.

    Returns ``None`` when the label is absent or unclassifiable — the
    caller must skip class-dependent checks, never guess.
    """

    if not solution_code:
        return None
    code = normalize_code(solution_code)
    if not code or code == "NA":
        return None
    alias = _ALIASES.get((code, product_line))
    if alias is not None:
        return alias
    if product_line == "P01":
        if "仪表" in solution_code or "INSTRUMENT" in code:
            return SolutionClass("instrument", "instrument row booked under P01", "report §2.3/F14")
        if "华为" in solution_code or "HUAWEI" in code:
            return SolutionClass("bundle", "Huawei full-solution bundle", "Ho Q11: bundle price")
        if code.startswith("主机:"):
            return SolutionClass("host", "cockpit host SoC", "report §2.1: VW host label")
        return SolutionClass("host", "cockpit host SoC", "P01 block default: SoC/host code (Ho Q4)")
    if product_line == "P02":
        if "华为" in solution_code or "HUAWEI" in code:
            return SolutionClass("dc", "driving domain controller (Huawei bundle)", "Ho Q11: bundle price")
        if any(marker in code for marker in _DC_MARKERS):
            return SolutionClass("dc", "driving domain controller", "report §0.2: DC markers")
        if any(marker in code for marker in _CAMMOD_MARKERS):
            return SolutionClass("cammod", "front-view integrated module", "report §0.2: CAMMOD markers")
        return None
    if product_line == "P03":
        if "CDD" in code or "CDI" in code:
            return SolutionClass("passenger", "passenger display", "Ho Q3: CDD/CDI are passenger screens")
        if "FID" in code or "仪表" in solution_code:
            return SolutionClass("instrument", "instrument display", "report §2.1: FID/instrument label")
        if "ABT" in code or "中控" in solution_code or "三联屏" in solution_code:
            return SolutionClass("central", "central display", "report §2.1: ABT/central label")
        if any(marker in code for marker in ("KBT", "RSE", "SSL", "ISM")) or any(
            word in solution_code for word in ("吸顶", "扶手", "后排")
        ):
            return SolutionClass("other_screen", "other display", "report §2.1: other-screen label")
        return None
    if product_line == "P04":
        if "华为" in solution_code or "HUAWEI" in code:
            return SolutionClass("bundle", "Huawei full-solution bundle", "Ho Q11: bundle price")
        if "5G" in code:
            return SolutionClass("terminal_5g", "5G comm terminal", "report §2.1: 5G label")
        if "4G" in code:
            return SolutionClass("terminal_4g", "4G comm terminal", "report §2.1: 4G label")
        return SolutionClass("terminal", "comm terminal", "P04 block default (Ho Q4)")
    if product_line == "P05":
        if "环视" in solution_code:
            return SolutionClass("surround_group", "surround-view camera group", "report §2.1: surround label")
        if "11" in code and "颗" in solution_code:
            return SolutionClass("camera_group_11", "11-camera group", "report §1.1: 11-camera group")
        if "前视" in solution_code or "后视" in solution_code:
            return SolutionClass("single_camera", "single-direction camera", "report §2.1: directional label")
        return SolutionClass("camera_unspecified", "camera(s), group unspecified", "report §2.1: uncounted label")
    return None


def is_huawei_solution(solution_code: str | None) -> bool:
    """True when the label names Huawei (bundle-price rows, Ho Q11)."""

    if not solution_code:
        return False
    return "华为" in solution_code or "HUAWEI" in normalize_code(solution_code)


def dc_platform(solution_code: str | None) -> str | None:
    """The driving-compute platform of a P02 label, for the R2 ladder.

    Returns one of ``"ifc"``, ``"8620"``, ``"8650"``, ``"rhp"``,
    ``"ngx"``, ``"idu"``, ``"huawei"``, ``"other_dc"``, or ``None``
    when the label names no driving compute at all. CAMMOD labels
    (MFK/IFC/J3/J6) return ``"ifc"`` — the ladder's 5-camera tier is
    the front-view-module tier, whatever the module's chip.
    """

    if not solution_code:
        return None
    code = normalize_code(solution_code)
    if "华为" in solution_code or "HUAWEI" in code:
        return "huawei"
    if "RHP" in code:
        return "rhp"
    if "NGX" in code:
        return "ngx"
    if "8650" in code:
        return "8650"
    if "8620" in code:
        return "8620"
    if "IDU" in code:
        return "idu"
    if "智驾" in solution_code:
        return "other_dc"
    if any(marker in code for marker in _CAMMOD_MARKERS):
        return "ifc"
    return None


_COUNT_MULTIPLIER = re.compile(r"\*(\d+)")
_CHINESE_NUMERALS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8}


def parse_camera_count(solution_code: str | None) -> int | None:
    """Parse the camera-group size out of a P05 solution label.

    ``*N`` multipliers, binocular/trinocular markers, and the explicit
    11-camera group parse to counts; labels without a countable size
    (Toyota/Honda groups, bare ``摄像头``) return ``None``. When a
    label lists several groups (``前视*2 + 环视*4``), the counts sum.
    """

    if not solution_code:
        return None
    label = solution_code
    if "11" in label and "颗" in label:
        return 11
    total = 0
    for match in _COUNT_MULTIPLIER.finditer(label):
        total += int(match.group(1))
    if total:
        return total
    if "双目" in label:
        return 2
    if "三目" in label:
        return 3
    if "单目" in label:
        return 1
    return None

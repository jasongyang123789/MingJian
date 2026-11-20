"""Deterministic completeness checks (Phase 4, Track 8).

The no-LLM path of the red team, and the layer that MUST catch the
desay-2020 miss: the case ran on the generic corporate template with
no NEV variable and no domain-controller-substitution variable, and no
transmission chain at all, so the biggest revenue driver was invisible
to the model.

Design rule — evidence-grounded, never hallucinating: a driver check
fires ONLY when the case's own internal situation (or decision
question) names the driver but no variable represents it. The check
never invents a driver the case never mentions, which is what makes
the complete-case acceptance test pass: a case whose situation
mentions NEV and whose variable table contains it produces no
finding. Coverage matching scans variable ``name`` + ``description``
only, never free-form evidence text — a passing mention of NEV inside
another variable's evidence is not modelling NEV.

Checks, in evaluation order:

1. Catalog driver checks (``DRIVER_CATALOG``): one per known
   structural driver. ``missing_driver`` when the variable is absent;
   ``missing_link`` when the variable exists but no formula connects
   it to revenue/share (a present-but-unlinked driver moves nothing).
2. Unlinked-driver check: any variable whose name matches a catalog
   driver but which no formula references.
3. ``unjustified_discount``: a growth variable whose own evidence
   cites a recent realized GROWTH rate more than 2x its mode AND carries
   no justification note (recovery year, one-off, low base, explicit
   conservatism, margin/price pressure, or a stated scope difference).
   Like-for-like only: a percentage is compared with the mode ONLY when
   the word next to it says it is a growth rate — a revenue share
   ("86.95% of revenue") or a margin level ("25.78% in 2017") is not a
   growth rate and never enters the comparison. Honest discounting —
   the desay cases discount deliberately and say why — never fires.
4. ``overconfident_parameter``: a triangular so tight its spread is
   under 10% of its mode.
5. ``weak_assumption``: a variable with no evidence and no notes.

There is deliberately NO generic "no formulas at all" finding: the
transmission-chain gap is captured by the specific checks above
(catalog + unlinked-driver), each anchored in the case's own words.
A generic no-chain flag would fire on simple exogenous-growth cases
with no evidence anchor — exactly the hallucination the acceptance
tests forbid.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from planagent.services.redteam.models import CaseSnapshot, RedTeamFinding

# A cited recent rate more than this many times the variable's mode,
# without a justification note, is an unjustified discount.
_DISCOUNT_RATIO = 2.0
# A triangular spread under this fraction of the mode is overconfident.
_TIGHT_SPREAD = 0.10

_JUSTIFICATION_KEYWORDS = (
    "恢复年",
    "recovery",
    "一次性",
    "one-off",
    "one off",
    "低基数",
    "low base",
    "保守",
    "conservative",
    "折扣",
    "discount",
    "上限",
    "cap",
    "capped",
    "审慎",
    "prudently",
    "不可持续",
    "unsustainable",
    "均值回归",
    "mean reversion",
    # A4 (2026-11-20): the audit's second false positive — profit_growth
    # DID state its reason ("margin pressure"), but the table did not
    # contain it, so the reason was invisible to the check.
    "margin pressure",
    "毛利压力",
    "margin compression",
    "price pressure",
    "价格压力",
    "降价压力",
    "cost pressure",
    "成本压力",
    # A stated scope difference is a justification too: the cited rate
    # covers a quantity this variable deliberately excludes.
    "adoption effect",
    "采用效应",
    "无采用",
    "不含采用",
    "未含采用",
)

# Scope-exclusion reasons that need word proximity, not a bare
# substring: "absent intelligent-driving adoption" says the cited
# segment rate INCLUDES adoption this variable EXCLUDES — the plain
# substring "absent adoption" never occurs in that sentence.
_JUSTIFICATION_PATTERNS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("absent adoption", re.compile(r"absent[^.;]{0,40}adoption", re.IGNORECASE)),
    ("excluding adoption", re.compile(r"excluding[^.;]{0,40}adoption", re.IGNORECASE)),
    ("without adoption", re.compile(r"without[^.;]{0,40}adoption", re.IGNORECASE)),
)

_PERCENT_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)\s*%")

# A4 (2026-11-20): like-for-like anchors for the discount check. The old
# rule compared EVERY percentage in the evidence with the mode, which
# read a revenue share ("86.95% of revenue") and a 2017 margin level
# ("25.78%") as growth rates. A percentage now counts as a cited growth
# rate only when the anchor CLOSEST to it is a growth word — or the
# number carries an explicit +/- sign, which marks a change, not a
# level. When the closest anchor is a share/level word, or there is no
# anchor nearby at all, the quantity is not a growth rate (or is
# unknown) and is never compared with the mode.
_GROWTH_ANCHORS = (
    "grow",
    "grew",
    "growing",
    "growth",
    "cagr",
    "rose",
    "risen",
    "increase",
    "increased",
    "increasing",
    "surged",
    "jumped",
    "climbed",
    "增长",
    "增速",
    "同比",
    "增幅",
    "上升",
    "上涨",
    "提升",
)
_LEVEL_ANCHORS = (
    "of revenue",
    "of sales",
    "of total",
    "of the market",
    "share",
    "margin",
    "penetration",
    "level",
    "down from",
    "up from",
    "from",
    "占比",
    "份额",
    "毛利",
    "渗透率",
    "水平",
)
# Anchors further away than this (chars) do not classify a percentage:
# the word that quantifies a number is the one next to it.
_ANCHOR_WINDOW = 60


@dataclass(frozen=True)
class DriverCheck:
    """One catalog entry: a structural driver the case may be missing."""

    id: str
    kind: str  # "missing_driver" | "missing_link"
    target: str
    label: str
    # Matched (substring, case-insensitive) against decision_question +
    # internal_situation: the case's own words saying this driver matters.
    situation_keywords: tuple[str, ...]
    # Matched against variable name + description: the driver is modelled.
    variable_keywords: tuple[str, ...]
    severity: str  # "high" | "medium" | "low"
    suggested_fix: str
    evidence_template: str


DRIVER_CATALOG: tuple[DriverCheck, ...] = (
    DriverCheck(
        id="nev_penetration",
        kind="missing_driver",
        target="nev_penetration",
        label="NEV penetration",
        situation_keywords=(
            "nev",
            "新能源",
            "new energy vehicle",
            "electric vehicle penetration",
            "电动汽车渗透",
            "electrification",
            "电动化",
        ),
        variable_keywords=(
            "nev",
            "新能源",
            "ev_penetration",
            "ev_share",
            "electrification",
            "电动化",
        ),
        severity="high",
        suggested_fix=(
            "Add a nev_penetration variable (triangular, anchored to the "
            "decision-time level and the stated policy target, e.g. 5.4% in "
            "2020 rising toward the 20% 2025 target) and link revenue_growth "
            "and market_share to it with a transmission formula, so NEV "
            "adoption — not a bare time curve — drives the growth."
        ),
        evidence_template=(
            "The internal situation names NEV adoption as a live driver "
            "({mentions}), but no variable in the case represents it: the "
            "biggest demand shift in the market is invisible to the model."
        ),
    ),
    DriverCheck(
        id="domain_controller_substitution",
        kind="missing_link",
        target="domain_controller_substitution",
        label="domain-controller substitution",
        situation_keywords=(
            "domain controller",
            "域控制器",
            "域控",
            "ipu03",
            "ipu04",
            "cockpit domain",
            "座舱域控",
            "智驾域控",
        ),
        variable_keywords=(
            "domain_controller",
            "域控制器",
            "域控",
            "substitution",
            "替代",
            "displacement",
            "cockpit_domain",
        ),
        severity="high",
        suggested_fix=(
            "Add a domain_controller_substitution variable (the share of "
            "cockpit/ADAS value shifting from discrete ECUs to domain "
            "controllers) and a transmission formula linking it to revenue "
            "and share: substitution changes content-per-vehicle and the "
            "supplier's share of the value chain, it is not a level shift "
            "a bare growth rate can express."
        ),
        evidence_template=(
            "The internal situation names domain controllers as shipping "
            "product ({mentions}), but no variable or formula connects "
            "domain-controller substitution to revenue or share: the "
            "architecture shift that re-prices the product is unmodelled."
        ),
    ),
    DriverCheck(
        id="adas_penetration",
        kind="missing_driver",
        target="adas_penetration",
        label="ADAS / assisted-driving penetration",
        situation_keywords=(
            "adas",
            "智能驾驶",
            "assisted driving",
            "autonomous driving",
            "自动驾驶",
            "l2",
            "l2 装配",
            "驾驶辅助",
        ),
        variable_keywords=(
            "adas",
            "adas_penetration",
            "assisted_driving",
            "autonomous",
            "自动驾驶",
            "智能驾驶",
            "l2",
        ),
        severity="medium",
        suggested_fix=(
            "Add an adas_penetration variable (e.g. L2 fitment rate, "
            "anchored to the decision-time level) and link it to revenue "
            "and share, so assisted-driving adoption — not a generic "
            "growth rate — carries the intelligent-driving upside."
        ),
        evidence_template=(
            "The internal situation names assisted-driving adoption "
            "({mentions}), but no variable in the case represents it."
        ),
    ),
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _mentions(text: str, keywords: tuple[str, ...]) -> list[str]:
    haystack = _normalize(text)
    return [kw for kw in keywords if kw.lower() in haystack]


def _nearest_anchor_distance(
    window: str, num_start: int, num_end: int, anchor: str
) -> int | None:
    """Gap in chars between `anchor` and the number at [num_start, num_end)
    inside `window`, or None when the anchor does not occur there. ASCII
    word anchors match on word boundaries, so "from" never matches
    "platform"; Chinese anchors match as substrings."""
    if anchor.isascii() and anchor.replace(" ", "").isalpha():
        pattern = re.compile(r"\b" + re.escape(anchor) + r"\b", re.IGNORECASE)
    else:
        pattern = re.compile(re.escape(anchor))
    best: int | None = None
    for match in pattern.finditer(window):
        if match.end() <= num_start:
            dist = num_start - match.end()
        elif match.start() >= num_end:
            dist = match.start() - num_end
        else:
            dist = 0
        if best is None or dist < best:
            best = dist
    return best


def _cited_growth_rates(text: str) -> list[float]:
    """Percentages in `text` that cite a growth rate — like-for-like with
    the variable's mode, as magnitudes (fractions, e.g. 0.335).

    Each percentage is classified by the anchor CLOSEST to it within
    ``_ANCHOR_WINDOW`` chars: a growth word (or an explicit +/- sign,
    which marks a change) makes it a cited growth rate; a share/level
    word next to it ("of revenue", "margin", "占比", "down from", ...)
    means the number is a share or a level, not a rate. With no anchor
    nearby the quantity is unknown and is ignored — the old rule
    compared every percentage, which is what turned a revenue share
    (86.95%) and a 2017 margin level (25.78%) into "recent growth".
    Ties go to the level reading: the check fails toward no flag."""
    text = _normalize(text)
    cited: list[float] = []
    for match in _PERCENT_RE.finditer(text):
        start, end = match.start(1), match.end()
        window_start = max(0, start - _ANCHOR_WINDOW)
        window_end = min(len(text), end + _ANCHOR_WINDOW)
        window = text[window_start:window_end]
        num_start, num_end = start - window_start, end - window_start
        growth_dist: int | None = None
        if match.group(1)[0] in "+-":
            growth_dist = 1  # a sign marks a change, not a level
        for anchor in _GROWTH_ANCHORS:
            dist = _nearest_anchor_distance(window, num_start, num_end, anchor)
            if dist is not None and (growth_dist is None or dist < growth_dist):
                growth_dist = dist
        level_dist: int | None = None
        for anchor in _LEVEL_ANCHORS:
            dist = _nearest_anchor_distance(window, num_start, num_end, anchor)
            if dist is not None and (level_dist is None or dist < level_dist):
                level_dist = dist
        if growth_dist is None:
            continue  # unknown quantity: do not compare
        if level_dist is not None and level_dist <= growth_dist:
            continue  # a share/level anchor is at least as close
        cited.append(abs(float(match.group(1))) / 100.0)
    return cited


def _has_justification(text: str) -> list[str]:
    """Stated reasons for a discount: keyword hits plus the
    scope-exclusion patterns (e.g. "absent ... adoption")."""
    found = _mentions(text, _JUSTIFICATION_KEYWORDS)
    normalized = _normalize(text)
    for label, pattern in _JUSTIFICATION_PATTERNS:
        if pattern.search(normalized):
            found.append(label)
    return found


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")
    return slug or "finding"


def finding_id(kind: str, target: str) -> str:
    """Stable id for a deterministic finding."""
    return f"rt-{kind}-{_slug(target)}"


def llm_finding_id(kind: str, target: str, summary: str) -> str:
    """Stable id for an LLM finding: same output, same snapshot, same id."""
    digest = hashlib.sha1(f"{kind}|{target}|{summary}".encode(), usedforsecurity=False).hexdigest()[
        :10
    ]
    return f"rt-llm-{digest}"


def _situation_text(snapshot: CaseSnapshot) -> str:
    return f"{snapshot.decision_question}\n{snapshot.internal_situation}"


def _variable_text(snapshot: CaseSnapshot) -> list[tuple[str, str]]:
    """(variable name, name + description) per variable — evidence excluded."""
    return [
        (variable.name, f"{variable.name} {variable.description}")
        for variable in snapshot.variables
    ]


def _formula_text(snapshot: CaseSnapshot) -> str:
    return "\n".join(
        f"{formula.target} = {formula.expression} {formula.description}"
        for formula in snapshot.formulas
    )


def _driver_present(snapshot: CaseSnapshot, check: DriverCheck) -> bool:
    for _name, text in _variable_text(snapshot):
        if _mentions(text, check.variable_keywords):
            return True
    return False


def _driver_linked(snapshot: CaseSnapshot, check: DriverCheck) -> bool:
    formula_text = _formula_text(snapshot)
    if not formula_text.strip():
        return False
    return bool(_mentions(formula_text, check.variable_keywords))


def run_completeness_checks(snapshot: CaseSnapshot) -> list[RedTeamFinding]:
    """Run every deterministic check over the frozen snapshot."""
    findings: list[RedTeamFinding] = []
    situation = _situation_text(snapshot)

    # 1. Catalog driver checks.
    for check in DRIVER_CATALOG:
        mentioned = _mentions(situation, check.situation_keywords)
        if not mentioned:
            continue
        present = _driver_present(snapshot, check)
        linked = _driver_linked(snapshot, check) if present else False
        if check.kind == "missing_driver" and not present:
            findings.append(
                RedTeamFinding(
                    id=finding_id(check.kind, check.target),
                    kind=check.kind,  # type: ignore[arg-type]
                    target=check.target,
                    severity=check.severity,  # type: ignore[arg-type]
                    summary=(
                        f"Missing driver: {check.label} is named in the "
                        "case situation but has no variable."
                    ),
                    evidence=[check.evidence_template.format(mentions=", ".join(mentioned[:3]))],
                    suggested_fix=check.suggested_fix,
                    source="completeness_check",
                    boundary_class="fixable_defect",
                    boundary_basis=(
                        f"{check.label} was named in decision-time public evidence "
                        f"({', '.join(mentioned[:3])}) encodable as a distribution — "
                        "it should have been in the case."
                    ),
                )
            )
        elif check.kind == "missing_link" and not (present and linked):
            reason = (
                "no variable represents it"
                if not present
                else "a variable names it but no formula links it to revenue or share"
            )
            findings.append(
                RedTeamFinding(
                    id=finding_id(check.kind, check.target),
                    kind=check.kind,  # type: ignore[arg-type]
                    target=check.target,
                    severity=check.severity,  # type: ignore[arg-type]
                    summary=(
                        f"Missing link: {check.label} is named in the case situation but {reason}."
                    ),
                    evidence=[check.evidence_template.format(mentions=", ".join(mentioned[:3]))],
                    suggested_fix=check.suggested_fix,
                    source="completeness_check",
                    boundary_class="fixable_defect",
                    boundary_basis=(
                        f"{check.label} was public decision-time evidence "
                        f"({', '.join(mentioned[:3])}) — the substitution could "
                        "have been encoded then."
                    ),
                )
            )

    # 2. Unlinked-driver check: a catalog driver present as a variable
    # but referenced by no formula moves nothing in the model.
    for check in DRIVER_CATALOG:
        if not _driver_present(snapshot, check):
            continue
        if _driver_linked(snapshot, check):
            continue
        if any(f.target == check.target and f.kind == "missing_link" for f in findings):
            continue
        findings.append(
            RedTeamFinding(
                id=finding_id("missing_link", check.target),
                kind="missing_link",
                target=check.target,
                severity="medium",
                summary=(
                    f"Unlinked driver: {check.label} exists as a variable "
                    "but no formula references it, so it cannot move revenue or share."
                ),
                evidence=[
                    (
                        f"Variable {check.target} is present in the variable table, "
                        "but no transmission formula mentions it."
                    )
                ],
                suggested_fix=(
                    f"Add a formula linking {check.target} to revenue_growth "
                    "and/or market_share, or remove the variable and record "
                    "explicitly that the driver is out of scope."
                ),
                source="completeness_check",
                boundary_class="fixable_defect",
                boundary_basis=(
                    "The variable already exists; linking it to revenue or share is a "
                    "modeling step that needed only decision-time evidence."
                ),
            )
        )

    # 3-5. Per-variable checks.
    for variable in snapshot.variables:
        own_text = "\n".join([*variable.evidence, variable.notes])
        name_lower = variable.name.lower()

        # 3. Unjustified discount: own evidence cites a recent realized
        # GROWTH rate far above the mode, with no justification note.
        # Only like-for-like percentages are compared: _cited_growth_rates
        # drops shares/levels ("86.95% of revenue", "25.78% in 2017") and
        # percentages with no growth anchor nearby, so the mode is never
        # judged against a number that is not a growth rate.
        if "growth" in name_lower and variable.mode is not None and variable.mode > 0:
            cited = _cited_growth_rates(own_text)
            if cited and max(cited) > _DISCOUNT_RATIO * variable.mode:
                justification = _has_justification(own_text)
                if not justification:
                    findings.append(
                        RedTeamFinding(
                            id=finding_id("unjustified_discount", variable.name),
                            kind="unjustified_discount",
                            target=variable.name,
                            severity="medium",
                            summary=(
                                f"Discounted growth: {variable.name} mode "
                                f"{variable.mode:.2%} sits far below the recent "
                                f"realized growth rate cited in its own evidence "
                                f"({max(cited):.2%}), with no stated reason for the discount."
                            ),
                            evidence=[
                                (
                                    f"Evidence cites {max(cited):.2%} recent growth; variable mode is "
                                    f"{variable.mode:.2%} (ratio {max(cited) / variable.mode:.1f}x)."
                                )
                            ],
                            suggested_fix=(
                                "Either record the explicit reason for the discount "
                                "(recovery year, one-off, low base, conservatism, "
                                "margin/price pressure, or that the cited rate covers "
                                "a different quantity — e.g. a segment rate that "
                                "includes adoption effects, or a share/margin level) "
                                "as a labeled assumption on the variable, or raise "
                                "the mode toward the cited rate and let the "
                                "distribution — not a silent discount — carry the "
                                "uncertainty."
                            ),
                            source="completeness_check",
                            boundary_class="fixable_defect",
                            boundary_basis=(
                                "The discount's reason, if one existed, was knowable at "
                                "decision time and could have been recorded as a labeled assumption."
                            ),
                        )
                    )

        # 4. Overconfident parameter: triangular spread under 10% of mode.
        if (
            variable.low is not None
            and variable.high is not None
            and variable.mode is not None
            and variable.mode != 0
        ):
            spread = (variable.high - variable.low) / abs(variable.mode)
            if 0 <= spread < _TIGHT_SPREAD:
                findings.append(
                    RedTeamFinding(
                        id=finding_id("overconfident_parameter", variable.name),
                        kind="overconfident_parameter",
                        target=variable.name,
                        severity="medium",
                        summary=(
                            f"Overconfident parameter: {variable.name} spans "
                            f"[{variable.low}, {variable.high}] around mode "
                            f"{variable.mode} — a spread of {spread:.1%} of the mode, "
                            "tighter than the evidence supports."
                        ),
                        evidence=[
                            (
                                f"Triangular({variable.low}, {variable.mode}, {variable.high}): "
                                f"spread/mode = {spread:.1%}."
                            )
                        ],
                        suggested_fix=(
                            "Widen the range to reflect genuine uncertainty, or cite "
                            "the measurement that justifies the tight band."
                        ),
                        source="completeness_check",
                        boundary_class="fixable_defect",
                        boundary_basis=(
                            "The tight band could have been widened or justified from "
                            "decision-time evidence."
                        ),
                    )
                )

        # 5. Weak assumption: no evidence and no notes at all.
        if not variable.evidence and not variable.notes.strip():
            findings.append(
                RedTeamFinding(
                    id=finding_id("weak_assumption", variable.name),
                    kind="weak_assumption",
                    target=variable.name,
                    severity="low",
                    summary=(
                        f"Weak assumption: {variable.name} carries no evidence "
                        "reference and no notes."
                    ),
                    evidence=[
                        f"Variable {variable.name} has an empty evidence list and empty notes."
                    ],
                    suggested_fix=(
                        f"Attach the evidence or the labeled-assumption note "
                        f"that justifies {variable.name}, or mark it explicitly "
                        "as an untested judgment call."
                    ),
                    source="completeness_check",
                    boundary_class="fixable_defect",
                    boundary_basis=(
                        "Evidence or an explicit judgment-call label could have been "
                        "attached at decision time."
                    ),
                )
            )

    return findings


__all__ = [
    "DRIVER_CATALOG",
    "DriverCheck",
    "finding_id",
    "llm_finding_id",
    "run_completeness_checks",
]

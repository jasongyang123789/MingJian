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
   cites a recent realized rate more than 2x its mode AND carries no
   justification note (recovery year, one-off, low base, explicit
   conservatism). Honest discounting — the desay cases discount
   deliberately and say why — never fires.
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
)

_PERCENT_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)\s*%")


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
        # rate far above the mode, with no justification note.
        if "growth" in name_lower and variable.mode is not None and variable.mode > 0:
            cited = [abs(float(match.group(1))) for match in _PERCENT_RE.finditer(own_text)]
            if cited and max(cited) / 100.0 > _DISCOUNT_RATIO * variable.mode:
                justification = _mentions(own_text, _JUSTIFICATION_KEYWORDS)
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
                                f"realized rate cited in its own evidence "
                                f"({max(cited):.2f}%), with no stated reason for the discount."
                            ),
                            evidence=[
                                (
                                    f"Evidence cites {max(cited):.2f}% recent growth; variable mode is "
                                    f"{variable.mode:.2%} (ratio {max(cited) / 100.0 / variable.mode:.1f}x)."
                                )
                            ],
                            suggested_fix=(
                                "Either record the explicit reason for the discount "
                                "(recovery year, one-off, low base, conservatism) as a "
                                "labeled assumption on the variable, or raise the mode "
                                "toward the cited rate and let the distribution — not a "
                                "silent discount — carry the uncertainty."
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

"""Deterministic driver-completeness check (Phase 4, Track 10).

For each key variable in a case, list its external drivers (from the
domain driver registry, or from the general guided checklist when the
domain has no registry); check whether each driver is in the model —
as a variable, a formula/driver output, or a rule — and report the
missing ones RANKED, the top finding phrased as the meta-check.

The check is deterministic: same case in, same findings out, in the
same order, regardless of input ordering. It is the DETERMINISTIC
counterpart to the LLM red-team layer (Track 8): same finding shape,
different source — ``completeness_check`` vs ``red_team_llm`` — so the
two layers never duplicate or contradict each other. The LLM layer
hunts unknown unknowns; this layer pins the known ones.

Presence rules (all comparisons lowercased, exact id match):
- a registry driver is PRESENT when any of its ``model_elements`` is
  among the case's variable ids, formula outputs, driver outputs, or
  rule ids. A generic adoption curve (``disruptor_rate``) does NOT
  count as the NEV chain: the registry names the NEV elements
  explicitly, and that is exactly the desay-2020 miss this check must
  catch.
- a present driver is LINKED when any of its ``link_outputs`` is among
  the case's formula/driver outputs — or when it has no link outputs,
  in which case its carrier is the split structure or a rule and
  presence alone passes. Present-but-unlinked is a ``missing_link``
  finding, never a silent pass.
- a checklist item is COVERED when any of its keywords appears as a
  substring in any variable id or description (deliberately coarse:
  the checklist asks questions, it does not know the domain).

Ranking: severity high > medium > low, then weight descending, then
driver id ascending. The top finding's summary carries the meta-check
prefix; all other findings use plain summaries.

Every finding carries a §6 boundary verdict (diagnostic-2020 §6):
``fixable_defect`` (encodable from decision-time public evidence —
missing it is a defect) or ``acceptable_limit`` (only knowable from
post-decision data — missing it is a prediction limit, not a defect),
with a one-sentence ``boundary_basis``. Registry findings take their
verdict from the registry entry; checklist findings are
``unclassified`` (the checklist cannot judge encodability); residual
gaps — supplied by the backtest/diagnostic flow, which knows actuals —
are ``acceptable_limit`` by construction.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .findings import (
    META_CHECK_PREFIX,
    UNCLASSIFIED_BASIS,
    BoundaryClass,
    FindingKind,
    FindingSeverity,
    FindingSource,
    RedTeamFinding,
)
from .registry import (
    GENERAL_DRIVER_CHECKLIST,
    REGISTRIES,
    ChecklistItem,
    DriverRegistryEntry,
)

__all__ = [
    "CompletenessCase",
    "CompletenessReport",
    "CoverageEntry",
    "run_completeness_check",
]

_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


class ResidualGap(BaseModel):
    """One residual gap after the missing drivers are added back.

    ``model_with_fix`` is the model's value with every flagged driver
    added at defensible decision-time values (diagnostic-2020 §5.2:
    desay-2020 revenue 18212); ``actual`` is the realized value
    (32557.18). ``basis`` states why the remainder is a limit under
    §6 — it must cite the standard, e.g. that the fitted values
    needed to close the gap are indefensible at decision time.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    target: str = Field(min_length=1)
    actual: float
    model_with_fix: float
    unit: str = ""
    basis: str = Field(min_length=1)


class CompletenessCase(BaseModel):
    """A case to check, as assembled at case-build time.

    ``domain_id`` selects the registry; any other value (including the
    generic ``corporate`` pack) falls back to the general checklist.
    A case about an automotive company built on generic corporate
    variables should be checked with ``domain_id="automotive"`` — the
    subject domain, not the pack it happened to be built on — because
    that mismatch is precisely the miss the check exists to catch.
    """

    model_config = ConfigDict(extra="forbid")

    domain_id: str = Field(min_length=1)
    variable_ids: list[str] = Field(default_factory=list)
    variable_descriptions: dict[str, str] = Field(default_factory=dict)
    formula_outputs: list[str] = Field(default_factory=list)
    driver_outputs: list[str] = Field(default_factory=list)
    rule_ids: list[str] = Field(default_factory=list)
    # Assumption-data keys shipped with the case/template (e.g. the
    # automotive template's `fitment_lookup`): some drivers live in
    # assumption data, not in a variable.
    assumption_data_keys: list[str] = Field(default_factory=list)
    key_variables: list[str] = Field(default_factory=list)
    # Residual gaps, supplied by the backtest/diagnostic flow (the only
    # caller that knows actuals): for each, the model's value WITH the
    # missing drivers added at defensible decision-time values, vs the
    # actual. The check cannot compute these itself — it has no
    # actuals — but it labels them per §6: the remainder is an
    # acceptable prediction limit, not a defect.
    residual_gaps: list[ResidualGap] = Field(default_factory=list)


class CoverageEntry(BaseModel):
    """Per-key-variable driver coverage."""

    model_config = ConfigDict(extra="forbid")

    present: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


class CompletenessReport(BaseModel):
    """The ranked result of a completeness check."""

    model_config = ConfigDict(extra="forbid")

    domain_id: str
    registry: str  # domain id, or "general-checklist"
    findings: list[RedTeamFinding] = Field(default_factory=list)
    top_finding: RedTeamFinding | None = None
    drivers_checked: int
    drivers_present: int
    drivers_missing: int
    coverage: dict[str, CoverageEntry] = Field(default_factory=dict)


def _norm(ids: list[str]) -> set[str]:
    return {i.strip().lower() for i in ids if i and i.strip()}


def _target_for(entry: DriverRegistryEntry, key_variables: list[str]) -> str:
    for drive in entry.drives:
        if drive in key_variables:
            return drive
    return entry.drives[0] if entry.drives else "case"


def _check_note(entry: DriverRegistryEntry) -> str:
    return (
        "Checked model elements against the registered driver "
        f"'{entry.name}': none of {sorted(entry.model_elements)} present."
    )


def _missing_summary_prefix(kind: FindingKind) -> str:
    """The summary prefix for a missing-driver finding of this kind."""
    if kind is FindingKind.MISSING_SEGMENT_SPLIT:
        return "Missing segment split"
    return "Missing driver"


def _registry_findings(
    entries: list[DriverRegistryEntry],
    elements: set[str],
    link_outputs: set[str],
    key_variables: list[str],
) -> tuple[list[RedTeamFinding], dict[str, CoverageEntry], int]:
    findings: list[RedTeamFinding] = []
    coverage: dict[str, CoverageEntry] = {}
    present_count = 0
    for entry in entries:
        target = _target_for(entry, key_variables)
        coverage_key = target
        bucket = coverage.setdefault(coverage_key, CoverageEntry())
        present = bool(set(entry.model_elements) & elements)
        if present:
            present_count += 1
            linked = not entry.link_outputs or bool(set(entry.link_outputs) & link_outputs)
            bucket.present.append(entry.id)
            if linked:
                continue
            findings.append(
                RedTeamFinding(
                    id=f"completeness:{entry.id}:link",
                    kind=FindingKind.MISSING_LINK,
                    target=target,
                    severity=FindingSeverity(entry.severity),
                    summary=(
                        f"Missing link: {entry.name} is in the model but no "
                        f"formula or driver carries it to {target}."
                    ),
                    evidence=[
                        *entry.evidence,
                        (
                            f"Present as one of {sorted(set(entry.model_elements) & elements)} "
                            f"but none of its link outputs {sorted(entry.link_outputs)} "
                            "is produced by any formula or driver."
                        ),
                    ],
                    suggested_fix=entry.suggested_fix,
                    source=FindingSource.COMPLETENESS_CHECK,
                    boundary_class=entry.boundary_class,
                    boundary_basis=entry.boundary_basis,
                )
            )
        else:
            bucket.missing.append(entry.id)
            findings.append(
                RedTeamFinding(
                    id=f"completeness:{entry.id}",
                    kind=entry.finding_kind,
                    target=target,
                    severity=FindingSeverity(entry.severity),
                    summary=(
                        f"{_missing_summary_prefix(entry.finding_kind)}: {entry.name} — "
                        f"{target} has no {entry.name} driver in the model."
                    ),
                    evidence=[*entry.evidence, _check_note(entry)],
                    suggested_fix=entry.suggested_fix,
                    source=FindingSource.COMPLETENESS_CHECK,
                    boundary_class=entry.boundary_class,
                    boundary_basis=entry.boundary_basis,
                )
            )
    return findings, coverage, present_count


def _checklist_findings(
    items: list[ChecklistItem],
    variable_ids: list[str],
    descriptions: dict[str, str],
    key_variables: list[str],
) -> tuple[list[RedTeamFinding], dict[str, CoverageEntry], int]:
    haystacks = [v.lower() for v in variable_ids]
    haystacks += [d.lower() for d in descriptions.values()]
    target = key_variables[0] if key_variables else "case"
    bucket = CoverageEntry()
    findings: list[RedTeamFinding] = []
    present_count = 0
    for item in items:
        covered = any(kw.lower() in hay for kw in item.keywords for hay in haystacks)
        if covered:
            present_count += 1
            bucket.present.append(item.id)
            continue
        bucket.missing.append(item.id)
        findings.append(
            RedTeamFinding(
                id=f"completeness:checklist:{item.id}",
                kind=item.finding_kind,
                target=target,
                severity=FindingSeverity.MEDIUM,
                summary=f"{_missing_summary_prefix(item.finding_kind)}: {item.question}",
                evidence=[
                    (
                        "General guided checklist (no driver registry for this domain): "
                        f"no variable id or description mentions any of {sorted(item.keywords)}."
                    ),
                ],
                suggested_fix=item.suggested_fix,
                source=FindingSource.COMPLETENESS_CHECK,
                # The checklist cannot judge encodability in general: it
                # does not know the domain or the decision-time evidence.
                # Leave it unclassified rather than forcing a verdict
                # (§6) — unless the item declares its verdict, as the
                # revenue-split item does (a split is encodable from
                # decision-time published segment data).
                boundary_class=(
                    item.boundary_class
                    if item.boundary_class is not None
                    else BoundaryClass.UNCLASSIFIED
                ),
                boundary_basis=item.boundary_basis or UNCLASSIFIED_BASIS,
            )
        )
    return findings, {target: bucket}, present_count


def _residual_findings(gaps: list[ResidualGap]) -> list[RedTeamFinding]:
    """Label supplied residual gaps per §6.

    A residual gap is the remainder AFTER the missing drivers are added
    back at defensible decision-time values. By §6 it is an acceptable
    prediction limit, not a defect: the fitted values needed to close
    it are only knowable from post-decision data, so tuning parameters
    to fit it would breach the hindsight firewall. The suggested fix
    is therefore explicitly "no model fix".
    """
    findings: list[RedTeamFinding] = []
    for gap in gaps:
        unit = f" {gap.unit}" if gap.unit else ""
        findings.append(
            RedTeamFinding(
                id=f"completeness:residual:{gap.id}",
                kind=FindingKind.WEAK_ASSUMPTION,
                target=gap.target,
                severity=FindingSeverity.MEDIUM,
                summary=(
                    f"Residual gap beyond the predictive ceiling: with the missing "
                    f"drivers added at defensible decision-time values, {gap.target} "
                    f"reaches {gap.model_with_fix}{unit} vs actual {gap.actual}{unit} "
                    f"— the remainder is an acceptable prediction limit, not a defect."
                ),
                evidence=[
                    (
                        f"Actual {gap.target}: {gap.actual}{unit}; model with the missing "
                        f"drivers added at defensible values: {gap.model_with_fix}{unit}."
                    ),
                    gap.basis,
                ],
                suggested_fix=(
                    "No model fix: record as an accepted prediction limit; do not "
                    "tune parameters to fit post-decision actuals (hindsight firewall)."
                ),
                source=FindingSource.COMPLETENESS_CHECK,
                boundary_class=BoundaryClass.ACCEPTABLE_LIMIT,
                boundary_basis=gap.basis,
            )
        )
    return findings


def run_completeness_check(case: CompletenessCase) -> CompletenessReport:
    """Run the deterministic completeness check on one case.

    Pure function: no I/O, no randomness, no LLM. Safe to call at
    case-build time (after the variable table is assembled, before the
    run is created) and from the ``POST /completeness/check`` endpoint.
    """
    elements = (
        _norm(case.variable_ids)
        | _norm(case.formula_outputs)
        | _norm(case.driver_outputs)
        | _norm(case.rule_ids)
        | _norm(case.assumption_data_keys)
    )
    link_outputs = _norm(case.formula_outputs) | _norm(case.driver_outputs)
    key_variables = [k for k in case.key_variables if k]

    entries = REGISTRIES.get(case.domain_id.lower())
    if entries is not None:
        registry_name = case.domain_id.lower()
        findings, coverage, present_count = _registry_findings(
            entries, elements, link_outputs, key_variables
        )
        checked = len(entries)
    else:
        registry_name = "general-checklist"
        findings, coverage, present_count = _checklist_findings(
            GENERAL_DRIVER_CHECKLIST,
            case.variable_ids,
            case.variable_descriptions,
            key_variables,
        )
        checked = len(GENERAL_DRIVER_CHECKLIST)
    findings.extend(_residual_findings(case.residual_gaps))

    weight_by_id = {f"completeness:{e.id}": e.weight for e in (entries or [])}
    weight_by_id.update({f"completeness:{e.id}:link": e.weight for e in (entries or [])})
    findings.sort(
        key=lambda f: (
            _SEVERITY_RANK[f.severity.value],
            -weight_by_id.get(f.id, 0.5),
            f.id,
        )
    )
    # The top finding carries the meta-check phrasing. Only the top one,
    # and only when it is a missing driver (the phrase is about a
    # variable that was never included — a present-but-unlinked driver
    # keeps its plain summary): rewording every finding would bury the
    # signal.
    top = None
    if findings and findings[0].kind is FindingKind.MISSING_DRIVER:
        stripped = findings[0].summary.removeprefix("Missing driver: ")
        top = findings[0].model_copy(update={"summary": f"{META_CHECK_PREFIX}: {stripped}"})
        findings = [top, *findings[1:]]
    elif findings:
        top = findings[0]

    return CompletenessReport(
        domain_id=case.domain_id,
        registry=registry_name,
        findings=findings,
        top_finding=top,
        drivers_checked=checked,
        drivers_present=present_count,
        drivers_missing=checked - present_count,
        coverage=coverage,
    )

"""Versioned prompt template for the red-team LLM stage (Phase 4, Track 8).

One template, following the Sprint 6 pattern: versioned, pure and
byte-stable rendering, declared slots validated at import, and the
JSON-only / do-not-compute-numbers instruction on every template.

The red team is NOT the seminar (model-vs-model deliberation over a
run's results). It is a challenge to the frozen case STRUCTURE before
any run exists: what driver is missing, what assumption is weak, what
discount is unjustified, what link is absent, what parameter is
overconfident. The template therefore instructs the model to argue
from the snapshot's own evidence and to return findings in the shared
shape — never new numbers, never a verdict about the decision itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from string import Formatter

_TEMPLATE_VERSION = "1"

_PLACEHOLDER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_JSON_ONLY = (
    "Return valid JSON only, matching the shape described above. "
    "Do not compute new numbers: every number you cite must come from the "
    "context block above. Argue about the case structure; do not invent, "
    "adjust, or recompute numbers, and do not give a verdict on the "
    "decision itself. Write in {output_language}."
)


@dataclass(frozen=True)
class RedTeamTemplate:
    id: str
    version: str
    title: str
    source_note: str
    system_prompt: str
    user_template: str
    slots: tuple[str, ...]
    max_tokens: int


def _template() -> RedTeamTemplate:
    system_prompt = (
        "You are a red-team reviewer of a frozen decision case. Your job "
        "is to challenge the case STRUCTURE — the variables, formulas, and "
        "assumptions it was built from — not to re-run the simulation and "
        "not to recommend a decision. Attack the model: find the driver "
        "that is missing, the assumption that is weak, the discount that "
        "is unjustified, the link that is absent, the parameter that is "
        "overconfident. Every finding must cite evidence from the context "
        "block (a fact in the internal situation, a variable with its "
        "distribution, or the absence of a formula). A finding with no "
        "cited evidence is not a finding. Prefer two strong findings over "
        "ten weak ones."
    )
    user_template = (
        "FROZEN CASE SNAPSHOT\n"
        "====================\n"
        "{context}\n"
        "\n"
        "{completeness_block}\n"
        "\n"
        "YOUR TASK\n"
        "=========\n"
        "Challenge this frozen case. Return findings in the five kinds "
        "below — and ONLY these kinds:\n"
        "- missing_driver: a demand, technology, policy, or market driver "
        "named in the internal situation that has no variable at all.\n"
        "- weak_assumption: a variable or claim whose justification is "
        "missing, circular, or contradicted by the situation.\n"
        "- unjustified_discount: a growth or rate variable set far below a "
        "recent realized GROWTH rate cited in the case, with no stated reason. "
        "Compare like for like only: a revenue share (\"86.95% of revenue\") "
        "or a margin level is not a growth rate, and a stated reason such as "
        "margin pressure — or that the cited rate covers a different scope — "
        "counts as justification.\n"
        "- missing_link: a variable that exists but is connected to nothing, "
        "or a transmission chain the case needs but does not have (for "
        "example a driver that should move revenue or share through a "
        "formula, but does not).\n"
        "- overconfident_parameter: a distribution so tight, or a point "
        "estimate so precise, that the evidence cannot support it.\n"
        "\n"
        "Severity: high = the gap can change the direction of the "
        "decision; medium = it can move the magnitude materially; low = "
        "it weakens auditability. Be strict with high: reserve it for gaps "
        "whose evidence is in the context block.\n"
        "\n"
        "BOUNDARY CLASS (diagnostic section 6 — judge every finding, "
        "never leave it blank):\n"
        "- fixable_defect: the missing element could have been encoded "
        "into a distribution from decision-time public evidence — it is "
        "something the case should have had, and its absence is a defect "
        "to fix.\n"
        "- acceptable_limit: only data from AFTER the decision time could "
        "have known it — missing it is a prediction ceiling, not a defect.\n"
        "- unclassified: use ONLY when the evidence in the context block "
        "is insufficient to judge either way, and say why in "
        "boundary_basis. Never force a judgment just to fill the field.\n"
        "\n"
        "OUTPUT SHAPE (exact — every key, no extras):\n"
        "{{\n"
        '  "findings": [\n'
        "    {{\n"
        '      "kind": "missing_driver | weak_assumption | unjustified_discount | missing_link | overconfident_parameter",\n'
        '      "target": "the variable or model element challenged (short name)",\n'
        '      "severity": "high | medium | low",\n'
        '      "summary": "one line, what is wrong",\n'
        '      "evidence": ["cited facts from the context block, at least one"],\n'
        '      "suggested_fix": "concrete fix: what variable, formula, or evidence to add",\n'
        '      "boundary_class": "fixable_defect | acceptable_limit | unclassified",\n'
        '      "boundary_basis": "one sentence: which decision-time evidence (or its absence) decides the class"\n'
        "    }}\n"
        "  ]\n"
        "}}\n"
        "At most 10 findings. An empty findings list is a valid answer "
        "when the case is sound — do not invent gaps to fill the list.\n"
        "\n" + _JSON_ONLY
    )
    return RedTeamTemplate(
        id="redteam.challenge",
        version=_TEMPLATE_VERSION,
        title="Red-team challenge of a frozen case snapshot",
        source_note=(
            "Original prompt written for Phase 4 Track 8 (2026-11-19); "
            "no external source. Informed by the desay-2020 backtest miss "
            "(REPORT.md): a generic corporate template with no NEV variable "
            "and no domain-controller-substitution variable."
        ),
        system_prompt=system_prompt,
        user_template=user_template,
        slots=("context", "completeness_block", "output_language"),
        max_tokens=8000,
    )


_REGISTRY: dict[str, RedTeamTemplate] = {"redteam.challenge": _template()}


def get_template(template_id: str) -> RedTeamTemplate:
    try:
        return _REGISTRY[template_id]
    except KeyError:
        raise KeyError(f"Unknown red-team template: {template_id!r}") from None


def list_templates() -> list[RedTeamTemplate]:
    return [get_template(template_id) for template_id in sorted(_REGISTRY)]


def render_template(template: RedTeamTemplate, inputs: dict[str, str]) -> tuple[str, str]:
    """Render (system_prompt, user_content); byte-stable, missing slots named."""
    missing = [slot for slot in template.slots if slot not in inputs]
    if missing:
        raise ValueError(f"Template {template.id!r} is missing slots: {', '.join(missing)}")
    extra = [key for key in inputs if key not in template.slots]
    if extra:
        raise ValueError(f"Template {template.id!r} got unexpected slots: {', '.join(extra)}")
    return template.system_prompt, template.user_template.format(
        **{slot: inputs[slot] for slot in template.slots}
    )


def _validate_registry() -> None:
    for template in _REGISTRY.values():
        used = {
            name for _, name, _, _ in Formatter().parse(template.user_template) if name is not None
        }
        declared = set(template.slots)
        if used != declared:
            raise ValueError(
                f"Template {template.id!r}: declared slots {sorted(declared)} "
                f"!= used placeholders {sorted(used)}"
            )
        for placeholder in used:
            if not _PLACEHOLDER_RE.match(placeholder):
                raise ValueError(f"Template {template.id!r}: bad placeholder {placeholder!r}")


_validate_registry()

__all__ = [
    "RedTeamTemplate",
    "get_template",
    "list_templates",
    "render_template",
]

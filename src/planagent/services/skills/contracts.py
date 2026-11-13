"""Pydantic output contracts for grafted skill stages (Sprint 6, D9).

OMEN lesson applied: every LLM stage output is validated against a
Pydantic contract, exactly like OMEN's artifact chain. Malformed output
is a structured failure (:class:`SkillContractError`), never a silent
pass-through. The contract version is recorded with each stored stage
output for audit.

Contracts mirror the JSON shapes promised by the templates in
:mod:`planagent.services.skills.templates`. Unknown keys are forbidden:
a stage that returns fields outside its contract is a contract failure.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from planagent.services.mece.models import DecompositionTree

SKILL_CONTRACT_VERSION = "1"

Score = Annotated[float, Field(ge=0.0, le=10.0)]
Importance = Annotated[int, Field(ge=1, le=5)]


class SkillContractError(RuntimeError):
    """A stage's LLM output failed its Pydantic contract."""

    def __init__(self, template_id: str, details: list[dict[str, Any]]) -> None:
        self.template_id = template_id
        self.contract_version = SKILL_CONTRACT_VERSION
        self.details = details
        summary = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in details
        )
        super().__init__(
            f"LLM output for stage {template_id!r} failed contract "
            f"skills-v{SKILL_CONTRACT_VERSION}: {summary}"
        )


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# McKinsey pipeline contracts
# ---------------------------------------------------------------------------


class IntakeClassification(_Contract):
    problem_statement: str = Field(min_length=1)
    decision_question: str = Field(min_length=1)
    engagement_type: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    constraints: list[str] = Field(default_factory=list)
    stakes: Literal["standard", "deep"]
    frameworks: list[str] = Field(min_length=1)
    wave_plan: list[str] = Field(min_length=1)
    open_questions: list[str] = Field(default_factory=list)


class Diagnosis(_Contract):
    findings: list[str] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    barriers: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class MarketMap(_Contract):
    summary: str = Field(min_length=1)
    segments: list[str] = Field(default_factory=list)
    competitors: list[str] = Field(default_factory=list)
    white_space: list[str] = Field(default_factory=list)
    profit_pools: list[str] = Field(default_factory=list)
    threats: list[str] = Field(default_factory=list)


class OptionCandidate(_Contract):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    upside: str = Field(min_length=1)
    trade_off: str = Field(min_length=1)
    what_must_be_true: list[str] = Field(min_length=1)


class OptionSet(_Contract):
    options: list[OptionCandidate] = Field(min_length=1, max_length=6)


class ShortlistEntry(_Contract):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    scores: dict[str, Score] = Field(min_length=1)
    rationale: str = Field(min_length=1)


class DroppedOption(_Contract):
    name: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class Shortlist(_Contract):
    ranked: list[ShortlistEntry] = Field(min_length=1, max_length=3)
    dropped: list[DroppedOption] = Field(default_factory=list)


class SynthesisArgument(_Contract):
    claim: str = Field(min_length=1)
    backing: str = Field(min_length=1)


class Synthesis(_Contract):
    governing_thought: str = Field(min_length=1)
    arguments: list[SynthesisArgument] = Field(min_length=1)
    recommended_option: str = Field(min_length=1)
    load_bearing_assumptions: list[str] = Field(min_length=1)
    alternatives_considered: list[str] = Field(default_factory=list)


class AuditedAssumption(_Contract):
    assumption: str = Field(min_length=1)
    category: str = Field(min_length=1)
    importance: Importance
    evidence_strength: Literal["strong", "moderate", "weak", "speculative"]
    risk: str = Field(min_length=1)


class AssumptionAudit(_Contract):
    assumptions: list[AuditedAssumption] = Field(min_length=1)
    load_bearing: list[str] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)
    fatal_flags: list[str] = Field(default_factory=list)


class WarGameScenario(_Contract):
    name: str = Field(min_length=1)
    trigger: str = Field(min_length=1)
    impact: str = Field(min_length=1)
    likelihood: str = Field(min_length=1)
    severity: str = Field(min_length=1)


class Vulnerability(_Contract):
    weak_point: str = Field(min_length=1)
    why_it_matters: str = Field(min_length=1)
    mitigation: str = Field(min_length=1)


class PlaybookEntry(_Contract):
    signal: str = Field(min_length=1)
    response: str = Field(min_length=1)
    owner: str = Field(min_length=1)


class WarGame(_Contract):
    scenarios: list[WarGameScenario] = Field(min_length=1)
    vulnerabilities: list[Vulnerability] = Field(default_factory=list)
    playbook: list[PlaybookEntry] = Field(default_factory=list)
    fatal_flags: list[str] = Field(default_factory=list)


class ExecutionRisk(_Contract):
    risk: str = Field(min_length=1)
    mitigation: str = Field(min_length=1)
    owner: str = Field(min_length=1)


class ExecutionReview(_Contract):
    feasibility: str = Field(min_length=1)
    risks: list[ExecutionRisk] = Field(default_factory=list)
    economics_survive_bad_case: str = Field(min_length=1)
    fatal_flags: list[str] = Field(default_factory=list)


class FailureMode(_Contract):
    mode: str = Field(min_length=1)
    cause: str = Field(min_length=1)
    early_signal: str = Field(min_length=1)
    prevention: str = Field(min_length=1)


class PreMortem(_Contract):
    failure_narrative: str = Field(min_length=1)
    failure_modes: list[FailureMode] = Field(min_length=1)
    fatal_flags: list[str] = Field(default_factory=list)


class TournamentJudgment(_Contract):
    winner: str = Field(min_length=1)
    loser: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    criteria_scores: dict[str, Score] = Field(min_length=1)


# ---------------------------------------------------------------------------
# Advisory-board contracts
# ---------------------------------------------------------------------------


class CritIntake(_Contract):
    decision: str = Field(min_length=1)
    options: list[str] = Field(min_length=1)
    context: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    economics: str = Field(min_length=1)
    constraints: list[str] = Field(default_factory=list)
    success: str = Field(min_length=1)
    current_preference: str = Field(min_length=1)
    reversibility: str = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list, max_length=3)


class RiskVeto(_Contract):
    failure_path: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    severity: str = Field(min_length=1)
    mitigation: str = Field(min_length=1)


class LensPosition(_Contract):
    lens: str = Field(min_length=1)
    option_scores: dict[str, Score] = Field(min_length=1)
    confidence: Literal["low", "medium", "high"]
    decisive_evidence: str = Field(min_length=1)
    primary_upside: str = Field(min_length=1)
    primary_failure_mode: str = Field(min_length=1)
    opening_recommendation: str = Field(min_length=1)
    risk_veto: RiskVeto | None = None


class LensRevision(_Contract):
    lens: str = Field(min_length=1)
    final_option: str = Field(min_length=1)
    revised_scores: dict[str, Score] = Field(min_length=1)
    confidence: Literal["low", "medium", "high"]
    what_changed: str = Field(min_length=1)
    required_conditions: list[str] = Field(default_factory=list)
    kill_criterion: str = Field(min_length=1)
    unresolved_objection: str = Field(min_length=1)


class DebateDisagreement(_Contract):
    trade_off: str = Field(min_length=1)
    case_a: str = Field(min_length=1)
    case_b: str = Field(min_length=1)
    rebuttals: list[str] = Field(min_length=1)
    settling_evidence: str = Field(min_length=1)
    cheapest_test: str = Field(min_length=1)


class ForcedDebate(_Contract):
    disagreements: list[DebateDisagreement] = Field(min_length=1)
    minority_objection: str = Field(min_length=1)


class DecisionContract(_Contract):
    verdict: Literal["choose", "reject", "validate_first"]
    why_now: str = Field(min_length=1)
    conditions: list[str] = Field(default_factory=list)
    minority_report: str = Field(min_length=1)
    cheapest_validation_test: str = Field(min_length=1)
    go_threshold: str = Field(min_length=1)
    kill_criterion: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    deadline: str = Field(min_length=1)
    review_date: str = Field(min_length=1)
    next_action: str = Field(min_length=1)
    do_not_do: str = Field(min_length=1)
    lens_weights: dict[str, Annotated[int, Field(ge=1, le=3)]] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Template -> contract dispatch
# ---------------------------------------------------------------------------

CONTRACT_FOR_TEMPLATE: dict[str, type[BaseModel]] = {
    "mckinsey.intake_classify": IntakeClassification,
    "mckinsey.diagnose": Diagnosis,
    "mckinsey.market_map": MarketMap,
    "mckinsey.option_generate": OptionSet,
    "mckinsey.filter_shortlist": Shortlist,
    "mckinsey.synthesize": Synthesis,
    "mckinsey.verify_assumptions": AssumptionAudit,
    "mckinsey.verify_wargame": WarGame,
    "mckinsey.verify_execution": ExecutionReview,
    "mckinsey.tournament_judge": TournamentJudgment,
    "advisory.crit_intake": CritIntake,
    "advisory.lens_position": LensPosition,
    "advisory.lens_revision": LensRevision,
    "advisory.forced_debate": ForcedDebate,
    "advisory.chair_synthesis": DecisionContract,
    "gambit.premortem": PreMortem,
    "mece.propose_tree": DecompositionTree,
}


def parse_stage_output(template_id: str, raw: Any) -> BaseModel:
    """Validate one stage's raw LLM output against its contract.

    ``raw`` must be a JSON object (dict). Anything else, or any contract
    violation, raises :class:`SkillContractError`.
    """
    model = CONTRACT_FOR_TEMPLATE.get(template_id)
    if model is None:
        raise ValueError(f"No output contract registered for template {template_id!r}.")
    if not isinstance(raw, dict):
        raise SkillContractError(
            template_id,
            [{"loc": ("root",), "msg": f"expected a JSON object, got {type(raw).__name__}"}],
        )
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        raise SkillContractError(template_id, exc.errors()) from exc


__all__ = [
    "CONTRACT_FOR_TEMPLATE",
    "SKILL_CONTRACT_VERSION",
    "AssumptionAudit",
    "CritIntake",
    "DecisionContract",
    "Diagnosis",
    "ExecutionReview",
    "ForcedDebate",
    "IntakeClassification",
    "LensPosition",
    "LensRevision",
    "MarketMap",
    "OptionSet",
    "PreMortem",
    "Shortlist",
    "SkillContractError",
    "Synthesis",
    "TournamentJudgment",
    "WarGame",
    "parse_stage_output",
]

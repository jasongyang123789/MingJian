"""Stage orchestration for grafted skill pipelines (Sprint 6, D9).

Two pipelines, both built from the versioned templates in
:mod:`planagent.services.skills.templates` and validated against the
contracts in :mod:`planagent.services.skills.contracts`:

* ``strategy_team`` — the McKinsey pipeline: intake/classify, fan-out
  diagnosis + market mapping, option generation from opposing mandates,
  lead filter, synthesis, adversarial verifier panel (assumptions,
  war-game, execution, plus the gambit pre-mortem as a fourth lens).
  Deep mode adds a pairwise tournament and a loop-until-done war-game.
* ``advisory_board`` — the 5-persona board: CRIT intake, independent
  Round 1 positions, forced debate, Round 3 revisions, chair synthesis
  into a decision contract.

Agent-teams adaptation (recorded, not hidden): the McKinsey skill
expects Claude Code agent teams (``CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS``)
with TeamCreate/Agent primitives. That runtime feature does not exist
here, so "waves" run as sequential stage calls over a shared context
store: each stage's validated output is serialized into the next
stage's inputs. The wave structure (what runs in parallel in the
original) is preserved as stage ordering + shared inputs, not as
concurrency.

The LLM boundary is a narrow port protocol. Stages call the existing
``OpenAIService`` through :class:`OpenAIServiceSkillPort` — no new LLM
client code. When the LLM is unavailable, stages raise
:class:`SkillLLMUnavailable`: a structured failure, never fabricated
content (unlike the debate service's text fallback, which is a
different system with different guarantees and is left untouched).

Tally and weighting rules live in code, not in prompts: the verifier
tally, the tournament win count, the unanimity check, and the weighted
direction are deterministic functions of validated stage outputs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from itertools import combinations
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from planagent.services.skills.contracts import (
    SKILL_CONTRACT_VERSION,
    AssumptionAudit,
    CritIntake,
    DecisionContract,
    Diagnosis,
    ExecutionReview,
    ForcedDebate,
    IntakeClassification,
    LensPosition,
    LensRevision,
    MarketMap,
    OptionSet,
    PreMortem,
    Shortlist,
    SkillContractError,
    Synthesis,
    TournamentJudgment,
    WarGame,
    parse_stage_output,
)
from planagent.services.skills.templates import (
    DECISION_CRITERIA,
    LENS_BRIEFS,
    LENS_QUESTIONS,
    OPTION_MANDATES,
    get_template,
    render_template,
)

if TYPE_CHECKING:
    from planagent.services.openai_client import OpenAIService

# Deep-mode war-game loop: stop after two consecutive rounds that add no
# NEW fatal flag, and never run more than this many extra rounds.
MAX_WARGAME_EXTRA_ROUNDS = 3
WARGAME_QUIET_ROUNDS_TO_STOP = 2

# Fixed lens order: deterministic stage sequencing and tie-breaking.
LENS_ORDER = (
    "product_clarity",
    "risk_capital",
    "scale_systems",
    "offer_strength",
    "future_self",
)

# Panel lenses in fixed order (premortem is the fourth, gated lens).
PANEL_LENSES = ("assumptions", "wargame", "execution", "premortem")

_NOT_RUN = "Not run in this mode."


class SkillLLMUnavailable(RuntimeError):
    """No configured LLM target for skill stages; nothing was fabricated."""


@dataclass
class SkillLLMResponse:
    model: str | None
    payload: dict[str, Any] | None


class SkillLLMPort(Protocol):
    """The narrow LLM boundary for skill stages."""

    def is_available(self) -> bool: ...

    async def generate_json(
        self,
        *,
        template_id: str,
        system_prompt: str,
        user_content: str,
        max_tokens: int,
    ) -> SkillLLMResponse: ...


class OpenAIServiceSkillPort:
    """Skill port backed by the existing ``OpenAIService`` (target ``primary``).

    Skill stages use the ``primary`` target: it is the only target the
    deliberation layer can assume is configured, and debate_* targets
    return ``(None, None)`` when their own keys are absent.
    """

    def __init__(self, openai_service: OpenAIService) -> None:
        self._service = openai_service

    def is_available(self) -> bool:
        return self._service.is_configured("primary")

    async def generate_json(
        self,
        *,
        template_id: str,
        system_prompt: str,
        user_content: str,
        max_tokens: int,
    ) -> SkillLLMResponse:
        meta, parsed = await self._service.generate_json_for_target(
            target="primary",
            system_prompt=system_prompt,
            user_content=user_content,
            max_tokens=max_tokens,
        )
        model = meta.get("model") if isinstance(meta, dict) else None
        return SkillLLMResponse(
            model=str(model) if model else None,
            payload=parsed if isinstance(parsed, dict) else None,
        )


# ---------------------------------------------------------------------------
# Stage records and pure tally/weighting rules
# ---------------------------------------------------------------------------


class StageRecord(BaseModel):
    """One executed stage, with full provenance for audit."""

    model_config = ConfigDict(extra="forbid")

    stage: str
    template_id: str
    template_version: str
    contract_version: str
    output: dict[str, Any]
    model: str | None = None


def dump_stage_json(output: dict[str, Any]) -> str:
    """Deterministic serialization of a validated stage output for prompts."""
    return json.dumps(output, sort_keys=True, indent=2, ensure_ascii=False)


async def run_stage(
    port: SkillLLMPort,
    *,
    stage: str,
    template_id: str,
    inputs: dict[str, str],
) -> StageRecord:
    """Render, call, and contract-validate one stage.

    Raises :class:`SkillLLMUnavailable` when no LLM is configured, and
    :class:`SkillContractError` when the response is empty or malformed.
    """
    template = get_template(template_id)
    system_prompt, user_content = render_template(template, inputs)
    if not port.is_available():
        raise SkillLLMUnavailable(
            f"No LLM target is configured for skill stage {template_id!r}; "
            "deliberation cannot run without one."
        )
    response = await port.generate_json(
        template_id=template_id,
        system_prompt=system_prompt,
        user_content=user_content,
        max_tokens=template.max_tokens,
    )
    if response.payload is None:
        raise SkillContractError(
            template_id,
            [
                {
                    "loc": ("root",),
                    "msg": (
                        "no usable JSON response (empty, unparseable, "
                        "or upstream failure)"
                    ),
                }
            ],
        )
    parsed = parse_stage_output(template_id, response.payload)
    return StageRecord(
        stage=stage,
        template_id=template_id,
        template_version=template.version,
        contract_version=SKILL_CONTRACT_VERSION,
        output=parsed.model_dump(mode="json"),
        model=response.model,
    )


def normalize_flag(text: str) -> str:
    """Normalize a fatal flag for grouping: case/whitespace-insensitive."""
    return re.sub(r"\s+", " ", text.strip().lower())


class PanelFlag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flag: str
    lenses: list[str]
    lens_count: int
    must_address: bool


class PanelTally(BaseModel):
    """Verifier-panel tally, computed in code from validated outputs.

    A flag is ``must_address`` when at least two DISTINCT lenses flag
    the same (normalized) statement as fatal — the McKinsey panel rule
    that two independent angles agreeing on a fatal risk outranks any
    single lens's objection.
    """

    model_config = ConfigDict(extra="forbid")

    flags: list[PanelFlag] = Field(default_factory=list)
    must_address: list[str] = Field(default_factory=list)


def tally_panel_flags(panel_flags: dict[str, list[str]]) -> PanelTally:
    """Group fatal flags across panel lenses; >=2 lenses => must_address."""
    grouped: dict[str, dict[str, Any]] = {}
    for lens in PANEL_LENSES:
        for flag in panel_flags.get(lens, []):
            key = normalize_flag(flag)
            if not key:
                continue
            entry = grouped.setdefault(key, {"flag": flag, "lenses": []})
            if lens not in entry["lenses"]:
                entry["lenses"].append(lens)
    flags = []
    for key in sorted(grouped, key=lambda k: (-len(grouped[k]["lenses"]), k)):
        entry = grouped[key]
        flags.append(
            PanelFlag(
                flag=entry["flag"],
                lenses=sorted(entry["lenses"]),
                lens_count=len(entry["lenses"]),
                must_address=len(entry["lenses"]) >= 2,
            )
        )
    return PanelTally(
        flags=flags,
        must_address=[flag.flag for flag in flags if flag.must_address],
    )


class WeightedDirection(BaseModel):
    """Weighted mean of lens scores per option — a summary, never an answer."""

    model_config = ConfigDict(extra="forbid")

    scores: dict[str, float] = Field(default_factory=dict)
    weights: dict[str, int] = Field(default_factory=dict)
    ranking: list[str] = Field(default_factory=list)
    top_option: str | None = None


def assemble_weighted_direction(
    scores_by_lens: dict[str, dict[str, float]],
    weights: dict[str, int],
) -> WeightedDirection:
    """Weighted mean per option over the lenses that scored it.

    Options are ranked by weighted mean descending, ties broken by
    option name for determinism. Lenses missing from ``weights``
    default to weight 2 (the middle of the 1-3 relevance scale).
    """
    totals: dict[str, float] = {}
    weight_sums: dict[str, float] = {}
    for lens in LENS_ORDER:
        scores = scores_by_lens.get(lens)
        if not scores:
            continue
        weight = weights.get(lens, 2)
        for option, score in scores.items():
            totals[option] = totals.get(option, 0.0) + weight * score
            weight_sums[option] = weight_sums.get(option, 0.0) + weight
    averaged = {
        option: totals[option] / weight_sums[option] for option in totals
    }
    ranking = sorted(averaged, key=lambda name: (-averaged[name], name))
    return WeightedDirection(
        scores=averaged,
        weights={lens: weights.get(lens, 2) for lens in LENS_ORDER if lens in scores_by_lens},
        ranking=ranking,
        top_option=ranking[0] if ranking else None,
    )


def detect_unanimity(positions: list[LensPosition]) -> str | None:
    """Return the unanimously top-ranked option, or None.

    A lens's top option is its highest score; ties break by option
    name. Unanimity triggers the anti-groupthink rule in the forced
    debate: steelman the strongest rejected alternative.
    """
    if not positions:
        return None
    tops = set()
    for position in positions:
        if not position.option_scores:
            return None
        best = sorted(
            position.option_scores.items(), key=lambda item: (-item[1], item[0])
        )[0][0]
        tops.add(best)
    if len(tops) == 1:
        return tops.pop()
    return None


def unanimity_note(unanimous_option: str | None) -> str:
    if unanimous_option is None:
        return ""
    return (
        "ANTI-GROUPTHINK RULE: all five lenses independently ranked "
        f"'{unanimous_option}' first. Before debating, steelman the "
        "strongest rejected alternative: state its best case, then "
        "require each lens to name what evidence would change its vote."
    )


# ---------------------------------------------------------------------------
# Strategy-team pipeline (McKinsey)
# ---------------------------------------------------------------------------


class TournamentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matches: list[dict[str, Any]] = Field(default_factory=list)
    wins: dict[str, int] = Field(default_factory=dict)
    winner: str | None = None


class StrategyTeamResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pipeline: Literal["strategy_team"] = "strategy_team"
    mode: Literal["standard", "deep"]
    topic: str
    stages: list[StageRecord] = Field(default_factory=list)
    intake: dict[str, Any]
    diagnosis: dict[str, Any]
    market_map: dict[str, Any]
    option_sets: list[dict[str, Any]] = Field(default_factory=list)
    shortlist: dict[str, Any]
    synthesis: dict[str, Any]
    synthesis_recommendation_in_shortlist: bool
    panel: dict[str, dict[str, Any]] = Field(default_factory=dict)
    wargame_rounds: list[dict[str, Any]] = Field(default_factory=list)
    tally: PanelTally
    tournament: TournamentResult | None = None
    wargame_loop_rounds: int = 0
    wargame_loop_stop_reason: str = "not_deep"


async def run_strategy_team(
    port: SkillLLMPort,
    *,
    topic: str,
    decision_question: str,
    context: str,
    mode: Literal["standard", "deep"] = "standard",
    output_language: str = "English",
    include_premortem: bool = True,
    failure_date: str = "one year from now",
) -> StrategyTeamResult:
    """Run the McKinsey pipeline end to end over validated stage outputs."""
    stages: list[StageRecord] = []
    base_inputs = {
        "topic": topic,
        "decision_question": decision_question,
        "context": context,
        "output_language": output_language,
    }

    intake_record = await run_stage(
        port, stage="intake", template_id="mckinsey.intake_classify", inputs=base_inputs
    )
    stages.append(intake_record)
    intake = IntakeClassification.model_validate(intake_record.output)
    intake_json = dump_stage_json(intake_record.output)

    diagnose_record = await run_stage(
        port,
        stage="diagnose",
        template_id="mckinsey.diagnose",
        inputs={**base_inputs, "intake": intake_json},
    )
    stages.append(diagnose_record)
    diagnosis = Diagnosis.model_validate(diagnose_record.output)

    market_record = await run_stage(
        port,
        stage="market_map",
        template_id="mckinsey.market_map",
        inputs={**base_inputs, "intake": intake_json},
    )
    stages.append(market_record)
    market_map = MarketMap.model_validate(market_record.output)
    diagnosis_json = dump_stage_json(diagnose_record.output)
    market_json = dump_stage_json(market_record.output)

    mandates = ["bull", "lean"] + (["contrarian"] if mode == "deep" else [])
    option_sets: list[dict[str, Any]] = []
    for mandate_name in mandates:
        record = await run_stage(
            port,
            stage=f"option_generate:{mandate_name}",
            template_id="mckinsey.option_generate",
            inputs={
                **base_inputs,
                "intake": intake_json,
                "diagnosis": diagnosis_json,
                "market_map": market_json,
                "mandate_name": mandate_name,
                "mandate": OPTION_MANDATES[mandate_name],
            },
        )
        stages.append(record)
        option_set = OptionSet.model_validate(record.output)
        option_sets.append(
            {"mandate": mandate_name, "options": option_set.model_dump(mode="json")["options"]}
        )

    shortlist_record = await run_stage(
        port,
        stage="filter_shortlist",
        template_id="mckinsey.filter_shortlist",
        inputs={
            **base_inputs,
            "option_sets": dump_stage_json({"option_sets": option_sets}),
            "criteria": DECISION_CRITERIA,
        },
    )
    stages.append(shortlist_record)
    shortlist = Shortlist.model_validate(shortlist_record.output)

    synthesis_record = await run_stage(
        port,
        stage="synthesize",
        template_id="mckinsey.synthesize",
        inputs={
            **base_inputs,
            "shortlist": dump_stage_json(shortlist_record.output),
            "diagnosis": diagnosis_json,
            "market_map": market_json,
        },
    )
    stages.append(synthesis_record)
    synthesis = Synthesis.model_validate(synthesis_record.output)
    draft_json = dump_stage_json(synthesis_record.output)
    shortlist_names = {entry.name for entry in shortlist.ranked}

    panel: dict[str, dict[str, Any]] = {}

    assumptions_record = await run_stage(
        port,
        stage="verify:assumptions",
        template_id="mckinsey.verify_assumptions",
        inputs={**base_inputs, "draft": draft_json},
    )
    stages.append(assumptions_record)
    audit = AssumptionAudit.model_validate(assumptions_record.output)
    panel["assumptions"] = assumptions_record.output

    wargame_rounds: list[WarGame] = []
    wargame_record = await run_stage(
        port,
        stage="verify:wargame:round1",
        template_id="mckinsey.verify_wargame",
        inputs={**base_inputs, "draft": draft_json, "prior_rounds": "No prior rounds."},
    )
    stages.append(wargame_record)
    wargame_rounds.append(WarGame.model_validate(wargame_record.output))

    execution_record = await run_stage(
        port,
        stage="verify:execution",
        template_id="mckinsey.verify_execution",
        inputs={**base_inputs, "draft": draft_json},
    )
    stages.append(execution_record)
    execution = ExecutionReview.model_validate(execution_record.output)
    panel["execution"] = execution_record.output

    if include_premortem:
        premortem_record = await run_stage(
            port,
            stage="verify:premortem",
            template_id="gambit.premortem",
            inputs={**base_inputs, "draft": draft_json, "failure_date": failure_date},
        )
        stages.append(premortem_record)
        panel["premortem"] = premortem_record.output

    # Deep mode: loop-until-done war-gaming. Extra rounds run until two
    # consecutive rounds add no NEW fatal flag, capped at 3 extra rounds.
    loop_rounds = 0
    stop_reason = "not_deep"
    if mode == "deep":
        seen_flags = {
            normalize_flag(flag)
            for round_output in wargame_rounds
            for flag in round_output.fatal_flags
        }
        quiet_rounds = 0
        stop_reason = "cap_reached"
        for extra in range(1, MAX_WARGAME_EXTRA_ROUNDS + 1):
            prior_json = dump_stage_json(
                {"prior_wargame_rounds": [r.model_dump(mode="json") for r in wargame_rounds]}
            )
            record = await run_stage(
                port,
                stage=f"verify:wargame:round{extra + 1}",
                template_id="mckinsey.verify_wargame",
                inputs={**base_inputs, "draft": draft_json, "prior_rounds": prior_json},
            )
            stages.append(record)
            loop_rounds += 1
            round_output = WarGame.model_validate(record.output)
            wargame_rounds.append(round_output)
            new_flags = {
                normalize_flag(flag) for flag in round_output.fatal_flags
            } - seen_flags
            seen_flags |= {normalize_flag(flag) for flag in round_output.fatal_flags}
            if new_flags:
                quiet_rounds = 0
            else:
                quiet_rounds += 1
                if quiet_rounds >= WARGAME_QUIET_ROUNDS_TO_STOP:
                    stop_reason = "two_quiet_rounds"
                    break
    panel["wargame"] = wargame_rounds[-1].model_dump(mode="json")

    panel_flags: dict[str, list[str]] = {
        "assumptions": audit.fatal_flags,
        "wargame": [flag for r in wargame_rounds for flag in r.fatal_flags],
        "execution": execution.fatal_flags,
    }
    if include_premortem:
        premortem = PreMortem.model_validate(panel["premortem"])
        panel_flags["premortem"] = premortem.fatal_flags
    tally = tally_panel_flags(panel_flags)

    # Deep mode: pairwise tournament over the shortlist.
    tournament: TournamentResult | None = None
    if mode == "deep" and len(shortlist.ranked) >= 2:
        wins: dict[str, int] = {entry.name: 0 for entry in shortlist.ranked}
        matches: list[dict[str, Any]] = []
        for first, second in combinations(shortlist.ranked, 2):
            record = await run_stage(
                port,
                stage=f"tournament:{first.name}-vs-{second.name}",
                template_id="mckinsey.tournament_judge",
                inputs={
                    **base_inputs,
                    "option_a": dump_stage_json(first.model_dump(mode="json")),
                    "option_b": dump_stage_json(second.model_dump(mode="json")),
                    "criteria": DECISION_CRITERIA,
                },
            )
            stages.append(record)
            judgment = TournamentJudgment.model_validate(record.output)
            if judgment.winner in wins:
                wins[judgment.winner] += 1
            matches.append(
                {
                    "option_a": first.name,
                    "option_b": second.name,
                    "winner": judgment.winner,
                    "rationale": judgment.rationale,
                }
            )
        winner = sorted(wins.items(), key=lambda item: (-item[1], item[0]))[0][0]
        tournament = TournamentResult(matches=matches, wins=wins, winner=winner)

    return StrategyTeamResult(
        mode=mode,
        topic=topic,
        stages=stages,
        intake=intake.model_dump(mode="json"),
        diagnosis=diagnosis.model_dump(mode="json"),
        market_map=market_map.model_dump(mode="json"),
        option_sets=option_sets,
        shortlist=shortlist.model_dump(mode="json"),
        synthesis=synthesis.model_dump(mode="json"),
        synthesis_recommendation_in_shortlist=synthesis.recommended_option in shortlist_names,
        panel=panel,
        wargame_rounds=[r.model_dump(mode="json") for r in wargame_rounds],
        tally=tally,
        tournament=tournament,
        wargame_loop_rounds=loop_rounds,
        wargame_loop_stop_reason=stop_reason,
    )


# ---------------------------------------------------------------------------
# Advisory-board pipeline (5-persona)
# ---------------------------------------------------------------------------


class RiskVetoRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lens: str
    failure_path: str
    evidence: str
    severity: str
    mitigation: str


class AdvisoryBoardResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pipeline: Literal["advisory_board"] = "advisory_board"
    mode: Literal["quick", "standard"]
    decision: str
    stages: list[StageRecord] = Field(default_factory=list)
    intake: dict[str, Any]
    positions: list[dict[str, Any]] = Field(default_factory=list)
    debate: dict[str, Any] | None = None
    revisions: list[dict[str, Any]] = Field(default_factory=list)
    contract: dict[str, Any]
    weighted_direction_round1: WeightedDirection
    weighted_direction_final: WeightedDirection
    vetoes: list[RiskVetoRecord] = Field(default_factory=list)
    has_unmitigated_veto: bool
    unanimous_option: str | None = None


async def run_advisory_board(
    port: SkillLLMPort,
    *,
    decision: str,
    options: list[str],
    context: str,
    mode: Literal["quick", "standard"] = "standard",
    output_language: str = "English",
) -> AdvisoryBoardResult:
    """Run the advisory-board pipeline end to end over validated outputs."""
    stages: list[StageRecord] = []
    options_text = "\n".join(f"- {option}" for option in options) or "(none offered)"
    base_inputs = {
        "decision": decision,
        "options": options_text,
        "context": context,
        "output_language": output_language,
    }

    intake_record = await run_stage(
        port, stage="crit_intake", template_id="advisory.crit_intake", inputs=base_inputs
    )
    stages.append(intake_record)
    intake = CritIntake.model_validate(intake_record.output)
    intake_json = dump_stage_json(intake_record.output)

    positions: list[LensPosition] = []
    position_records: list[StageRecord] = []
    for lens in LENS_ORDER:
        record = await run_stage(
            port,
            stage=f"lens_position:{lens}",
            template_id="advisory.lens_position",
            inputs={
                **base_inputs,
                "intake": intake_json,
                "lens_name": lens,
                "lens_brief": LENS_BRIEFS[lens],
                "lens_question": LENS_QUESTIONS[lens],
            },
        )
        stages.append(record)
        position_records.append(record)
        positions.append(LensPosition.model_validate(record.output))

    weighted_round1 = assemble_weighted_direction(
        {position.lens: position.option_scores for position in positions},
        {lens: 2 for lens in LENS_ORDER},
    )
    unanimous = detect_unanimity(positions)

    vetoes = [
        RiskVetoRecord(
            lens=position.lens,
            failure_path=position.risk_veto.failure_path,
            evidence=position.risk_veto.evidence,
            severity=position.risk_veto.severity,
            mitigation=position.risk_veto.mitigation,
        )
        for position in positions
        if position.risk_veto is not None
    ]

    debate: ForcedDebate | None = None
    debate_json = _NOT_RUN
    revisions: list[LensRevision] = []
    if mode == "standard":
        debate_record = await run_stage(
            port,
            stage="forced_debate",
            template_id="advisory.forced_debate",
            inputs={
                **base_inputs,
                "positions": dump_stage_json(
                    {"positions": [r.output for r in position_records]}
                ),
                "unanimity_note": unanimity_note(unanimous),
            },
        )
        stages.append(debate_record)
        debate = ForcedDebate.model_validate(debate_record.output)
        debate_json = dump_stage_json(debate_record.output)

        for lens, own_record in zip(LENS_ORDER, position_records, strict=True):
            record = await run_stage(
                port,
                stage=f"lens_revision:{lens}",
                template_id="advisory.lens_revision",
                inputs={
                    **base_inputs,
                    "lens_name": lens,
                    "lens_brief": LENS_BRIEFS[lens],
                    "own_position": dump_stage_json(own_record.output),
                    "debate": debate_json,
                },
            )
            stages.append(record)
            revisions.append(LensRevision.model_validate(record.output))

    revisions_json = (
        dump_stage_json({"revisions": [r.model_dump(mode="json") for r in revisions]})
        if revisions
        else _NOT_RUN
    )
    chair_record = await run_stage(
        port,
        stage="chair_synthesis",
        template_id="advisory.chair_synthesis",
        inputs={
            **base_inputs,
            "positions": dump_stage_json(
                {"positions": [r.output for r in position_records]}
            ),
            "debate": debate_json,
            "revisions": revisions_json,
            "weighted_direction": dump_stage_json(weighted_round1.model_dump(mode="json")),
            "vetoes": dump_stage_json({"vetoes": [v.model_dump(mode="json") for v in vetoes]}),
        },
    )
    stages.append(chair_record)
    contract = DecisionContract.model_validate(chair_record.output)

    # Final weighted direction: Round 3 revised scores (standard) or
    # Round 1 scores (quick), weighted by the chair's relevance weights.
    final_scores: dict[str, dict[str, float]] = {}
    if revisions:
        final_scores = {
            revision.lens: revision.revised_scores for revision in revisions
        }
    else:
        final_scores = {
            position.lens: position.option_scores for position in positions
        }
    chair_weights = {
        lens: weight for lens, weight in contract.lens_weights.items() if lens in LENS_ORDER
    }
    weighted_final = assemble_weighted_direction(final_scores, chair_weights)

    # A veto is "unmitigated" when the chair still says "choose": the
    # verdict proceeds despite a credible ruin-risk warning. A
    # validate_first/reject verdict is the mitigation path, not a
    # dismissal — the veto stays recorded in the contract either way.
    has_unmitigated_veto = bool(vetoes) and contract.verdict == "choose"

    return AdvisoryBoardResult(
        mode=mode,
        decision=decision,
        stages=stages,
        intake=intake.model_dump(mode="json"),
        positions=[p.model_dump(mode="json") for p in positions],
        debate=debate.model_dump(mode="json") if debate is not None else None,
        revisions=[r.model_dump(mode="json") for r in revisions],
        contract=contract.model_dump(mode="json"),
        weighted_direction_round1=weighted_round1,
        weighted_direction_final=weighted_final,
        vetoes=vetoes,
        has_unmitigated_veto=has_unmitigated_veto,
        unanimous_option=unanimous,
    )


__all__ = [
    "LENS_ORDER",
    "MAX_WARGAME_EXTRA_ROUNDS",
    "OpenAIServiceSkillPort",
    "PANEL_LENSES",
    "AdvisoryBoardResult",
    "PanelFlag",
    "PanelTally",
    "RiskVetoRecord",
    "SkillLLMPort",
    "SkillLLMResponse",
    "SkillLLMUnavailable",
    "StageRecord",
    "StrategyTeamResult",
    "TournamentResult",
    "WeightedDirection",
    "assemble_weighted_direction",
    "detect_unanimity",
    "dump_stage_json",
    "normalize_flag",
    "run_advisory_board",
    "run_stage",
    "run_strategy_team",
    "tally_panel_flags",
    "unanimity_note",
]

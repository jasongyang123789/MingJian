"""Unit tests for the Sprint 13 narrative composer, renderer, and polish hook.

Pure-function tests: no database, no LLM. Fixture ensembles and
deliberations are built inline so every asserted number is visible
in this file. The byte-identity test pins the Sprint 3 discipline:
same inputs compose byte-identical bodies.
"""

from __future__ import annotations

import pytest

from planagent.services.distributions.canonical import canonical_json, sha256_hash
from planagent.services.distributions.models import (
    DistributionSummary,
    MonteCarloResult,
    PairedDeltaSummary,
)
from planagent.services.living_loop.models import ThresholdTrigger
from planagent.services.mece.models import (
    DecompositionBranch,
    DecompositionTree,
    MeceValidationResult,
)
from planagent.services.narratives.composer import (
    DirectionInputs,
    LoopContextInput,
    NarrativeInputs,
    compose_narrative,
)
from planagent.services.narratives.models import (
    DirectionDefinition,
    NarrativeError,
    NarrativeGenerateRequest,
)
from planagent.services.narratives.polish import POLISH_TEMPLATE_ID, polish_markdown
from planagent.services.robustness.models import (
    BootstrapInterval,
    BootstrapResult,
    DecisionGatesRead,
    ExpectedShortfallDetail,
    ExpectedShortfallResult,
    GateDefinition,
    GateEvaluation,
    GateMetric,
    GateOperator,
    GateOutcome,
    GateRegistration,
    ThresholdSearchResult,
    TornadoResult,
    TornadoRow,
)
from planagent.services.skills.contracts import SkillContractError
from planagent.services.skills.models import SkillDeliberationRecord
from planagent.services.skills.orchestration import SkillLLMUnavailable
from tests.skill_fixtures import ScriptedSkillPort

RUN_A = "run-anchor-0001"
RUN_B = "run-source-0002"


def _summary(
    p50: float, p10: float = 0.0, p90: float = 0.0, p_loss: float = 0.0
) -> DistributionSummary:
    return DistributionSummary(
        n=20, mean=p50, min=p10, max=p90, p10=p10, p50=p50, p90=p90, stddev=1.0, p_loss=p_loss
    )


def _ensemble(
    run_id: str, *, baseline_p50: float, strategy_p50: float, seed: int = 42
) -> MonteCarloResult:
    return MonteCarloResult(
        ensemble_id=f"ens-{run_id}",
        base_run_id=run_id,
        trials=20,
        seed=seed,
        metric="final_value",
        loss_threshold=0.0,
        strategy_levers={"lever": 1.5},
        baseline=_summary(baseline_p50, p10=baseline_p50 - 10, p90=baseline_p50 + 10, p_loss=0.2),
        strategy=_summary(strategy_p50, p10=strategy_p50 - 5, p90=strategy_p50 + 5, p_loss=0.1),
        paired=PairedDeltaSummary(
            n=20, mean_delta=1.0, p10=0.0, p50=1.0, p90=2.0, p_strategy_better=0.6
        ),
        trial_run_ids={},
        protocol="sprint3-v1",
    )


def _tree() -> DecompositionTree:
    return DecompositionTree(
        topic="AI customer-service line",
        root=DecompositionBranch(
            name="all",
            scope=["a", "b"],
            children=[
                DecompositionBranch(name="cost", scope=["a"], children=[]),
                DecompositionBranch(name="revenue", scope=["b"], children=[]),
            ],
        ),
    )


def _validation() -> MeceValidationResult:
    return MeceValidationResult(
        is_mece=True, checks=[], issues=[], scope_tag_count=2, branch_count=3
    )


def _strategy_record(record_id: str = "delib-strategy-1") -> SkillDeliberationRecord:
    return SkillDeliberationRecord(
        id=record_id,
        run_id=RUN_A,
        pipeline="strategy_team",
        mode="standard",
        created_at="2026-11-15T00:00:00+00:00",
        result={
            "panel": {
                "premortem": {
                    "failure_narrative": "The launch failed in month three.",
                    "failure_modes": [
                        {
                            "mode": "Support overload",
                            "cause": "Ticket volume tripled",
                            "early_signal": "Queue depth rising",
                            "prevention": "Hire ahead",
                        }
                    ],
                    "fatal_flags": ["No fallback vendor"],
                },
                "wargame": {
                    "scenarios": [
                        {
                            "name": "Rival undercuts",
                            "trigger": "Price war",
                            "impact": "Margin loss",
                            "likelihood": "medium",
                            "severity": "high",
                        }
                    ],
                    "vulnerabilities": [],
                    "playbook": [
                        {
                            "signal": "Rival price drop",
                            "response": "Match on core tier",
                            "owner": "Ho",
                        }
                    ],
                    "fatal_flags": [],
                },
            }
        },
    )


def _advisory_record(record_id: str = "delib-advisory-1") -> SkillDeliberationRecord:
    return SkillDeliberationRecord(
        id=record_id,
        run_id=RUN_A,
        pipeline="advisory_board",
        mode="standard",
        created_at="2026-11-15T00:00:00+00:00",
        result={
            "contract": {
                "verdict": "validate_first",
                "why_now": "Window closing",
                "conditions": ["Pilot with two clients"],
                "minority_report": "One lens dissents",
                "cheapest_validation_test": "Concierge pilot",
                "go_threshold": "Pilot NPS above 40",
                "kill_criterion": "Churn above 5 percent",
                "owner": "Ho",
                "deadline": "2026-12-01",
                "review_date": "2026-12-15",
                "next_action": "Call the two pilot clients",
                "do_not_do": "Do not hire yet",
                "lens_weights": {"finance": 3},
                "assumptions": ["Demand holds"],
            }
        },
    )


def _inputs(
    directions: list[DirectionInputs],
    *,
    topic: str | None = None,
    tree: DecompositionTree | None = None,
    validation: MeceValidationResult | None = None,
    loop: LoopContextInput | None = None,
) -> NarrativeInputs:
    return NarrativeInputs(
        anchor_run_id=RUN_A,
        domain_id="corporate",
        request_topic=topic,
        mece_tree=tree,
        mece_validation=validation,
        directions=directions,
        loop_context=loop,
    )


def _direction(
    name: str,
    run_id: str,
    *,
    arm: str = "baseline",
    baseline_p50: float = 10.0,
    strategy_p50: float = 20.0,
    **kwargs: object,
) -> DirectionInputs:
    return DirectionInputs(
        definition=DirectionDefinition(name=name, source_run_id=run_id, arm=arm),  # type: ignore[arg-type]
        ensemble=_ensemble(run_id, baseline_p50=baseline_p50, strategy_p50=strategy_p50),
        **kwargs,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Ranking, arms, byte identity
# ---------------------------------------------------------------------------


def test_compose_ranks_by_p50_descending_ties_broken_by_name() -> None:
    composed = compose_narrative(
        _inputs(
            [
                _direction("Zulu", RUN_A, baseline_p50=10.0),
                _direction("Alpha", RUN_B, baseline_p50=30.0),
                _direction("Mike", RUN_B, baseline_p50=10.0),
            ]
        )
    )
    names = [direction.name for direction in composed.body.directions]
    assert names == ["Alpha", "Mike", "Zulu"]
    assert [direction.rank for direction in composed.body.directions] == [1, 2, 3]


def test_compose_uses_chosen_arm_distribution() -> None:
    composed = compose_narrative(_inputs([_direction("Solo", RUN_A, arm="strategy")]))
    dist = composed.body.directions[0].distribution
    assert dist.arm == "strategy"
    assert dist.p50 == 20.0
    assert dist.p10 == 15.0
    assert dist.p90 == 25.0
    assert dist.p_loss == 0.1


def test_compose_same_inputs_byte_identical_body() -> None:
    inputs = _inputs(
        [_direction("Solo", RUN_A, deliberations=[_strategy_record(), _advisory_record()])],
        tree=_tree(),
        validation=_validation(),
    )
    first = compose_narrative(inputs)
    second = compose_narrative(inputs)
    first_bytes = canonical_json(first.body.model_dump(mode="json"))
    second_bytes = canonical_json(second.body.model_dump(mode="json"))
    assert first_bytes == second_bytes
    assert sha256_hash(first.body.model_dump(mode="json")) == sha256_hash(
        second.body.model_dump(mode="json")
    )
    assert first.body.markdown == second.body.markdown


def test_compose_different_seed_changes_content_hash() -> None:
    low = compose_narrative(_inputs([_direction("Solo", RUN_A)]))
    high_inputs = _inputs([_direction("Solo", RUN_A)])
    high_inputs.directions[0].ensemble = _ensemble(
        RUN_A, baseline_p50=10.0, strategy_p50=20.0, seed=43
    )
    high = compose_narrative(high_inputs)
    assert sha256_hash(low.body.model_dump(mode="json")) != sha256_hash(
        high.body.model_dump(mode="json")
    )


# ---------------------------------------------------------------------------
# Provenance: template notices vs deliberated quotes
# ---------------------------------------------------------------------------


def test_compose_template_sections_when_no_deliberations_exist() -> None:
    composed = compose_narrative(_inputs([_direction("Solo", RUN_A)]))
    direction = composed.body.directions[0]
    assert direction.premortem.provenance == "template"
    assert direction.premortem.failure_narrative is None
    assert "strategy-team" in (direction.premortem.note or "")
    assert direction.first_step.provenance == "template"
    assert direction.first_step.next_action is None
    assert "advisory-board" in (direction.first_step.note or "")
    assert direction.signals == []
    assert direction.signals_note is not None
    assert direction.drivers.note is not None
    assert "tornado" in direction.drivers.note


def test_compose_quotes_premortem_and_contract_with_deliberation_ids() -> None:
    composed = compose_narrative(
        _inputs(
            [
                _direction(
                    "Solo",
                    RUN_A,
                    deliberations=[_strategy_record(), _advisory_record()],
                )
            ]
        )
    )
    direction = composed.body.directions[0]
    assert direction.premortem.provenance == "deliberated"
    assert direction.premortem.deliberation_id == "delib-strategy-1"
    assert direction.premortem.template_id == "gambit.premortem"
    assert direction.premortem.failure_narrative == "The launch failed in month three."
    assert direction.premortem.failure_modes[0].mode == "Support overload"
    assert direction.premortem.fatal_flags == ["No fallback vendor"]
    assert direction.first_step.provenance == "deliberated"
    assert direction.first_step.deliberation_id == "delib-advisory-1"
    assert direction.first_step.next_action == "Call the two pilot clients"
    assert direction.first_step.cheapest_validation_test == "Concierge pilot"
    assert direction.first_step.conditions == ["Pilot with two clients"]


def test_compose_deliberation_falls_back_to_anchor_run() -> None:
    composed = compose_narrative(
        _inputs(
            [
                _direction(
                    "Solo",
                    RUN_B,
                    anchor_deliberations=[_strategy_record(), _advisory_record()],
                )
            ]
        )
    )
    direction = composed.body.directions[0]
    assert direction.premortem.provenance == "deliberated"
    assert direction.first_step.provenance == "deliberated"


def test_compose_pinned_deliberation_restricts_quotes() -> None:
    definition = DirectionDefinition(
        name="Solo", source_run_id=RUN_A, deliberation_id="delib-advisory-1"
    )
    composed = compose_narrative(
        _inputs(
            [
                DirectionInputs(
                    definition=definition,
                    ensemble=_ensemble(RUN_A, baseline_p50=10.0, strategy_p50=20.0),
                    deliberations=[_strategy_record(), _advisory_record()],
                )
            ]
        )
    )
    direction = composed.body.directions[0]
    assert direction.first_step.provenance == "deliberated"
    assert direction.premortem.provenance == "template"


def test_compose_unknown_pinned_deliberation_refuses() -> None:
    definition = DirectionDefinition(
        name="Solo", source_run_id=RUN_A, deliberation_id="delib-missing"
    )
    with pytest.raises(NarrativeError) as excinfo:
        compose_narrative(
            _inputs(
                [
                    DirectionInputs(
                        definition=definition,
                        ensemble=_ensemble(RUN_A, baseline_p50=10.0, strategy_p50=20.0),
                        deliberations=[_strategy_record()],
                    )
                ]
            )
        )
    assert excinfo.value.code == "narrative_deliberation_not_found"


def test_compose_corrupt_premortem_refuses() -> None:
    corrupt = _strategy_record()
    corrupt.result["panel"]["premortem"] = {"failure_narrative": "x", "failure_modes": []}
    with pytest.raises(NarrativeError) as excinfo:
        compose_narrative(_inputs([_direction("Solo", RUN_A, deliberations=[corrupt])]))
    assert excinfo.value.code == "narrative_corrupt_deliberation"


# ---------------------------------------------------------------------------
# Drivers, signals, MECE traces
# ---------------------------------------------------------------------------


def test_compose_drivers_capped_at_five_in_stored_order() -> None:
    rows = [
        TornadoRow(
            variable=f"v{i}",
            low_value=0.0,
            high_value=1.0,
            base_value=0.5,
            outcome_low=0.0,
            outcome_high=float(7 - i),
            outcome_base=1.0,
            swing=float(7 - i),
        )
        for i in range(7)
    ]
    tornado = TornadoResult(
        run_id=RUN_A,
        ensemble_id="ens-x",
        metric="final_value",
        seed=42,
        low_quantile=0.1,
        high_quantile=0.9,
        base_run_id=RUN_A,
        rows=rows,
        protocol="sprint4-v1",
    )
    composed = compose_narrative(_inputs([_direction("Solo", RUN_A, tornado=tornado)]))
    drivers = composed.body.directions[0].drivers
    assert [row.variable for row in drivers.rows] == ["v0", "v1", "v2", "v3", "v4"]
    assert drivers.rows[0].swing == 7.0
    assert drivers.ensemble_id == "ens-x"


def test_compose_signals_union_in_fixed_kind_order() -> None:
    gate = GateDefinition(
        name="floor", metric=GateMetric.P50, operator=GateOperator.GTE, threshold=5.0
    )
    registration = GateRegistration(
        id="reg-1",
        run_id=RUN_A,
        ensemble_id="ens-x",
        gates=[gate],
        supersedes=None,
        registered_at="2026-11-15T00:00:00+00:00",
        ensemble_existed_at_registration=False,
        status="active",
    )
    evaluation = GateEvaluation(
        id="eval-1",
        registration_id="reg-1",
        run_id=RUN_A,
        ensemble_id="ens-x",
        evaluated_at="2026-11-15T00:00:00+00:00",
        outcomes=[
            GateOutcome(
                name="floor",
                metric=GateMetric.P50,
                operator=GateOperator.GTE,
                threshold=5.0,
                arm="baseline",
                observed=10.0,
                passed=True,
            )
        ],
        all_passed=True,
        pre_registered=True,
    )
    search = ThresholdSearchResult(
        run_id=RUN_A,
        ensemble_id="ens-x",
        metric="final_value",
        variable="demand",
        mode="p_loss",
        target=0.1,
        direction="increasing",
        bounds=(0.0, 100.0),
        threshold=42.0,
        achieved_statistic=0.1,
        reachable=True,
        iterations=3,
        trials_per_evaluation=20,
        tolerance=0.01,
        loss_threshold=0.0,
        seed=42,
        protocol="sprint4-v1",
    )
    loop = LoopContextInput(
        loop_id="loop-1",
        loop_name="Watch",
        registration_id="trig-reg-1",
        triggers=[ThresholdTrigger(name="watch", field="final_value", operator="<", threshold=0.0)],
    )
    composed = compose_narrative(
        _inputs(
            [
                _direction(
                    "Solo",
                    RUN_A,
                    gates=DecisionGatesRead(
                        run_id=RUN_A, registrations=[registration], evaluations=[evaluation]
                    ),
                    threshold_search=search,
                    deliberations=[_strategy_record(), _advisory_record()],
                )
            ],
            loop=loop,
        )
    )
    kinds = [signal.kind for signal in composed.body.directions[0].signals]
    assert kinds == [
        "decision_gate",
        "threshold_search",
        "loop_trigger",
        "advisory_contract",
        "advisory_contract",
        "wargame_playbook",
    ]
    gate_signal = composed.body.directions[0].signals[0]
    assert gate_signal.provenance == "computed"
    assert gate_signal.observed == 10.0
    assert gate_signal.passed is True
    assert gate_signal.source_ids["gate_evaluation_id"] == "eval-1"


def test_compose_gate_registration_without_evaluation_is_honest() -> None:
    gate = GateDefinition(
        name="floor", metric=GateMetric.P50, operator=GateOperator.GTE, threshold=5.0
    )
    registration = GateRegistration(
        id="reg-1",
        run_id=RUN_A,
        ensemble_id="ens-x",
        gates=[gate],
        supersedes=None,
        registered_at="2026-11-15T00:00:00+00:00",
        ensemble_existed_at_registration=False,
        status="active",
    )
    composed = compose_narrative(
        _inputs(
            [
                _direction(
                    "Solo",
                    RUN_A,
                    gates=DecisionGatesRead(
                        run_id=RUN_A, registrations=[registration], evaluations=[]
                    ),
                )
            ]
        )
    )
    signal = composed.body.directions[0].signals[0]
    assert signal.passed is None
    assert signal.observed is None
    assert "not yet evaluated" in signal.text


def test_compose_unreachable_threshold_search_is_honest() -> None:
    search = ThresholdSearchResult(
        run_id=RUN_A,
        ensemble_id="ens-x",
        metric="final_value",
        variable="demand",
        mode="p_loss",
        target=0.01,
        direction="increasing",
        bounds=(0.0, 100.0),
        threshold=None,
        reachable=False,
        iterations=5,
        trials_per_evaluation=20,
        tolerance=0.01,
        loss_threshold=0.0,
        seed=42,
        protocol="sprint4-v1",
    )
    composed = compose_narrative(_inputs([_direction("Solo", RUN_A, threshold_search=search)]))
    signal = composed.body.directions[0].signals[0]
    assert signal.kind == "threshold_search"
    assert "No threshold found" in signal.text
    assert signal.threshold is None


def test_compose_mece_trace_copies_scope_tags() -> None:
    definition = DirectionDefinition(
        name="Solo", source_run_id=RUN_A, mece_branches=["revenue", "cost"]
    )
    composed = compose_narrative(
        _inputs(
            [
                DirectionInputs(
                    definition=definition,
                    ensemble=_ensemble(RUN_A, baseline_p50=10.0, strategy_p50=20.0),
                )
            ],
            tree=_tree(),
            validation=_validation(),
        )
    )
    trace = composed.body.directions[0].mece_trace
    assert trace is not None
    assert [branch.name for branch in trace.branches] == ["revenue", "cost"]
    assert trace.branches[0].scope == ["b"]
    assert trace.tree_topic == "AI customer-service line"
    assert composed.body.mece is not None
    assert composed.body.mece.is_mece is True
    assert composed.body.mece.branch_count == 3


def test_compose_unknown_mece_branch_refuses_naming_valid_branches() -> None:
    definition = DirectionDefinition(name="Solo", source_run_id=RUN_A, mece_branches=["nope"])
    with pytest.raises(NarrativeError) as excinfo:
        compose_narrative(
            _inputs(
                [
                    DirectionInputs(
                        definition=definition,
                        ensemble=_ensemble(RUN_A, baseline_p50=10.0, strategy_p50=20.0),
                    )
                ],
                tree=_tree(),
                validation=_validation(),
            )
        )
    assert excinfo.value.code == "narrative_unknown_mece_branch"
    assert "nope" in str(excinfo.value)
    assert "cost" in str(excinfo.value)


def test_compose_branches_without_tree_refuses() -> None:
    definition = DirectionDefinition(name="Solo", source_run_id=RUN_A, mece_branches=["cost"])
    with pytest.raises(NarrativeError) as excinfo:
        compose_narrative(
            _inputs(
                [
                    DirectionInputs(
                        definition=definition,
                        ensemble=_ensemble(RUN_A, baseline_p50=10.0, strategy_p50=20.0),
                    )
                ]
            )
        )
    assert excinfo.value.code == "narrative_mece_branches_without_tree"


def test_compose_expected_shortfall_and_bootstrap_for_chosen_arm() -> None:
    shortfall = ExpectedShortfallResult(
        run_id=RUN_A,
        ensemble_id="ens-x",
        metric="final_value",
        alpha=0.05,
        tail="lower",
        baseline=ExpectedShortfallDetail(value=-3.0, threshold=-2.0, tail_count=1, n=20),
        strategy=ExpectedShortfallDetail(value=-1.0, threshold=-0.5, tail_count=1, n=20),
        paired=ExpectedShortfallDetail(value=0.5, threshold=0.0, tail_count=1, n=20),
        trial_values_hash="sha256:es",
        protocol="sprint4-v1",
    )
    bootstrap = BootstrapResult(
        run_id=RUN_A,
        ensemble_id="ens-x",
        metric="final_value",
        loss_threshold=0.0,
        baseline=[
            BootstrapInterval(
                statistic="p50",
                estimate=10.0,
                low=8.0,
                high=12.0,
                draws=200,
                seed=7,
                level=0.9,
                method="percentile",
            )
        ],
        strategy=[
            BootstrapInterval(
                statistic="p50",
                estimate=20.0,
                low=18.0,
                high=22.0,
                draws=200,
                seed=7,
                level=0.9,
                method="percentile",
            )
        ],
        trial_values_hash="sha256:boot",
        protocol="sprint4-v1",
    )
    composed = compose_narrative(
        _inputs(
            [
                _direction(
                    "Solo",
                    RUN_A,
                    arm="strategy",
                    expected_shortfall=shortfall,
                    bootstrap=bootstrap,
                )
            ]
        )
    )
    dist = composed.body.directions[0].distribution
    assert dist.expected_shortfall is not None
    assert dist.expected_shortfall["value"] == -1.0
    assert dist.trial_values_hash == "sha256:es"
    assert len(dist.bootstrap_intervals) == 1
    assert dist.bootstrap_intervals[0]["estimate"] == 20.0


# ---------------------------------------------------------------------------
# Topic resolution + request model
# ---------------------------------------------------------------------------


def test_compose_topic_prefers_request_then_tree_then_run_id() -> None:
    with_tree = compose_narrative(
        _inputs([_direction("Solo", RUN_A)], tree=_tree(), validation=_validation())
    )
    assert with_tree.body.topic == "AI customer-service line"
    assert with_tree.body.topic_source == "mece_tree"
    with_request = compose_narrative(
        _inputs(
            [_direction("Solo", RUN_A)],
            topic="Custom topic",
            tree=_tree(),
            validation=_validation(),
        )
    )
    assert with_request.body.topic == "Custom topic"
    assert with_request.body.topic_source == "request"
    bare = compose_narrative(_inputs([_direction("Solo", RUN_A)]))
    assert bare.body.topic == f"run {RUN_A}"
    assert bare.body.topic_source == "run_id"


def test_generate_request_rejects_duplicate_direction_names() -> None:
    with pytest.raises(ValueError, match="unique"):
        NarrativeGenerateRequest(
            directions=[
                DirectionDefinition(name="Same", source_run_id=RUN_A),
                DirectionDefinition(name="Same", source_run_id=RUN_B),
            ]
        )


def test_generate_request_rejects_empty_directions() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        NarrativeGenerateRequest(directions=[])


def test_generate_request_rejects_more_than_four_directions() -> None:
    with pytest.raises(ValueError, match="at most 4"):
        NarrativeGenerateRequest(
            directions=[DirectionDefinition(name=f"D{i}", source_run_id=RUN_A) for i in range(5)]
        )


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


def test_render_marks_provenance_and_formats_numbers() -> None:
    composed = compose_narrative(
        _inputs(
            [_direction("Solo", RUN_A, deliberations=[_strategy_record(), _advisory_record()])],
            tree=_tree(),
            validation=_validation(),
        )
    )
    markdown = composed.body.markdown
    assert "[computed]" in markdown
    assert "[deliberated]" in markdown
    assert "P10 0 / P50 10 / P90 20" in markdown
    assert "The launch failed in month three." in markdown
    assert "Call the two pilot clients" in markdown


# ---------------------------------------------------------------------------
# Polish hook (scripted port; no live LLM)
# ---------------------------------------------------------------------------


async def test_polish_returns_output_and_model() -> None:
    port = ScriptedSkillPort({POLISH_TEMPLATE_ID: [{"polished_markdown": "# Polished brief"}]})
    output, model = await polish_markdown(port, "# Draft")
    assert output.polished_markdown == "# Polished brief"
    assert model == "fixture"
    assert port.calls[0]["template_id"] == POLISH_TEMPLATE_ID
    assert "Do not compute new numbers" in port.calls[0]["system_prompt"]
    port.assert_exhausted()


async def test_polish_unavailable_port_raises() -> None:
    port = ScriptedSkillPort({}, available=False)
    with pytest.raises(SkillLLMUnavailable):
        await polish_markdown(port, "# Draft")
    assert port.calls == []


async def test_polish_contract_failure_raises() -> None:
    port = ScriptedSkillPort({POLISH_TEMPLATE_ID: [{"wrong_key": "nope"}]})
    with pytest.raises(SkillContractError):
        await polish_markdown(port, "# Draft")

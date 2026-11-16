"""Pure deterministic composer for decision-direction narratives.

``compose_narrative`` is a pure function of its inputs: no I/O, no
clock, no randomness. The service assembles :class:`NarrativeInputs`
from stored rows and fragments; the composer validates references,
derives directions, ranks them, and renders the deterministic
markdown. Same inputs compose byte-identical bodies (the service
pins this with ``content_hash``).

Direction-derivation rules (see SPRINT13.md §2 for the full design):

1. Directions come ONLY from direction definitions: explicit
   definitions in the generation request, or (since Sprint 14)
   stored direction mappings resolved by the service when the
   request omits them. Nothing is invented from options, branches,
   or deliberations.
2. Each direction's distribution is its source run's stored
   ensemble, chosen arm. No ensemble means the service refuses
   before composing; the composer never sees an ensemble-less
   direction.
3. Ranking is P50 descending, ties broken by direction name
   ascending.
4. MECE traces name branches of the anchor run's stored tree;
   unknown names refuse loudly.
5. Deliberation quotes come from the latest-per-pipeline record on
   the source run, falling back to the anchor run; a pinned
   deliberation id must exist on either run and then solely
   determines what is quotable.
6. Drivers are the stored tornado rows in stored order (cap 5).
7. Signals union, in fixed order: latest gate evaluation (or active
   registration), stored threshold search, loop triggers (when a
   loop is supplied), advisory go/kill quotes, war-game playbook.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from planagent.services.distributions.models import MonteCarloResult
from planagent.services.living_loop.models import LoopTriggerDefinition
from planagent.services.mece.models import DecompositionTree, MeceValidationResult
from planagent.services.narratives.models import (
    MAX_DRIVER_ROWS,
    NARRATIVE_PROTOCOL_VERSION,
    CalibrationContextEntry,
    DirectionDefinition,
    DirectionNarrative,
    DistributionSection,
    DriverRow,
    DriversSection,
    FailureModeQuote,
    FirstStepSection,
    LoopContext,
    MeceBranchTrace,
    MeceContext,
    MeceTrace,
    NarrativeBody,
    NarrativeError,
    PremortemSection,
    TripwireSignal,
)
from planagent.services.narratives.render import render_narrative_markdown
from planagent.services.robustness.models import (
    BootstrapResult,
    DecisionGatesRead,
    ExpectedShortfallResult,
    ThresholdSearchResult,
    TornadoResult,
)
from planagent.services.skills.contracts import DecisionContract, PreMortem, WarGame
from planagent.services.skills.models import SkillDeliberationRecord

_TEMPLATE_PREMORTEM = (
    "No pre-mortem deliberation is recorded for this direction, so no "
    "failure narrative is quoted. Run a strategy-team deliberation "
    "(POST /runs/{run_id}/skills/strategy-team) to produce one; this "
    "narrative does not invent failure modes."
)
_TEMPLATE_FIRST_STEP = (
    "No advisory-board deliberation is recorded for this direction, so "
    "no first step is quoted. Run an advisory-board deliberation "
    "(POST /runs/{run_id}/skills/advisory-board) to produce one; this "
    "narrative does not invent next actions."
)
_TEMPLATE_DRIVERS = (
    "No tornado analysis is stored on the source run, so no key drivers "
    "are listed. Run POST /runs/{run_id}/robustness/tornado first."
)
_TEMPLATE_SIGNALS = "No tripwire signals exist for this direction yet."
_TEMPLATE_MECE = "No MECE tree is stored on the anchor run, so no branch trace is recorded."


@dataclass
class DirectionInputs:
    """Everything the composer needs for one direction, pre-loaded."""

    definition: DirectionDefinition
    ensemble: MonteCarloResult
    tornado: TornadoResult | None = None
    threshold_search: ThresholdSearchResult | None = None
    expected_shortfall: ExpectedShortfallResult | None = None
    bootstrap: BootstrapResult | None = None
    gates: DecisionGatesRead | None = None
    deliberations: list[SkillDeliberationRecord] = field(default_factory=list)
    anchor_deliberations: list[SkillDeliberationRecord] = field(default_factory=list)


@dataclass
class LoopContextInput:
    """Resolved monitoring-loop context for signal derivation."""

    loop_id: str
    loop_name: str
    registration_id: str | None
    triggers: list[LoopTriggerDefinition] = field(default_factory=list)


@dataclass
class NarrativeInputs:
    """Everything the composer needs, pre-loaded by the service."""

    anchor_run_id: str
    domain_id: str
    request_topic: str | None
    mece_tree: DecompositionTree | None
    mece_validation: MeceValidationResult | None
    directions: list[DirectionInputs]
    calibration_context: list[CalibrationContextEntry] = field(default_factory=list)
    loop_context: LoopContextInput | None = None


@dataclass
class ComposedNarrative:
    """Composer output: the artifact body plus its input pins."""

    body: NarrativeBody
    input_pins: dict[str, Any]


def _collect_branches(tree: DecompositionTree) -> list[tuple[str, list[str]]]:
    """Branch (name, scope) pairs in pre-order, first occurrence wins."""
    collected: list[tuple[str, list[str]]] = []
    seen: set[str] = set()

    def walk(branch: Any) -> None:
        if branch.name not in seen:
            seen.add(branch.name)
            collected.append((branch.name, list(branch.scope)))
        for child in branch.children:
            walk(child)

    walk(tree.root)
    return collected


def _select_deliberations(
    inputs: DirectionInputs,
) -> tuple[SkillDeliberationRecord | None, SkillDeliberationRecord | None]:
    """Latest-per-pipeline deliberation, honoring a pinned id.

    Default: latest record of each pipeline on the source run, with
    fallback to the anchor run. A pinned id must exist on the source
    or anchor run and then solely determines what is quotable: a
    pinned strategy-team record yields no advisory quotes, and vice
    versa.
    """
    pinned = inputs.definition.deliberation_id
    if pinned is not None:
        for record in inputs.deliberations:
            if record.id == pinned:
                return (
                    record if record.pipeline == "strategy_team" else None,
                    record if record.pipeline == "advisory_board" else None,
                )
        for record in inputs.anchor_deliberations:
            if record.id == pinned:
                return (
                    record if record.pipeline == "strategy_team" else None,
                    record if record.pipeline == "advisory_board" else None,
                )
        raise NarrativeError(
            "narrative_deliberation_not_found",
            f"Pinned deliberation {pinned!r} was not found on the source run "
            f"{inputs.definition.source_run_id!r} or its anchor run.",
        )

    def latest(
        pipeline: str, records: list[SkillDeliberationRecord]
    ) -> SkillDeliberationRecord | None:
        for record in reversed(records):
            if record.pipeline == pipeline:
                return record
        return None

    strategy = latest("strategy_team", inputs.deliberations) or latest(
        "strategy_team", inputs.anchor_deliberations
    )
    advisory = latest("advisory_board", inputs.deliberations) or latest(
        "advisory_board", inputs.anchor_deliberations
    )
    return strategy, advisory


def _extract_premortem(
    record: SkillDeliberationRecord | None,
) -> PremortemSection:
    if record is None:
        return PremortemSection(provenance="template", note=_TEMPLATE_PREMORTEM)
    panel = record.result.get("panel")
    raw = panel.get("premortem") if isinstance(panel, dict) else None
    if raw is None:
        return PremortemSection(
            provenance="template",
            deliberation_id=record.id,
            note=(
                "The latest strategy-team deliberation recorded no "
                "pre-mortem stage (it may have run with pre-mortem "
                "disabled), so no failure narrative is quoted."
            ),
        )
    try:
        premortem = PreMortem.model_validate(raw)
    except ValidationError as exc:
        raise NarrativeError(
            "narrative_corrupt_deliberation",
            f"Stored deliberation {record.id!r} carries a pre-mortem stage "
            f"that fails its contract: {exc}",
        ) from exc
    return PremortemSection(
        provenance="deliberated",
        deliberation_id=record.id,
        template_id="gambit.premortem",
        failure_narrative=premortem.failure_narrative,
        failure_modes=[
            FailureModeQuote(
                mode=mode.mode,
                cause=mode.cause,
                early_signal=mode.early_signal,
                prevention=mode.prevention,
            )
            for mode in premortem.failure_modes
        ],
        fatal_flags=list(premortem.fatal_flags),
    )


def _extract_first_step(
    record: SkillDeliberationRecord | None,
) -> FirstStepSection:
    if record is None:
        return FirstStepSection(provenance="template", note=_TEMPLATE_FIRST_STEP)
    raw = record.result.get("contract")
    if raw is None:
        return FirstStepSection(
            provenance="template",
            deliberation_id=record.id,
            note=(
                "The latest advisory-board deliberation recorded no "
                "decision contract, so no first step is quoted."
            ),
        )
    try:
        contract = DecisionContract.model_validate(raw)
    except ValidationError as exc:
        raise NarrativeError(
            "narrative_corrupt_deliberation",
            f"Stored deliberation {record.id!r} carries a decision contract "
            f"that fails its contract: {exc}",
        ) from exc
    return FirstStepSection(
        provenance="deliberated",
        deliberation_id=record.id,
        template_id="advisory.chair_synthesis",
        next_action=contract.next_action,
        cheapest_validation_test=contract.cheapest_validation_test,
        conditions=list(contract.conditions),
    )


def _contract_signals(record: SkillDeliberationRecord | None) -> list[TripwireSignal]:
    if record is None:
        return []
    raw = record.result.get("contract")
    if raw is None:
        return []
    try:
        contract = DecisionContract.model_validate(raw)
    except ValidationError as exc:
        raise NarrativeError(
            "narrative_corrupt_deliberation",
            f"Stored deliberation {record.id!r} carries a decision contract "
            f"that fails its contract: {exc}",
        ) from exc
    return [
        TripwireSignal(
            kind="advisory_contract",
            provenance="deliberated",
            text=f"Go threshold: {contract.go_threshold}",
            source_ids={"deliberation_id": record.id, "template_id": "advisory.chair_synthesis"},
            name="go_threshold",
        ),
        TripwireSignal(
            kind="advisory_contract",
            provenance="deliberated",
            text=f"Kill criterion: {contract.kill_criterion}",
            source_ids={"deliberation_id": record.id, "template_id": "advisory.chair_synthesis"},
            name="kill_criterion",
        ),
    ]


def _wargame_signals(record: SkillDeliberationRecord | None) -> list[TripwireSignal]:
    if record is None:
        return []
    panel = record.result.get("panel")
    raw = panel.get("wargame") if isinstance(panel, dict) else None
    if raw is None:
        return []
    try:
        wargame = WarGame.model_validate(raw)
    except ValidationError as exc:
        raise NarrativeError(
            "narrative_corrupt_deliberation",
            f"Stored deliberation {record.id!r} carries a war-game stage "
            f"that fails its contract: {exc}",
        ) from exc
    return [
        TripwireSignal(
            kind="wargame_playbook",
            provenance="deliberated",
            text=f"Signal: {entry.signal} — Response: {entry.response} (owner: {entry.owner})",
            source_ids={"deliberation_id": record.id, "template_id": "mckinsey.verify_wargame"},
            name="playbook",
        )
        for entry in wargame.playbook
    ]


def _gate_signals(gates: DecisionGatesRead | None) -> list[TripwireSignal]:
    if gates is None:
        return []
    if gates.evaluations:
        evaluation = gates.evaluations[-1]
        return [
            TripwireSignal(
                kind="decision_gate",
                provenance="computed",
                text=(
                    f"Gate {outcome.name}: {outcome.metric.value} "
                    f"{outcome.operator.value} {outcome.threshold} "
                    f"(observed {outcome.observed}, "
                    f"{'passed' if outcome.passed else 'FAILED'})"
                ),
                source_ids={
                    "gate_evaluation_id": evaluation.id,
                    "gate_registration_id": evaluation.registration_id,
                },
                name=outcome.name,
                metric=outcome.metric.value,
                operator=outcome.operator.value,
                threshold=outcome.threshold,
                observed=outcome.observed,
                passed=outcome.passed,
            )
            for outcome in evaluation.outcomes
        ]
    active = [r for r in gates.registrations if r.status == "active"]
    registration = (
        active[-1] if active else (gates.registrations[-1] if gates.registrations else None)
    )
    if registration is None:
        return []
    return [
        TripwireSignal(
            kind="decision_gate",
            provenance="computed",
            text=(
                f"Gate {gate.name}: {gate.metric.value} {gate.operator.value} "
                f"{gate.threshold} (registered, not yet evaluated)"
            ),
            source_ids={"gate_registration_id": registration.id},
            name=gate.name,
            metric=gate.metric.value,
            operator=gate.operator.value,
            threshold=gate.threshold,
        )
        for gate in registration.gates
    ]


def _threshold_signal(
    search: ThresholdSearchResult | None,
) -> list[TripwireSignal]:
    if search is None:
        return []
    if search.reachable and search.threshold is not None:
        text = (
            f"Threshold: {search.variable} at {search.threshold} "
            f"({search.mode}, target {search.target}, {search.direction})"
        )
    else:
        text = (
            f"No threshold found for {search.variable} within "
            f"[{search.bounds[0]}, {search.bounds[1]}] "
            f"({search.mode}, target {search.target})"
        )
    return [
        TripwireSignal(
            kind="threshold_search",
            provenance="computed",
            text=text,
            source_ids={"ensemble_id": search.ensemble_id},
            name=search.variable,
            metric=search.metric,
            threshold=search.threshold,
        )
    ]


def _format_trigger(trigger: LoopTriggerDefinition) -> str:
    if trigger.kind == "threshold":
        return (
            f"Loop trigger {trigger.name}: {trigger.field} {trigger.operator} {trigger.threshold}"
        )
    if trigger.kind == "gate":
        return (
            f"Loop trigger {trigger.name}: gate {trigger.gate.metric.value} "
            f"{trigger.gate.operator.value} {trigger.gate.threshold} "
            f"on {trigger.field}"
        )
    reference = (
        f"reference {trigger.reference_value}"
        if trigger.reference_value is not None
        else "baseline reference"
    )
    return (
        f"Loop trigger {trigger.name}: {trigger.field} deviates more than "
        f"{trigger.tolerance} from {reference} for {trigger.consecutive} "
        f"consecutive observations"
    )


def _loop_signals(loop: LoopContextInput | None) -> list[TripwireSignal]:
    if loop is None:
        return []
    source_ids = {"loop_id": loop.loop_id}
    if loop.registration_id is not None:
        source_ids["registration_id"] = loop.registration_id
    return [
        TripwireSignal(
            kind="loop_trigger",
            provenance="computed",
            text=_format_trigger(trigger),
            source_ids=dict(source_ids),
            name=trigger.name,
        )
        for trigger in loop.triggers
    ]


def _compose_direction(
    inputs: DirectionInputs,
    branches: list[tuple[str, list[str]]],
    tree_topic: str | None,
    loop: LoopContextInput | None,
) -> tuple[DirectionNarrative, dict[str, Any]]:
    definition = inputs.definition
    ensemble = inputs.ensemble
    arm_summary = ensemble.baseline if definition.arm == "baseline" else ensemble.strategy

    expected_shortfall: dict[str, Any] | None = None
    trial_values_hash: str | None = None
    if inputs.expected_shortfall is not None:
        detail = (
            inputs.expected_shortfall.baseline
            if definition.arm == "baseline"
            else inputs.expected_shortfall.strategy
        )
        expected_shortfall = {
            "value": detail.value,
            "threshold": detail.threshold,
            "tail_count": detail.tail_count,
            "n": detail.n,
            "alpha": inputs.expected_shortfall.alpha,
            "tail": inputs.expected_shortfall.tail,
        }
        trial_values_hash = inputs.expected_shortfall.trial_values_hash
    bootstrap_intervals: list[dict[str, Any]] = []
    if inputs.bootstrap is not None:
        intervals = (
            inputs.bootstrap.baseline if definition.arm == "baseline" else inputs.bootstrap.strategy
        )
        bootstrap_intervals = [interval.model_dump(mode="json") for interval in intervals]
        trial_values_hash = trial_values_hash or inputs.bootstrap.trial_values_hash

    distribution = DistributionSection(
        run_id=ensemble.base_run_id,
        ensemble_id=ensemble.ensemble_id,
        metric=ensemble.metric,
        loss_threshold=ensemble.loss_threshold,
        trials=ensemble.trials,
        seed=ensemble.seed,
        arm=definition.arm,
        n=arm_summary.n,
        mean=arm_summary.mean,
        min=arm_summary.min,
        max=arm_summary.max,
        p10=arm_summary.p10,
        p50=arm_summary.p50,
        p90=arm_summary.p90,
        stddev=arm_summary.stddev,
        p_loss=arm_summary.p_loss,
        expected_shortfall=expected_shortfall,
        bootstrap_intervals=bootstrap_intervals,
        trial_values_hash=trial_values_hash,
    )

    if inputs.tornado is not None:
        drivers = DriversSection(
            rows=[
                DriverRow(
                    variable=row.variable,
                    low_value=row.low_value,
                    high_value=row.high_value,
                    outcome_low=row.outcome_low,
                    outcome_high=row.outcome_high,
                    swing=row.swing,
                )
                for row in inputs.tornado.rows[:MAX_DRIVER_ROWS]
            ],
            ensemble_id=inputs.tornado.ensemble_id,
        )
    else:
        drivers = DriversSection(note=_TEMPLATE_DRIVERS)

    strategy_record, advisory_record = _select_deliberations(inputs)
    signals = (
        _gate_signals(inputs.gates)
        + _threshold_signal(inputs.threshold_search)
        + _loop_signals(loop)
        + _contract_signals(advisory_record)
        + _wargame_signals(strategy_record)
    )
    signals_note = _TEMPLATE_SIGNALS if not signals else None

    if definition.mece_branches:
        if tree_topic is None:
            raise NarrativeError(
                "narrative_mece_branches_without_tree",
                f"Direction {definition.name!r} names MECE branches but no "
                "MECE tree is stored on the anchor run.",
            )
        known = dict(branches)
        for branch_name in definition.mece_branches:
            if branch_name not in known:
                raise NarrativeError(
                    "narrative_unknown_mece_branch",
                    f"Direction {definition.name!r} names unknown MECE branch "
                    f"{branch_name!r}; known branches: {sorted(known)}.",
                )
        mece_trace = MeceTrace(
            branches=[
                MeceBranchTrace(name=name, scope=list(known[name]))
                for name in definition.mece_branches
            ],
            tree_topic=tree_topic,
        )
        mece_note = None
    else:
        mece_trace = None
        mece_note = _TEMPLATE_MECE if tree_topic is None else None

    direction = DirectionNarrative(
        rank=0,  # assigned after ranking
        name=definition.name,
        source_run_id=definition.source_run_id,
        arm=definition.arm,
        distribution=distribution,
        drivers=drivers,
        signals=signals,
        signals_note=signals_note,
        premortem=_extract_premortem(strategy_record),
        first_step=_extract_first_step(advisory_record),
        mece_trace=mece_trace,
        mece_note=mece_note,
    )
    pins: dict[str, Any] = {
        "definition": definition.model_dump(mode="json"),
        "ensemble_id": ensemble.ensemble_id,
        "ensemble_seed": ensemble.seed,
        "ensemble_trials": ensemble.trials,
        "ensemble_metric": ensemble.metric,
        "ensemble_loss_threshold": ensemble.loss_threshold,
        "strategy_levers": ensemble.strategy_levers,
        "tornado_ensemble_id": inputs.tornado.ensemble_id if inputs.tornado else None,
        "threshold_search": (
            {
                "ensemble_id": inputs.threshold_search.ensemble_id,
                "variable": inputs.threshold_search.variable,
                "mode": inputs.threshold_search.mode,
            }
            if inputs.threshold_search
            else None
        ),
        "gate_evaluation_id": (
            inputs.gates.evaluations[-1].id if inputs.gates and inputs.gates.evaluations else None
        ),
        "gate_registration_ids": (
            [r.id for r in inputs.gates.registrations] if inputs.gates else []
        ),
        "strategy_deliberation_id": strategy_record.id if strategy_record else None,
        "advisory_deliberation_id": advisory_record.id if advisory_record else None,
    }
    return direction, pins


def compose_narrative(inputs: NarrativeInputs) -> ComposedNarrative:
    """Compose the artifact body from pre-loaded inputs (pure)."""
    if inputs.mece_tree is not None:
        branches = _collect_branches(inputs.mece_tree)
        tree_topic: str | None = inputs.mece_tree.topic
        mece_context = MeceContext(
            topic=inputs.mece_tree.topic,
            is_mece=inputs.mece_validation.is_mece if inputs.mece_validation else False,
            branch_count=inputs.mece_validation.branch_count if inputs.mece_validation else 0,
            scope_tag_count=inputs.mece_validation.scope_tag_count if inputs.mece_validation else 0,
            issue_count=len(inputs.mece_validation.issues) if inputs.mece_validation else 0,
        )
    else:
        branches = []
        tree_topic = None
        mece_context = None

    directions: list[DirectionNarrative] = []
    direction_pins: list[dict[str, Any]] = []
    for direction_inputs in inputs.directions:
        direction, pins = _compose_direction(
            direction_inputs, branches, tree_topic, inputs.loop_context
        )
        directions.append(direction)
        direction_pins.append(pins)

    directions.sort(key=lambda d: (-d.distribution.p50, d.name))
    for index, direction in enumerate(directions, start=1):
        direction.rank = index

    if inputs.request_topic is not None:
        topic, topic_source = inputs.request_topic, "request"
    elif tree_topic:
        topic, topic_source = tree_topic, "mece_tree"
    else:
        topic, topic_source = f"run {inputs.anchor_run_id}", "run_id"

    loop_context = None
    if inputs.loop_context is not None:
        loop_context = LoopContext(
            loop_id=inputs.loop_context.loop_id,
            loop_name=inputs.loop_context.loop_name,
            registration_id=inputs.loop_context.registration_id,
            trigger_count=len(inputs.loop_context.triggers),
        )

    body = NarrativeBody(
        protocol=NARRATIVE_PROTOCOL_VERSION,
        anchor_run_id=inputs.anchor_run_id,
        domain_id=inputs.domain_id,
        topic=topic,
        topic_source=topic_source,
        mece=mece_context,
        calibration_context=list(inputs.calibration_context),
        loop_context=loop_context,
        directions=directions,
        markdown="",
    )
    body.markdown = render_narrative_markdown(body)
    pins = {
        "anchor_run_id": inputs.anchor_run_id,
        "topic": topic,
        "mece": (
            {
                "topic": inputs.mece_tree.topic,
                "is_mece": mece_context.is_mece if mece_context else None,
            }
            if inputs.mece_tree is not None
            else None
        ),
        "directions": direction_pins,
        "calibration_fit_ids": [entry.fit_id for entry in inputs.calibration_context],
        "loop": (
            {
                "loop_id": inputs.loop_context.loop_id,
                "registration_id": inputs.loop_context.registration_id,
            }
            if inputs.loop_context is not None
            else None
        ),
    }
    return ComposedNarrative(body=body, input_pins=pins)


__all__ = [
    "ComposedNarrative",
    "DirectionInputs",
    "LoopContextInput",
    "NarrativeInputs",
    "compose_narrative",
]

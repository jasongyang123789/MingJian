"""Narrative service: input assembly, validation, persistence, polish.

Reads stored fragments directly with the same Pydantic models the
writing services used (Sprint 6 context-builder precedent) — no
coupling to ``SimulationService``. Every direction reference is
validated before composing or persisting anything: a generation
request with a bad reference refuses before any row is written.

Storage is a new table (migration 0035), not a run-summary key:
narratives are versioned, append-only deliverables that must be
queryable on their own, following the calibration-fits precedent.
Regeneration inserts a new version; nothing is ever overwritten.
"""

from __future__ import annotations

from typing import Any, Literal, cast

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from planagent.config import Settings
from planagent.domain.enums import SimulationRunStatus
from planagent.domain.models import (
    CalibrationFitRecord,
    DecisionNarrativePolishRecord,
    DecisionNarrativeRecord,
    DirectionMappingRecord,
    SimulationRun,
    StateSnapshotRecord,
    StrategyLoopRecord,
)
from planagent.services.distributions.canonical import sha256_hash
from planagent.services.distributions.models import MonteCarloResult
from planagent.services.living_loop.models import TriggerRegistration
from planagent.services.living_loop.monitoring import select_registration
from planagent.services.mece.models import DecompositionTree, MeceValidationResult
from planagent.services.narratives.composer import (
    DirectionInputs,
    LoopContextInput,
    NarrativeInputs,
    _collect_branches,
    compose_narrative,
)
from planagent.services.narratives.derivation import (
    DERIVATION_RULES_VERSION,
    DerivationCandidate,
    derive_directions,
)
from planagent.services.narratives.models import (
    MAX_CALIBRATION_FITS_IN_CONTEXT,
    MAX_DIRECTIONS,
    CalibrationContextEntry,
    DecisionNarrativeListRead,
    DecisionNarrativeRead,
    DerivationRead,
    DerivationRuleOutcome,
    DirectionDefinition,
    DirectionError,
    DirectionMappingCreate,
    DirectionMappingListRead,
    DirectionMappingRead,
    DirectionMappingUpdate,
    DirectionOverrideOutcome,
    DirectionOverrideRead,
    DirectionOverrideReforkRead,
    DirectionOverrideReforkRequest,
    DirectionOverrideRequest,
    DirectionOverrideSpec,
    DirectionProposeRead,
    DirectionProposeRequest,
    NarrativeBody,
    NarrativeError,
    NarrativeGenerateRequest,
    NarrativePolishRead,
    ProposalOutcome,
)
from planagent.services.narratives.overrides import (
    BranchCreationFailed,
    BranchRequest,
    BranchResult,
    BranchRunner,
    assumption_line,
    build_override_set,
    validate_merged_overrides,
)
from planagent.services.narratives.polish import (
    POLISH_TEMPLATE_ID,
    POLISH_TEMPLATE_VERSION,
    polish_markdown,
)
from planagent.services.narratives.proposals import (
    PROPOSAL_TEMPLATE_ID,
    PROPOSAL_TEMPLATE_VERSION,
    DirectionProposal,
    DirectionProposals,
    ProposalContext,
    ProposalFamilyRun,
    ProposalVariable,
    build_proposal_user_content,
    propose_directions,
)
from planagent.services.narratives.recheck import check_polish
from planagent.services.openai_client import OpenAIService
from planagent.services.robustness.models import (
    BootstrapResult,
    DecisionGatesRead,
    ExpectedShortfallResult,
    GateEvaluation,
    GateRegistration,
    RobustnessRead,
    ThresholdSearchResult,
    TornadoResult,
)
from planagent.services.simulation.distributions import MONTE_CARLO_SUMMARY_KEY
from planagent.services.simulation.robustness import (
    DECISION_GATES_SUMMARY_KEY,
    ROBUSTNESS_SUMMARY_KEY,
)
from planagent.services.skills.contracts import SkillContractError, SkillTruncatedError
from planagent.services.skills.models import SkillDeliberationRecord
from planagent.services.skills.orchestration import (
    OpenAIServiceSkillPort,
    SkillLLMPort,
    SkillLLMResponse,
    SkillLLMUnavailable,
)
from planagent.services.skills.service import SKILL_DELIBERATIONS_SUMMARY_KEY
from planagent.services.variables.models import VariableSet

_MECE_CONFIGURATION_KEY = "mece"


class _NoLLMPort:
    """Port used when no LLM service is wired: always unavailable."""

    def is_available(self) -> bool:
        return False

    async def generate_json(self, **_kwargs: Any) -> SkillLLMResponse:
        raise SkillLLMUnavailable("No LLM service is configured for narrative polish.")


class _NoBranchRunner:
    """Branch runner used when none is wired: override always refuses."""

    def is_available(self) -> bool:
        return False

    async def create_branch(
        self, _session: AsyncSession, _parent_run_id: str, _request: BranchRequest
    ) -> BranchResult:
        raise DirectionError(
            "direction_override_unavailable",
            "No branch runner is configured for variable-override directions.",
        )

    async def discard_branch(self, _session: AsyncSession, _branch_id: str) -> bool:
        # Nothing was ever created through this runner.
        return False


def _is_mapping_unique_violation(exc: IntegrityError) -> bool:
    """Whether an integrity error is the direction-mapping name clash.

    Only this clash is a concurrent same-name race, convertible to
    a ``skipped`` outcome; every other integrity error is a real
    defect and must surface. SQLite reports the failing columns
    (``UNIQUE constraint failed: direction_mappings.anchor_run_id,
    direction_mappings.name``); Postgres reports the constraint
    name (``uq_direction_mappings_anchor_name``). Match on the
    driver error when present, else the wrapped message.
    """
    detail = str(getattr(exc, "orig", None) or exc).lower()
    return "uq_direction_mappings_anchor_name" in detail or (
        "direction_mappings" in detail and "unique" in detail
    )


def _corrupt(fragment: str, exc: ValidationError) -> NarrativeError:
    return NarrativeError(
        "narrative_corrupt_fragment",
        f"Stored {fragment} fragment fails its model: {exc}",
    )


def _direction_corrupt(fragment: str, exc: ValidationError) -> DirectionError:
    return DirectionError(
        "direction_corrupt_fragment",
        f"Stored {fragment} fragment fails its model: {exc}",
    )


def _read_sub_fragment[ModelT: BaseModel](
    fragment: dict[str, Any], key: str, model: type[ModelT], fragment_name: str
) -> ModelT | None:
    """Validate one stored sub-fragment, or None when absent.

    A present-but-not-a-dict value is corrupt, not silently absent:
    writers only ever store model dumps, so anything else means the
    stored data is wrong-shaped.
    """
    value = fragment.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise NarrativeError(
            "narrative_corrupt_fragment",
            f"Stored {fragment_name} fragment fails its model: sub-fragment "
            f"{key!r} is not a JSON object.",
        )
    try:
        return model.model_validate(value)
    except ValidationError as exc:
        raise _corrupt(fragment_name, exc) from exc


def _read_robustness(fragment: object, *, run_id: str, ensemble_id: str) -> RobustnessRead:
    """Build a RobustnessRead from the stored robustness fragment.

    Writers store per-analysis sub-fragments (``{"tornado": ...}``)
    with no top-level ``run_id``; this validates each sub-fragment
    on its own model and injects ``run_id``, exactly as the
    robustness service's own ``get_robustness`` does. Validating
    the raw fragment against ``RobustnessRead`` always failed (the
    Sprint 13 bug, fixed in fix batch 1). Unknown keys are
    ignored, matching ``get_robustness``.
    """
    if not isinstance(fragment, dict):
        raise NarrativeError(
            "narrative_corrupt_fragment",
            "Stored robustness fragment fails its model: expected a JSON object.",
        )
    return RobustnessRead(
        run_id=run_id,
        ensemble_id=ensemble_id,
        expected_shortfall=_read_sub_fragment(
            fragment, "expected_shortfall", ExpectedShortfallResult, "robustness"
        ),
        tornado=_read_sub_fragment(fragment, "tornado", TornadoResult, "robustness"),
        threshold_search=_read_sub_fragment(
            fragment, "threshold_search", ThresholdSearchResult, "robustness"
        ),
        bootstrap=_read_sub_fragment(fragment, "bootstrap", BootstrapResult, "robustness"),
    )


def _read_gates_list(fragment: dict[str, Any], key: str) -> list[Any]:
    value = fragment.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list):
        raise NarrativeError(
            "narrative_corrupt_fragment",
            f"Stored decision_gates fragment fails its model: {key!r} is not a list.",
        )
    return value


def _read_gates(fragment: object, *, run_id: str) -> DecisionGatesRead:
    """Build a DecisionGatesRead from the stored decision_gates fragment.

    Same shape rule as :func:`_read_robustness`: writers store
    ``{"registrations": [...], "evaluations": [...]}`` with no
    top-level ``run_id``; each item is validated on its own model
    and ``run_id`` is injected, as the gates read path does.
    """
    if not isinstance(fragment, dict):
        raise NarrativeError(
            "narrative_corrupt_fragment",
            "Stored decision_gates fragment fails its model: expected a JSON object.",
        )
    try:
        return DecisionGatesRead(
            run_id=run_id,
            registrations=[
                GateRegistration.model_validate(item)
                for item in _read_gates_list(fragment, "registrations")
            ],
            evaluations=[
                GateEvaluation.model_validate(item)
                for item in _read_gates_list(fragment, "evaluations")
            ],
        )
    except ValidationError as exc:
        raise _corrupt("decision_gates", exc) from exc


def _lower_tail_shortfall(
    expected_shortfall: ExpectedShortfallResult | None, arm: str
) -> tuple[float | None, float | None]:
    """Lower-tail expected shortfall for one arm, if stored.

    Only the lower tail counts: derivation's loss-probability
    primary already assumes lower-is-worse, and an upper-tail
    shortfall answers a different question. Returns
    ``(value, alpha)`` or ``(None, None)``.
    """
    if expected_shortfall is None or expected_shortfall.tail != "lower":
        return None, None
    detail = getattr(expected_shortfall, arm)
    return detail.value, expected_shortfall.alpha


class NarrativeService:
    """Generates, lists, reads, and optionally polishes narratives."""

    def __init__(
        self,
        settings: Settings,
        openai_service: OpenAIService | None = None,
        llm_port: SkillLLMPort | None = None,
        branch_runner: BranchRunner | None = None,
    ) -> None:
        self.settings = settings
        if llm_port is not None:
            self._port: SkillLLMPort = llm_port
        elif openai_service is not None:
            self._port = OpenAIServiceSkillPort(openai_service)
        else:
            self._port = _NoLLMPort()  # type: ignore[assignment]
        self._branch_runner: BranchRunner = (
            branch_runner if branch_runner is not None else _NoBranchRunner()
        )

    # -- generation ------------------------------------------------------

    async def generate(
        self, session: AsyncSession, run_id: str, request: NarrativeGenerateRequest
    ) -> DecisionNarrativeRead:
        anchor = await session.get(SimulationRun, run_id)
        if anchor is None:
            raise LookupError(f"Simulation run {run_id} was not found.")
        if anchor.status != SimulationRunStatus.COMPLETED.value:
            raise NarrativeError(
                "narrative_requires_completed_run",
                "Narrative generation requires a completed anchor run.",
            )
        tree, validation = self._read_mece(anchor)
        anchor_deliberations = self._read_deliberations(anchor)
        definitions, mapping_ids = await self._resolve_definitions(session, anchor, request)
        direction_inputs = [
            await self._assemble_direction(session, definition, anchor_deliberations)
            for definition in definitions
        ]
        loop_context = await self._read_loop(session, request.loop_id, anchor.id)
        calibration_context = await self._read_calibration(session, anchor.domain_id)
        composed = compose_narrative(
            NarrativeInputs(
                anchor_run_id=anchor.id,
                domain_id=anchor.domain_id,
                request_topic=request.topic,
                mece_tree=tree,
                mece_validation=validation,
                directions=direction_inputs,
                calibration_context=calibration_context,
                loop_context=loop_context,
            )
        )
        body_dump = composed.body.model_dump(mode="json")
        input_pins = dict(composed.input_pins)
        if mapping_ids:
            # Only when mappings were used: inline-definition
            # generations keep their Sprint 13 input pins byte-identical.
            input_pins["direction_mapping_ids"] = mapping_ids
        max_version = (
            await session.execute(
                select(func.coalesce(func.max(DecisionNarrativeRecord.version), 0)).where(
                    DecisionNarrativeRecord.run_id == anchor.id
                )
            )
        ).scalar_one()
        record = DecisionNarrativeRecord(
            run_id=anchor.id,
            version=int(max_version) + 1,
            topic=composed.body.topic,
            inputs_hash=sha256_hash(input_pins),
            content_hash=sha256_hash(body_dump),
            artifact=body_dump,
            direction_mapping_ids=mapping_ids or None,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return self._to_read(record, polish=None)

    async def _assemble_direction(
        self,
        session: AsyncSession,
        definition: DirectionDefinition,
        anchor_deliberations: list[SkillDeliberationRecord],
    ) -> DirectionInputs:
        source = await session.get(SimulationRun, definition.source_run_id)
        if source is None:
            raise NarrativeError(
                "narrative_unknown_source_run",
                f"Direction {definition.name!r} names unknown source run "
                f"{definition.source_run_id!r}.",
            )
        if source.status != SimulationRunStatus.COMPLETED.value:
            raise NarrativeError(
                "narrative_source_run_not_completed",
                f"Direction {definition.name!r} draws on run "
                f"{definition.source_run_id!r}, which is not completed.",
            )
        summary = source.summary or {}
        ensemble_fragment = summary.get(MONTE_CARLO_SUMMARY_KEY)
        if ensemble_fragment is None:
            raise NarrativeError(
                "narrative_requires_ensemble",
                f"Direction {definition.name!r} draws on run "
                f"{definition.source_run_id!r}, which has no stored ensemble. "
                f"Run POST /runs/{definition.source_run_id}/monte-carlo first.",
            )
        try:
            ensemble = MonteCarloResult.model_validate(ensemble_fragment)
        except ValidationError as exc:
            raise _corrupt("monte_carlo", exc) from exc
        robustness: RobustnessRead | None = None
        robustness_fragment = summary.get(ROBUSTNESS_SUMMARY_KEY)
        if robustness_fragment is not None:
            robustness = _read_robustness(
                robustness_fragment, run_id=source.id, ensemble_id=ensemble.ensemble_id
            )
        gates: DecisionGatesRead | None = None
        gates_fragment = summary.get(DECISION_GATES_SUMMARY_KEY)
        if gates_fragment is not None:
            gates = _read_gates(gates_fragment, run_id=source.id)
        return DirectionInputs(
            definition=definition,
            ensemble=ensemble,
            tornado=robustness.tornado if robustness else None,
            threshold_search=robustness.threshold_search if robustness else None,
            expected_shortfall=robustness.expected_shortfall if robustness else None,
            bootstrap=robustness.bootstrap if robustness else None,
            gates=gates,
            deliberations=self._read_deliberations(source),
            anchor_deliberations=anchor_deliberations,
        )

    def _read_mece(
        self, run: SimulationRun
    ) -> tuple[DecompositionTree | None, MeceValidationResult | None]:
        fragment = (run.configuration or {}).get(_MECE_CONFIGURATION_KEY)
        if fragment is None:
            return None, None
        try:
            tree = DecompositionTree.model_validate(fragment["decomposition"])
            validation = MeceValidationResult.model_validate(fragment["validation"])
        except (ValidationError, KeyError, TypeError) as exc:
            raise NarrativeError(
                "narrative_corrupt_fragment",
                f"Stored mece fragment fails its model: {exc}",
            ) from exc
        return tree, validation

    def _read_deliberations(self, run: SimulationRun) -> list[SkillDeliberationRecord]:
        stored = (run.summary or {}).get(SKILL_DELIBERATIONS_SUMMARY_KEY) or []
        try:
            return [SkillDeliberationRecord.model_validate(item) for item in stored]
        except ValidationError as exc:
            raise _corrupt("skill_deliberations", exc) from exc

    async def _read_loop(
        self, session: AsyncSession, loop_id: str | None, anchor_run_id: str
    ) -> LoopContextInput | None:
        if loop_id is None:
            return None
        row = await session.get(StrategyLoopRecord, loop_id)
        if row is None:
            raise NarrativeError(
                "narrative_loop_not_found",
                f"Loop {loop_id!r} was not found.",
            )
        if row.baseline_run_id != anchor_run_id:
            raise NarrativeError(
                "narrative_loop_baseline_mismatch",
                f"Loop {loop_id!r} baselines run {row.baseline_run_id!r}, "
                f"not the anchor run {anchor_run_id!r}.",
            )
        try:
            registrations = [
                TriggerRegistration.model_validate(item) for item in (row.triggers or [])
            ]
        except ValidationError as exc:
            raise _corrupt("loop triggers", exc) from exc
        registration = select_registration(registrations)
        return LoopContextInput(
            loop_id=row.id,
            loop_name=row.name,
            registration_id=registration.id if registration else None,
            triggers=list(registration.triggers) if registration else [],
        )

    async def _read_calibration(
        self, session: AsyncSession, domain_id: str
    ) -> list[CalibrationContextEntry]:
        result = await session.execute(
            select(CalibrationFitRecord)
            .where(CalibrationFitRecord.domain_id == domain_id)
            .order_by(CalibrationFitRecord.created_at.desc(), CalibrationFitRecord.id.desc())
            .limit(MAX_CALIBRATION_FITS_IN_CONTEXT)
        )
        return [
            CalibrationContextEntry(
                fit_id=row.id,
                kind=row.kind,
                loo_rmse=row.loo_rmse,
                inputs_hash=row.inputs_hash,
                calibrated_template_id=row.calibrated_template_id,
                n_observations=row.n_observations,
                created_at=row.created_at.isoformat(),
            )
            for row in result.scalars().all()
        ]

    async def _resolve_definitions(
        self,
        session: AsyncSession,
        anchor: SimulationRun,
        request: NarrativeGenerateRequest,
    ) -> tuple[list[DirectionDefinition], list[str]]:
        """Resolve generation directions: inline wins, else mappings.

        Returns ``(definitions, mapping_ids_used)``. When the request
        omits ``directions`` and no stored mappings exist, refuses
        with a named code pointing at the derive endpoint.
        """
        if request.directions is not None:
            return list(request.directions), []
        rows = (await self._mapping_rows(session, anchor.id, active_only=True))[:MAX_DIRECTIONS]
        if not rows:
            raise NarrativeError(
                "narrative_requires_directions",
                f"No direction definitions were provided and no stored "
                f"direction mappings exist for run {anchor.id!r}. Provide "
                f'"directions" in the request or run POST '
                f"/runs/{anchor.id}/directions/derive first.",
            )
        return [
            DirectionDefinition(
                name=row.name,
                source_run_id=row.source_run_id,
                arm=cast(Literal["baseline", "strategy"], row.arm),
                mece_branches=list(row.mece_branches),
                deliberation_id=row.deliberation_id,
            )
            for row in rows
        ], [row.id for row in rows]

    # -- derivation + mappings (Sprint 14) ---------------------------------

    async def derive(self, session: AsyncSession, run_id: str) -> DerivationRead:
        """Derive directions from the anchor run's scenario family.

        Explicit trigger only: derivation never runs automatically
        and never creates simulation runs or ensembles. Produced
        directions are upserted by name; a user-edited mapping of
        the same name is never overwritten (no-clobber rule) and
        the outcome is reported as ``skipped``.
        """
        anchor = await session.get(SimulationRun, run_id)
        if anchor is None:
            raise LookupError(f"Simulation run {run_id} was not found.")
        if anchor.status != SimulationRunStatus.COMPLETED.value:
            raise DirectionError(
                "direction_requires_completed_run",
                "Direction derivation requires a completed anchor run.",
            )
        family = await self._family_runs(session, anchor)
        candidates = await self._assemble_candidates(session, family)
        if not candidates:
            raise DirectionError(
                "direction_no_ensemble",
                f"No run in the scenario family of {run_id!r} has a stored "
                f"ensemble. Run POST /runs/{run_id}/monte-carlo first.",
            )
        derived = derive_directions(anchor.id, candidates)
        derivation_hash = sha256_hash(derived.model_dump(mode="json"))
        existing = {row.name: row for row in await self._mapping_rows(session, anchor.id)}
        next_position = max((row.position for row in existing.values()), default=-1) + 1
        definitions = {definition.name: definition for definition in derived.directions}
        outcomes: list[DerivationRuleOutcome] = []
        for outcome in derived.outcomes:
            if outcome.status != "produced" or outcome.direction_name is None:
                outcomes.append(outcome)
                continue
            definition = definitions[outcome.direction_name]
            row = existing.get(outcome.direction_name)
            if row is not None and row.user_edited:
                outcomes.append(
                    outcome.model_copy(
                        update={
                            "status": "skipped",
                            "reason": (
                                f"A user-edited mapping named "
                                f"{outcome.direction_name!r} exists; left untouched."
                            ),
                        }
                    )
                )
                continue
            if row is not None and row.status != "active":
                # Option C: derive never overwrites a pending or
                # rejected proposal either — the no-clobber rule
                # extends to proposal rows, which only an explicit
                # human accept/reject/delete may resolve.
                outcomes.append(
                    outcome.model_copy(
                        update={
                            "status": "skipped",
                            "reason": (
                                f"A {row.status} mapping named "
                                f"{outcome.direction_name!r} exists; left untouched."
                            ),
                        }
                    )
                )
                continue
            if row is not None and row.origin == "override":
                # Option B: derive never overwrites an override
                # direction either — the row pins a human-authored
                # override spec and the scenario-branch run it
                # created, which only an explicit human edit/delete
                # may resolve.
                outcomes.append(
                    outcome.model_copy(
                        update={
                            "status": "skipped",
                            "reason": (
                                "An override direction named "
                                f"{outcome.direction_name!r} exists; left untouched."
                            ),
                        }
                    )
                )
                continue
            rule_record = outcome.model_dump(mode="json")
            rule_record["derivation_hash"] = derivation_hash
            rule_record["rules_version"] = DERIVATION_RULES_VERSION
            if row is not None:
                row.source_run_id = definition.source_run_id
                row.arm = definition.arm
                row.mece_branches = []
                row.deliberation_id = None
                row.origin = "derived"
                row.rule_id = outcome.rule_id
                row.rules_version = DERIVATION_RULES_VERSION
                row.rule_record = rule_record
            else:
                session.add(
                    DirectionMappingRecord(
                        anchor_run_id=anchor.id,
                        name=definition.name,
                        source_run_id=definition.source_run_id,
                        arm=definition.arm,
                        mece_branches=[],
                        deliberation_id=None,
                        origin="derived",
                        rule_id=outcome.rule_id,
                        rules_version=DERIVATION_RULES_VERSION,
                        rule_record=rule_record,
                        user_edited=False,
                        position=next_position,
                    )
                )
                next_position += 1
            outcomes.append(outcome)
        await session.commit()
        rows = await self._mapping_rows(session, anchor.id)
        return DerivationRead(
            anchor_run_id=anchor.id,
            rules_version=DERIVATION_RULES_VERSION,
            derivation_hash=derivation_hash,
            family_size=len(family),
            candidates_considered=len(candidates),
            outcomes=outcomes,
            mappings=[self._mapping_to_read(row) for row in rows],
        )

    async def _family_runs(
        self, session: AsyncSession, anchor: SimulationRun
    ) -> list[SimulationRun]:
        """Root ancestor + all descendants (Sprint 10 family rule).

        Walks up the ``parent_run_id`` chain to the root (a dangling
        parent or a cycle stops the walk), then descends breadth-first.
        Returns runs sorted by id for deterministic behavior.
        """
        seen = {anchor.id}
        current = anchor
        while current.parent_run_id is not None:
            parent = await session.get(SimulationRun, current.parent_run_id)
            if parent is None or parent.id in seen:
                break
            seen.add(parent.id)
            current = parent
        family = {current.id: current}
        frontier = [current.id]
        while frontier:
            result = await session.execute(
                select(SimulationRun).where(SimulationRun.parent_run_id.in_(frontier))
            )
            frontier = []
            for child in result.scalars().all():
                if child.id not in family:
                    family[child.id] = child
                    frontier.append(child.id)
        return [family[run_id] for run_id in sorted(family)]

    async def _assemble_candidates(
        self, session: AsyncSession, runs: list[SimulationRun]
    ) -> list[DerivationCandidate]:
        """One candidate per (COMPLETED run with ensemble, arm)."""
        candidates: list[DerivationCandidate] = []
        for run in runs:
            if run.status != SimulationRunStatus.COMPLETED.value:
                continue
            summary = run.summary or {}
            ensemble_fragment = summary.get(MONTE_CARLO_SUMMARY_KEY)
            if ensemble_fragment is None:
                continue
            try:
                ensemble = MonteCarloResult.model_validate(ensemble_fragment)
            except ValidationError as exc:
                raise _direction_corrupt("monte_carlo", exc) from exc
            # Derivation reads ONLY the expected_shortfall sub-fragment,
            # validated on its own model. It deliberately does NOT
            # validate the whole robustness fragment against
            # RobustnessRead: the stored fragment has no top-level
            # run_id (writers store per-analysis sub-fragments), so
            # whole-fragment validation always fails — the Sprint 13
            # bug in _assemble_direction, fixed in fix batch 1 by
            # reading sub-fragments the same way. Other
            # sub-fragments (tornado, bootstrap, ...) are irrelevant
            # to derivation and are not read here.
            expected_shortfall: ExpectedShortfallResult | None = None
            robustness_fragment = summary.get(ROBUSTNESS_SUMMARY_KEY)
            if isinstance(robustness_fragment, dict):
                es_fragment = robustness_fragment.get("expected_shortfall")
                if es_fragment is not None:
                    try:
                        expected_shortfall = ExpectedShortfallResult.model_validate(es_fragment)
                    except ValidationError as exc:
                        raise _direction_corrupt("expected_shortfall", exc) from exc
            for arm in ("baseline", "strategy"):
                arm_summary = getattr(ensemble, arm)
                es_value, es_alpha = _lower_tail_shortfall(expected_shortfall, arm)
                candidates.append(
                    DerivationCandidate(
                        run_id=run.id,
                        arm=cast(Literal["baseline", "strategy"], arm),
                        ensemble_id=ensemble.ensemble_id,
                        p50=arm_summary.p50,
                        p_loss=arm_summary.p_loss,
                        expected_shortfall=es_value,
                        expected_shortfall_alpha=es_alpha,
                    )
                )
        return candidates

    # -- LLM proposals (option C) ------------------------------------------

    async def propose(
        self, session: AsyncSession, run_id: str, request: DirectionProposeRequest
    ) -> DirectionProposeRead:
        """Run one LLM proposal pass over the anchor run's artifacts.

        Explicit trigger only: proposing never runs automatically.
        Refusals that need no LLM call (missing/non-completed anchor,
        no MECE tree, no ensemble in the family) happen BEFORE the
        port is touched. The LLM's output is then grounding-validated
        as a whole: any proposal naming a non-existent MECE branch,
        scenario-family run, or variable — or a gate on an unbound
        variable — refuses the entire request before any row is
        written (refuse, not flag — a hallucinated reference
        impeaches the whole proposal set, and proposing is cheap,
        explicit, and retryable). Proposals that pass validation are
        stored as ``proposed`` mappings; a proposal whose name is
        already taken is reported ``skipped`` and the existing row
        is left untouched — proposals never overwrite anything,
        including user-edited mappings.
        """
        anchor = await session.get(SimulationRun, run_id)
        if anchor is None:
            raise LookupError(f"Simulation run {run_id} was not found.")
        if anchor.status != SimulationRunStatus.COMPLETED.value:
            raise DirectionError(
                "direction_requires_completed_run",
                "Direction proposals require a completed anchor run.",
            )
        try:
            tree, _validation = self._read_mece(anchor)
        except NarrativeError as exc:
            raise DirectionError("direction_corrupt_fragment", str(exc)) from exc
        if tree is None:
            raise DirectionError(
                "direction_proposal_requires_tree",
                "Direction proposals must trace to MECE branches, but the "
                f"anchor run {run_id!r} has no stored MECE tree.",
            )
        if not tree.root.children:
            # An empty tree (a root that does not decompose) cannot
            # ground any proposal: _collect_branches includes the
            # root, so without this check a proposal tracing only to
            # the root name would pass grounding and be stored. The
            # creation gate refuses empty trees, so this is reachable
            # only via a directly rewritten or legacy fragment — but
            # the refusal is the same named code, before any LLM call.
            raise DirectionError(
                "direction_proposal_requires_tree",
                "Direction proposals must trace to MECE branches, but the "
                f"anchor run {run_id!r} has a stored MECE tree with no "
                "branches (the root scope is not decomposed).",
            )
        family = await self._family_runs(session, anchor)
        candidates = await self._assemble_candidates(session, family)
        if not candidates:
            raise DirectionError(
                "direction_no_ensemble",
                f"No run in the scenario family of {run_id!r} has a stored "
                f"ensemble. Run POST /runs/{run_id}/monte-carlo first.",
            )
        variables = self._read_anchor_variables(anchor)
        family_runs = self._proposal_family_runs(family, candidates)
        context = ProposalContext(
            topic=tree.topic or f"run {anchor.id}",
            branches=_collect_branches(tree),
            family_runs=family_runs,
            variables=variables,
            guidance=request.guidance,
        )
        try:
            proposals, model = await propose_directions(
                self._port, build_proposal_user_content(context)
            )
        except SkillLLMUnavailable as exc:
            raise DirectionError("direction_propose_unavailable", str(exc)) from exc
        except SkillTruncatedError as exc:
            raise DirectionError("direction_propose_truncated", str(exc)) from exc
        except SkillContractError as exc:
            raise DirectionError("direction_propose_contract_failed", str(exc)) from exc
        proposal_hash = sha256_hash(proposals.model_dump(mode="json"))
        family_by_id = {run.id: run for run in family}
        self._validate_proposals(
            family_by_id, {variable.id for variable in variables}, tree, proposals
        )
        existing = {row.name: row for row in await self._mapping_rows(session, anchor.id)}
        next_position = max((row.position for row in existing.values()), default=-1) + 1
        staged: list[tuple[DirectionProposal, DirectionMappingRecord | None]] = []
        for proposal in proposals.proposals:
            row = existing.get(proposal.name)
            if row is not None:
                staged.append((proposal, None))
                continue
            record = DirectionMappingRecord(
                anchor_run_id=anchor.id,
                name=proposal.name,
                source_run_id=proposal.source_run_id,
                arm=proposal.arm,
                mece_branches=list(proposal.mece_branches),
                deliberation_id=None,
                origin="llm_proposal",
                rule_id=None,
                rules_version=None,
                rule_record=None,
                status="proposed",
                proposal_record={
                    "rationale": proposal.rationale,
                    "key_variables": list(proposal.key_variables),
                    "gates": [gate.model_dump(mode="json") for gate in proposal.gates],
                    "model": model,
                    "template_id": PROPOSAL_TEMPLATE_ID,
                    "template_version": PROPOSAL_TEMPLATE_VERSION,
                    "proposal_hash": proposal_hash,
                },
                user_edited=False,
                position=next_position,
            )
            session.add(record)
            next_position += 1
            staged.append((proposal, record))
        await session.flush()
        outcomes: list[ProposalOutcome] = []
        for proposal, stored in staged:
            if stored is None:
                existing_row = existing[proposal.name]
                outcomes.append(
                    ProposalOutcome(
                        name=proposal.name,
                        status="skipped",
                        reason=(
                            f"A mapping named {proposal.name!r} already exists "
                            f"(origin {existing_row.origin}, status "
                            f"{existing_row.status}); left untouched."
                        ),
                        mapping_id=None,
                        source_run_id=proposal.source_run_id,
                        arm=proposal.arm,
                        mece_branches=list(proposal.mece_branches),
                    )
                )
            else:
                outcomes.append(
                    ProposalOutcome(
                        name=proposal.name,
                        status="stored",
                        reason="Proposal passed grounding validation and awaits review.",
                        mapping_id=stored.id,
                        source_run_id=proposal.source_run_id,
                        arm=proposal.arm,
                        mece_branches=list(proposal.mece_branches),
                    )
                )
        await session.commit()
        rows = await self._mapping_rows(session, anchor.id)
        return DirectionProposeRead(
            anchor_run_id=anchor.id,
            template_id=PROPOSAL_TEMPLATE_ID,
            template_version=PROPOSAL_TEMPLATE_VERSION,
            model=model,
            proposal_hash=proposal_hash,
            family_runs_considered=len(family_runs),
            outcomes=outcomes,
            mappings=[self._mapping_to_read(row) for row in rows],
        )

    def _validate_proposals(
        self,
        family_by_id: dict[str, SimulationRun],
        variable_ids: set[str],
        tree: DecompositionTree,
        proposals: DirectionProposals,
    ) -> None:
        """Ground every proposal against stored artifacts, or refuse all.

        Runs synchronously: every check reads already-loaded state
        (family runs, the anchor tree, the anchor's variable ids).
        The first failure refuses the whole request — nothing is
        written, including valid proposals in the same set.
        """
        valid_branches = [name for name, _scope in _collect_branches(tree)]
        for proposal in proposals.proposals:
            source = family_by_id.get(proposal.source_run_id)
            if source is None:
                raise DirectionError(
                    "direction_proposal_unknown_source_run",
                    f"Proposal {proposal.name!r} names source run "
                    f"{proposal.source_run_id!r}, which is not in the anchor "
                    f"run's scenario family. Valid runs: "
                    f"{', '.join(sorted(family_by_id))}.",
                )
            if source.status != SimulationRunStatus.COMPLETED.value:
                raise DirectionError(
                    "direction_proposal_source_run_not_completed",
                    f"Proposal {proposal.name!r} draws on run "
                    f"{proposal.source_run_id!r}, which is not completed.",
                )
            ensemble_fragment = (source.summary or {}).get(MONTE_CARLO_SUMMARY_KEY)
            if ensemble_fragment is None:
                raise DirectionError(
                    "direction_proposal_source_run_no_ensemble",
                    f"Proposal {proposal.name!r} draws on run "
                    f"{proposal.source_run_id!r}, which has no stored ensemble. "
                    f"Run POST /runs/{proposal.source_run_id}/monte-carlo first.",
                )
            try:
                MonteCarloResult.model_validate(ensemble_fragment)
            except ValidationError as exc:
                raise _direction_corrupt("monte_carlo", exc) from exc
            for branch in proposal.mece_branches:
                if branch not in valid_branches:
                    raise DirectionError(
                        "direction_proposal_unknown_mece_branch",
                        f"Proposal {proposal.name!r} names unknown MECE branch "
                        f"{branch!r}. Valid branches: "
                        f"{', '.join(valid_branches) or '(none)'}",
                    )
            for variable_id in proposal.key_variables:
                if variable_id not in variable_ids:
                    raise DirectionError(
                        "direction_proposal_unknown_variable",
                        f"Proposal {proposal.name!r} names unknown variable "
                        f"{variable_id!r}. Valid variables: "
                        f"{', '.join(sorted(variable_ids)) or '(none)'}",
                    )
            for gate in proposal.gates:
                if gate.variable_id not in variable_ids:
                    raise DirectionError(
                        "direction_proposal_unknown_gate_variable",
                        f"Proposal {proposal.name!r} has a gate on unknown "
                        f"variable {gate.variable_id!r}. Valid variables: "
                        f"{', '.join(sorted(variable_ids)) or '(none)'}",
                    )

    async def override(
        self, session: AsyncSession, run_id: str, request: DirectionOverrideRequest
    ) -> DirectionOverrideRead:
        """Create scenario-branch runs from variable overrides (option B).

        Each direction names fixed values for variables bound on the
        anchor run. The whole request is grounded and validated
        BEFORE any branch is created: the anchor must be completed
        and branchable, every override id must already be bound on
        the anchor, every MECE branch must exist on the anchor's
        tree, the merged variable set must pass the run-creation
        validation gate, and a state snapshot must exist at each
        direction's fork step. Any failure refuses the whole
        request with zero runs created.

        Directions whose name already has a mapping are skipped
        (no-clobber): no branch run is created for them and the
        existing row is left untouched. The remaining directions
        each create one scenario branch via the configured branch
        runner; a branch failure is reported per direction and
        leaves the others unaffected. A runner that fails AFTER
        committing reports the committed branch, which is
        discarded so no orphan row survives. A concurrent request
        that commits the same name first wins: the loser is
        ``skipped`` (its branch discarded), never a 500 — the
        mapping unique constraint arbitrates, with no locking.
        Stored directions are
        ``active`` mappings with origin ``override`` and the
        override spec pinned in ``override_record``. The child
        runs have no ensemble yet — narrative generation refuses
        until one exists — and each stored outcome names the
        monte-carlo endpoint to run.
        """
        anchor = await session.get(SimulationRun, run_id)
        if anchor is None:
            raise LookupError(f"Run {run_id!r} not found")
        if anchor.status != SimulationRunStatus.COMPLETED.value:
            raise DirectionError(
                "direction_requires_completed_run",
                "Variable-override directions require a completed anchor run.",
            )
        self._check_override_domain(anchor)
        bindings = self._read_anchor_bindings(anchor)
        if bindings is None or not bindings.variables:
            raise DirectionError(
                "direction_override_requires_bindings",
                "Variable-override directions require variables bound on "
                "the anchor run; none were found in its configuration.",
            )
        try:
            tree, _validation = self._read_mece(anchor)
        except NarrativeError as exc:
            raise DirectionError("direction_corrupt_fragment", str(exc)) from exc
        valid_branches = (
            [name for name, _scope in _collect_branches(tree)] if tree is not None else []
        )
        root_scope = list(tree.root.scope) if tree is not None else None
        # Capture primitives now: branch creation commits and
        # expires the anchor row.
        anchor_id = anchor.id
        anchor_tick_count = anchor.tick_count

        override_hash = sha256_hash(request.model_dump(mode="json"))
        prepared: list[tuple[DirectionOverrideSpec, VariableSet, int]] = []
        for spec in request.directions:
            for branch in spec.mece_branches:
                if tree is None:
                    raise DirectionError(
                        "direction_mece_branches_without_tree",
                        f"Direction {spec.name!r} names MECE branches but "
                        "the anchor run has no decomposition tree.",
                    )
                if branch not in valid_branches:
                    raise DirectionError(
                        "direction_unknown_mece_branch",
                        f"Direction {spec.name!r} names unknown MECE branch "
                        f"{branch!r}. Valid branches: "
                        f"{', '.join(valid_branches) or '(none)'}",
                    )
            override_set = build_override_set(bindings, spec.overrides)
            merged = validate_merged_overrides(bindings, override_set, root_scope)
            fork_step = (
                spec.fork_step if spec.fork_step is not None else max(1, anchor_tick_count // 2)
            )
            if not await self._snapshot_exists(session, anchor_id, fork_step):
                raise DirectionError(
                    "direction_override_no_snapshot",
                    f"No state snapshot found at fork step {fork_step} for run {anchor_id!r}.",
                )
            prepared.append((spec, merged, fork_step))

        if not self._branch_runner.is_available():
            # Grounding passed, but branch creation is not wired:
            # refuse the whole request (503 via the route) with
            # zero branches created, rather than failing each
            # direction in turn.
            raise DirectionError(
                "direction_override_unavailable",
                "No branch runner is configured for variable-override directions.",
            )

        existing = {row.name: row for row in await self._mapping_rows(session, anchor_id)}
        staged: list[
            tuple[DirectionOverrideSpec, BranchResult | None, str | None, str | None, int]
        ] = []
        for spec, merged, fork_step in prepared:
            if spec.name in existing:
                staged.append((spec, None, None, "collision", fork_step))
                continue
            try:
                result = await self._branch_runner.create_branch(
                    session,
                    anchor_id,
                    BranchRequest(
                        fork_step=fork_step,
                        variable_set=merged,
                        assumptions=[assumption_line(spec.name, spec.overrides)],
                        resample_variables=spec.resample_variables,
                    ),
                )
            except BranchCreationFailed as exc:
                # The runner committed a branch it could not
                # report: roll back our session state, then
                # discard the committed branch so no orphan row
                # survives. A discard failure is reported in the
                # reason, with the branch id, for explicit human
                # cleanup; it never masks the original failure.
                await session.rollback()
                discarded = False
                if exc.branch_id is not None:
                    discarded = await self._discard_branch_best_effort(
                        session, exc.branch_id
                    )
                if exc.branch_id is None:
                    problem = (
                        f"Branch creation failed after commit: {exc}. "
                        "No branch identity was reported, so nothing "
                        "could be discarded."
                    )
                elif discarded:
                    problem = (
                        f"Branch creation failed after commit: {exc}. "
                        f"The committed branch {exc.branch_id} was discarded."
                    )
                else:
                    problem = (
                        f"Branch creation failed after commit: {exc}. "
                        f"The committed branch {exc.branch_id} could not be "
                        "discarded; it needs explicit cleanup."
                    )
                staged.append((spec, None, None, problem, fork_step))
                continue
            except Exception as exc:  # noqa: BLE001 — per-direction isolation
                # A plain runner failure means nothing committed;
                # roll back so a failed branch leaves no orphan rows.
                await session.rollback()
                staged.append((spec, None, None, f"Branch creation failed: {exc}", fork_step))
                continue
            child = await session.get(SimulationRun, result.run_id)
            staged.append(
                (spec, result, child.status if child is not None else None, None, fork_step)
            )

        outcomes = await self._store_override_records(
            session, anchor_id, staged, override_hash
        )
        rows = await self._mapping_rows(session, anchor_id)
        return DirectionOverrideRead(
            anchor_run_id=anchor_id,
            override_hash=override_hash,
            directions_considered=len(request.directions),
            outcomes=outcomes,
            mappings=[self._mapping_to_read(row) for row in rows],
        )

    async def refork_override_mapping(
        self,
        session: AsyncSession,
        run_id: str,
        mapping_id: str,
        request: DirectionOverrideReforkRequest,
    ) -> DirectionOverrideReforkRead:
        """Re-fork one stored override mapping with new fixed values.

        A stored override mapping's fixed values are baked into its
        branch run, so silently rewriting the pinned
        ``override_record`` would lie about what the branch
        contains. "Editing" the values therefore creates a NEW
        scenario-branch run with the new values and repoints the
        SAME mapping (same id, name, and position) at it; the old
        branch run and its rows are left untouched (append-only
        history — the old run stays visible in scenario-compare).

        Only ``origin == "override"`` + ``status == "active"``
        mappings can be reforked. Grounding is identical to
        :meth:`override` (stored bindings only, no range check,
        snapshot must exist at the fork step) and refuses the
        whole request before any branch is created. A runner
        failure after commit reuses the hardening mechanism: the
        new branch is discarded and the failure names the branch
        id. If the mapping was deleted concurrently between the
        read and the repoint, the new branch is discarded and a
        named conflict surfaces instead of a 500. No other
        mapping is touched.
        """
        row = await self._mapping_for_run(session, run_id, mapping_id)
        if row.origin != "override":
            raise DirectionError(
                "direction_mapping_not_override",
                f"Mapping {row.name!r} has origin {row.origin!r}; only "
                "variable-override mappings can be re-forked.",
            )
        if row.status != "active":
            raise DirectionError(
                "direction_mapping_not_active",
                f"Mapping {row.name!r} has status {row.status!r}; only "
                "active mappings can be re-forked.",
            )
        anchor = await self._completed_anchor(session, run_id)
        self._check_override_domain(anchor)
        bindings = self._read_anchor_bindings(anchor)
        if bindings is None or not bindings.variables:
            raise DirectionError(
                "direction_override_requires_bindings",
                "Variable-override directions require variables bound on "
                "the anchor run; none were found in its configuration.",
            )
        try:
            tree, _validation = self._read_mece(anchor)
        except NarrativeError as exc:
            raise DirectionError("direction_corrupt_fragment", str(exc)) from exc
        root_scope = list(tree.root.scope) if tree is not None else None
        # Capture primitives now: branch creation commits and
        # expires the anchor and mapping rows.
        anchor_id = anchor.id
        anchor_tick_count = anchor.tick_count
        mapping_name = row.name

        override_set = build_override_set(bindings, request.overrides)
        merged = validate_merged_overrides(bindings, override_set, root_scope)
        fork_step = (
            request.fork_step if request.fork_step is not None else max(1, anchor_tick_count // 2)
        )
        if not await self._snapshot_exists(session, anchor_id, fork_step):
            raise DirectionError(
                "direction_override_no_snapshot",
                f"No state snapshot found at fork step {fork_step} for run {anchor_id!r}.",
            )
        override_hash = sha256_hash(request.model_dump(mode="json"))
        # Arm resampling (fix/arm-resample): a refork inherits the
        # stored mapping's setting unless the request states one
        # explicitly; pre-flag records read as False.
        stored_resample = False
        if isinstance(row.override_record, dict):
            stored_resample = bool(row.override_record.get("resample_variables", False))
        resample_variables = (
            request.resample_variables
            if request.resample_variables is not None
            else stored_resample
        )

        if not self._branch_runner.is_available():
            # Grounding passed, but branch creation is not wired:
            # refuse the whole request (503 via the route) with
            # zero branches created, rather than failing after
            # the mapping was read.
            raise DirectionError(
                "direction_override_unavailable",
                "No branch runner is configured for variable-override directions.",
            )

        try:
            result = await self._branch_runner.create_branch(
                session,
                anchor_id,
                BranchRequest(
                    fork_step=fork_step,
                    variable_set=merged,
                    assumptions=[assumption_line(mapping_name, request.overrides)],
                    resample_variables=resample_variables,
                ),
            )
        except BranchCreationFailed as exc:
            # The runner committed a branch it could not report:
            # roll back, discard the committed branch (the
            # hardening mechanism), and report the failure with
            # the branch id — never a bare 500.
            await session.rollback()
            discarded = False
            if exc.branch_id is not None:
                discarded = await self._discard_branch_best_effort(session, exc.branch_id)
            if exc.branch_id is None:
                problem = (
                    f"Branch creation failed after commit: {exc}. "
                    "No branch identity was reported, so nothing could be discarded."
                )
            elif discarded:
                problem = (
                    f"Branch creation failed after commit: {exc}. "
                    f"The committed branch {exc.branch_id} was discarded."
                )
            else:
                problem = (
                    f"Branch creation failed after commit: {exc}. "
                    f"The committed branch {exc.branch_id} could not be "
                    "discarded; it needs explicit cleanup."
                )
            raise DirectionError("direction_override_refork_failed", problem) from exc
        except Exception as exc:
            # A plain runner failure means nothing committed;
            # roll back so no orphan rows survive it, then report
            # the failure as a named refusal, not a 500.
            await session.rollback()
            raise DirectionError(
                "direction_override_refork_failed", f"Branch creation failed: {exc}"
            ) from exc

        child = await session.get(SimulationRun, result.run_id)
        # Re-fetch: branch creation committed, and the mapping
        # may have been deleted concurrently. A vanished row
        # surfaces as a named conflict, and the branch created
        # for it is discarded — it must not survive orphaned.
        current = await session.get(DirectionMappingRecord, mapping_id)
        if current is None or current.anchor_run_id != anchor_id:
            await self._discard_branch_best_effort(session, result.branch_id)
            raise DirectionError(
                "direction_mapping_deleted_concurrently",
                f"Mapping {mapping_name!r} was deleted while its re-fork "
                "was running; the new branch was discarded and nothing "
                "was repointed.",
            )
        current.source_run_id = result.run_id
        current.override_record = {
            "overrides": dict(request.overrides),
            "branch_id": result.branch_id,
            "fork_step": fork_step,
            "override_hash": override_hash,
            "resample_variables": resample_variables,
        }
        # A re-fork is an explicit human edit of the row, like
        # the name/source edit: mark it so.
        current.user_edited = True
        await session.commit()
        await session.refresh(current)
        return DirectionOverrideReforkRead(
            mapping=self._mapping_to_read(current),
            branch_id=result.branch_id,
            child_run_id=result.run_id,
            fork_step=fork_step,
            child_status=child.status if child is not None else None,
            override_hash=override_hash,
            reason=(
                f"Child run {result.run_id} created (branch "
                f"{result.branch_id}, fork step {fork_step}, "
                f"status {child.status if child is not None else None}). "
                "No ensemble yet: run "
                f"POST /runs/{result.run_id}/monte-carlo before "
                "generating from this direction. The previous branch "
                "run was left untouched."
            ),
        )

    async def _discard_branch_best_effort(
        self, session: AsyncSession, branch_id: str
    ) -> bool:
        """Discard one committed branch; a discard failure never raises."""
        try:
            return await self._branch_runner.discard_branch(session, branch_id)
        except Exception:  # noqa: BLE001 — the caller reports the outcome, not this
            return False

    async def _store_override_records(
        self,
        session: AsyncSession,
        anchor_id: str,
        staged: list[
            tuple[DirectionOverrideSpec, BranchResult | None, str | None, str | None, int]
        ],
        override_hash: str,
    ) -> list[DirectionOverrideOutcome]:
        """Store mappings for staged directions, tolerating a same-name race.

        Check-then-insert, with a bounded retry: each pass re-reads
        the anchor's mappings, converts any direction whose name
        appeared meanwhile to ``skipped`` (discarding the branch
        created for it — same no-clobber semantics as the upfront
        name check), and stores the survivors. If the flush/commit
        itself hits the mapping unique constraint, only that
        clash retries; any other integrity error surfaces. Names
        are unique within one request (the request model rejects
        duplicates), so a clash can only come from a concurrent
        commit, which the next pass's re-read sees — each retry
        settles at least one direction, so ``len(staged) + 1``
        attempts always suffice. No locking: the unique
        constraint is the arbiter, and the loser's outcome is
        ``skipped``, never a 500. Outcomes are emitted in
        request order.
        """
        pending = list(staged)
        by_name: dict[str, DirectionOverrideOutcome] = {}
        final_survivors: list[
            tuple[DirectionOverrideSpec, BranchResult, str | None, int]
        ] = []
        final_records: dict[str, DirectionMappingRecord] = {}
        for _attempt in range(len(staged) + 1):
            rows_now = await self._mapping_rows(session, anchor_id)
            existing_now = {row.name: row for row in rows_now}
            next_position = max((row.position for row in rows_now), default=-1) + 1
            survivors: list[tuple[DirectionOverrideSpec, BranchResult, str | None, int]] = []
            for spec, staged_result, child_status, problem, fork_step in pending:
                if problem == "collision":
                    row = existing_now[spec.name]
                    by_name[spec.name] = DirectionOverrideOutcome(
                        name=spec.name,
                        status="skipped",
                        reason=(
                            f"A mapping named {spec.name!r} already exists "
                            f"(origin {row.origin}, status {row.status}); "
                            "no branch run was created; left untouched."
                        ),
                        arm=spec.arm,
                        mece_branches=list(spec.mece_branches),
                    )
                elif problem is not None:
                    by_name[spec.name] = DirectionOverrideOutcome(
                        name=spec.name,
                        status="failed",
                        reason=problem,
                        fork_step=fork_step,
                        arm=spec.arm,
                        mece_branches=list(spec.mece_branches),
                    )
                elif spec.name in existing_now:
                    # A concurrent request committed this name
                    # after our name check: skip, leave the first
                    # row untouched, discard our branch. The
                    # discard commits, but nothing is pending yet
                    # on this pass, so it cannot commit a record.
                    assert staged_result is not None  # staged shape guarantees it
                    row = existing_now[spec.name]
                    discarded = await self._discard_branch_best_effort(
                        session, staged_result.branch_id
                    )
                    if discarded:
                        reason = (
                            f"A mapping named {spec.name!r} was created "
                            f"concurrently (origin {row.origin}, status "
                            f"{row.status}); left untouched. The branch run "
                            f"created for this direction (branch "
                            f"{staged_result.branch_id}) was discarded."
                        )
                    else:
                        reason = (
                            f"A mapping named {spec.name!r} was created "
                            f"concurrently (origin {row.origin}, status "
                            f"{row.status}); left untouched. The branch run "
                            f"created for this direction (branch "
                            f"{staged_result.branch_id}) could not be "
                            "discarded; it needs explicit cleanup."
                        )
                    by_name[spec.name] = DirectionOverrideOutcome(
                        name=spec.name,
                        status="skipped",
                        reason=reason,
                        fork_step=fork_step,
                        arm=spec.arm,
                        mece_branches=list(spec.mece_branches),
                    )
                else:
                    assert staged_result is not None  # staged shape guarantees it
                    survivors.append((spec, staged_result, child_status, fork_step))
            pending = []
            records_by_name: dict[str, DirectionMappingRecord] = {}
            for spec, branch_result, _child_status, fork_step in survivors:
                record = DirectionMappingRecord(
                    anchor_run_id=anchor_id,
                    name=spec.name,
                    source_run_id=branch_result.run_id,
                    arm=spec.arm,
                    mece_branches=list(spec.mece_branches),
                    deliberation_id=None,
                    origin="override",
                    rule_id=None,
                    rules_version=None,
                    rule_record=None,
                    status="active",
                    proposal_record=None,
                    override_record={
                        "overrides": dict(spec.overrides),
                        "branch_id": branch_result.branch_id,
                        "fork_step": fork_step,
                        "override_hash": override_hash,
                        "resample_variables": spec.resample_variables,
                    },
                    user_edited=False,
                    position=next_position,
                )
                session.add(record)
                records_by_name[spec.name] = record
                next_position += 1
            try:
                await session.flush()
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                if not _is_mapping_unique_violation(exc):
                    raise
                pending = [
                    (spec, result, child_status, None, fork_step)
                    for spec, result, child_status, fork_step in survivors
                ]
                continue
            final_survivors = survivors
            final_records = records_by_name
            break
        else:  # pragma: no cover — each retry settles a direction; unreachable
            raise DirectionError(
                "direction_override_store_exhausted",
                "Could not store override directions: repeated concurrent "
                "same-name collisions exhausted the retry bound.",
            )
        stored_rows = {row.name: row for row in await self._mapping_rows(session, anchor_id)}
        for spec, branch_result, child_status, fork_step in final_survivors:
            stored_row = stored_rows.get(spec.name)
            # A concurrent delete between our commit and this
            # re-read must not turn a stored direction into a
            # 500: fall back to the committed record's id.
            mapping_id = (
                stored_row.id if stored_row is not None else final_records[spec.name].id
            )
            by_name[spec.name] = DirectionOverrideOutcome(
                name=spec.name,
                status="stored",
                reason=(
                    f"Child run {branch_result.run_id} created (branch "
                    f"{branch_result.branch_id}, fork step {fork_step}, "
                    f"status {child_status}). No ensemble yet: run "
                    f"POST /runs/{branch_result.run_id}/monte-carlo before "
                    "generating from this direction."
                ),
                mapping_id=mapping_id,
                branch_id=branch_result.branch_id,
                child_run_id=branch_result.run_id,
                fork_step=fork_step,
                child_status=child_status,
                arm=spec.arm,
                mece_branches=list(spec.mece_branches),
            )
        return [by_name[spec.name] for spec, *_rest in staged]

    @staticmethod
    def _check_override_domain(anchor: SimulationRun) -> None:
        """Branchability gates, mirroring scenario branching.

        Military runs need a force-backed baseline; corporate and
        automotive runs need a company; other domains are not
        implemented for branching. The scenario-branch runner
        re-checks these on its own path; the upfront check refuses
        before any work is staged.
        """
        if anchor.domain_id == "military":
            if anchor.force_id is None:
                raise DirectionError(
                    "direction_override_domain_unsupported",
                    "Military variable-override directions require a force-backed baseline run.",
                )
        elif anchor.domain_id in ("corporate", "automotive"):
            if anchor.company_id is None:
                raise DirectionError(
                    "direction_override_domain_unsupported",
                    f"{anchor.domain_id.capitalize()} variable-override directions require a company-backed baseline run.",
                )
        else:
            raise DirectionError(
                "direction_override_domain_unsupported",
                f"Variable-override directions are not implemented for domain {anchor.domain_id}.",
            )

    def _read_anchor_bindings(self, anchor: SimulationRun) -> VariableSet | None:
        """The anchor run's bound variable set (the grounding surface).

        Same fragment and discipline as ``_read_anchor_variables``:
        ``configuration["variables"]["bindings"]``, a ``VariableSet``
        dump. Absent or non-dict fragments mean no bindings; a
        present-but-malformed bindings value is corrupt stored
        data.
        """
        fragment = (anchor.configuration or {}).get("variables")
        if not isinstance(fragment, dict):
            return None
        bindings = fragment.get("bindings")
        if not isinstance(bindings, dict):
            return None
        try:
            return VariableSet.model_validate(bindings)
        except ValidationError as exc:
            raise DirectionError(
                "direction_corrupt_fragment",
                f"Stored variables fragment fails its model: {exc}",
            ) from exc

    @staticmethod
    async def _snapshot_exists(session: AsyncSession, run_id: str, tick: int) -> bool:
        """Whether any state snapshot exists at ``tick`` for the run.

        Same existence check the scenario-branch runner performs
        before forking; the upfront check refuses the whole
        request before any branch is created.
        """
        result = await session.execute(
            select(StateSnapshotRecord.id)
            .where(StateSnapshotRecord.run_id == run_id, StateSnapshotRecord.tick == tick)
            .limit(1)
        )
        return result.scalars().first() is not None

    def _read_anchor_variables(self, anchor: SimulationRun) -> list[ProposalVariable]:
        """Variable ids bound to the anchor run (the grounding surface).

        Mirrors the distributions reader: the fragment is
        ``configuration["variables"]["bindings"]``, a ``VariableSet``
        dump. Absent or non-dict fragments mean no bindings; a
        present-but-malformed bindings value is corrupt stored data.
        """
        fragment = (anchor.configuration or {}).get("variables")
        if not isinstance(fragment, dict):
            return []
        bindings = fragment.get("bindings")
        if not isinstance(bindings, dict):
            return []
        try:
            variable_set = VariableSet.model_validate(bindings)
        except ValidationError as exc:
            raise DirectionError(
                "direction_corrupt_fragment",
                f"Stored variables fragment fails its model: {exc}",
            ) from exc
        return [
            ProposalVariable(id=variable.id, unit=variable.unit, description=variable.description)
            for variable in variable_set.variables
        ]

    @staticmethod
    def _proposal_family_runs(
        family: list[SimulationRun], candidates: list[DerivationCandidate]
    ) -> list[ProposalFamilyRun]:
        """One prompt row per family run that has an ensemble."""
        by_run: dict[str, dict[str, DerivationCandidate]] = {}
        for candidate in candidates:
            by_run.setdefault(candidate.run_id, {})[candidate.arm] = candidate
        parents = {run.id: run.parent_run_id for run in family}
        # The metric name each ensemble measures, read from the
        # already-validated ensemble fragments (_assemble_candidates
        # validated them above): the prompt names the metric so gate
        # bases can cite the stored number they derive from.
        metrics: dict[str, str | None] = {}
        for run in family:
            fragment = (run.summary or {}).get(MONTE_CARLO_SUMMARY_KEY)
            metric = fragment.get("metric") if isinstance(fragment, dict) else None
            metrics[run.id] = metric if isinstance(metric, str) else None
        rows: list[ProposalFamilyRun] = []
        for run_id in sorted(by_run):
            arms = by_run[run_id]
            baseline = arms["baseline"]
            strategy = arms["strategy"]
            rows.append(
                ProposalFamilyRun(
                    run_id=run_id,
                    parent_run_id=parents.get(run_id),
                    ensemble_id=baseline.ensemble_id,
                    baseline_p50=baseline.p50,
                    baseline_p_loss=baseline.p_loss,
                    strategy_p50=strategy.p50,
                    strategy_p_loss=strategy.p_loss,
                    metric=metrics.get(run_id),
                )
            )
        return rows

    async def accept_mapping(
        self, session: AsyncSession, run_id: str, mapping_id: str
    ) -> DirectionMappingRead:
        """Accept a proposed mapping: it becomes usable for generation.

        Re-validates the mapping's references before flipping the
        status — a proposal accepted after its grounding went stale
        refuses and stays ``proposed``. Accepting changes the status
        only: the row's content, origin, and proposal record are
        untouched, and ``user_edited`` is not set by acceptance.
        """
        row = await self._mapping_for_run(session, run_id, mapping_id)
        if row.status != "proposed":
            raise DirectionError(
                "direction_mapping_not_proposed",
                f"Mapping {row.name!r} has status {row.status!r}; only "
                f"proposed mappings can be accepted.",
            )
        anchor = await self._completed_anchor(session, run_id)
        await self._validate_mapping_references(
            session,
            anchor,
            DirectionDefinition(
                name=row.name,
                source_run_id=row.source_run_id,
                arm=cast(Literal["baseline", "strategy"], row.arm),
                mece_branches=list(row.mece_branches),
                deliberation_id=row.deliberation_id,
            ),
        )
        row.status = "active"
        await session.commit()
        await session.refresh(row)
        return self._mapping_to_read(row)

    async def reject_mapping(
        self, session: AsyncSession, run_id: str, mapping_id: str
    ) -> DirectionMappingRead:
        """Reject a proposed mapping: retained for audit, never used.

        Rejection needs no grounding validation — it removes the
        proposal from consideration. The row keeps its content,
        origin, and proposal record; only the status changes.
        Rejected is terminal: the row can only be deleted afterward.
        """
        row = await self._mapping_for_run(session, run_id, mapping_id)
        if row.status != "proposed":
            raise DirectionError(
                "direction_mapping_not_proposed",
                f"Mapping {row.name!r} has status {row.status!r}; only "
                f"proposed mappings can be rejected.",
            )
        row.status = "rejected"
        await session.commit()
        await session.refresh(row)
        return self._mapping_to_read(row)

    # -- mappings ----------------------------------------------------------

    async def list_mappings(self, session: AsyncSession, run_id: str) -> DirectionMappingListRead:
        anchor = await session.get(SimulationRun, run_id)
        if anchor is None:
            raise LookupError(f"Simulation run {run_id} was not found.")
        rows = await self._mapping_rows(session, anchor.id)
        return DirectionMappingListRead(
            run_id=anchor.id,
            mappings=[self._mapping_to_read(row) for row in rows],
        )

    async def create_mapping(
        self,
        session: AsyncSession,
        run_id: str,
        payload: DirectionMappingCreate,
    ) -> DirectionMappingRead:
        anchor = await self._completed_anchor(session, run_id)
        await self._validate_mapping_references(session, anchor, payload)
        await self._check_name_available(session, anchor.id, payload.name)
        rows = await self._mapping_rows(session, anchor.id)
        position = max((row.position for row in rows), default=-1) + 1
        row = DirectionMappingRecord(
            anchor_run_id=anchor.id,
            name=payload.name,
            source_run_id=payload.source_run_id,
            arm=payload.arm,
            mece_branches=list(payload.mece_branches),
            deliberation_id=payload.deliberation_id,
            origin="authored",
            rule_id=None,
            rules_version=None,
            rule_record=None,
            user_edited=False,
            position=position,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return self._mapping_to_read(row)

    async def update_mapping(
        self,
        session: AsyncSession,
        run_id: str,
        mapping_id: str,
        payload: DirectionMappingUpdate,
    ) -> DirectionMappingRead:
        anchor = await self._completed_anchor(session, run_id)
        row = await self._mapping_for_run(session, run_id, mapping_id)
        fields_set = payload.model_fields_set
        merged = DirectionDefinition.model_validate(
            {
                "name": payload.name if "name" in fields_set else row.name,
                "source_run_id": (
                    payload.source_run_id if "source_run_id" in fields_set else row.source_run_id
                ),
                "arm": (
                    payload.arm if "arm" in fields_set and payload.arm is not None else row.arm
                ),
                "mece_branches": (
                    payload.mece_branches
                    if "mece_branches" in fields_set
                    else list(row.mece_branches)
                ),
                "deliberation_id": (
                    payload.deliberation_id
                    if "deliberation_id" in fields_set
                    else row.deliberation_id
                ),
            }
        )
        await self._validate_mapping_references(session, anchor, merged)
        if merged.name != row.name:
            await self._check_name_available(session, anchor.id, merged.name)
        row.name = merged.name
        row.source_run_id = merged.source_run_id
        row.arm = merged.arm
        row.mece_branches = list(merged.mece_branches)
        row.deliberation_id = merged.deliberation_id
        row.user_edited = True
        await session.commit()
        await session.refresh(row)
        return self._mapping_to_read(row)

    async def delete_mapping(self, session: AsyncSession, run_id: str, mapping_id: str) -> None:
        row = await self._mapping_for_run(session, run_id, mapping_id)
        await session.delete(row)
        await session.commit()

    async def _completed_anchor(self, session: AsyncSession, run_id: str) -> SimulationRun:
        anchor = await session.get(SimulationRun, run_id)
        if anchor is None:
            raise LookupError(f"Simulation run {run_id} was not found.")
        if anchor.status != SimulationRunStatus.COMPLETED.value:
            raise DirectionError(
                "direction_requires_completed_run",
                "Direction mappings require a completed anchor run.",
            )
        return anchor

    async def _mapping_rows(
        self,
        session: AsyncSession,
        anchor_run_id: str,
        *,
        active_only: bool = False,
    ) -> list[DirectionMappingRecord]:
        stmt = select(DirectionMappingRecord).where(
            DirectionMappingRecord.anchor_run_id == anchor_run_id
        )
        if active_only:
            # Generation resolves only active rows: proposed rows
            # await human review and rejected rows are audit-only.
            stmt = stmt.where(DirectionMappingRecord.status == "active")
        stmt = stmt.order_by(DirectionMappingRecord.position.asc(), DirectionMappingRecord.id.asc())
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def _mapping_for_run(
        self, session: AsyncSession, run_id: str, mapping_id: str
    ) -> DirectionMappingRecord:
        row = await session.get(DirectionMappingRecord, mapping_id)
        if row is None or row.anchor_run_id != run_id:
            raise LookupError(f"Direction mapping {mapping_id} was not found for run {run_id}.")
        return row

    async def _check_name_available(
        self, session: AsyncSession, anchor_run_id: str, name: str
    ) -> None:
        result = await session.execute(
            select(DirectionMappingRecord.id).where(
                DirectionMappingRecord.anchor_run_id == anchor_run_id,
                DirectionMappingRecord.name == name,
            )
        )
        if result.scalars().first() is not None:
            raise DirectionError(
                "direction_mapping_name_conflict",
                f"A direction mapping named {name!r} already exists for this run.",
            )

    async def _validate_mapping_references(
        self,
        session: AsyncSession,
        anchor: SimulationRun,
        definition: DirectionDefinition,
    ) -> None:
        """Validate a mapping definition before any row is written.

        Mirrors the generation-time checks: the source run must exist,
        be completed, and hold an ensemble; MECE branches must name
        branches of the anchor run's tree; a deliberation pin must
        exist on the source or anchor run.
        """
        source = await session.get(SimulationRun, definition.source_run_id)
        if source is None:
            raise DirectionError(
                "direction_unknown_source_run",
                f"Direction {definition.name!r} names unknown source run "
                f"{definition.source_run_id!r}.",
            )
        if source.status != SimulationRunStatus.COMPLETED.value:
            raise DirectionError(
                "direction_source_run_not_completed",
                f"Direction {definition.name!r} draws on run "
                f"{definition.source_run_id!r}, which is not completed.",
            )
        summary = source.summary or {}
        ensemble_fragment = summary.get(MONTE_CARLO_SUMMARY_KEY)
        if ensemble_fragment is None:
            raise DirectionError(
                "direction_source_run_no_ensemble",
                f"Direction {definition.name!r} draws on run "
                f"{definition.source_run_id!r}, which has no stored ensemble. "
                f"Run POST /runs/{definition.source_run_id}/monte-carlo first.",
            )
        try:
            MonteCarloResult.model_validate(ensemble_fragment)
        except ValidationError as exc:
            raise _direction_corrupt("monte_carlo", exc) from exc
        try:
            tree, _validation = self._read_mece(anchor)
        except NarrativeError as exc:
            raise DirectionError("direction_corrupt_fragment", str(exc)) from exc
        if definition.mece_branches:
            if tree is None:
                raise DirectionError(
                    "direction_mece_branches_without_tree",
                    f"Direction {definition.name!r} names MECE branches but the "
                    f"anchor run has no stored MECE tree.",
                )
            valid = [name for name, _scope in _collect_branches(tree)]
            for branch in definition.mece_branches:
                if branch not in valid:
                    raise DirectionError(
                        "direction_unknown_mece_branch",
                        f"Direction {definition.name!r} names unknown MECE branch "
                        f"{branch!r}. Valid branches: {', '.join(valid) or '(none)'}",
                    )
        if definition.deliberation_id is not None:
            try:
                source_deliberations = self._read_deliberations(source)
                anchor_deliberations = self._read_deliberations(anchor)
            except NarrativeError as exc:
                raise DirectionError("direction_corrupt_fragment", str(exc)) from exc
            known = {record.id for record in source_deliberations} | {
                record.id for record in anchor_deliberations
            }
            if definition.deliberation_id not in known:
                raise DirectionError(
                    "direction_deliberation_not_found",
                    f"Direction {definition.name!r} pins unknown deliberation "
                    f"{definition.deliberation_id!r}.",
                )

    @staticmethod
    def _mapping_to_read(row: DirectionMappingRecord) -> DirectionMappingRead:
        return DirectionMappingRead(
            id=row.id,
            anchor_run_id=row.anchor_run_id,
            name=row.name,
            source_run_id=row.source_run_id,
            arm=cast(Literal["baseline", "strategy"], row.arm),
            mece_branches=list(row.mece_branches),
            deliberation_id=row.deliberation_id,
            origin=cast(Literal["derived", "authored", "llm_proposal", "override"], row.origin),
            rule_id=row.rule_id,
            rules_version=row.rules_version,
            rule_record=dict(row.rule_record) if row.rule_record is not None else None,
            status=cast(Literal["active", "proposed", "rejected"], row.status),
            proposal_record=(
                dict(row.proposal_record) if row.proposal_record is not None else None
            ),
            override_record=(
                dict(row.override_record) if row.override_record is not None else None
            ),
            user_edited=row.user_edited,
            position=row.position,
            created_at=row.created_at.isoformat(),
            updated_at=row.updated_at.isoformat(),
        )

    # -- reads -----------------------------------------------------------

    async def list_narratives(
        self, session: AsyncSession, run_id: str
    ) -> DecisionNarrativeListRead:
        run = await session.get(SimulationRun, run_id)
        if run is None:
            raise LookupError(f"Simulation run {run_id} was not found.")
        result = await session.execute(
            select(DecisionNarrativeRecord)
            .where(DecisionNarrativeRecord.run_id == run_id)
            .order_by(DecisionNarrativeRecord.version.desc())
        )
        rows = list(result.scalars().all())
        polishes = await self._latest_polishes(session, [row.id for row in rows])
        return DecisionNarrativeListRead(
            run_id=run_id,
            narratives=[self._to_read(row, polishes.get(row.id)) for row in rows],
        )

    async def get_narrative(
        self, session: AsyncSession, run_id: str, narrative_id: str
    ) -> DecisionNarrativeRead:
        record = await self._narrative_for_run(session, run_id, narrative_id)
        polishes = await self._latest_polishes(session, [record.id])
        return self._to_read(record, polishes.get(record.id))

    async def _narrative_for_run(
        self, session: AsyncSession, run_id: str, narrative_id: str
    ) -> DecisionNarrativeRecord:
        record = await session.get(DecisionNarrativeRecord, narrative_id)
        if record is None or record.run_id != run_id:
            raise LookupError(f"Narrative {narrative_id} was not found for run {run_id}.")
        return record

    async def _latest_polishes(
        self, session: AsyncSession, narrative_ids: list[str]
    ) -> dict[str, NarrativePolishRead]:
        if not narrative_ids:
            return {}
        result = await session.execute(
            select(DecisionNarrativePolishRecord)
            .where(DecisionNarrativePolishRecord.narrative_id.in_(narrative_ids))
            .order_by(
                DecisionNarrativePolishRecord.created_at.desc(),
                DecisionNarrativePolishRecord.id.desc(),
            )
        )
        latest: dict[str, NarrativePolishRead] = {}
        for row in result.scalars().all():
            latest.setdefault(row.narrative_id, self._polish_to_read(row))
        return latest

    def _to_read(
        self, record: DecisionNarrativeRecord, polish: NarrativePolishRead | None
    ) -> DecisionNarrativeRead:
        try:
            body = NarrativeBody.model_validate(record.artifact)
        except ValidationError as exc:
            raise _corrupt("decision_narratives.artifact", exc) from exc
        return DecisionNarrativeRead(
            id=record.id,
            run_id=record.run_id,
            version=record.version,
            topic=record.topic,
            inputs_hash=record.inputs_hash,
            content_hash=record.content_hash,
            created_at=record.created_at.isoformat(),
            body=body,
            polish=polish,
            direction_mapping_ids=list(record.direction_mapping_ids or []),
        )

    @staticmethod
    def _polish_to_read(row: DecisionNarrativePolishRecord) -> NarrativePolishRead:
        return NarrativePolishRead(
            id=row.id,
            narrative_id=row.narrative_id,
            model=row.model,
            template_id=row.template_id,
            template_version=row.template_version,
            polished_markdown=row.polished_markdown,
            created_at=row.created_at.isoformat(),
        )

    # -- polish ----------------------------------------------------------

    async def polish(
        self, session: AsyncSession, run_id: str, narrative_id: str
    ) -> NarrativePolishRead:
        """Run one LLM polish pass; the artifact row is never touched.

        Raises :class:`NarrativeError` with code
        ``narrative_polish_unavailable`` (route maps to 503) when no
        LLM is configured, ``narrative_polish_contract_failed``
        (route maps to 502) when the output fails its contract, and
        ``narrative_polish_recheck_failed`` (route maps to 502)
        when the polished text fails the numbers/provenance
        re-check against the deterministic markdown. All three
        write nothing: the re-check runs after the polish pass
        returns and before any row is written.
        """
        record = await self._narrative_for_run(session, run_id, narrative_id)
        body = self._to_read(record, polish=None).body
        try:
            output, model = await polish_markdown(self._port, body.markdown)
        except SkillLLMUnavailable as exc:
            raise NarrativeError("narrative_polish_unavailable", str(exc)) from exc
        except SkillContractError as exc:
            raise NarrativeError("narrative_polish_contract_failed", str(exc)) from exc
        recheck = check_polish(body.markdown, output.polished_markdown)
        if not recheck.passed:
            raise NarrativeError("narrative_polish_recheck_failed", recheck.describe())
        row = DecisionNarrativePolishRecord(
            narrative_id=record.id,
            model=model,
            template_id=POLISH_TEMPLATE_ID,
            template_version=POLISH_TEMPLATE_VERSION,
            polished_markdown=output.polished_markdown,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return self._polish_to_read(row)


__all__ = ["NarrativeService"]

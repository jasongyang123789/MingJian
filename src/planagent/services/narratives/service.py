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
from sqlalchemy.ext.asyncio import AsyncSession

from planagent.config import Settings
from planagent.domain.enums import SimulationRunStatus
from planagent.domain.models import (
    CalibrationFitRecord,
    DecisionNarrativePolishRecord,
    DecisionNarrativeRecord,
    DirectionMappingRecord,
    SimulationRun,
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
    NarrativeBody,
    NarrativeError,
    NarrativeGenerateRequest,
    NarrativePolishRead,
)
from planagent.services.narratives.polish import (
    POLISH_TEMPLATE_ID,
    POLISH_TEMPLATE_VERSION,
    polish_markdown,
)
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
from planagent.services.skills.contracts import SkillContractError
from planagent.services.skills.models import SkillDeliberationRecord
from planagent.services.skills.orchestration import (
    OpenAIServiceSkillPort,
    SkillLLMPort,
    SkillLLMResponse,
    SkillLLMUnavailable,
)
from planagent.services.skills.service import SKILL_DELIBERATIONS_SUMMARY_KEY

_MECE_CONFIGURATION_KEY = "mece"


class _NoLLMPort:
    """Port used when no LLM service is wired: always unavailable."""

    def is_available(self) -> bool:
        return False

    async def generate_json(self, **_kwargs: Any) -> SkillLLMResponse:
        raise SkillLLMUnavailable("No LLM service is configured for narrative polish.")


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
    ) -> None:
        self.settings = settings
        if llm_port is not None:
            self._port: SkillLLMPort = llm_port
        elif openai_service is not None:
            self._port = OpenAIServiceSkillPort(openai_service)
        else:
            self._port = _NoLLMPort()  # type: ignore[assignment]

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
        rows = (await self._mapping_rows(session, anchor.id))[:MAX_DIRECTIONS]
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
        self, session: AsyncSession, anchor_run_id: str
    ) -> list[DirectionMappingRecord]:
        result = await session.execute(
            select(DirectionMappingRecord)
            .where(DirectionMappingRecord.anchor_run_id == anchor_run_id)
            .order_by(DirectionMappingRecord.position.asc(), DirectionMappingRecord.id.asc())
        )
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
            origin=cast(Literal["derived", "authored"], row.origin),
            rule_id=row.rule_id,
            rules_version=row.rules_version,
            rule_record=dict(row.rule_record) if row.rule_record is not None else None,
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
        LLM is configured, and ``narrative_polish_contract_failed``
        (route maps to 502) when the output fails its contract. Both
        write nothing.
        """
        record = await self._narrative_for_run(session, run_id, narrative_id)
        body = self._to_read(record, polish=None).body
        try:
            output, model = await polish_markdown(self._port, body.markdown)
        except SkillLLMUnavailable as exc:
            raise NarrativeError("narrative_polish_unavailable", str(exc)) from exc
        except SkillContractError as exc:
            raise NarrativeError("narrative_polish_contract_failed", str(exc)) from exc
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

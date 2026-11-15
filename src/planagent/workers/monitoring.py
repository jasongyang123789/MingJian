"""Monitoring worker (Sprint 11): evaluate loop triggers + record.

AUTOMATION BOUNDARY (SPRINT9.md §10): this worker only evaluates
and records. Each ``run_once()`` evaluates every living-strategy
loop's active trigger registration against its recorded
observations and writes one evaluation row per loop whose inputs
changed (see
``SimulationLivingLoopMixin.run_monitoring_cycle``). It never
creates simulation runs or loop iterations, never transitions
iteration state, and never mutates loop rows: a recorded trigger
firing plus an explicit review is still what starts a
re-simulation, and this worker starts none.

The worker follows the CalibrationWorker pattern: a thin
``run_once()`` over a database session, per-loop isolation inside
the cycle, and a summary-dict result. Scheduling is the
``worker_cli --loop`` mechanism; the default interval comes from
``settings.monitoring_worker_interval_seconds`` (conservative
default: one hour) and ``--interval-seconds`` overrides it.
"""

from __future__ import annotations

from planagent.config import Settings
from planagent.db import get_database
from planagent.events.bus import EventBus
from planagent.services.simulation import SimulationService
from planagent.simulation.rules import RuleRegistry
from planagent.workers.base import Worker, WorkerDescription


class MonitoringWorker(Worker):
    description = WorkerDescription(
        worker_id="monitoring-worker",
        summary=(
            "Evaluates living-strategy loop triggers against recorded "
            "observations and records the outcome; never creates runs "
            "or changes loop state."
        ),
        consumes=(),
        produces=(),
    )

    def __init__(
        self,
        settings: Settings,
        event_bus: EventBus,
        rule_registry: RuleRegistry,
    ) -> None:
        self.settings = settings
        self.event_bus = event_bus
        self.rule_registry = rule_registry
        self.worker_instance_id = self.description.worker_id
        self.default_interval_seconds = float(settings.monitoring_worker_interval_seconds)
        self.service = SimulationService(settings, event_bus, rule_registry)

    async def run_once(self) -> dict[str, object]:
        database = get_database()
        async with database.session() as session:
            result = await self.service.run_monitoring_cycle(session)
        return {
            "cycle_id": result.cycle_id,
            "evaluated_at": result.evaluated_at,
            "loops_evaluated": result.loops_evaluated,
            "loops_skipped": result.loops_skipped,
            "loops_fired": result.loops_fired,
            "loops_errored": result.loops_errored,
            "errors": result.errors,
        }

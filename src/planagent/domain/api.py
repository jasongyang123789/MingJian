from __future__ import annotations

from datetime import datetime
from typing import Any
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from planagent.domain.enums import (
    ExecutionMode,
    IngestRunStatus,
    ReviewItemStatus,
    SimulationRunStatus,
)
from planagent.domain.types import GeneratedReportModel
from planagent.services.mece.models import DecompositionTree
from planagent.services.splits.models import OemProductionShares, SplitStructure
from planagent.services.variables.models import VariableSet
from planagent.services.variables.opportunities import (
    BreakoutPrompt,
    KeyOpportunityPrompt,
)


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _normalize_decision_context(value: dict[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    total_length = 0
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip()
        context_value = str(raw_value).strip()
        if not key or len(key) > 64:
            raise ValueError("context keys must contain 1 to 64 characters")
        if len(context_value) > 2000:
            raise ValueError("context values must contain at most 2000 characters")
        total_length += len(key) + len(context_value)
        normalized[key] = context_value
    if total_length > 8000:
        raise ValueError("context must contain at most 8000 characters")
    return normalized


def _validate_external_http_url(value: str) -> str:
    if value == "":
        return value
    if len(value) > 2048 or value != value.strip():
        raise ValueError("source URL must be an explicit http(s) URL")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("source URL must be an explicit http(s) URL")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        raise ValueError("source URL must be an explicit http(s) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("source URL must not contain credentials")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("source URL must have a valid port") from exc
    return value


class SourceSeedInput(APIModel):
    source_type: str
    source_url: str
    title: str
    content_text: str
    published_at: datetime | None = None
    source_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        return _validate_external_http_url(value)


class IngestRunCreate(APIModel):
    requested_by: str = "system"
    tenant_id: str | None = None
    preset_id: str | None = None
    execution_mode: ExecutionMode | None = None
    items: list[SourceSeedInput] = Field(default_factory=list)


class IngestRunRead(APIModel):
    id: str
    requested_by: str
    execution_mode: ExecutionMode
    status: IngestRunStatus
    source_types: list[str] = Field(default_factory=list)
    request_payload: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, int] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    tenant_id: str | None = None
    preset_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def populate_metadata(cls, value: object) -> object:
        if isinstance(value, dict) or not hasattr(value, "request_payload"):
            return value
        request_payload = getattr(value, "request_payload", {}) or {}
        return {
            "id": value.id,
            "requested_by": value.requested_by,
            "execution_mode": value.execution_mode,
            "status": value.status,
            "source_types": value.source_types,
            "request_payload": value.request_payload,
            "summary": value.summary,
            "created_at": value.created_at,
            "updated_at": value.updated_at,
            "tenant_id": getattr(value, "tenant_id", None) or request_payload.get("tenant_id"),
            "preset_id": getattr(value, "preset_id", None) or request_payload.get("preset_id"),
        }


class ReviewDecisionRequest(APIModel):
    reviewer_id: str
    note: str | None = None


class ReviewItemRead(APIModel):
    id: str
    claim_id: str
    tenant_id: str | None = None
    preset_id: str | None = None
    queue_reason: str
    status: ReviewItemStatus
    reviewer_id: str | None = None
    review_note: str | None = None
    resolved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DownsideConfig(APIModel):
    """Cyclical downturn / reversal shock (fix/downside-mechanism, Track C).

    Default ON since Track C (2026-11-20): Ho ordered the default flipped
    from OFF to ON on 2026-11-20 08:42, reversing his 2026-11-19 14:31
    default-OFF decision ("下行风险机制，默认关闭保向后兼容"). A run that
    omits ``downside`` gets the default config (``enabled`` true, fields
    revenue + profit, persistent reversal named); the engine auto-binds
    the canonical labeled-assumption variables (see
    :mod:`planagent.services.simulation.downside`) where they apply.
    Pass ``downside: null`` or ``{"enabled": false}`` to opt out; an
    explicitly supplied fragment keeps the loud-failure contract (named
    variables must be bound, or run creation fails). When enabled, the
    named variables must be bound as sampled variables on the run
    (Bernoulli for ``occurs``, triangular for ``depth`` / ``start`` /
    ``duration``); the executor resolves them per run from the run seed
    and applies the shock after the tick drivers. ``persistent_variable``
    is None by default on an explicitly supplied fragment (pure cycle,
    no reversal regime); name a Bernoulli variable to enable the
    reversal draw. All parameters are LABELED ASSUMPTIONS with no
    independent estimate — see
    :mod:`planagent.services.simulation.downside`.
    """

    enabled: bool = True
    fields: list[str] = Field(default_factory=lambda: ["revenue", "profit"])
    occurs_variable: str = "downturn_occurs"
    depth_variable: str = "downturn_depth"
    start_variable: str = "downturn_start"
    duration_variable: str = "downturn_duration"
    persistent_variable: str | None = None
    label: str | None = None

    @field_validator("fields", mode="before")
    @classmethod
    def _validate_fields(cls, value: object) -> object:
        if not isinstance(value, list) or not value:
            raise ValueError("Downside 'fields' must be a non-empty list of state-field names.")
        if not all(isinstance(item, str) and item.strip() for item in value):
            raise ValueError("Downside 'fields' entries must be non-empty strings.")
        return [item.strip() for item in value]

    @field_validator(
        "occurs_variable", "depth_variable", "start_variable", "duration_variable", mode="before"
    )
    @classmethod
    def _validate_variable_name(cls, value: object) -> object:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Downside variable names must be non-empty strings.")
        return value.strip()


def _default_downside_config() -> DownsideConfig:
    """Default downside config for new runs (Track C, default ON).

    The ``persistent_variable`` is named here (unlike the bare
    ``DownsideConfig`` default of None) so the default shock includes
    the reversal regime. The label literal must stay identical to
    ``DOWNSIDE_DEFAULT_LABEL`` in
    :mod:`planagent.services.simulation.downside` — ``domain/api.py``
    cannot import that module (it would pull in the simulation package
    and cycle back here); a test pins the two equal.
    """

    return DownsideConfig(
        enabled=True,
        persistent_variable="downturn_persistent",
        label=(
            "LABELED ASSUMPTION — default downside shock (Track C, 2026-11-20): "
            "cyclical downturn + optional reversal; parameters have no "
            "independent estimate"
        ),
    )


class SimulationRunCreate(APIModel):
    company_id: str | None = None
    company_name: str | None = None
    force_id: str | None = None
    force_name: str | None = None
    theater: str | None = None
    market: str = "ai"
    domain_id: str = "corporate"
    actor_template: str = "ai_model_provider"
    execution_mode: ExecutionMode | None = None
    tick_count: int | None = None
    seed: int = 7
    tenant_id: str | None = None
    preset_id: str | None = None
    initial_state: dict[str, float] = Field(default_factory=dict)
    military_use_mode: Literal["osint", "training", "full_domain"] = "full_domain"
    # Optional MECE decomposition (Sprint 1, PRD delta D1). When attached,
    # run creation validates it and REFUSES to run on FAIL — there is no
    # bypass. When absent, runs behave exactly as before.
    decomposition: DecompositionTree | None = None
    # Optional variable bindings (Sprint 2, PRD deltas D2/D3). A template
    # id (built-in "builtin:<domain>" or a stored template) supplies state
    # defaults, metric policies, and a base variable set; an inline set
    # overrides template variables by id. Invalid bindings refuse run
    # creation, like the MECE gate. When both are absent, runs behave
    # exactly as before.
    variable_template_id: str | None = None
    variable_set: VariableSet | None = None
    # Optional hindsight-firewall cutoff (Sprint 5, PRD delta D8). When
    # supplied, only claims ingested at or before decision_time are
    # visible to the run; later evidence cannot influence it. When
    # absent, the cutoff defaults to the run's creation time. Naive
    # datetimes are assumed UTC. The cutoff is stored in the run
    # configuration, so it enters the Sprint 3 input hash and replays
    # reproduce the same evidence set.
    decision_time: datetime | None = None
    # Optional bottom-layer split structure (Phase 1, automotive track).
    # When attached, run creation validates the OEM → nameplate →
    # generation → trim → product → supplier-share tree and REFUSES to
    # run on failure — there is no bypass, mirroring the MECE gate. Only
    # automotive runs accept a split structure. When absent, runs behave
    # exactly as before.
    split_structure: SplitStructure | None = None
    # Optional stored OEM production shares (S-layer real splits). The
    # S-layer's OEM-mix input, stored beside the split structure it
    # covers: requires an attached split structure, must cover exactly
    # the structure's OEMs and sum to 1, and refuses run creation on
    # failure like the split gate. Stored in the run's split_structure
    # fragment (so the Sprint 3 input hash covers it); the sales-layer
    # endpoint uses the stored shares when its request body omits them.
    # When absent, runs behave exactly as before (the caller must pass
    # shares to the sales-layer endpoint).
    oem_production_shares: OemProductionShares | None = None
    # Cyclical downturn / reversal shock (fix/downside-mechanism, Track C).
    # Default ON: when omitted, the run gets the default config (enabled,
    # fields revenue + profit, canonical labeled-assumption variables
    # auto-bound by the engine where they apply). Pass ``downside: null``
    # or ``{"enabled": false}`` to opt out. Stored in the run's
    # ``downside`` fragment, so the Sprint 3 input hash covers it and
    # Monte Carlo trials, scenario branches, and replays inherit it.
    downside: DownsideConfig | None = Field(default_factory=_default_downside_config)

    @model_validator(mode="after")
    def validate_domain_subject(self) -> "SimulationRunCreate":
        if self.domain_id == "corporate":
            if not self.company_id or not self.company_name:
                raise ValueError("Corporate simulation requires company_id and company_name.")
            return self
        if self.domain_id == "military":
            if not self.force_id or not self.force_name:
                raise ValueError("Military simulation requires force_id and force_name.")
            return self
        if self.domain_id == "automotive":
            # Automotive runs reuse the company subject (the OEM or
            # Tier-1 supplier under simulation), like corporate runs.
            if not self.company_id or not self.company_name:
                raise ValueError("Automotive simulation requires company_id and company_name.")
            return self
        raise ValueError(f"Unsupported domain_id: {self.domain_id}.")


class SimulationRunRead(APIModel):
    id: str
    company_id: str | None = None
    force_id: str | None = None
    domain_id: str
    actor_template: str
    status: SimulationRunStatus
    execution_mode: ExecutionMode
    tick_count: int
    seed: int
    parent_run_id: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    tenant_id: str | None = None
    preset_id: str | None = None
    military_use_mode: str | None = None
    # Phase 4, Track 9 — report-time opportunity / breakout prompts,
    # computed at run creation from the effective variable set. They
    # change no numbers; they only surface what the inputs discount
    # (``key_opportunities``: a modeled value deliberately below an
    # observed rate) or stretch (``breakout_prompts``: T1 growth
    # assumptions above the sustained-growth trigger). T2–T4 need
    # post-decision actuals or diagnostic fitted values, so they are
    # review-time checks, not part of this response. Reads of an existing
    # run (GET) do not re-derive them — they are in the creation
    # response and re-derivable from the stored bindings.
    key_opportunities: list[KeyOpportunityPrompt] = Field(default_factory=list)
    breakout_prompts: list[BreakoutPrompt] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def populate_metadata(cls, value: object) -> object:
        if isinstance(value, dict) or not hasattr(value, "configuration"):
            return value
        configuration = getattr(value, "configuration", {}) or {}
        return {
            "id": value.id,
            "company_id": value.company_id,
            "force_id": value.force_id,
            "domain_id": value.domain_id,
            "actor_template": value.actor_template,
            "status": value.status,
            "execution_mode": value.execution_mode,
            "tick_count": value.tick_count,
            "seed": value.seed,
            "parent_run_id": value.parent_run_id,
            "summary": value.summary,
            "created_at": value.created_at,
            "updated_at": value.updated_at,
            "completed_at": value.completed_at,
            "tenant_id": getattr(value, "tenant_id", None) or configuration.get("tenant_id"),
            "preset_id": getattr(value, "preset_id", None) or configuration.get("preset_id"),
            "military_use_mode": getattr(value, "military_use_mode", None)
            or configuration.get("military_use_mode"),
        }


class ScenarioRunCreate(APIModel):
    fork_step: int | None = Field(default=None, ge=1)
    tick_count: int | None = Field(default=None, ge=1)
    assumptions: list[str] = Field(default_factory=list)
    decision_deltas: list[str] = Field(default_factory=list)
    state_overrides: dict[str, float] = Field(default_factory=dict)
    probability_band: str = "medium"
    # Optional branch-level variable bindings (Sprint 3). A template id
    # replaces the parent run's template snapshot; an inline set merges
    # over the inherited bindings (inline wins per variable id); a
    # decomposition branch path scopes the tag cross-check to one MECE
    # branch instead of the root scope. All three absent means the child
    # inherits the parent's variables fragment unchanged.
    variable_template_id: str | None = None
    variable_set: VariableSet | None = None
    decomposition_branch: str | None = None
    # Arm resampling (fix/arm-resample). False (default): the child
    # run starts from the parent's fork-snapshot state, so a sampled
    # variable that names a state field keeps the forked value and a
    # Monte Carlo ensemble over the child can collapse to a degenerate
    # point estimate when every remaining driver variable is pinned.
    # True: the child re-draws its non-pinned variables from their own
    # distributions, deterministically from the run seed, and the
    # re-drawn values take precedence over the inherited fork state
    # for exactly the state fields they cover; pinned FIXED overrides
    # still sample at exactly their pinned value, and every other
    # forked state field is unchanged. The flag is stored on the
    # child's ``scenario`` fragment, so Monte Carlo trials and replays
    # of the child inherit it.
    resample_variables: bool = False


class ScenarioSearchRequest(APIModel):
    depth: int = Field(default=2, ge=1, le=3)
    beam_width: int = Field(default=3, ge=1, le=5)
    tick_count: int | None = Field(default=None, ge=1, le=12)
    assumptions: list[str] = Field(default_factory=list)


class ScenarioRunRead(APIModel):
    branch_id: str
    run_id: str
    parent_run_id: str
    fork_step: int
    assumptions: list[str] = Field(default_factory=list)
    decision_deltas: list[str] = Field(default_factory=list)
    kpi_trajectory: list[dict[str, Any]] = Field(default_factory=list)
    probability_band: str
    notable_events: list[str] = Field(default_factory=list)
    evidence_summary: str
    report_id: str | None = None
    created_at: datetime


class ScenarioCompareRead(APIModel):
    baseline_run_id: str
    domain_id: str
    branch_count: int
    metric_names: list[str] = Field(default_factory=list)
    baseline_final_state: dict[str, float] = Field(default_factory=dict)
    baseline_report_id: str | None = None
    baseline_recommendations: list[str] = Field(default_factory=list)
    recommended_branch_id: str | None = None
    summary: list[str] = Field(default_factory=list)
    branches: list[dict[str, Any]] = Field(default_factory=list)


class TimelineEventRead(APIModel):
    event_id: str
    event_type: str
    tick: int | None = None
    title: str
    detail: str | None = None
    related_ids: list[str] = Field(default_factory=list)
    created_at: datetime


class EvidenceGraphNodeRead(APIModel):
    node_id: str
    label: str
    node_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceGraphEdgeRead(APIModel):
    source_id: str
    target_id: str
    relation_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceGraphRead(APIModel):
    nodes: list[EvidenceGraphNodeRead] = Field(default_factory=list)
    edges: list[EvidenceGraphEdgeRead] = Field(default_factory=list)


class KnowledgeSearchResultRead(APIModel):
    node_id: str
    label: str
    node_type: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class GeoMapRead(APIModel):
    mode: str
    theater: str | None = None
    note: str | None = None
    assets: list[dict[str, Any]] = Field(default_factory=list)
    network: dict[str, Any] = Field(default_factory=dict)
    overlays: dict[str, Any] = Field(default_factory=dict)


class ScenarioTreeRead(APIModel):
    baseline_run_id: str
    active_run_id: str
    active_branch_id: str | None = None
    nodes: list[dict[str, Any]] = Field(default_factory=list)


class KPIMetricRead(APIModel):
    metric: str
    start: float | None = None
    end: float | None = None
    baseline_end: float | None = None
    delta: float | None = None


class KPIComparatorRead(APIModel):
    baseline_run_id: str
    current_run_id: str
    metrics: list[KPIMetricRead] = Field(default_factory=list)


class StartupKPICardRead(APIModel):
    metric_id: str
    label: str
    value: float | int | str
    unit: str | None = None
    target: str | None = None
    status: Literal["good", "watch", "risk"]
    insight: str


class StartupKPIPackRead(APIModel):
    preset_id: str
    tenant_id: str | None = None
    cards: list[StartupKPICardRead] = Field(default_factory=list)


class DebateSummaryRead(APIModel):
    debate_id: str
    topic: str
    trigger_type: str
    verdict: str | None = None
    confidence: float | None = None
    recommendation_count: int = 0
    created_at: datetime


class RunWorkbenchRead(APIModel):
    run_id: str
    domain_id: str
    tenant_id: str | None = None
    preset_id: str | None = None
    latest_report_id: str | None = None
    review_queue: list[ReviewItemRead] = Field(default_factory=list)
    evidence_graph: EvidenceGraphRead
    timeline: list[TimelineEventRead] = Field(default_factory=list)
    geo_map: GeoMapRead
    scenario_tree: ScenarioTreeRead
    scenario_compare: ScenarioCompareRead | None = None
    decision_trace: list[dict[str, Any]] = Field(default_factory=list)
    prediction_versions: list[dict[str, Any]] = Field(default_factory=list)
    kpi_comparator: KPIComparatorRead
    startup_kpi_pack: StartupKPIPackRead | None = None
    debate_records: list[DebateSummaryRead] = Field(default_factory=list)


class AgentStartupPresetRunCreate(APIModel):
    requested_by: str = "agent-startup-preset"
    tenant_id: str | None = None
    scenarios: list[Literal["baseline", "upside", "downside"]] = Field(
        default_factory=lambda: ["baseline", "upside", "downside"]
    )


class AgentStartupPresetScenarioRead(APIModel):
    scenario: Literal["baseline", "upside", "downside"]
    company_id: str
    run: SimulationRunRead
    startup_kpi_pack: StartupKPIPackRead | None = None
    report_id: str | None = None
    report_path: str
    decision_trace_path: str


class AgentStartupPresetRunRead(APIModel):
    preset_id: str
    tenant_id: str
    ingest_run: IngestRunRead
    scenarios: list[AgentStartupPresetScenarioRead] = Field(default_factory=list)


class DebateTriggerRequest(APIModel):
    run_id: str | None = None
    claim_id: str | None = None
    topic: str = Field(min_length=1)
    trigger_type: Literal[
        "manual",
        "evidence_assessment",
        "conflict_resolution",
        "pivot_decision",
        "branch_evaluation",
        "report_challenge",
    ] = "manual"
    target_type: Literal["run", "claim", "branch", "report"] = "run"
    target_id: str | None = None
    context_lines: list[str] = Field(default_factory=list)
    debate_mode: Literal["full", "fast"] = "full"
    domain_id: str | None = None


class DebateRoundRead(APIModel):
    round_number: int
    role: str
    position: str
    confidence: float
    arguments: list[dict[str, Any]] = Field(default_factory=list)
    rebuttals: list[dict[str, Any]] = Field(default_factory=list)
    concessions: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime


class PlanningRecommendation(APIModel):
    title: str
    priority: str = Field(default="medium", pattern="^(high|medium|low)$")
    rationale: str = ""
    action_items: list[str] = Field(default_factory=list)


class DebateVerdictRead(APIModel):
    debate_id: str
    topic: str
    trigger_type: str
    rounds_completed: int
    verdict: str
    confidence: float
    winning_arguments: list[str] = Field(default_factory=list)
    decisive_evidence: list[str] = Field(default_factory=list)
    conditions: list[str] | None = None
    minority_opinion: str | None = None
    recommendations: list[PlanningRecommendation] = Field(default_factory=list)
    risk_factors: list[str] = Field(default_factory=list)
    alternative_scenarios: list[dict[str, Any]] = Field(default_factory=list)
    conclusion_summary: str | None = None
    created_at: datetime


class DebateDetailRead(APIModel):
    id: str
    run_id: str | None = None
    claim_id: str | None = None
    topic: str
    trigger_type: str
    status: str
    target_type: str
    target_id: str | None = None
    context_payload: dict[str, Any] = Field(default_factory=dict)
    rounds: list[DebateRoundRead] = Field(default_factory=list)
    verdict: DebateVerdictRead | None = None
    created_at: datetime
    updated_at: datetime


class DebateVoteCreate(APIModel):
    debate_session_id: str
    round_number: int = Field(ge=1)
    role: Literal["advocate", "challenger", "arbitrator"]
    vote: Literal["agree", "disagree", "neutral"]
    comment: str | None = None


class DebateVoteRead(APIModel):
    id: str
    debate_session_id: str
    round_number: int
    role: str
    vote: str
    comment: str | None = None
    created_at: datetime


# ── Debate Interrupt Models ──────────────────────────────────────────────────


class DebateInterruptCreate(APIModel):
    """用户在辩论中途提交的插话/补充信息"""

    message: str = Field(min_length=1, description="用户插话的内容")
    interrupt_type: str = Field(
        default="general",
        pattern="^(supplementary_info|direction_correction|new_evidence|general)$",
        description="插话类型：补充信息/修正方向/新证据/通用",
    )


class DebateInterruptRead(APIModel):
    """辩论插话记录"""

    id: str
    debate_session_id: str
    message: str
    interrupt_type: str
    injected_at_round: int | None = None
    status: str
    created_at: datetime


# ── Debate Replay Models ─────────────────────────────────────────────────────


class DebateReplayRead(APIModel):
    """完整回放数据（按时间顺序 + 按轮次两种视图）"""

    debate_id: str
    topic: str
    trigger_type: str
    status: str
    target_type: str
    target_id: str | None = None
    total_rounds: int = 0
    rounds_by_number: dict[str, list[dict[str, Any]]] = Field(
        default_factory=dict,
        description="按轮次编号分组的辩论数据（key 为轮次编号字符串）",
    )
    timeline: list[dict[str, Any]] = Field(
        default_factory=list,
        description="按时间顺序排列的所有发言",
    )
    events: list[dict[str, Any]] = Field(
        default_factory=list,
        description="前端可直接消费的回放事件列表，兼容 timeline",
    )
    verdict: DebateVerdictRead | None = None
    created_at: datetime
    updated_at: datetime


class DebateRoundDetailRead(APIModel):
    """单轮辩论详情"""

    debate_id: str
    topic: str
    round_number: int
    speeches: list[dict[str, Any]] = Field(
        default_factory=list,
        description="本轮所有发言（role, position, confidence, arguments, rebuttals, concessions）",
    )
    created_at: datetime


class DebateTimelineRead(APIModel):
    """辩论时间线"""

    debate_id: str
    topic: str
    event_count: int = 0
    events: list[dict[str, Any]] = Field(
        default_factory=list,
        description="按时间排序的发言事件",
    )
    verdict_event: dict[str, Any] | None = None
    started_at: datetime
    completed_at: datetime | None = None


class DebateComparisonRead(APIModel):
    """对比两场辩论"""

    debate_1: dict[str, Any] = Field(default_factory=dict)
    debate_2: dict[str, Any] = Field(default_factory=dict)
    differences: dict[str, Any] = Field(
        default_factory=dict,
        description="两场辩论之间的差异统计",
    )


class DebateReplaySummaryRead(APIModel):
    """辩论摘要（包含关键转折点）"""

    debate_id: str
    topic: str
    trigger_type: str
    status: str
    total_rounds: int = 0
    verdict: str | None = None
    verdict_confidence: float | None = None
    winning_arguments: list[str] = Field(default_factory=list)
    conclusion_summary: str | None = None
    minority_opinion: str | None = None
    round_summaries: list[dict[str, Any]] = Field(
        default_factory=list,
        description="每轮摘要",
    )
    turning_points: list[dict[str, Any]] = Field(
        default_factory=list,
        description="关键转折点（信心大幅变动、让步等）",
    )
    created_at: datetime


class RuleReloadResponse(APIModel):
    domains: list[str]
    rules_loaded: int


class QueueHealthBucketRead(APIModel):
    queue: str
    pending: int = 0
    processing: int = 0
    completed: int = 0
    failed: int = 0
    reclaimable: int = 0


class ReviewQueueReasonRead(APIModel):
    queue_reason: str
    pending: int = 0
    processing: int = 0
    completed: int = 0
    reclaimable: int = 0


class RuntimeQueueHealthRead(APIModel):
    generated_at: datetime
    tenant_id: str | None = None
    preset_id: str | None = None
    queues: list[QueueHealthBucketRead] = Field(default_factory=list)
    review_queue_reasons: list[ReviewQueueReasonRead] = Field(default_factory=list)
    dead_letter_count: int = 0
    degraded_sources: list[dict[str, Any]] = Field(default_factory=list)
    backpressure_active: bool = False


class PlatformTopologyComponentRead(APIModel):
    name: str
    status: str
    detail: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlatformTopologyRead(APIModel):
    generated_at: datetime
    ready: bool
    edition: str = "community"
    database: PlatformTopologyComponentRead
    object_storage: PlatformTopologyComponentRead
    event_bus: PlatformTopologyComponentRead
    rules: PlatformTopologyComponentRead
    domain_packs: PlatformTopologyComponentRead
    workflow: PlatformTopologyComponentRead
    issues: list[str] = Field(default_factory=list)


class StrategicAssistantRequest(APIModel):
    topic: str = Field(min_length=1)
    context: dict[str, str] = Field(default_factory=dict, max_length=20)
    domain_id: Literal["auto", "corporate", "military"] = "auto"
    session_id: str | None = None
    session_name: str | None = None
    subject_id: str | None = None
    subject_name: str | None = None
    market: str = "ai"
    theater: str | None = None
    actor_template: str | None = None
    tick_count: int | None = Field(default=None, ge=1, le=12)
    tenant_id: str | None = None
    preset_id: str | None = None
    auto_refresh_enabled: bool = True
    refresh_timezone: str = "UTC"
    refresh_hour_local: int = Field(default=9, ge=0, le=23)
    auto_fetch_news: bool = True
    include_google_news: bool = True
    include_reddit: bool = True
    include_hacker_news: bool = True
    include_github: bool = True
    include_rss_feeds: bool = True
    include_gdelt: bool = True
    include_weather: bool = False
    include_aviation: bool = False
    include_x: bool = True
    source_types: list[str] = Field(default_factory=list)
    max_source_items: dict[str, int] = Field(default_factory=dict)
    max_news_items: int = Field(default=5, ge=0, le=10)
    max_tech_items: int = Field(default=3, ge=0, le=10)
    max_reddit_items: int = Field(default=3, ge=0, le=10)
    max_github_items: int = Field(default=3, ge=0, le=10)
    max_rss_items: int = Field(default=3, ge=0, le=10)
    max_gdelt_items: int = Field(default=3, ge=0, le=10)
    max_weather_items: int = Field(default=1, ge=0, le=3)
    max_aviation_items: int = Field(default=1, ge=0, le=3)
    max_x_items: int = Field(default=3, ge=0, le=10)

    @field_validator("context")
    @classmethod
    def validate_context(cls, value: dict[str, str]) -> dict[str, str]:
        """Normalize and validate user-supplied decision context fields."""
        return _normalize_decision_context(value)


class PanelDiscussionMessageRead(APIModel):
    participant_id: str
    label: str
    model_target: Literal["primary", "extraction", "x_search", "report"] | str
    stance: Literal["support", "challenge", "monitor"]
    summary: str
    key_points: list[str] = Field(default_factory=list)
    recommendation: str
    confidence: float = Field(ge=0.0, le=1.0)


class StrategicAssistantResponse(APIModel):
    session_id: str | None = None
    topic: str
    domain_id: str
    subject_id: str
    subject_name: str
    analysis: AnalysisResponse
    ingest_run: IngestRunRead
    simulation_run: SimulationRunRead
    latest_report: GeneratedReportModel | None = None
    debate: DebateDetailRead | None = None
    workbench: RunWorkbenchRead
    panel_discussion: list[PanelDiscussionMessageRead] = Field(default_factory=list)
    workflow: dict[str, Any] = Field(default_factory=dict)
    monitoring: dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime


class AnalysisRequest(APIModel):
    content: str = Field(min_length=1)
    decision_context: dict[str, str] = Field(default_factory=dict, max_length=20)
    domain_id: Literal["auto", "general", "corporate", "military"] = "auto"
    auto_fetch_news: bool = True
    include_google_news: bool = True
    include_reddit: bool = True
    include_hacker_news: bool = True
    include_github: bool = True
    include_rss_feeds: bool = True
    include_gdelt: bool = True
    include_weather: bool = False
    include_aviation: bool = False
    include_x: bool = False
    source_types: list[str] = Field(default_factory=list)
    max_source_items: dict[str, int] = Field(default_factory=dict)
    max_news_items: int = Field(default=5, ge=0, le=10)
    max_tech_items: int = Field(default=3, ge=0, le=10)
    max_reddit_items: int = Field(default=3, ge=0, le=10)
    max_github_items: int = Field(default=3, ge=0, le=10)
    max_rss_items: int = Field(default=3, ge=0, le=10)
    max_gdelt_items: int = Field(default=3, ge=0, le=10)
    max_weather_items: int = Field(default=1, ge=0, le=3)
    max_aviation_items: int = Field(default=1, ge=0, le=3)
    max_x_items: int = Field(default=3, ge=0, le=10)

    @field_validator("decision_context")
    @classmethod
    def validate_decision_context(cls, value: dict[str, str]) -> dict[str, str]:
        """Normalize and validate analysis decision context fields."""
        return _normalize_decision_context(value)


class AnalysisSourceRead(APIModel):
    source_type: str
    title: str
    url: str
    summary: str
    published_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        return _validate_external_http_url(value)


class AnalysisStepRead(APIModel):
    stage: str
    message: str
    detail: str | None = None


class AnalysisResponse(APIModel):
    query: str
    domain_id: str
    status: Literal["completed"]
    summary: str
    reasoning_steps: list[AnalysisStepRead] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    sources: list[AnalysisSourceRead] = Field(default_factory=list)
    generated_at: datetime


StrategicAssistantResponse.model_rebuild()


class StrategicSessionRead(APIModel):
    id: str
    name: str
    topic: str
    domain_id: str
    subject_id: str | None = None
    subject_name: str | None = None
    market: str | None = None
    theater: str | None = None
    actor_template: str | None = None
    tick_count: int | None = None
    tenant_id: str | None = None
    preset_id: str | None = None
    source_preferences: dict[str, Any] = Field(default_factory=dict)
    auto_refresh_enabled: bool = True
    refresh_timezone: str = "UTC"
    refresh_hour_local: int = 9
    next_refresh_at: datetime | None = None
    refresh_attempts: int = 0
    last_refresh_error: str | None = None
    latest_brief_summary: str | None = None
    latest_run_summary: str | None = None
    latest_debate_verdict: str | None = None
    latest_briefed_at: datetime | None = None
    latest_run_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class StrategicBriefRecordRead(APIModel):
    id: str
    session_id: str
    tenant_id: str | None = None
    preset_id: str | None = None
    domain_id: str
    summary: str
    source_count: int = 0
    analysis: AnalysisResponse
    generated_at: datetime


class StrategicRunSnapshotRead(APIModel):
    id: str
    session_id: str
    tenant_id: str | None = None
    preset_id: str | None = None
    ingest_run_id: str | None = None
    simulation_run_id: str | None = None
    debate_id: str | None = None
    generated_report_id: str | None = None
    latest_prediction_version: dict[str, Any] | None = None
    result: StrategicAssistantResponse
    generated_at: datetime


class RecommendationVersionRead(APIModel):
    id: str
    session_id: str
    watch_rule_id: str | None = None
    tenant_id: str | None = None
    preset_id: str | None = None
    version_number: int
    trigger_type: str
    trigger_source_change_id: str | None = None
    source_change_ids: list[str] = Field(default_factory=list)
    significance: str = "none"
    change_summary: str | None = None
    recommendation_summary: str
    result_payload: dict[str, Any] = Field(default_factory=dict)
    source_snapshot: list[dict[str, Any]] = Field(default_factory=list)
    ingest_run_id: str | None = None
    simulation_run_id: str | None = None
    debate_id: str | None = None
    generated_at: datetime


class StrategicSessionDetailRead(APIModel):
    session: StrategicSessionRead
    daily_briefs: list[StrategicBriefRecordRead] = Field(default_factory=list)
    recent_runs: list[StrategicRunSnapshotRead] = Field(default_factory=list)
    recommendation_versions: list[RecommendationVersionRead] = Field(default_factory=list)


StrategicRunSnapshotRead.model_rebuild()


UserDecisionValue = Literal["adopt", "defer", "need_more_info", "reject"]


class UserDecisionCreate(APIModel):
    session_id: str
    decision: UserDecisionValue
    notes: str | None = None


class UserDecisionOutcomeUpdate(APIModel):
    outcome: str


class UserDecisionRead(APIModel):
    id: str
    session_id: str
    decision: UserDecisionValue
    notes: str | None = None
    outcome: str | None = None
    outcome_recorded_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class UserDecisionStatsRead(APIModel):
    total: int
    counts: dict[str, int] = Field(default_factory=dict)
    ratios: dict[str, float] = Field(default_factory=dict)


class OpenAIStatusResponse(APIModel):
    configured: bool
    responses_api: bool = True
    auth_mode: str = "api_key"
    configured_targets: list[str] = Field(default_factory=list)
    primary_configured: bool
    extraction_configured: bool
    x_search_configured: bool
    report_configured: bool
    primary_model: str
    resolved_primary_model: str
    extraction_model: str
    x_search_model: str
    report_model: str
    primary_base_url: str | None = None
    extraction_base_url: str | None = None
    x_search_base_url: str | None = None
    report_base_url: str | None = None
    resolved_extraction_model: str
    resolved_x_search_model: str
    resolved_report_model: str
    model_sources: dict[str, str] = Field(default_factory=dict)
    api_key_sources: dict[str, str] = Field(default_factory=dict)
    base_url_sources: dict[str, str] = Field(default_factory=dict)
    target_diagnostics: dict[str, dict[str, Any]] = Field(default_factory=dict)
    base_url: str | None = None
    last_error: str | None = None


class OpenAITestRequest(APIModel):
    target: Literal[
        "primary",
        "extraction",
        "x_search",
        "report",
        "debate_advocate",
        "debate_challenger",
        "debate_arbitrator",
    ] = "primary"
    model: str | None = None
    prompt: str = "Reply with exactly: OK"
    max_output_tokens: int = Field(default=32, ge=1, le=256)


class OpenAITestResponse(APIModel):
    ok: bool
    configured: bool
    target: str
    model: str
    resolved_model: str
    base_url: str | None = None
    api_mode: Literal["responses", "chat.completions", "chat.completions.raw"] | None = None
    response_id: str | None = None
    output_text: str | None = None
    last_error: str | None = None


class WatchRuleCreate(APIModel):
    session_id: str | None = None
    name: str = Field(min_length=1)
    domain_id: Literal["corporate", "military"]
    query: str = Field(min_length=1)
    source_types: list[str] = Field(
        default_factory=lambda: [
            "google_news",
            "reddit",
            "hacker_news",
            "github",
            "rss",
            "gdelt",
            "aviation",
        ]
    )
    keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    entity_tags: list[str] = Field(default_factory=list)
    trigger_threshold: float = Field(default=0.0, ge=0.0, le=1.0)
    min_new_evidence_count: int = Field(default=1, ge=0, le=50)
    importance_threshold: float = Field(default=0.0, ge=0.0, le=1.0)
    poll_interval_minutes: int = Field(default=60, ge=5, le=1440)
    auto_trigger_simulation: bool = False
    auto_trigger_debate: bool = False
    tick_count: int = Field(default=0, ge=0)
    incremental_enabled: bool = True
    force_full_refresh_every_minutes: int = Field(default=24 * 60, ge=1, le=24 * 60)
    change_significance_threshold: Literal["none", "low", "medium", "high"] = "medium"
    tenant_id: str | None = None
    preset_id: str | None = None


class WatchRuleUpdate(APIModel):
    session_id: str | None = None
    name: str | None = None
    query: str | None = None
    source_types: list[str] | None = None
    keywords: list[str] | None = None
    exclude_keywords: list[str] | None = None
    entity_tags: list[str] | None = None
    trigger_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    min_new_evidence_count: int | None = Field(default=None, ge=0, le=50)
    importance_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    poll_interval_minutes: int | None = Field(default=None, ge=5, le=1440)
    enabled: bool | None = None
    auto_trigger_simulation: bool | None = None
    auto_trigger_debate: bool | None = None
    tick_count: int | None = Field(default=None, ge=0)
    incremental_enabled: bool | None = None
    force_full_refresh_every_minutes: int | None = Field(default=None, ge=1, le=24 * 60)
    change_significance_threshold: Literal["none", "low", "medium", "high"] | None = None


class WatchRuleRead(APIModel):
    id: str
    session_id: str | None = None
    name: str
    domain_id: str
    query: str
    source_types: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    entity_tags: list[str] = Field(default_factory=list)
    trigger_threshold: float = 0.0
    min_new_evidence_count: int = 1
    importance_threshold: float = 0.0
    poll_interval_minutes: int
    enabled: bool
    next_poll_at: datetime | None = None
    poll_attempts: int = 0
    last_poll_at: datetime | None = None
    last_poll_error: str | None = None
    auto_trigger_simulation: bool
    auto_trigger_debate: bool
    tick_count: int
    incremental_enabled: bool = True
    force_full_refresh_every_minutes: int = 24 * 60
    last_cursor_reset_at: datetime | None = None
    change_significance_threshold: str = "medium"
    tenant_id: str | None = None
    preset_id: str | None = None
    created_at: datetime
    updated_at: datetime


class WatchRuleTriggerRead(APIModel):
    rule_id: str
    rule_name: str
    status: str
    ingest_run_id: str | None = None
    sources_fetched: int = 0
    simulation_run_id: str | None = None
    debate_id: str | None = None
    recommendation_version_id: str | None = None
    error: str | None = None


class ReplayPackageRead(APIModel):
    run_id: str
    domain_id: str
    package: dict[str, Any]
    created_at: datetime


class JarvisRunCreate(APIModel):
    run_id: str | None = None
    target_type: Literal["run", "claim", "report", "debate", "analysis"] = "run"
    target_id: str | None = None
    prompt: str | None = None


class JarvisRunRead(APIModel):
    id: str
    run_id: str | None = None
    target_type: str
    target_id: str | None = None
    status: str
    profile_id: str
    result_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class DecisionOptionCreate(APIModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    expected_effects: dict[str, Any] = Field(default_factory=dict)
    risks: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    conditions: list[str] = Field(default_factory=list)
    ranking: int = Field(default=1, ge=1)


class DecisionOptionRead(APIModel):
    id: str
    run_id: str
    tenant_id: str | None = None
    preset_id: str | None = None
    title: str
    description: str
    expected_effects: dict[str, Any] = Field(default_factory=dict)
    risks: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float
    conditions: list[str] = Field(default_factory=list)
    ranking: int
    created_at: datetime | None = None


class HypothesisCreate(APIModel):
    prediction: str = Field(min_length=1)
    time_horizon: str = Field(default="3_months", min_length=1, max_length=64)
    decision_option_id: str | None = None


class HypothesisVerify(APIModel):
    verification_status: Literal["PENDING", "CONFIRMED", "REFUTED", "PARTIAL"]
    actual_outcome: str | None = None


class HypothesisRead(APIModel):
    id: str
    run_id: str
    decision_option_id: str | None = None
    prediction_version_id: str | None = None
    tenant_id: str | None = None
    preset_id: str | None = None
    prediction: str
    time_horizon: str
    verification_status: str
    actual_outcome: str | None = None
    verified_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PredictionSeriesRead(APIModel):
    id: str
    subject_type: str
    subject_id: str | None = None
    domain_id: str
    tenant_id: str | None = None
    preset_id: str | None = None
    source_run_id: str | None = None
    current_version_id: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def populate_domain(cls, value: object) -> object:
        if isinstance(value, dict) or hasattr(value, "domain_id"):
            return value
        metadata = getattr(value, "series_metadata", {}) or {}
        return {
            "id": value.id,
            "subject_type": value.subject_type,
            "subject_id": value.subject_id,
            "domain_id": metadata.get("domain_id", "unknown"),
            "tenant_id": value.tenant_id,
            "preset_id": value.preset_id,
            "source_run_id": value.source_run_id,
            "current_version_id": value.current_version_id,
            "status": value.status,
            "created_at": value.created_at,
            "updated_at": value.updated_at,
        }


class PredictionVersionRead(APIModel):
    id: str
    series_id: str
    version_number: int
    run_id: str | None = None
    hypothesis_id: str | None = None
    decision_option_id: str | None = None
    parent_version_id: str | None = None
    trigger_type: str
    trigger_event_id: str | None = None
    prediction_text: str
    time_horizon: str
    probability: float | None = None
    confidence: float | None = None
    status: str
    summary_delta: str | None = None
    created_at: datetime
    superseded_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def populate_version_aliases(cls, value: object) -> object:
        if isinstance(value, dict) or hasattr(value, "parent_version_id"):
            return value
        metadata = getattr(value, "version_metadata", {}) or {}
        return {
            "id": value.id,
            "series_id": value.series_id,
            "version_number": value.version_number,
            "run_id": value.run_id,
            "hypothesis_id": metadata.get("hypothesis_id"),
            "decision_option_id": metadata.get("decision_option_id"),
            "parent_version_id": getattr(value, "base_version_id", None),
            "trigger_type": value.trigger_type,
            "trigger_event_id": getattr(value, "trigger_ref_id", None),
            "prediction_text": value.prediction_text,
            "time_horizon": metadata.get("time_horizon") or "3_months",
            "probability": value.probability,
            "confidence": value.confidence,
            "status": value.status,
            "summary_delta": metadata.get("summary_delta"),
            "created_at": value.created_at,
            "superseded_at": None,
        }


class PredictionEvidenceLinkRead(APIModel):
    id: str
    prediction_version_id: str
    evidence_item_id: str | None = None
    claim_id: str | None = None
    run_id: str | None = None
    decision_record_id: str | None = None
    link_type: str
    impact_score: float
    impact_direction: str
    impact_reason: str | None = None
    created_at: datetime

    @model_validator(mode="before")
    @classmethod
    def populate_link_aliases(cls, value: object) -> object:
        if isinstance(value, dict) or hasattr(value, "prediction_version_id"):
            return value
        return {
            "id": value.id,
            "prediction_version_id": value.version_id,
            "evidence_item_id": value.evidence_item_id,
            "claim_id": value.claim_id,
            "run_id": None,
            "decision_record_id": None,
            "link_type": value.link_type,
            "impact_score": value.impact_score,
            "impact_direction": "unknown",
            "impact_reason": None,
            "created_at": value.created_at,
        }


class PredictionRevisionJobRead(APIModel):
    id: str
    series_id: str
    base_version_id: str | None = None
    trigger_claim_id: str | None = None
    trigger_evidence_item_id: str | None = None
    trigger_topic: str | None = None
    status: str
    reason: str | None = None
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    attempts: int
    last_error: str | None = None
    new_run_id: str | None = None
    new_version_id: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def populate_job_aliases(cls, value: object) -> object:
        if isinstance(value, dict) or hasattr(value, "trigger_claim_id"):
            return value
        metadata = getattr(value, "job_metadata", {}) or {}
        return {
            "id": value.id,
            "series_id": value.series_id,
            "base_version_id": value.base_version_id,
            "trigger_claim_id": getattr(value, "claim_id", None),
            "trigger_evidence_item_id": getattr(value, "evidence_item_id", None),
            "trigger_topic": metadata.get("trigger_topic"),
            "status": value.status,
            "reason": value.reason,
            "lease_owner": value.lease_owner,
            "lease_expires_at": value.lease_expires_at,
            "attempts": getattr(value, "processing_attempts", 0),
            "last_error": value.last_error,
            "new_run_id": getattr(value, "revision_run_id", None),
            "new_version_id": metadata.get("new_version_id"),
            "created_at": value.created_at,
            "updated_at": value.updated_at,
            "completed_at": value.completed_at,
        }


class RefForecastRequest(APIModel):
    reason: str | None = None
    trigger_claim_id: str | None = None
    trigger_evidence_item_id: str | None = None
    trigger_topic: str = "manual"


class CalibrationRead(APIModel):
    id: str
    domain_id: str
    tenant_id: str | None = None
    period_start: datetime
    period_end: datetime
    total_hypotheses: int
    confirmed: int
    refuted: int
    partial: int
    pending: int
    calibration_score: float
    rule_accuracy: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class CalibrationComputeRequest(APIModel):
    domain_id: str
    tenant_id: str | None = None


class SourceCursorStateRead(APIModel):
    id: str
    watch_rule_id: str | None = None
    tenant_id: str | None = None
    preset_id: str | None = None
    source_type: str
    source_url_or_query: str
    cursor: str | None = None
    health_status: str = "pending"
    etag: str | None = None
    last_modified: str | None = None
    last_seen_hash: str | None = None
    last_seen_raw_source_item_id: str | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_checked_at: datetime | None = None
    last_change_at: datetime | None = None
    consecutive_failures: int = 0
    created_at: datetime
    updated_at: datetime


class SourceChangeRecordRead(APIModel):
    id: str
    source_state_id: str
    watch_rule_id: str | None = None
    old_raw_source_item_id: str | None = None
    new_raw_source_item_id: str | None = None
    old_hash: str | None = None
    new_hash: str | None = None
    change_type: str
    significance: str
    diff_summary: str | None = None
    changed_fields: dict
    claim_ids: list
    prediction_revision_job_ids: list
    created_at: datetime

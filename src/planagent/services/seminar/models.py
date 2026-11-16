"""Seminar API / stored models (Sprint 16).

Dependency-free Pydantic models for the multi-model seminar mechanism
(design: ``seminar-mechanism-design.md``). Every model here is both an
API shape and a stored shape: roster entries, configs, digests, and
rounds validate their stored JSON back into these models, so stored
and served shapes cannot drift — the Sprint 1-5 fragment discipline,
applied to dedicated tables.

Credential iron rule: endpoint configuration carries target names and
environment variable NAMES only. Keys never appear in a request body,
a stored row, or a log line.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from planagent.config.openai import TARGET_NAMES
from planagent.services.seminar.locks import (
    DEFAULT_LEASE_TTL_SECONDS,
    DEFAULT_LOCK_WAIT_TIMEOUT_SECONDS,
)

MAX_ROSTER_MODELS = 10
MAX_SEMINAR_ROUNDS = 10

#: The chair model id recorded on agent-chair reports (Sprint 18):
#: the chair is the agent (Glint), not a roster model. Stored on the
#: report row and rendered in the report header as chair provenance.
AGENT_CHAIR_MODEL_ID = "glint-agent"

#: Default per-seminar budget: 200 stage-call attempts (design §10.3/
#: §14). Counts attempts, so retries consume budget too.
DEFAULT_MAX_STAGE_CALLS = 200

#: Default per-seminar token budget: 1,000,000 tokens. Generous on
#: purpose — the guardrail catches runaway seminars, not normal ones.
DEFAULT_MAX_TOKENS = 1_000_000

#: Default timeout-only retries (design §10.3): 2 retries = 3 attempts.
DEFAULT_MAX_RETRIES = 2

#: Default fixed backoff between timeout retries (seconds).
DEFAULT_RETRY_BACKOFF_SECONDS = 1.0

#: Default Jaccard threshold for near-duplicate pre-pass grouping.
DEFAULT_NEAR_DUPLICATE_THRESHOLD = 0.8

#: Default audit retention policy floor (Sprint 19): a purge may
#: never retain fewer than 1000 events or drop events younger than
#: 90 days unless the seminar was created with a looser policy
#: (including None = no floor on that dimension).
DEFAULT_AUDIT_RETENTION_MAX_EVENTS = 1000
DEFAULT_AUDIT_RETENTION_MAX_AGE_DAYS = 90


def _strip_text(value: object) -> object:
    if isinstance(value, str):
        return value.strip()
    return value


class _StripMixin(BaseModel):
    @field_validator("*", mode="before")
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        return _strip_text(value)


class EndpointConfig(_StripMixin):
    """How one model is reached: a configured target OR an inline endpoint.

    Exactly one form: ``target`` names a configured OpenAI target
    (primary/extraction/...), or the inline form names environment
    variables holding the base URL and API key plus a model name.
    """

    model_config = ConfigDict(extra="forbid")

    target: str | None = None
    base_url_env: str | None = Field(default=None, max_length=120)
    api_key_env: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def _exactly_one_form(self) -> EndpointConfig:
        inline = self.base_url_env is not None or self.api_key_env is not None
        if self.target is not None and inline:
            raise ValueError(
                "Endpoint must use exactly one form: 'target' or "
                "'base_url_env'/'api_key_env', not both."
            )
        if self.target is None and not inline:
            raise ValueError(
                "Endpoint must declare 'target' or an inline 'base_url_env'/'api_key_env' endpoint."
            )
        if self.target is not None and self.target not in TARGET_NAMES:
            raise ValueError(
                f"Unknown LLM target {self.target!r}; known targets: {', '.join(TARGET_NAMES)}."
            )
        if inline and self.api_key_env is None:
            raise ValueError("An inline endpoint requires 'api_key_env'.")
        if inline and self.model is None:
            raise ValueError("An inline endpoint requires 'model'.")
        return self


class ModelPortConfig(_StripMixin):
    """One model's port configuration: endpoint + temperature + timeout.

    Defaults preserve the existing single-model behavior exactly:
    target ``primary``, temperature 0.3. The timeout default (180s) is
    the design's roster default — the 45s Sprint 6 default proved too
    short for deliberation stages on the live 2026-11-16 runs.
    """

    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=1, max_length=120)
    endpoint: EndpointConfig = Field(default_factory=lambda: EndpointConfig(target="primary"))
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    timeout_seconds: float = Field(default=180.0, gt=0.0, le=3600.0)


class RosterEntry(ModelPortConfig):
    """One seminar participant: a port config plus round/role settings."""

    max_rounds: int | None = Field(default=None, ge=1, le=MAX_SEMINAR_ROUNDS)
    role: Literal["participant", "chair"] = "participant"


class SeminarConfig(_StripMixin):
    """Stored seminar configuration (frozen at creation)."""

    model_config = ConfigDict(extra="forbid")

    pipeline: Literal["strategy_team", "advisory_board"] = "strategy_team"
    mode: str = "standard"
    max_rounds: int = Field(default=3, ge=1, le=MAX_SEMINAR_ROUNDS)
    quiet_rounds: int = Field(default=2, ge=1, le=MAX_SEMINAR_ROUNDS)
    snapshot_policy: Literal["latest_per_model"] = "latest_per_model"
    max_concurrency: int = Field(default=3, ge=1, le=MAX_ROSTER_MODELS)
    output_language: str = Field(default="English", max_length=40)
    include_premortem: bool = True
    failure_date: str = Field(default="one year from now", max_length=120)
    decision_question: str = Field(default="", max_length=1000)
    options: list[str] = Field(default_factory=list, max_length=20)
    context_lines: list[str] = Field(default_factory=list, max_length=50)
    chair_participates: bool = False
    chair_mode: Literal["model", "agent"] = "model"
    max_stage_calls: int = Field(default=DEFAULT_MAX_STAGE_CALLS, ge=1)
    max_tokens: int = Field(default=DEFAULT_MAX_TOKENS, ge=1)
    max_retries: int = Field(default=DEFAULT_MAX_RETRIES, ge=0, le=5)
    retry_backoff_seconds: float = Field(default=DEFAULT_RETRY_BACKOFF_SECONDS, ge=0.0, le=60.0)
    near_duplicate_threshold: float = Field(
        default=DEFAULT_NEAR_DUPLICATE_THRESHOLD, gt=0.0, le=1.0
    )
    similarity_provider: Literal["jaccard", "embedding"] = "jaccard"
    synthesize_lock_provider: Literal["process", "lease"] = "process"
    lease_ttl_seconds: float = Field(default=DEFAULT_LEASE_TTL_SECONDS, gt=0.0, le=3600.0)
    lock_wait_timeout_seconds: float = Field(
        default=DEFAULT_LOCK_WAIT_TIMEOUT_SECONDS, gt=0.0, le=600.0
    )
    audit_retention_max_events: int | None = Field(default=DEFAULT_AUDIT_RETENTION_MAX_EVENTS, ge=1)
    audit_retention_max_age_days: int | None = Field(
        default=DEFAULT_AUDIT_RETENTION_MAX_AGE_DAYS, ge=1
    )

    @model_validator(mode="after")
    def _mode_matches_pipeline(self) -> SeminarConfig:
        allowed = (
            {"standard", "deep"} if self.pipeline == "strategy_team" else {"quick", "standard"}
        )
        if self.mode not in allowed:
            raise ValueError(
                f"Mode {self.mode!r} is not valid for pipeline "
                f"{self.pipeline!r}; allowed: {', '.join(sorted(allowed))}."
            )
        return self


class SeminarCreateRequest(_StripMixin):
    """Create a seminar over a completed run (design §12)."""

    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=1, max_length=500)
    decision_question: str = Field(default="", max_length=1000)
    options: list[str] = Field(default_factory=list, max_length=20)
    roster: list[RosterEntry] = Field(default_factory=list, max_length=MAX_ROSTER_MODELS)
    pipeline: Literal["strategy_team", "advisory_board"] = "strategy_team"
    mode: str = "standard"
    max_rounds: int = Field(default=3, ge=1, le=MAX_SEMINAR_ROUNDS)
    quiet_rounds: int = Field(default=2, ge=1, le=MAX_SEMINAR_ROUNDS)
    snapshot_policy: Literal["latest_per_model"] = "latest_per_model"
    max_concurrency: int = Field(default=3, ge=1, le=MAX_ROSTER_MODELS)
    output_language: str = Field(default="English", max_length=40)
    include_premortem: bool = True
    failure_date: str = Field(default="one year from now", max_length=120)
    chair_model: ModelPortConfig
    context_lines: list[str] = Field(default_factory=list, max_length=50)
    chair_mode: Literal["model", "agent"] = "model"
    max_stage_calls: int = Field(default=DEFAULT_MAX_STAGE_CALLS, ge=1)
    max_tokens: int = Field(default=DEFAULT_MAX_TOKENS, ge=1)
    max_retries: int = Field(default=DEFAULT_MAX_RETRIES, ge=0, le=5)
    retry_backoff_seconds: float = Field(default=DEFAULT_RETRY_BACKOFF_SECONDS, ge=0.0, le=60.0)
    near_duplicate_threshold: float = Field(
        default=DEFAULT_NEAR_DUPLICATE_THRESHOLD, gt=0.0, le=1.0
    )
    similarity_provider: Literal["jaccard", "embedding"] = "jaccard"
    synthesize_lock_provider: Literal["process", "lease"] = "process"
    lease_ttl_seconds: float = Field(default=DEFAULT_LEASE_TTL_SECONDS, gt=0.0, le=3600.0)
    lock_wait_timeout_seconds: float = Field(
        default=DEFAULT_LOCK_WAIT_TIMEOUT_SECONDS, gt=0.0, le=600.0
    )
    audit_retention_max_events: int | None = Field(default=DEFAULT_AUDIT_RETENTION_MAX_EVENTS, ge=1)
    audit_retention_max_age_days: int | None = Field(
        default=DEFAULT_AUDIT_RETENTION_MAX_AGE_DAYS, ge=1
    )

    @model_validator(mode="after")
    def _mode_matches_pipeline(self) -> SeminarCreateRequest:
        # Same rule as SeminarConfig; validated here so a bad request
        # fails before any row is written.
        SeminarConfig(
            pipeline=self.pipeline,
            mode=self.mode,
            max_rounds=self.max_rounds,
            quiet_rounds=self.quiet_rounds,
            snapshot_policy=self.snapshot_policy,
            max_concurrency=self.max_concurrency,
            output_language=self.output_language,
            include_premortem=self.include_premortem,
            failure_date=self.failure_date,
            decision_question=self.decision_question,
            options=self.options,
            context_lines=self.context_lines,
        )
        return self

    def to_config(self, *, chair_participates: bool) -> SeminarConfig:
        return SeminarConfig(
            pipeline=self.pipeline,
            mode=self.mode,
            max_rounds=self.max_rounds,
            quiet_rounds=self.quiet_rounds,
            snapshot_policy=self.snapshot_policy,
            max_concurrency=self.max_concurrency,
            output_language=self.output_language,
            include_premortem=self.include_premortem,
            failure_date=self.failure_date,
            decision_question=self.decision_question,
            options=list(self.options),
            context_lines=list(self.context_lines),
            chair_participates=chair_participates,
            chair_mode=self.chair_mode,
            max_stage_calls=self.max_stage_calls,
            max_tokens=self.max_tokens,
            max_retries=self.max_retries,
            retry_backoff_seconds=self.retry_backoff_seconds,
            near_duplicate_threshold=self.near_duplicate_threshold,
            similarity_provider=self.similarity_provider,
            synthesize_lock_provider=self.synthesize_lock_provider,
            lease_ttl_seconds=self.lease_ttl_seconds,
            lock_wait_timeout_seconds=self.lock_wait_timeout_seconds,
            audit_retention_max_events=self.audit_retention_max_events,
            audit_retention_max_age_days=self.audit_retention_max_age_days,
        )


class SeminarStatus(str, Enum):
    """Seminar state machine (design §2). Strictly forward-only."""

    OPEN = "open"
    RUNNING = "running"
    COLLECTING = "collecting"
    SYNTHESIZING = "synthesizing"
    REPORTED = "reported"
    PARTIAL = "partial"


_ALLOWED_TRANSITIONS: dict[SeminarStatus, frozenset[SeminarStatus]] = {
    # open -> collecting: a first wave that terminates every model
    # (all converged/capped/failed) lands directly in collecting; the
    # running state is never observable for such a seminar.
    SeminarStatus.OPEN: frozenset({SeminarStatus.RUNNING, SeminarStatus.COLLECTING}),
    # running -> synthesizing: the explicit close (design §2): the
    # caller synthesizes before every model terminates; the report is
    # partial iff finals are missing (derived from stored rows, not
    # from the prior status).
    SeminarStatus.RUNNING: frozenset(
        {SeminarStatus.RUNNING, SeminarStatus.COLLECTING, SeminarStatus.SYNTHESIZING}
    ),
    SeminarStatus.COLLECTING: frozenset(
        {SeminarStatus.COLLECTING, SeminarStatus.SYNTHESIZING, SeminarStatus.PARTIAL}
    ),
    SeminarStatus.SYNTHESIZING: frozenset(
        {SeminarStatus.REPORTED, SeminarStatus.PARTIAL, SeminarStatus.COLLECTING}
    ),
    # reported/partial -> synthesizing: versioned re-synthesis
    # (design §10.1: a failed chair synthesis may be retried later as
    # a NEW version, never overwriting). This is the only backward
    # step, and the append-only versioning keeps the audit trail.
    SeminarStatus.REPORTED: frozenset({SeminarStatus.SYNTHESIZING}),
    SeminarStatus.PARTIAL: frozenset({SeminarStatus.SYNTHESIZING}),
}


def validate_seminar_transition(current: str, target: str) -> None:
    """Refuse any state-machine step outside the allowed forward set.

    S16 code performs open → running → collecting only; S17 adds the
    synthesize transitions (collecting/running/reported/partial →
    synthesizing → reported/partial, plus synthesizing → collecting
    as the failure rollback). Re-synthesis from reported/partial is
    the only backward step and always creates a new report version.
    """
    current_status = SeminarStatus(current)
    target_status = SeminarStatus(target)
    if target_status not in _ALLOWED_TRANSITIONS[current_status]:
        raise ValueError(f"Illegal seminar transition {current!r} -> {target!r}.")


# Round statuses: "completed" (analysis + reflection stored),
# "failed" (analysis failed; no digest published), and
# "completed_reflection_missing" (stage-level isolation: the analysis
# stands, a digest is published marked reflection-missing, and the
# model is terminated as failed per design §5.3).
RoundStatus = Literal["completed", "failed", "completed_reflection_missing"]

# Per-model status, DERIVED from stored rounds + finals (never stored
# separately, so it cannot drift from the audit trail).
ModelStatus = Literal["active", "converged", "capped", "failed", "final"]


class BoardDigest(BaseModel):
    """One round's structured board publication (design §4.1)."""

    model_config = ConfigDict(extra="forbid")

    model_id: str
    round_no: int
    recommendation: str
    confidence: Literal["low", "medium", "high"] | None = None
    key_arguments: list[str] = Field(default_factory=list)
    kill_criteria: list[str] = Field(default_factory=list)
    changes: list[str] = Field(default_factory=list)
    reflection_missing: bool = False
    board_snapshot_seq: int


class RoundError(BaseModel):
    """A recorded round failure: taxonomy kind + stage + message.

    ``kind`` is an :class:`~planagent.services.seminar.errors.ErrorKind`
    value (timeout / contract / truncated / unavailable /
    budget_exhausted / cancelled / error), formalized in Sprint 18
    (design §10.2); ``truncated`` added in fix batch 2.
    """

    model_config = ConfigDict(extra="forbid")

    kind: str
    stage: str | None = None
    message: str


class SeminarCreateRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seminar_id: str
    run_id: str
    status: str
    case_snapshot_hash: str
    topic: str
    roster: list[RosterEntry]
    config: SeminarConfig
    chair_model: ModelPortConfig


class AdvanceModelRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str
    round_no: int
    status: str
    board_snapshot_seq: int


class AdvanceRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seminar_id: str
    wave_no: int
    per_model: list[AdvanceModelRead] = Field(default_factory=list)
    status: str


class FinalizeModelRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str
    status: str
    error: dict[str, Any] | None = None


class FinalizeRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seminar_id: str
    finals: list[FinalizeModelRead] = Field(default_factory=list)
    status: str


class SynthesizeRequest(BaseModel):
    """Synthesize a seminar report (design §12).

    ``allow_partial`` relaxes the two-final minimum to one final
    (design §10.4); zero finals always refuse, since there is nothing
    to cluster. Partiality of the resulting report is derived from
    stored rows (finals < roster), never from this flag alone.
    ``deterministic_fallback`` skips the chair stages and writes a
    deterministic report (design §7.4: the caller may require the
    deterministic composer); in agent-chair mode it is the explicit
    re-synthesize fallback path.
    """

    model_config = ConfigDict(extra="forbid")

    allow_partial: bool = False
    deterministic_fallback: bool = False


class ChairBriefRead(BaseModel):
    """The chair brief for an agent-chair seminar (Sprint 18).

    Produced (and stored, versioned) by POST /synthesize when
    ``chair_mode`` is ``agent``: everything the agent chair needs to
    write the clustering + synthesis, and nothing else — pre-pass
    clusters with exact + near-duplicate groups, disagreements
    derived in code, computed metrics, verbatim verdicts, the
    participation note, and absent models. The brief pins the item
    set the submission's merge-map coverage is validated against;
    ``brief_version`` + ``brief_hash`` identify it in the audit
    trail. No report is written by the brief step; the seminar
    awaits chair input via POST /chair-synthesis.
    """

    model_config = ConfigDict(extra="forbid")

    seminar_id: str
    brief_version: int
    brief_hash: str
    topic: str
    status: str
    chair_mode: str = "agent"
    chair_model_id: str = AGENT_CHAIR_MODEL_ID
    prepass: dict[str, Any]
    deterministic_clusters: dict[str, Any]
    disagreements: list[dict[str, Any]] = Field(default_factory=list)
    computed_metrics: dict[str, Any]
    verdicts: list[dict[str, Any]] = Field(default_factory=list)
    participation_note: str
    absent_models: list[dict[str, Any]] = Field(default_factory=list)
    finals_used: int
    roster_size: int
    partial: bool
    submit_endpoint: str


class ChairSynthesisRequest(BaseModel):
    """An agent chair's submission (Sprint 18).

    Both payloads are validated against the SAME contracts the model
    chair's outputs are validated against (``ClaimClusters`` and
    ``SeminarSynthesis``), and the clustering goes through the SAME
    merge-map coverage enforcement. ``brief_version`` pins which
    stored brief the submission answers (default: the latest brief);
    the submission is validated against that brief's pre-pass items.
    """

    model_config = ConfigDict(extra="forbid")

    clusters: dict[str, Any]
    synthesis: dict[str, Any]
    brief_version: int | None = None


class SynthesizeRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str
    seminar_id: str
    version: int
    partial: bool
    agreement_level: str | None
    production_path: str
    cluster_production: str
    fallback_reason: str | None = None
    report_hash: str
    chair_model_id: str
    status: str


class SeminarModelProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str
    status: str
    rounds: int
    has_final: bool
    latest_board_seq: int | None = None


class SeminarReportSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    partial: bool
    production_path: str
    cluster_production: str
    report_hash: str
    chair_model_id: str


class SeminarDetailRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seminar_id: str
    run_id: str
    topic: str
    status: str
    case_snapshot_hash: str
    roster: list[RosterEntry]
    config: SeminarConfig
    chair_model: ModelPortConfig
    per_model: list[SeminarModelProgress] = Field(default_factory=list)
    board_publications: int = 0
    board_latest_seq: int = 0
    finals_count: int = 0
    reports: list[SeminarReportSummary] = Field(default_factory=list)
    budgets: dict[str, Any] = Field(default_factory=dict)
    diagnosis: dict[str, Any] = Field(default_factory=dict)
    retention: dict[str, Any] = Field(default_factory=dict)


class AuditRetentionRead(BaseModel):
    """Audit-log retention status (Sprint 19).

    ``oldest_seq``/``newest_seq`` expose the surviving seq range —
    after a purge the oldest seq is > 1, which is how a reader
    knows history was compacted. ``max_events``/``max_age_days``
    are the seminar's configured policy floor (None = no floor on
    that dimension).
    """

    model_config = ConfigDict(extra="forbid")

    seminar_id: str
    event_count: int
    oldest_seq: int | None = None
    newest_seq: int | None = None
    max_events: int | None = None
    max_age_days: int | None = None


class AuditPurgeRequest(BaseModel):
    """An explicit audit-retention purge (Sprint 19).

    At least one criterion is required. An event survives only if
    it satisfies EVERY given bound (among the newest
    ``keep_last_n`` AND younger than ``older_than_days``). Criteria
    that would purge below the seminar's configured policy floor
    refuse (``seminar_retention_floor``): ``keep_last_n`` below the
    policy's max events, or ``older_than_days`` below the policy's
    max age. No scheduler or background job ever purges — this
    endpoint is the only purge path (Sprint 9 boundary).
    """

    model_config = ConfigDict(extra="forbid")

    keep_last_n: int | None = Field(default=None, ge=0)
    older_than_days: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _at_least_one_criterion(self) -> AuditPurgeRequest:
        if self.keep_last_n is None and self.older_than_days is None:
            raise ValueError(
                "A purge requires at least one criterion: 'keep_last_n' and/or 'older_than_days'."
            )
        return self


class AuditPurgeRead(BaseModel):
    """The outcome of an explicit audit-retention purge."""

    model_config = ConfigDict(extra="forbid")

    seminar_id: str
    deleted_count: int
    deleted_oldest_seq: int | None = None
    deleted_newest_seq: int | None = None
    remaining_count: int
    retention: AuditRetentionRead


class SeminarSummaryRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seminar_id: str
    run_id: str
    topic: str
    status: str
    roster_size: int
    finals_count: int
    report_versions: int


class BoardRowRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    seminar_id: str
    seq: int
    model_id: str
    round_no: int
    digest: dict[str, Any]


class RoundRowRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    seminar_id: str
    model_id: str
    round_no: int
    board_snapshot_seq: int
    stages: list[dict[str, Any]]
    reflection: dict[str, Any] | None = None
    reflection_stage: dict[str, Any] | None = None
    status: str
    error: dict[str, Any] | None = None


class FinalRowRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    seminar_id: str
    model_id: str
    verdict: dict[str, Any]
    stage: dict[str, Any]
    board_snapshot_seq: int
    status: str


class ReportDetailRead(BaseModel):
    """One report version: row metadata plus the composed document."""

    model_config = ConfigDict(extra="forbid")

    report_id: str
    seminar_id: str
    version: int
    partial: bool
    chair_model_id: str
    report_hash: str
    document: dict[str, Any]


__all__ = [
    "AGENT_CHAIR_MODEL_ID",
    "DEFAULT_AUDIT_RETENTION_MAX_AGE_DAYS",
    "DEFAULT_AUDIT_RETENTION_MAX_EVENTS",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_MAX_STAGE_CALLS",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_NEAR_DUPLICATE_THRESHOLD",
    "DEFAULT_RETRY_BACKOFF_SECONDS",
    "MAX_ROSTER_MODELS",
    "MAX_SEMINAR_ROUNDS",
    "AdvanceModelRead",
    "AdvanceRead",
    "AuditPurgeRead",
    "AuditPurgeRequest",
    "AuditRetentionRead",
    "BoardDigest",
    "BoardRowRead",
    "ChairBriefRead",
    "ChairSynthesisRequest",
    "EndpointConfig",
    "FinalRowRead",
    "FinalizeModelRead",
    "FinalizeRead",
    "ModelPortConfig",
    "ModelStatus",
    "ReportDetailRead",
    "RosterEntry",
    "RoundError",
    "RoundRowRead",
    "RoundStatus",
    "SeminarConfig",
    "SeminarCreateRead",
    "SeminarCreateRequest",
    "SeminarDetailRead",
    "SeminarModelProgress",
    "SeminarReportSummary",
    "SeminarStatus",
    "SeminarSummaryRead",
    "SynthesizeRead",
    "SynthesizeRequest",
    "validate_seminar_transition",
]

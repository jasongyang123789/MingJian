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

MAX_ROSTER_MODELS = 10
MAX_SEMINAR_ROUNDS = 10


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
    SeminarStatus.RUNNING: frozenset({SeminarStatus.RUNNING, SeminarStatus.COLLECTING}),
    SeminarStatus.COLLECTING: frozenset(
        {SeminarStatus.COLLECTING, SeminarStatus.SYNTHESIZING, SeminarStatus.PARTIAL}
    ),
    SeminarStatus.SYNTHESIZING: frozenset(
        {SeminarStatus.REPORTED, SeminarStatus.PARTIAL, SeminarStatus.COLLECTING}
    ),
    SeminarStatus.REPORTED: frozenset(),
    SeminarStatus.PARTIAL: frozenset(),
}


def validate_seminar_transition(current: str, target: str) -> None:
    """Refuse any state-machine step outside the allowed forward set.

    S16 code performs open → running → collecting only; the
    synthesizing/reported/partial transitions exist for S17 and are
    never produced by S16 code paths.
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
    """A recorded round failure: best-effort kind + stage + message.

    The formal error taxonomy (timeout/contract/unavailable/cancelled)
    is S18; S16 records the exception-derived kind string honestly and
    isolates the failure per model.
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


__all__ = [
    "MAX_ROSTER_MODELS",
    "MAX_SEMINAR_ROUNDS",
    "AdvanceModelRead",
    "AdvanceRead",
    "BoardDigest",
    "EndpointConfig",
    "FinalizeModelRead",
    "FinalizeRead",
    "ModelPortConfig",
    "ModelStatus",
    "RosterEntry",
    "RoundError",
    "RoundStatus",
    "SeminarConfig",
    "SeminarCreateRead",
    "SeminarCreateRequest",
    "SeminarStatus",
    "validate_seminar_transition",
]

"""Chair stage runners (Sprint 17, design §7).

Thin wrappers over :func:`run_seminar_stage` for the two chair
stages: ``seminar.cluster`` (semantic clustering over the
deterministic pre-pass) and ``seminar.synthesize`` (unified
synthesis over clustered claims + disagreements + verbatim verdicts
+ computed metrics). Prompt inputs are rendered from stored
artifacts only; the chair never sees full round stage outputs —
verdicts + board digests are the boundary (design §5.2/§6).

Both runners raise on stage failure (unavailable port, empty
response, contract violation); the service layer converts a chair
failure into the deterministic fallback path and records it — the
failure itself is never hidden.
"""

from __future__ import annotations

from typing import Any

from planagent.services.distributions.canonical import canonical_json
from planagent.services.seminar.clustering import (
    render_clustered_claims,
    render_disagreements,
    render_prepass_groups,
    render_quoted_claims,
)
from planagent.services.seminar.contracts import (
    ClaimClusters,
    SeminarSynthesis,
)
from planagent.services.seminar.engine import run_seminar_stage
from planagent.services.skills.orchestration import SkillLLMPort, StageRecord


def render_quoted_verdicts(verdicts: list[dict[str, Any]]) -> str:
    """Render final verdicts verbatim, labeled by source model."""
    blocks = []
    for entry in verdicts:
        blocks.append(
            f"[verdict: {entry['model_id']}]\n"
            + canonical_json(entry["verdict"])
        )
    return "\n\n".join(blocks) if blocks else "(No verdicts.)"


async def run_cluster(
    port: SkillLLMPort,
    *,
    topic: str,
    prepass: dict[str, Any],
    output_language: str,
) -> tuple[ClaimClusters, StageRecord]:
    """Run the ``seminar.cluster`` stage. Raises on stage failure."""
    record = await run_seminar_stage(
        port,
        stage="cluster",
        template_id="seminar.cluster",
        inputs={
            "topic": topic,
            "quoted_claims": render_quoted_claims(prepass),
            "prepass_groups": render_prepass_groups(prepass),
            "output_language": output_language,
        },
    )
    return ClaimClusters.model_validate(record.output), record


async def run_synthesize(
    port: SkillLLMPort,
    *,
    topic: str,
    clusters: dict[str, Any],
    verdicts: list[dict[str, Any]],
    computed_metrics: dict[str, Any],
    chair_participates: bool,
    chair_model_id: str,
    output_language: str,
) -> tuple[SeminarSynthesis, StageRecord]:
    """Run the ``seminar.synthesize`` stage. Raises on stage failure."""
    if chair_participates:
        participation = (
            f"The chair model ({chair_model_id}) ALSO participated in this "
            "seminar as a roster model. Its verdict was weighted equally "
            "with the others in clustering and in the computed metrics; "
            "guard against self-preference when weighing its verdict."
        )
    else:
        participation = (
            f"The chair model ({chair_model_id}) did NOT participate in "
            "this seminar; it synthesizes the roster models' verdicts only."
        )
    record = await run_seminar_stage(
        port,
        stage="synthesize",
        template_id="seminar.synthesize",
        inputs={
            "topic": topic,
            "clustered_claims": render_clustered_claims(clusters),
            "disagreements": render_disagreements(clusters),
            "quoted_verdicts": render_quoted_verdicts(verdicts),
            "computed_metrics": canonical_json(computed_metrics),
            "chair_participation": participation,
            "output_language": output_language,
        },
    )
    return SeminarSynthesis.model_validate(record.output), record


__all__ = ["render_quoted_verdicts", "run_cluster", "run_synthesize"]

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

Sprint 18 adds the agent-chair brief: :func:`build_chair_brief`
assembles, from stored artifacts only, everything an agent chair
needs to write the clustering + synthesis — the same deterministic
inputs the model chair's prompts are rendered from, plus the
participation note and absent models. The brief pins the item set
the submission is validated against.
"""

from __future__ import annotations

from typing import Any

from planagent.services.distributions.canonical import canonical_json, sha256_hash
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
from planagent.services.seminar.models import AGENT_CHAIR_MODEL_ID
from planagent.services.skills.orchestration import SkillLLMPort, StageRecord


def participation_note(
    *,
    chair_participates: bool,
    chair_model_id: str,
    chair_mode: str = "model",
) -> str:
    """The participation note for chair prompts and the chair brief.

    States plainly whether the chair also participated as a roster
    model (self-preference risk, design §3.2), or — in agent mode —
    that the chair is the agent, never a roster model.
    """
    if chair_mode == "agent":
        return (
            f"The chair is the agent chair ({AGENT_CHAIR_MODEL_ID}), not a "
            "roster model: it did NOT participate in this seminar and has "
            "no verdict of its own. It synthesizes the roster models' "
            "verdicts only."
        )
    if chair_participates:
        return (
            f"The chair model ({chair_model_id}) ALSO participated in this "
            "seminar as a roster model. Its verdict was weighted equally "
            "with the others in clustering and in the computed metrics; "
            "guard against self-preference when weighing its verdict."
        )
    return (
        f"The chair model ({chair_model_id}) did NOT participate in "
        "this seminar; it synthesizes the roster models' verdicts only."
    )


def build_chair_brief(
    *,
    seminar_id: str,
    topic: str,
    status: str,
    brief_version: int,
    prepass: dict[str, Any],
    deterministic_clusters: dict[str, Any],
    computed_metrics: dict[str, Any],
    verdicts: list[dict[str, Any]],
    absent_models: list[dict[str, Any]],
    chair_participates: bool,
    chair_model_id: str,
    chair_mode: str,
) -> dict[str, Any]:
    """Assemble the agent-chair brief document (pure function).

    The brief is the deterministic half of the synthesis: pre-pass
    items + groups, deterministic clusters, disagreements derived in
    code, computed metrics, verbatim verdicts, the participation
    note, and absent models. ``brief_hash`` covers the deterministic
    content (pre-pass, metrics, verbatim verdicts, partial flag) so
    a submission can be tied to exactly the brief it answered.
    """
    partial = bool(computed_metrics.get("finals_used", len(verdicts)) < computed_metrics.get("roster_size", len(verdicts)))
    brief_hash = sha256_hash(
        {
            "seminar_id": seminar_id,
            "prepass": prepass,
            "computed_metrics": computed_metrics,
            "verdicts": [entry["verdict"] for entry in verdicts],
            "partial": partial,
        }
    )
    return {
        "seminar_id": seminar_id,
        "brief_version": brief_version,
        "brief_hash": brief_hash,
        "topic": topic,
        "status": status,
        "chair_mode": chair_mode,
        "chair_model_id": chair_model_id,
        "prepass": prepass,
        "deterministic_clusters": deterministic_clusters,
        "disagreements": deterministic_clusters.get("disagreements") or [],
        "computed_metrics": computed_metrics,
        "verdicts": verdicts,
        "participation_note": participation_note(
            chair_participates=chair_participates,
            chair_model_id=chair_model_id,
            chair_mode=chair_mode,
        ),
        "absent_models": absent_models,
        "finals_used": int(computed_metrics.get("finals_used", len(verdicts))),
        "roster_size": int(computed_metrics.get("roster_size", 0)),
        "partial": partial,
        "submit_endpoint": f"POST /seminars/{seminar_id}/chair-synthesis",
    }


def render_quoted_verdicts(verdicts: list[dict[str, Any]]) -> str:
    """Render final verdicts verbatim, labeled by source model."""
    blocks = []
    for entry in verdicts:
        blocks.append(f"[verdict: {entry['model_id']}]\n" + canonical_json(entry["verdict"]))
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
    participation = participation_note(
        chair_participates=chair_participates,
        chair_model_id=chair_model_id,
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


__all__ = [
    "build_chair_brief",
    "participation_note",
    "render_quoted_verdicts",
    "run_cluster",
    "run_synthesize",
]

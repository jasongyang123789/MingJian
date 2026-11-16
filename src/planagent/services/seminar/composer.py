"""Deterministic seminar report composer (Sprint 17, design §7.4/§8).

A pure function assembling the full §8 report document from stored
artifacts. Both production paths use the same composer: the chair
path fills the narrative sections from the validated
``SeminarSynthesis`` contract (provenance ``deliberated``); the
fallback path fills them with explicit "not generated" notes
(provenance ``template``) naming the endpoint that can produce them
— the Sprint 13 discipline: template text never fabricates, it
states what is missing and where it comes from.

Deterministic sections (computed metrics, verbatim verdict material,
pre-pass clusters, disagreement derivation) are byte-identical for
identical stored inputs. The composer performs no LLM call, no I/O,
and no numeric invention: every number comes from the computed
metrics block or the stored verdicts.
"""

from __future__ import annotations

from typing import Any

from planagent.services.seminar.clustering import DISSENT_PLACEHOLDER


def _template_note(*, seminar_id: str, missing: str, reason: str) -> str:
    return (
        f"Not generated — {missing} unavailable ({reason}). "
        f"Re-run POST /seminars/{seminar_id}/synthesize to produce a chair synthesis."
    )


def _evidence_union(
    claims: list[dict[str, Any]], *, field: str
) -> list[dict[str, Any]]:
    """Deduped union of canonical claims sourced from one verdict field.

    Each entry carries the canonical claim text plus the distinct
    source models (roster order of first appearance). Claims sourced
    from several fields appear under each of their fields.
    """
    union: list[dict[str, Any]] = []
    for claim in claims:
        models: list[str] = []
        for source in claim["sources"]:
            if source["field"] == field and source["model_id"] not in models:
                models.append(str(source["model_id"]))
        if models:
            union.append({"text": str(claim["claim"]), "source_models": models})
    return union


def _verbatim_minority_report(verdicts: list[dict[str, Any]]) -> str:
    """Verbatim dissent union: every dissent_held item, labeled by model."""
    lines: list[str] = []
    for entry in verdicts:
        verdict = entry["verdict"] or {}
        for item in verdict.get("dissent_held") or []:
            text = str(item)
            if text.strip() and text.strip() != DISSENT_PLACEHOLDER:
                lines.append(f"[{entry['model_id']}] {text}")
    if not lines:
        return "No dissenting views were held: every model wrote \"None\" for dissent_held."
    return "\n".join(lines)


def compose_report(
    *,
    seminar_id: str,
    run_id: str,
    topic: str,
    version: int,
    partial: bool,
    chair_model_id: str,
    chair_participates: bool,
    case_snapshot_hash: str,
    roster: list[dict[str, Any]],
    chair_config: dict[str, Any],
    clusters: dict[str, Any],
    synthesis_envelope: dict[str, Any],
    computed_metrics: dict[str, Any],
    verdicts: list[dict[str, Any]],
    round_rows: list[dict[str, Any]],
    board_rows: list[dict[str, Any]],
    report_hash: str,
) -> dict[str, Any]:
    """Assemble the §8 report document from stored artifacts."""
    synthesis = synthesis_envelope.get("synthesis")
    synthesis_path = str(synthesis_envelope.get("production_path", "unknown"))
    fallback_reason = synthesis_envelope.get("fallback_reason")
    cluster_production = str(clusters.get("production", "unknown"))
    claims = clusters.get("claims") or []
    disagreements = clusters.get("disagreements") or []
    chair_path = synthesis is not None and synthesis_path == "chair"

    header: dict[str, Any] = {
        "seminar_id": seminar_id,
        "run_id": run_id,
        "topic": topic,
        "version": version,
        "partial": partial,
        "chair_model_id": chair_model_id,
        "chair_participates": chair_participates,
        "production_path": synthesis_path,
        "cluster_production": cluster_production,
        "report_hash": report_hash,
        "finals_used": int(computed_metrics.get("finals_used", len(verdicts))),
        "roster_size": int(computed_metrics.get("roster_size", len(roster))),
        "absent_models": computed_metrics.get("absent_models") or [],
    }
    if chair_participates:
        header["chair_participation_flag"] = (
            "The chair model also participated in this seminar as a roster model. "
            "Its verdict was weighted equally with the other models in clustering "
            "and in the Borda count; the chair synthesis must be read with this "
            "self-preference risk in mind (design §3.2, §17.2)."
        )
    if fallback_reason:
        header["fallback_reason"] = str(fallback_reason)

    if chair_path:
        assert isinstance(synthesis, dict)
        unified = {
            "text": str(synthesis["unified_recommendation"]),
            "basis": str(synthesis["recommendation_basis"]),
            "provenance": "deliberated",
        }
        agreement = {
            "chair_level": str(synthesis["agreement_level"]),
            "chair_provenance": "deliberated",
            "computed": computed_metrics.get("recommendation_agreement"),
            "computed_provenance": "computed",
            "note": (
                "The chair's agreement level is a judgment; the computed "
                "agreement rate is deterministic. They are presented side "
                "by side and neither substitutes for the other."
            ),
        }
        alternatives = {
            "borda": computed_metrics.get("borda"),
            "borda_provenance": "computed",
            "chair_ranked": list(synthesis["alternatives_ranked"]),
            "aggregation_rule": str(synthesis["aggregation_rule"]),
            "chair_provenance": "deliberated",
        }
        minority = {
            "text": str(synthesis["minority_report"]),
            "provenance": "deliberated",
            "verbatim": True,
        }
        open_questions = {
            "items": list(synthesis["open_questions"]),
            "provenance": "deliberated",
        }
        chair_notes = {
            "text": str(synthesis["chair_notes"]),
            "provenance": "deliberated",
        }
        chair_synthesis_section: dict[str, Any] | None = dict(synthesis)
    else:
        reason = str(fallback_reason or "chair synthesis unavailable")
        unified = {
            "text": _template_note(
                seminar_id=seminar_id, missing="chair synthesis", reason=reason
            ),
            "basis": None,
            "provenance": "template",
        }
        agreement = {
            "chair_level": None,
            "chair_provenance": "template",
            "computed": computed_metrics.get("recommendation_agreement"),
            "computed_provenance": "computed",
            "note": (
                "No chair agreement judgment was produced; only the computed "
                "agreement rate is available. "
                + _template_note(
                    seminar_id=seminar_id, missing="chair synthesis", reason=reason
                )
            ),
        }
        alternatives = {
            "borda": computed_metrics.get("borda"),
            "borda_provenance": "computed",
            "chair_ranked": None,
            "aggregation_rule": _template_note(
                seminar_id=seminar_id, missing="chair synthesis", reason=reason
            ),
            "chair_provenance": "template",
        }
        minority = {
            "text": _verbatim_minority_report(verdicts),
            "provenance": "deliberated",
            "verbatim": True,
        }
        open_questions = {
            "items": [],
            "provenance": "template",
            "note": _template_note(
                seminar_id=seminar_id, missing="chair synthesis", reason=reason
            ),
        }
        chair_notes = {
            "text": _template_note(
                seminar_id=seminar_id, missing="chair synthesis", reason=reason
            ),
            "provenance": "template",
        }
        chair_synthesis_section = None

    rounds_evolution = [
        {
            "model_id": str(entry["model_id"]),
            "rounds_summary": str((entry["verdict"] or {}).get("rounds_summary") or ""),
            "board_snapshot_seq": int(entry.get("board_snapshot_seq", 0)),
            "verbatim": True,
        }
        for entry in verdicts
    ]

    audit = {
        "case_snapshot_hash": case_snapshot_hash,
        "cluster_stage": clusters.get("stage"),
        "synthesis_stage": synthesis_envelope.get("stage"),
        "verdict_stages": [
            {
                "model_id": str(entry["model_id"]),
                "template_id": str((entry.get("stage") or {}).get("template_id")),
                "template_version": str((entry.get("stage") or {}).get("template_version")),
                "contract_version": str((entry.get("stage") or {}).get("contract_version")),
                "model": (entry.get("stage") or {}).get("model"),
            }
            for entry in verdicts
        ],
        "round_stage_counts": {
            str(model_id): sum(
                len(row.get("stages") or [])
                for row in round_rows
                if str(row["model_id"]) == model_id
            )
            for model_id in [str(entry.get("model_id")) for entry in roster]
        },
        "board_seq_range": (
            [int(board_rows[0]["seq"]), int(board_rows[-1]["seq"])] if board_rows else []
        ),
        "board_publications": len(board_rows),
        "model_configs": [
            {
                "model_id": str(entry.get("model_id")),
                "endpoint": entry.get("endpoint"),
                "temperature": entry.get("temperature"),
                "timeout_seconds": entry.get("timeout_seconds"),
                "max_rounds": entry.get("max_rounds"),
                "role": entry.get("role"),
            }
            for entry in roster
        ],
        "chair_config": {
            "model_id": chair_model_id,
            "endpoint": chair_config.get("endpoint"),
            "temperature": chair_config.get("temperature"),
            "timeout_seconds": chair_config.get("timeout_seconds"),
        },
        "token_usage": (
            "Not recorded: the Sprint 6 port protocol returns no usage "
            "figures (token accounting is S18 scope)."
        ),
    }

    return {
        "header": header,
        "unified_recommendation": unified,
        "agreement": agreement,
        "canonical_claims": {
            "claims": claims,
            "merge_map": clusters.get("merge_map") or {},
            "provenance": "deliberated" if cluster_production == "llm" else "computed",
            "production": cluster_production,
        },
        "disagreements": {
            "items": disagreements,
            "count": len(disagreements),
            "provenance": "computed",
            "note": "Derived in code from mixed claim stances; disagreements are identified, never resolved.",
        },
        "alternatives": alternatives,
        "key_evidence": {
            "items": _evidence_union(claims, field="key_evidence"),
            "provenance": "deliberated" if cluster_production == "llm" else "computed",
        },
        "kill_criteria": {
            "items": _evidence_union(claims, field="kill_criteria"),
            "provenance": "deliberated" if cluster_production == "llm" else "computed",
        },
        "minority_report": minority,
        "rounds_evolution": rounds_evolution,
        "open_questions": open_questions,
        "chair_notes": chair_notes,
        "chair_synthesis": chair_synthesis_section,
        "computed_metrics": computed_metrics,
        "audit_appendix": audit,
    }


__all__ = ["compose_report"]

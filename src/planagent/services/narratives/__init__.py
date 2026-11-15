"""Decision-direction narrative output (Sprint 13).

The deterministic composer assembles 1-4 decision directions from
stored artifacts only (ensembles, robustness results, decision gates,
deliberations, MECE trees, calibration fits, loop triggers) into a
versioned, hashed JSON artifact. No LLM call happens in the default
path; the optional polish hook lives in :mod:`polish` and is strictly
separated from the artifact.
"""

from __future__ import annotations

from planagent.services.narratives.composer import (
    DirectionInputs,
    LoopContextInput,
    NarrativeInputs,
    compose_narrative,
)
from planagent.services.narratives.models import (
    NARRATIVE_PROTOCOL_VERSION,
    DecisionNarrativeListRead,
    DecisionNarrativeRead,
    DirectionDefinition,
    NarrativeError,
    NarrativeGenerateRequest,
    NarrativePolishRead,
    ProvenanceKind,
)
from planagent.services.narratives.render import render_narrative_markdown

__all__ = [
    "NARRATIVE_PROTOCOL_VERSION",
    "DecisionNarrativeListRead",
    "DecisionNarrativeRead",
    "DirectionDefinition",
    "DirectionInputs",
    "LoopContextInput",
    "NarrativeError",
    "NarrativeGenerateRequest",
    "NarrativeInputs",
    "NarrativePolishRead",
    "ProvenanceKind",
    "compose_narrative",
    "render_narrative_markdown",
]

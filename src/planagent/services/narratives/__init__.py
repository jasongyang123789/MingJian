"""Decision-direction narrative output (Sprint 13).

The deterministic composer assembles 1-4 decision directions from
stored artifacts only (ensembles, robustness results, decision gates,
deliberations, MECE trees, calibration fits, loop triggers) into a
versioned, hashed JSON artifact. No LLM call happens in the default
path; the optional polish hook lives in :mod:`polish` and is strictly
separated from the artifact. Sprint 14 adds deterministic direction
derivation (:mod:`derivation`: versioned rules over the anchor run's
scenario family, no new runs) and persisted direction mappings.
Option C adds LLM-proposed directions (:mod:`proposals`): grounded
proposals stored as ``proposed`` mappings, usable only after an
explicit human accept.
"""

from __future__ import annotations

from planagent.services.narratives.composer import (
    DirectionInputs,
    LoopContextInput,
    NarrativeInputs,
    compose_narrative,
)
from planagent.services.narratives.derivation import (
    DERIVATION_RULES_VERSION,
    DerivationCandidate,
    DerivationResult,
    derive_directions,
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
from planagent.services.narratives.proposals import (
    PROPOSAL_TEMPLATE_ID,
    PROPOSAL_TEMPLATE_VERSION,
    DirectionProposal,
    DirectionProposals,
    ProposalContext,
    build_proposal_user_content,
    propose_directions,
)
from planagent.services.narratives.recheck import PolishRecheck, check_polish
from planagent.services.narratives.render import render_narrative_markdown

__all__ = [
    "DERIVATION_RULES_VERSION",
    "NARRATIVE_PROTOCOL_VERSION",
    "PROPOSAL_TEMPLATE_ID",
    "PROPOSAL_TEMPLATE_VERSION",
    "DecisionNarrativeListRead",
    "DecisionNarrativeRead",
    "DerivationCandidate",
    "DerivationResult",
    "DirectionDefinition",
    "DirectionInputs",
    "DirectionProposal",
    "DirectionProposals",
    "LoopContextInput",
    "NarrativeError",
    "NarrativeGenerateRequest",
    "NarrativeInputs",
    "NarrativePolishRead",
    "PolishRecheck",
    "ProposalContext",
    "ProvenanceKind",
    "build_proposal_user_content",
    "check_polish",
    "compose_narrative",
    "derive_directions",
    "propose_directions",
    "render_narrative_markdown",
]

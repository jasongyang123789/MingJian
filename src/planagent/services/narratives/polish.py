"""Optional LLM polish hook for narratives (Sprint 13, item 3).

Strictly separated from the deterministic artifact: the polish pass
only rewrites the deterministic markdown for readability. The
structured artifact stays the source of truth; polished text is
stored alongside (append-only polish rows), marked LLM-generated
with the model name, and the deterministic rendering is always
available. LLM absence or failure degrades to the deterministic
rendering: the polish endpoint returns 503/502 and writes nothing.

No live LLM verification is possible on this VM (the provider
blocks direct SDK access — see the deliberation report at
~/workspace/delib-run/real-deliberation-2026-11-15/REPORT.md).
Tests drive this module through a scripted port, exactly like
Sprint 6. Live polish quality is UNVERIFIED.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from planagent.services.skills.contracts import SkillContractError
from planagent.services.skills.orchestration import SkillLLMPort, SkillLLMUnavailable

POLISH_TEMPLATE_ID = "narrative.polish"
POLISH_TEMPLATE_VERSION = "1"
POLISH_MAX_TOKENS = 4096

POLISH_SYSTEM_PROMPT = (
    "You rewrite a deterministic decision brief for readability. "
    'Return valid JSON only, with exactly one key, "polished_markdown". '
    "Do not compute new numbers. Do not add, remove, or change any number, "
    "claim, provenance mark, or trace id. Do not invent failure modes, "
    "signals, or next actions. Keep every [computed], [deliberated], and "
    "[template] mark attached to the same text it marked. You may only "
    "improve wording, structure, and flow. If the input is empty, return "
    "an empty string."
)


class PolishOutput(BaseModel):
    """Contract for one polish pass."""

    model_config = ConfigDict(extra="forbid")

    polished_markdown: str = Field(min_length=0)


async def polish_markdown(
    port: SkillLLMPort,
    markdown: str,
    *,
    max_tokens: int = POLISH_MAX_TOKENS,
) -> tuple[PolishOutput, str | None]:
    """Run one polish pass. Returns (output, model name).

    Raises :class:`SkillLLMUnavailable` when no LLM is configured and
    :class:`SkillContractError` when the output fails the contract.
    Nothing is fabricated: an empty or malformed response is a
    structured failure, never a silent pass-through.
    """
    if not port.is_available():
        raise SkillLLMUnavailable("No LLM service is configured for narrative polish.")
    response = await port.generate_json(
        template_id=POLISH_TEMPLATE_ID,
        system_prompt=POLISH_SYSTEM_PROMPT,
        user_content=markdown,
        max_tokens=max_tokens,
    )
    if response.payload is None:
        raise SkillContractError(
            POLISH_TEMPLATE_ID,
            [
                {
                    "loc": ("root",),
                    "msg": ("no usable JSON response (empty, unparseable, or upstream failure)"),
                }
            ],
        )
    try:
        output = PolishOutput.model_validate(response.payload)
    except ValidationError as exc:
        raise SkillContractError(POLISH_TEMPLATE_ID, exc.errors())
    return output, response.model


__all__ = [
    "POLISH_MAX_TOKENS",
    "POLISH_SYSTEM_PROMPT",
    "POLISH_TEMPLATE_ID",
    "POLISH_TEMPLATE_VERSION",
    "PolishOutput",
    "polish_markdown",
]

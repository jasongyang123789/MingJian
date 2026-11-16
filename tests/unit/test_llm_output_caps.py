"""Output-cap sweep tests (fix batch 2).

Pins the shared loose cap everywhere it applies OUTSIDE the skill /
seminar template registries (those are pinned in
test_skill_templates.py / test_seminar_templates.py): provider
defaults, the polish cap, the debate call sites, and the Jarvis call
sites. No live LLM call is made anywhere: providers are inspected by
signature, debate/Jarvis run against fake services that record the
requested cap.
"""

from __future__ import annotations

import inspect
from typing import Any

from planagent.config import Settings
from planagent.services.debate.llm import LLMDebateAdapter
from planagent.services.jarvis import JarvisOrchestrator, JarvisStepResult, JarvisTask
from planagent.services.narratives.polish import POLISH_MAX_TOKENS
from planagent.services.providers.anthropic_provider import AnthropicProvider
from planagent.services.providers.base import LLMProvider
from planagent.services.providers.openai_provider import OpenAIProvider
from planagent.services.skills.templates import JSON_CONTRACT_MAX_TOKENS


def test_shared_cap_value_is_8000() -> None:
    # 3.3x the largest legitimate contract output observed live
    # (2408 completion tokens, 2026-11-16). The cap is a ceiling, not
    # a target; the seminar budget + timeout are the real guards.
    assert JSON_CONTRACT_MAX_TOKENS == 8000


def test_provider_defaults_are_the_shared_loose_cap() -> None:
    # Every production caller passes max_tokens explicitly, so these
    # defaults are currently unreachable — but a 1024 default is a
    # truncation trap for the next caller. All six signatures share
    # the one value.
    for cls in (LLMProvider, OpenAIProvider, AnthropicProvider):
        for method in ("generate_text", "generate_json"):
            default = inspect.signature(getattr(cls, method)).parameters["max_tokens"].default
            assert default == JSON_CONTRACT_MAX_TOKENS == 8000, (cls.__name__, method)


def test_polish_cap_is_the_shared_loose_cap() -> None:
    # Polish output is a full rewrite of the input markdown, whose
    # length scales with the direction count — it uses the shared
    # cap, not a polish-specific value.
    assert POLISH_MAX_TOKENS == JSON_CONTRACT_MAX_TOKENS == 8000


class _CapturingOpenAIService:
    """Fake OpenAIService: records generate_json_for_target kwargs."""

    def __init__(self, parsed: dict[str, Any] | None) -> None:
        self.parsed = parsed
        self.calls: list[dict[str, Any]] = []

    def is_configured(self, target: str) -> bool:
        return True

    async def generate_json_for_target(self, **kwargs: Any) -> tuple[dict[str, Any], Any]:
        self.calls.append(kwargs)
        return {"model": "fake-model"}, self.parsed

    async def generate_debate_position(self, **kwargs: Any) -> None:
        raise AssertionError("fallback must not run when the JSON path parses")


async def test_debate_openai_path_requests_the_shared_cap() -> None:
    service = _CapturingOpenAIService(
        {
            "position": "SUPPORT",
            "confidence": 0.8,
            "arguments": [{"claim": "c", "reasoning": "r"}],
        }
    )
    adapter = LLMDebateAdapter(Settings(_env_file=None), service, None)  # type: ignore[arg-type]
    position = await adapter._call_openai_llm(
        role="advocate",
        topic="T",
        trigger_type="manual",
        context="C",
        opponent_arguments=None,
        own_previous=None,
    )
    assert position is not None
    assert position.position == "SUPPORT"
    assert len(service.calls) == 1
    assert service.calls[0]["max_tokens"] == JSON_CONTRACT_MAX_TOKENS == 8000


async def test_jarvis_self_review_requests_the_shared_cap() -> None:
    service = _CapturingOpenAIService({"status": "ok", "findings": [], "recommendations": []})
    orchestrator = JarvisOrchestrator(Settings(_env_file=None), service)  # type: ignore[arg-type]
    step = JarvisStepResult(
        step="validate_primary", target="primary", provider="openai", model="m", status="success"
    )
    result = await orchestrator._self_review(JarvisTask(task_type="analysis", payload={}), [step])
    assert result.step == "self_review"
    assert len(service.calls) == 1
    assert service.calls[0]["max_tokens"] == JSON_CONTRACT_MAX_TOKENS == 8000


async def test_jarvis_execute_target_requests_the_shared_cap() -> None:
    service = _CapturingOpenAIService({"status": "ok", "findings": [], "recommendations": []})
    orchestrator = JarvisOrchestrator(Settings(_env_file=None), service)  # type: ignore[arg-type]
    result = await orchestrator._execute_target(
        "primary", JarvisTask(task_type="analysis", payload={"query": "q"})
    )
    assert result.status == "success"
    assert len(service.calls) == 1
    assert service.calls[0]["max_tokens"] == JSON_CONTRACT_MAX_TOKENS == 8000

"""Parameterized skill LLM port (Sprint 16).

One port per roster entry: target/temperature/timeout configurable,
where the Sprint 6 :class:`OpenAIServiceSkillPort` binds target
``primary`` and temperature 0.3. Defaults preserve the existing
single-model behavior exactly (primary target, temperature 0.3); the
timeout default (180s) is the design's roster default.

Endpoint resolution is a pure function of settings + environment
variable names: keys are read from the environment at resolution time,
held in memory only, and never stored, logged, or returned. A target
entry resolves through the same ``resolved_openai_*`` settings
machinery ``OpenAIService`` uses, so target behavior matches the
existing client construction exactly. An inline entry reads its base
URL and key from the NAMED environment variables.

``is_available`` mirrors ``generate_json_for_target``'s two gates: a
key must resolve AND a model must resolve. The call path mirrors that
method's semantics (json_object response format, shared JSON
extraction, any failure → ``payload=None`` so the stage runner raises
a contract error). The formal timeout/contract/unavailable error
taxonomy is S18; S16 records failures honestly at the round level.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from openai import AsyncOpenAI

from planagent.config import Settings
from planagent.services.openai_client import extract_json_payload
from planagent.services.seminar.models import EndpointConfig, ModelPortConfig
from planagent.services.skills.orchestration import SkillLLMResponse


@dataclass(frozen=True)
class ResolvedEndpoint:
    """A resolved endpoint: credentials in memory only, never persisted."""

    base_url: str | None
    api_key: str | None
    model: str | None
    temperature: float
    timeout_seconds: float


def resolve_endpoint(
    settings: Settings,
    endpoint: EndpointConfig,
    *,
    temperature: float,
    timeout_seconds: float,
    env: Mapping[str, str] | None = None,
) -> ResolvedEndpoint:
    """Resolve an endpoint config to concrete connection parameters.

    Target entries read the ``resolved_openai_{target}_*`` settings
    (the same fallback machinery ``OpenAIService`` uses). Inline
    entries read the named environment variables; ``base_url_env`` is
    optional (absent → the client default).
    """
    environ = os.environ if env is None else env
    if endpoint.target is not None:
        target = endpoint.target
        return ResolvedEndpoint(
            base_url=getattr(settings, f"resolved_openai_{target}_base_url"),
            api_key=getattr(settings, f"resolved_openai_{target}_api_key"),
            model=getattr(settings, f"resolved_openai_{target}_model"),
            temperature=temperature,
            timeout_seconds=timeout_seconds,
        )
    base_url = (
        environ.get(endpoint.base_url_env)
        if endpoint.base_url_env is not None
        else None
    )
    api_key = (
        environ.get(endpoint.api_key_env)
        if endpoint.api_key_env is not None
        else None
    )
    return ResolvedEndpoint(
        base_url=base_url or None,
        api_key=api_key or None,
        model=endpoint.model,
        temperature=temperature,
        timeout_seconds=timeout_seconds,
    )


class ParameterizedSkillPort:
    """A SkillLLMPort bound to one roster entry's endpoint + parameters."""

    def __init__(self, resolved: ResolvedEndpoint) -> None:
        self._resolved = resolved
        self._client: AsyncOpenAI | None = None

    @property
    def resolved(self) -> ResolvedEndpoint:
        return self._resolved

    def is_available(self) -> bool:
        return bool(self._resolved.api_key) and bool(self._resolved.model)

    async def generate_json(
        self,
        *,
        template_id: str,
        system_prompt: str,
        user_content: str,
        max_tokens: int,
    ) -> SkillLLMResponse:
        if not self.is_available():
            return SkillLLMResponse(model=None, payload=None)
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self._resolved.api_key,
                base_url=self._resolved.base_url or None,
                timeout=self._resolved.timeout_seconds,
            )
        try:
            response = await self._client.chat.completions.create(
                model=self._resolved.model or "",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                max_tokens=max_tokens,
                temperature=self._resolved.temperature,
                response_format={"type": "json_object"},
            )
            text = response.choices[0].message.content or "{}"
            try:
                parsed = json.loads(extract_json_payload(text))
            except json.JSONDecodeError:
                parsed = None
            return SkillLLMResponse(
                model=self._resolved.model,
                payload=parsed if isinstance(parsed, dict) else None,
            )
        except Exception:
            return SkillLLMResponse(model=None, payload=None)


def default_port_factory(
    settings: Settings,
) -> Callable[[ModelPortConfig], ParameterizedSkillPort]:
    """Build the production port factory: one port per roster entry."""

    def build(config: ModelPortConfig) -> ParameterizedSkillPort:
        resolved = resolve_endpoint(
            settings,
            config.endpoint,
            temperature=config.temperature,
            timeout_seconds=config.timeout_seconds,
        )
        return ParameterizedSkillPort(resolved)

    return build


__all__ = [
    "ParameterizedSkillPort",
    "ResolvedEndpoint",
    "default_port_factory",
    "resolve_endpoint",
]

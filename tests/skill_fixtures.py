"""Shared fixtures for Sprint 6 skill tests: recorded LLM outputs + a
scripted port. No live LLM call is ever made: the port serves recorded
fixture JSON in call order, keyed by template id, and records every
call for assertion."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from planagent.services.skills.orchestration import LENS_ORDER, SkillLLMResponse, TokenUsage

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "skill_outputs"


def load_fixture(name: str) -> dict:
    with open(FIXTURE_DIR / f"{name}.json", encoding="utf-8") as handle:
        return json.load(handle)


class ScriptedSkillPort:
    """Fake LLM port: serves queued fixture payloads per template id.

    ``usage_script`` (Sprint 18) is an optional parallel queue of
    scripted :class:`TokenUsage` values per template id, popped in
    call order alongside the payloads, so tests can pin token
    accounting end to end. Queues shorter than the payload queues
    yield ``None`` usage for the remaining calls.

    ``finish_reason_script`` (fix batch 2) is the same idea for the
    SDK finish reason: a parallel queue of scripted finish reasons
    per template id, so tests can pin truncation classification.
    Queues shorter than the payload queues yield ``None`` (not
    reported) for the remaining calls.
    """

    def __init__(
        self,
        script: dict[str, list[dict]],
        *,
        available: bool = True,
        usage_script: dict[str, list[TokenUsage]] | None = None,
        finish_reason_script: dict[str, list[str | None]] | None = None,
    ) -> None:
        self._script = {key: [copy.deepcopy(item) for item in queue] for key, queue in script.items()}
        self._usage_script = {
            key: list(queue) for key, queue in (usage_script or {}).items()
        }
        self._finish_reason_script = {
            key: list(queue) for key, queue in (finish_reason_script or {}).items()
        }
        self._available = available
        self.calls: list[dict[str, str]] = []

    def is_available(self) -> bool:
        return self._available

    async def generate_json(
        self,
        *,
        template_id: str,
        system_prompt: str,
        user_content: str,
        max_tokens: int,
    ) -> SkillLLMResponse:
        self.calls.append(
            {
                "template_id": template_id,
                "system_prompt": system_prompt,
                "user_content": user_content,
                "max_tokens": str(max_tokens),
            }
        )
        queue = self._script.get(template_id)
        if not queue:
            raise AssertionError(f"No scripted response left for template {template_id!r}.")
        usage_queue = self._usage_script.get(template_id) or []
        usage = usage_queue.pop(0) if usage_queue else None
        finish_queue = self._finish_reason_script.get(template_id) or []
        finish_reason = finish_queue.pop(0) if finish_queue else None
        return SkillLLMResponse(
            model="fixture", payload=queue.pop(0), usage=usage, finish_reason=finish_reason
        )

    def assert_exhausted(self) -> None:
        remaining = {key: len(queue) for key, queue in self._script.items() if queue}
        assert not remaining, f"Unconsumed scripted responses: {remaining}"


def strategy_team_script(
    *, mode: str = "standard", include_premortem: bool = True
) -> dict[str, list[dict]]:
    generators = [load_fixture("option_generate_bull"), load_fixture("option_generate_lean")]
    if mode == "deep":
        generators.append(load_fixture("option_generate_contrarian"))
    wargame = [load_fixture("verify_wargame_round1")]
    if mode == "deep":
        wargame.append(load_fixture("verify_wargame_round2"))
        wargame.append(load_fixture("verify_wargame_round3"))
    script: dict[str, list[dict]] = {
        "mckinsey.intake_classify": [load_fixture("intake_classify")],
        "mckinsey.diagnose": [load_fixture("diagnose")],
        "mckinsey.market_map": [load_fixture("market_map")],
        "mckinsey.option_generate": generators,
        "mckinsey.filter_shortlist": [load_fixture("filter_shortlist")],
        "mckinsey.synthesize": [load_fixture("synthesize")],
        "mckinsey.verify_assumptions": [load_fixture("verify_assumptions")],
        "mckinsey.verify_wargame": wargame,
        "mckinsey.verify_execution": [load_fixture("verify_execution")],
    }
    if include_premortem:
        script["gambit.premortem"] = [load_fixture("premortem")]
    if mode == "deep":
        script["mckinsey.tournament_judge"] = [
            load_fixture("tournament_1"),
            load_fixture("tournament_2"),
            load_fixture("tournament_3"),
        ]
    return script


def advisory_board_script(
    *, mode: str = "standard", unanimous: bool = False, chair_verdict: str | None = None
) -> dict[str, list[dict]]:
    positions = []
    for lens in LENS_ORDER:
        position = load_fixture(f"lens_position_{lens}")
        if unanimous:
            position = copy.deepcopy(position)
            position["option_scores"] = {
                "Phased rollout": 9.0,
                "Full launch": 4.0,
                "Partner-led": 5.0,
            }
        positions.append(position)
    chair = load_fixture("chair_synthesis")
    if chair_verdict is not None:
        chair = copy.deepcopy(chair)
        chair["verdict"] = chair_verdict
    script: dict[str, list[dict]] = {
        "advisory.crit_intake": [load_fixture("crit_intake")],
        "advisory.lens_position": positions,
        "advisory.chair_synthesis": [chair],
    }
    if mode == "standard":
        script["advisory.forced_debate"] = [load_fixture("forced_debate")]
        script["advisory.lens_revision"] = [
            load_fixture(f"lens_revision_{lens}") for lens in LENS_ORDER
        ]
    return script


def mece_proposal_script(*, valid: bool = True) -> dict[str, list[dict]]:
    name = "mece_propose_valid" if valid else "mece_propose_invalid"
    return {"mece.propose_tree": [load_fixture(name)]}

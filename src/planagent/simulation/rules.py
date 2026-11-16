from __future__ import annotations

from dataclasses import dataclass
import importlib
import importlib.util
import math
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

import yaml


@dataclass(frozen=True)
class RuleEffect:
    target: str
    op: str
    value: float
    # Phase 1 (automotive track): optional id of a sampled variable or
    # derived formula value the effect scales with. When set, the applied
    # effect is ``value * scope[scale_by]`` where scope is the run's
    # sampled + initial derived values; when the id is absent from the
    # scope (a run without that binding), the factor falls back to 1.0
    # and the effect applies at its base value. None keeps the fixed
    # constant semantics exactly.
    scale_by: str | None = None


def scaled_effect_value(effect: RuleEffect, scope: Mapping[str, float] | None) -> float:
    """The value of a rule effect under variable scaling.

    ``scope`` carries the run's sampled + initial derived values. An
    effect without ``scale_by`` returns its base value unchanged; an
    effect with ``scale_by`` multiplies the base value by the scope
    value for that id, falling back to a factor of 1.0 when the id is
    missing from the scope or the scope value is not finite. Pure and
    deterministic.
    """

    if effect.scale_by is None or scope is None:
        return float(effect.value)
    factor = scope.get(effect.scale_by)
    if factor is None or not math.isfinite(float(factor)):
        return float(effect.value)
    return float(effect.value) * float(factor)


@dataclass(frozen=True)
class RuleCondition:
    field: str
    op: str
    value: Any


@dataclass(frozen=True)
class RuleSpec:
    rule_id: str
    domain: str
    action_id: str
    priority: int
    trigger_keywords: tuple[str, ...]
    trigger_conditions: tuple[RuleCondition, ...]
    effects: tuple[RuleEffect, ...]
    explanation_template: str
    handler_id: str | None = None

    def matches(self, statement: str) -> bool:
        lowered = statement.lower()
        return any(keyword.lower() in lowered for keyword in self.trigger_keywords)


RuleHandler = Callable[[dict[str, Any], dict[str, Any]], list[RuleEffect] | list[dict[str, Any]]]
_RULE_HANDLERS: dict[str, RuleHandler] = {}


def rule_handler(rule_id: str) -> Callable[[RuleHandler], RuleHandler]:
    def decorator(func: RuleHandler) -> RuleHandler:
        _RULE_HANDLERS[rule_id] = func
        return func

    return decorator


class RuleRegistry:
    def __init__(self, rules_root: Path) -> None:
        self.rules_root = rules_root
        self._cache: dict[str, list[RuleSpec]] = {}
        self._calibration_weights: dict[str, float] = {}
        self._loaded_python_modules: set[str] = set()

    @property
    def calibration_weights(self) -> dict[str, float]:
        return dict(self._calibration_weights)

    def effective_priority(self, rule: RuleSpec) -> float:
        weight = self._calibration_weights.get(rule.rule_id, 1.0)
        return round(float(rule.priority) * weight, 2)

    def apply_calibration(self, rule_accuracies: dict[str, float]) -> None:
        """Adjust rule weights based on calibration accuracy.

        - Accuracy >= 0.75: boost weight up to 1.3
        - Accuracy <= 0.35: reduce weight down to 0.6
        - Otherwise: drift toward 1.0
        """
        for rule_id, accuracy in rule_accuracies.items():
            accuracy = max(0.0, min(1.0, float(accuracy)))
            current = self._calibration_weights.get(rule_id, 1.0)
            if accuracy >= 0.75:
                target = min(1.3, 1.0 + (accuracy - 0.75) * 2.0)
            elif accuracy <= 0.35:
                target = max(0.6, 1.0 - (0.35 - accuracy) * 2.0)
            else:
                target = 1.0
            self._calibration_weights[rule_id] = round(current * 0.4 + target * 0.6, 4)

    def apply_fitted_weights(self, fitted_weights: dict[str, float]) -> dict[str, float]:
        """Apply ridge-calibrated rule weights (Sprint 5, PRD delta D8).

        Unlike :meth:`apply_calibration` (the calibration worker's
        periodic accuracy blend), this is an explicit, audited
        override: the caller supplies fitted weights from a stored
        calibration fit, and they replace the current weights outright.
        Weights are validated finite and clipped to [0.0, 2.0] — the
        same range the worker's ``weight_multiplier`` uses — and the
        applied (post-clip) mapping is returned so the caller can
        record exactly what took effect. Weights live in memory only:
        ``reload()`` resets them, and the worker's next
        ``apply_calibration`` blends from these values toward its
        accuracy targets. The durable record of a fitted-weights
        application is the calibration fit row, not this registry.
        """
        applied: dict[str, float] = {}
        for rule_id, weight in fitted_weights.items():
            value = float(weight)
            if not math.isfinite(value):
                raise ValueError(f"Fitted weight for rule {rule_id!r} must be finite.")
            clipped = round(min(2.0, max(0.0, value)), 4)
            self._calibration_weights[rule_id] = clipped
            applied[rule_id] = clipped
        return applied

    def get_rules(self, domain_id: str) -> list[RuleSpec]:
        if domain_id not in self._cache:
            self._cache[domain_id] = self._load_domain(domain_id)
        return self._cache[domain_id]

    def get_handler(self, rule_id: str) -> RuleHandler | None:
        return _RULE_HANDLERS.get(rule_id)

    def reload(self) -> tuple[list[str], int]:
        previous_cache = dict(self._cache)
        previous_calibration_weights = dict(self._calibration_weights)
        previous_loaded_modules = set(self._loaded_python_modules)
        previous_handlers = dict(_RULE_HANDLERS)

        self._cache = {}
        self._calibration_weights = {}
        self._loaded_python_modules = set()
        domains: list[str] = []
        total = 0
        try:
            if self.rules_root.exists():
                for candidate in sorted(
                    path.name for path in self.rules_root.iterdir() if path.is_dir()
                ):
                    rules = self.get_rules(candidate)
                    if rules:
                        domains.append(candidate)
                        total += len(rules)
        except Exception:
            self._cache = previous_cache
            self._calibration_weights = previous_calibration_weights
            self._loaded_python_modules = previous_loaded_modules
            _RULE_HANDLERS.clear()
            _RULE_HANDLERS.update(previous_handlers)
            raise
        return domains, total

    def _load_domain(self, domain_id: str) -> list[RuleSpec]:
        domain_root = self.rules_root / domain_id
        if not domain_root.exists():
            return []

        self._load_python_handlers(domain_root, domain_id)
        rules: list[RuleSpec] = []
        for yaml_path in sorted(domain_root.rglob("*.yaml")):
            with yaml_path.open("r", encoding="utf-8") as handle:
                payload = yaml.safe_load(handle) or {}
            for raw_rule in payload.get("rules", []):
                rules.append(self._parse_rule(raw_rule))
        rules.sort(key=lambda item: item.priority, reverse=True)
        return rules

    def _parse_rule(self, raw_rule: dict[str, Any]) -> RuleSpec:
        trigger = raw_rule.get("trigger", {})
        conditions = tuple(
            RuleCondition(
                field=str(condition.get("field", "")),
                op=str(condition.get("op", "eq")),
                value=condition.get("value"),
            )
            for condition in trigger.get("conditions", [])
            if isinstance(condition, dict)
        )
        condition_keywords = tuple(
            str(condition.value) for condition in conditions if condition.value is not None
        )
        effects = tuple(
            RuleEffect(
                target=effect["target"],
                op=effect.get("op", "add"),
                value=float(effect["value"]),
                scale_by=_parse_scale_by(effect),
            )
            for effect in raw_rule.get("effects", [])
        )
        rule_id = raw_rule["id"]
        action_id = raw_rule.get("action_id") or raw_rule.get("action") or "monitor"
        return RuleSpec(
            rule_id=rule_id,
            domain=raw_rule["domain"],
            action_id=action_id,
            priority=int(raw_rule.get("priority", 50)),
            trigger_keywords=tuple(trigger.get("keywords", ())) + condition_keywords,
            trigger_conditions=conditions,
            effects=effects,
            explanation_template=raw_rule.get(
                "explanation_template",
                "Rule {rule_id} matched the current evidence and selected {action_id}.",
            ),
            handler_id=raw_rule.get("handler") or (rule_id if rule_id in _RULE_HANDLERS else None),
        )

    def _load_python_handlers(self, domain_root: Path, domain_id: str) -> None:
        for python_path in sorted(domain_root.rglob("*.py")):
            module_key = str(python_path.resolve())
            if module_key in self._loaded_python_modules:
                continue
            module_name = f"planagent_dynamic_rules.{domain_id}.{python_path.stem}"
            spec = importlib.util.spec_from_file_location(module_name, python_path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self._loaded_python_modules.add(module_key)

        for module_name in _configured_rule_modules():
            if module_name in self._loaded_python_modules:
                continue
            importlib.import_module(module_name)
            self._loaded_python_modules.add(module_name)


def _parse_scale_by(effect: dict[str, Any]) -> str | None:
    """Parse an effect's optional ``scale_by`` variable id.

    Absent means a fixed constant effect. A present value must be a
    non-empty string naming a sampled variable or derived formula id;
    anything else fails rule loading loudly, like the existing strict
    ``float(value)`` parse, instead of silently scaling by garbage.
    """

    raw = effect.get("scale_by")
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"Rule effect scale_by must be a non-empty string id, got {raw!r}.")
    return raw.strip()


def _configured_rule_modules() -> list[str]:
    raw = os.getenv("PLANAGENT_RULE_MODULES", "")
    return [item.strip() for item in raw.split(",") if item.strip()]


_rule_registry: RuleRegistry | None = None


def get_rule_registry(rules_root: Path) -> RuleRegistry:
    global _rule_registry
    if _rule_registry is None or _rule_registry.rules_root != rules_root:
        _rule_registry = RuleRegistry(rules_root)
    return _rule_registry

"""RuleLoader: turn JSON-friendly specs into rule instances.

Generalizes nav-rewards ``RewardObject._load_rule``/``_load_rule_from_dict``.
Accepted spec shapes (all coming from JSON or DB rows):

* ``"ClassName"``
* ``["ClassName"]`` / ``["ClassName", {kwargs}]``
* ``{"rule_type": "ClassName", **kwargs}`` (or ``"type"`` key)
* an already-built AbstractRule instance (passed through)

Unlike the original (which logged and returned None, letting None leak into
the rule list), malformed specs raise :class:`RuleLoadError`.
"""
from __future__ import annotations

import importlib
import logging
from typing import Any, Callable, Optional, Sequence, Union

from .abstract import AbstractRule


class RuleLoadError(ValueError):
    """Raised when a rule spec cannot be resolved or instantiated."""


class RuleLoader:
    """Resolves rule class names and instantiates rules from specs.

    Args:
        modules: Module paths searched (in order) for rule classes by name.
        types: Explicit name -> class mapping, checked before modules.
        defaults_injector: ``(rule_name, kwargs) -> kwargs`` hook to inject
            per-consumer defaults (e.g. rewards injects current_reward_id for
            ComputedRule).
        conditions: Base condition spec merged into every loaded rule
            (rewards passes the reward-level conditions here).
    """

    def __init__(
        self,
        modules: Sequence[str] = ("navrules.abstract",),
        types: Optional[dict[str, type[AbstractRule]]] = None,
        defaults_injector: Optional[Callable[[str, dict], dict]] = None,
        conditions: Optional[dict] = None,
    ) -> None:
        self.modules = tuple(modules)
        self.types = dict(types or {})
        self.defaults_injector = defaults_injector
        self.conditions = conditions
        self.logger = logging.getLogger("navrules.RuleLoader")

    def register(self, name: str, rule_class: type[AbstractRule]) -> None:
        """Register an explicit rule class under a name."""
        self.types[name] = rule_class

    def resolve_class(self, rule_name: str) -> type[AbstractRule]:
        """Resolve a rule class by name from types, then modules."""
        if rule_name in self.types:
            return self.types[rule_name]
        for module_path in self.modules:
            try:
                module = importlib.import_module(module_path)
            except ModuleNotFoundError as exc:
                raise RuleLoadError(
                    f"Rule module {module_path!r} not importable: {exc}"
                ) from exc
            rule_class = getattr(module, rule_name, None)
            if rule_class is not None:
                if not (
                    isinstance(rule_class, type)
                    and issubclass(rule_class, AbstractRule)
                ):
                    raise RuleLoadError(
                        f"{module_path}.{rule_name} is not an AbstractRule"
                    )
                return rule_class
        raise RuleLoadError(
            f"Rule class {rule_name!r} not found in {self.modules}"
        )

    def load(
        self, spec: Union[str, list, dict, AbstractRule]
    ) -> AbstractRule:
        """Instantiate a rule from any accepted spec shape."""
        if isinstance(spec, AbstractRule):
            return spec
        if isinstance(spec, str):
            return self._instantiate(spec, {})
        if isinstance(spec, list):
            if not spec:
                raise RuleLoadError("Empty rule list spec")
            # Copy: the historical implementation popped from the caller's
            # list, corrupting reward definitions on reload.
            items = list(spec)
            rule_name = items.pop(0)
            kwargs = dict(items[0]) if items else {}
            return self._instantiate(rule_name, kwargs)
        if isinstance(spec, dict):
            payload = dict(spec)
            rule_name = payload.pop("rule_type", None) or payload.pop(
                "type", None
            )
            if not rule_name:
                raise RuleLoadError(
                    "Rule dict spec must contain 'rule_type' or 'type'"
                )
            return self._instantiate(rule_name, payload)
        raise RuleLoadError(f"Invalid rule spec type: {type(spec)}")

    def _instantiate(self, rule_name: str, kwargs: dict) -> AbstractRule:
        if not isinstance(rule_name, str):
            raise RuleLoadError(f"Invalid rule name: {rule_name!r}")
        if self.defaults_injector:
            kwargs = self.defaults_injector(rule_name, dict(kwargs))
        rule_class = self.resolve_class(rule_name)
        # Spec-level conditions win over loader-level base conditions.
        conditions = kwargs.pop("conditions", None)
        if conditions is None:
            conditions = self.conditions
        elif self.conditions:
            conditions = {**self.conditions, **conditions}
        self.logger.debug("Loading rule: %s", rule_name)
        try:
            return rule_class(conditions=conditions, **kwargs)
        except (TypeError, ValueError) as exc:
            raise RuleLoadError(
                f"Error instantiating rule {rule_name!r}: {exc}"
            ) from exc

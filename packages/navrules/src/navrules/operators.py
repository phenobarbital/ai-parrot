"""Single operator registry for condition evaluation.

Unifies the operator maps that were duplicated across nav-rewards
(``rules/achievement.py`` and ``rewards/workflow.py``) and extends them with
the operators the declarative condition DSL supports.

Comparison semantics (mirrored exactly by the Rust backend — keep in sync):

* A *missing* value (``MISSING`` sentinel or ``None``) only matches
  ``is_null``; every other operator returns ``False``, including ``ne``.
* ``int`` and ``float`` coerce to each other for every operator; ``bool``
  never coerces to a number (``True != 1`` here, unlike plain Python).
* Ordering operators (``gt``/``gte``/``lt``/``lte``/``between``) work on
  number pairs or ``str`` pairs; any other combination is a no-match.
"""
from __future__ import annotations

import re
from typing import Any, Callable


class Missing:
    """Sentinel for absent context values."""

    _instance: "Missing | None" = None

    def __new__(cls) -> "Missing":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "<MISSING>"

    def __bool__(self) -> bool:
        return False


MISSING = Missing()

OperatorFunc = Callable[[Any, Any], bool]


def _is_missing(value: Any) -> bool:
    return value is MISSING or value is None


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _eq(value: Any, operand: Any) -> bool:
    if isinstance(value, bool) or isinstance(operand, bool):
        return isinstance(value, bool) and isinstance(operand, bool) and value == operand
    if _is_number(value) and _is_number(operand):
        return float(value) == float(operand)
    if isinstance(value, (list, tuple)) and isinstance(operand, (list, tuple)):
        return len(value) == len(operand) and all(
            _eq(a, b) for a, b in zip(value, operand)
        )
    if type(value) is type(operand):
        return value == operand
    return False


def _ordering(value: Any, operand: Any, cmp: Callable[[Any, Any], bool]) -> bool:
    if _is_number(value) and _is_number(operand):
        return cmp(value, operand)
    if isinstance(value, str) and isinstance(operand, str):
        return cmp(value, operand)
    return False


def _contains(value: Any, operand: Any) -> bool:
    if isinstance(value, str) and isinstance(operand, str):
        return operand in value
    if isinstance(value, (list, tuple)):
        return any(_eq(item, operand) for item in value)
    return False


def _between(value: Any, operand: Any) -> bool:
    if not isinstance(operand, (list, tuple)) or len(operand) != 2:
        return False
    low, high = operand
    return _ordering(value, low, lambda a, b: a >= b) and _ordering(
        value, high, lambda a, b: a <= b
    )


def _regex(value: Any, operand: Any) -> bool:
    if not isinstance(value, str):
        return False
    pattern = operand if isinstance(operand, re.Pattern) else re.compile(str(operand))
    return pattern.search(value) is not None


class OperatorRegistry:
    """Named comparison operators usable inside condition specs.

    Registering a custom operator marks any RuleSet using it as
    non-compilable to the Rust backend (it transparently falls back to the
    pure-Python matcher).
    """

    BUILTIN: dict[str, OperatorFunc] = {
        "eq": _eq,
        "ne": lambda v, o: not _eq(v, o),
        "gt": lambda v, o: _ordering(v, o, lambda a, b: a > b),
        "gte": lambda v, o: _ordering(v, o, lambda a, b: a >= b),
        "lt": lambda v, o: _ordering(v, o, lambda a, b: a < b),
        "lte": lambda v, o: _ordering(v, o, lambda a, b: a <= b),
        "in": lambda v, o: isinstance(o, (list, tuple)) and any(_eq(v, i) for i in o),
        "not_in": lambda v, o: isinstance(o, (list, tuple))
        and not any(_eq(v, i) for i in o),
        "contains": _contains,
        "startswith": lambda v, o: isinstance(v, str)
        and isinstance(o, str)
        and v.startswith(o),
        "endswith": lambda v, o: isinstance(v, str)
        and isinstance(o, str)
        and v.endswith(o),
        "regex": _regex,
        "between": _between,
        "is_null": lambda v, o: _is_missing(v) is bool(o),
    }

    def __init__(self) -> None:
        self._operators: dict[str, OperatorFunc] = dict(self.BUILTIN)
        self._custom: set[str] = set()

    def register(self, name: str, fn: OperatorFunc) -> None:
        """Register a custom operator (disables Rust compilation)."""
        self._operators[name] = fn
        self._custom.add(name)

    @property
    def has_custom(self) -> bool:
        return bool(self._custom)

    def is_builtin(self, name: str) -> bool:
        return name in self.BUILTIN

    def __contains__(self, name: str) -> bool:
        return name in self._operators

    def compare(self, op: str, value: Any, operand: Any) -> bool:
        """Apply operator ``op`` to (value, operand).

        Missing/None values only match ``is_null``; anything else is False.
        """
        try:
            fn = self._operators[op]
        except KeyError:
            raise ValueError(f"Invalid operator: {op}") from None
        if op != "is_null" and _is_missing(value):
            return False
        return bool(fn(value, operand))


# Shared default instance; rules use it unless given their own registry.
default_operators = OperatorRegistry()

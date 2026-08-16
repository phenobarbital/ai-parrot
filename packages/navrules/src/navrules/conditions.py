"""Declarative condition DSL: parsing and pure-Python matching.

Spec format (JSON-friendly, the same shape rewards stores in its DB):

    {
        "env.is_weekend": true,                      # scalar => eq
        "ctx.worked_hours": {"gt": 8},               # {operator: operand}
        "ctx.job_code": {"in": ["TECH1", "TECH2"]},  # list operand
        "quarter": "Q4"                              # bare key: ctx, then env
    }

Multiple operators under one field AND together:
    {"ctx.worked_hours": {"gte": 4, "lt": 12}}

Field resolution: ``ctx.``-prefixed keys look only at the context flat view;
``env.`` only at the environment; bare keys resolve ctx first, then env.
Missing values match only ``is_null`` (see navrules.operators).

This module is the reference implementation; the Rust backend must be
bit-for-bit equivalent (enforced by the parity test suite).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from .operators import MISSING, OperatorRegistry, default_operators

Resolver = Callable[[str], Any]


class ConditionError(ValueError):
    """Raised when a condition spec cannot be parsed."""


@dataclass(frozen=True, slots=True)
class Condition:
    """A single (field, operator, operand) check."""

    field: str
    op: str
    operand: Any

    def to_spec(self) -> dict[str, Any]:
        """JSON-serializable form (consumed by the Rust compiler)."""
        return {"field": self.field, "op": self.op, "operand": self.operand}


class ConditionSet:
    """A compiled, immutable AND-set of conditions.

    Args:
        conditions: The parsed conditions (all must match).
        operators: Registry used for comparisons.
    """

    __slots__ = ("conditions", "_operators")

    def __init__(
        self,
        conditions: tuple[Condition, ...],
        operators: Optional[OperatorRegistry] = None,
    ) -> None:
        self.conditions = conditions
        self._operators = operators or default_operators

    @classmethod
    def from_dict(
        cls,
        spec: Optional[dict[str, Any]],
        operators: Optional[OperatorRegistry] = None,
    ) -> "ConditionSet":
        """Parse a condition spec dict into a ConditionSet.

        Raises:
            ConditionError: On unknown operators or malformed entries.
        """
        registry = operators or default_operators
        conditions: list[Condition] = []
        for field, expr in (spec or {}).items():
            if not isinstance(field, str) or not field:
                raise ConditionError(f"Invalid condition field: {field!r}")
            if isinstance(expr, dict):
                if not expr:
                    raise ConditionError(
                        f"Empty operator map for field {field!r}"
                    )
                for op, operand in expr.items():
                    if op not in registry:
                        raise ConditionError(
                            f"Unknown operator {op!r} for field {field!r}"
                        )
                    conditions.append(Condition(field, op, operand))
            else:
                # Scalar (or list) shorthand for equality.
                conditions.append(Condition(field, "eq", expr))
        return cls(tuple(conditions), registry)

    @property
    def is_rust_compilable(self) -> bool:
        """True when every operator is a builtin (Rust knows them all)."""
        if self._operators.has_custom:
            return all(
                self._operators.is_builtin(c.op) for c in self.conditions
            )
        return True

    def match(self, resolver: Resolver) -> bool:
        """Evaluate all conditions (AND) against a value resolver."""
        registry = self._operators
        for cond in self.conditions:
            value = resolver(cond.field)
            if not registry.compare(cond.op, value, cond.operand):
                return False
        return True

    def match_flat(self, flat: dict[str, Any]) -> bool:
        """Evaluate against a pre-flattened context dict."""
        return self.match(lambda field: flat.get(field, MISSING))

    def to_spec(self) -> list[dict[str, Any]]:
        """JSON-serializable list form (fed to the Rust compiler)."""
        return [c.to_spec() for c in self.conditions]

    def __len__(self) -> int:
        return len(self.conditions)

    def __repr__(self) -> str:
        return f"<ConditionSet {self.to_spec()!r}>"


def make_resolver(ctx: Any, env: Any) -> Resolver:
    """Build a field resolver over (ctx, env) without pre-flattening.

    Used by the pure-Python path when evaluating a single context, where
    building the full flat dict would cost more than direct lookups.
    Resolution mirrors ``EvalContext.flatten``: ``ctx.``/``env.`` prefixes are
    explicit; bare keys try ctx (store, then user, then session), then env.
    """

    def _ctx_lookup(key: str) -> Any:
        store = getattr(ctx, "store", None)
        if isinstance(store, dict) and key in store:
            return store[key]
        user = store.get("user") if isinstance(store, dict) else None
        if isinstance(user, dict) and key in user:
            return user[key]
        if user is not None and hasattr(user, key):
            return getattr(user, key)
        session = store.get("session") if isinstance(store, dict) else None
        if isinstance(session, dict) and key in session:
            return session[key]
        if isinstance(ctx, dict) and key in ctx:
            return ctx[key]
        return MISSING

    def _env_lookup(key: str) -> Any:
        if env is None:
            return MISSING
        getter = getattr(env, "get", None)
        if callable(getter):
            value = getter(key, MISSING)
            if value is not MISSING:
                return value
        # Method-backed values exposed in to_dict (work_intensity, etc.)
        method = getattr(env, f"get_{key}", None)
        if callable(method):
            try:
                return method()
            except TypeError:
                return MISSING
        return MISSING

    def resolve(field: str) -> Any:
        if field.startswith("ctx."):
            return _ctx_lookup(field[4:])
        if field.startswith("env."):
            return _env_lookup(field[4:])
        value = _ctx_lookup(field)
        if value is MISSING:
            value = _env_lookup(field)
        return value

    return resolve

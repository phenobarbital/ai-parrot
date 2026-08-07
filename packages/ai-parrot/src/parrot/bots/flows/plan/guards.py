"""CEL guards for ExecutionPlan nodes.

``PlanNode.when`` reuses the CEL evaluator the flow package already ships
(``parrot.bots.flows.flow.cel_evaluator.CELPredicateEvaluator``) rather than
introducing a second predicate language. CEL is sandboxed, has no arbitrary
code execution, and compiles at construction time — which is exactly what a
fail-fast plan validator needs.

Activation
----------

A guard sees only cheap, structural values:

``ctx.artifacts.<node_id>.<facet>``
    Facets published by upstream nodes.
``ctx.status.<node_id>``
    ``"ok" | "skipped" | "partial" | "error"``.
``ctx.errors``
    Number of failed nodes so far.

There is deliberately no way to reach a payload body from a guard: branching
must stay free.

Examples::

    ctx.artifacts.triage.critical > 0
    ctx.artifacts.listing.n_reports > 0 && ctx.errors == 0
    ctx.status.fetch_reports == "ok"
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional

__all__ = ("GuardCompilationError", "PlanGuard", "compile_guard")

logger = logging.getLogger("parrot.plan.guards")


class GuardCompilationError(ValueError):
    """Raised when a ``when`` expression fails to compile."""


def _load_evaluator():
    """Import ``CELPredicateEvaluator`` lazily.

    Kept lazy so the schema and validator remain importable in environments
    without ``cel-python`` installed; only guard *evaluation* needs it.

    Returns:
        The ``CELPredicateEvaluator`` class.

    Raises:
        GuardCompilationError: If the dependency is unavailable.
    """
    try:
        from parrot.bots.flows.flow.cel_evaluator import (  # noqa: PLC0415
            CELPredicateEvaluator,
        )
    except ImportError:  # pragma: no cover - exercised only without celpy
        try:
            from cel_evaluator import CELPredicateEvaluator  # type: ignore # noqa: PLC0415
        except ImportError as exc:
            raise GuardCompilationError(
                "CEL guards require 'cel-python'. Install it, or omit 'when'."
            ) from exc
    return CELPredicateEvaluator


class PlanGuard:
    """A compiled ``when`` expression.

    Compilation happens in ``__init__`` so an invalid guard is caught during
    plan validation — before a single tool runs — rather than mid-flight.

    Args:
        expression: The CEL expression.

    Raises:
        GuardCompilationError: If the expression does not compile.
    """

    __slots__ = ("expression", "_evaluator")

    def __init__(self, expression: str) -> None:
        self.expression = expression
        evaluator_cls = _load_evaluator()
        try:
            self._evaluator = evaluator_cls(expression)
        except ValueError as exc:
            raise GuardCompilationError(
                f"Invalid 'when' expression {expression!r}: {exc}"
            ) from exc

    def evaluate(
        self,
        artifacts: Mapping[str, Mapping[str, Any]],
        statuses: Optional[Mapping[str, str]] = None,
        errors: int = 0,
    ) -> bool:
        """Evaluate the guard against the accumulated facet map.

        Evaluation is fail-safe in the underlying evaluator: a runtime error
        yields ``False``. That is the right default here — an unevaluable
        guard skips its node rather than running it on unknown state — but it
        does mean a typo in a facet name reads as "condition not met", so the
        validator warns about facets no node publishes.

        Args:
            artifacts: ``{node_id: {facet: value}}`` published so far.
            statuses: ``{node_id: status}`` for completed nodes.
            errors: Count of failed nodes so far.

        Returns:
            ``True`` when the node should run.
        """
        activation: Dict[str, Any] = {
            "artifacts": {k: dict(v) for k, v in artifacts.items()},
            "status": dict(statuses or {}),
            "errors": errors,
        }
        return bool(self._evaluator(None, None, **activation))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"PlanGuard({self.expression!r})"


def compile_guard(expression: Optional[str]) -> Optional[PlanGuard]:
    """Compile ``expression`` into a :class:`PlanGuard`, or ``None``.

    Args:
        expression: A CEL expression, or ``None`` for an unguarded node.

    Returns:
        The compiled guard, or ``None`` when no expression was given.

    Raises:
        GuardCompilationError: If the expression does not compile.
    """
    if expression is None or not expression.strip():
        return None
    return PlanGuard(expression)

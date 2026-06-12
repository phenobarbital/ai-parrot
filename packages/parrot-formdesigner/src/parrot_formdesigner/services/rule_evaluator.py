"""Server-side authoritative rule evaluator for FEAT-301.

Implements ``RuleEvaluator``: a stateless, synchronous evaluator for
``DependencyRule`` conditions.  No I/O — safe to call from async handlers
without ``await``.

Key-missing semantics (RESUELTO §8):
- Source key absent from ``EvaluationContext`` → key-missing state.
- ``IS_EMPTY`` evaluates ``True`` on key-missing.
- All other operators evaluate ``False`` on key-missing.
- Rules ALWAYS resolve, never raise.

Hidden-field exclusion (RESUELTO §8):
- ``evaluate_form()`` walks fields in topological order.
- Values of fields hidden by an upstream rule are excluded from downstream
  inputs (treated as not-present, not as zero/stale value).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict

from ..core.constraints import (
    ConditionOperator,
    DependencyRule,
    FieldRefCondition,
    LocationVarCondition,
    VisitContextCondition,
)

if TYPE_CHECKING:
    from ..core.schema import FormSchema

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public data models
# ---------------------------------------------------------------------------

class EvaluationContext(BaseModel):
    """Runtime context fed to RuleEvaluator for a single form evaluation pass.

    Attributes:
        answers: Map of field_id → current answer value.
        location_vars: Map of location variable key → resolved value (from
            the ai-parrot Org Graph, FEAT-302; pre-fetched before evaluation).
        visit_context: Arbitrary visit metadata (date, type, status, etc.).
    """

    model_config = ConfigDict(extra="forbid")

    answers: dict[str, Any] = {}
    location_vars: dict[str, Any] = {}
    visit_context: dict[str, Any] = {}


EffectResult = Literal["show", "hide", "require", "disable"]

_SENTINEL = object()  # Signals key-missing (distinct from None/0/False/"")


class EvaluationResult(BaseModel):
    """Per-field visibility/effect result from a single evaluation pass.

    Attributes:
        field_id: The field this result applies to.
        effect: The resolved effect (``"show"`` when no rule fires).
        matched: ``True`` when the rule's conditions fired and produced the
            effect; ``False`` when the field gets the default ``"show"`` state.
    """

    model_config = ConfigDict(extra="forbid")

    field_id: str
    effect: EffectResult
    matched: bool


# ---------------------------------------------------------------------------
# RuleEvaluator
# ---------------------------------------------------------------------------

class RuleEvaluator:
    """Server-side authoritative evaluator for DependencyRule conditions.

    Stateless — instantiate once (module-level singleton works) and call
    ``evaluate()`` per field per request.  No external I/O; safe to call
    synchronously inside async handlers.

    Example::

        evaluator = RuleEvaluator()
        ctx = EvaluationContext(answers={"q1": "yes"})
        result = evaluator.evaluate(rule, ctx)
        # "show" / "hide" / "require" / "disable", or None if no match
    """

    def __init__(self) -> None:
        """Initialize the RuleEvaluator."""
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        rule: DependencyRule,
        context: EvaluationContext,
    ) -> EffectResult | None:
        """Evaluate a single DependencyRule against the provided context.

        Args:
            rule: The dependency rule to evaluate.
            context: The runtime evaluation context (answers + location vars
                + visit context).

        Returns:
            The rule's effect string (``"show"``, ``"hide"``, ``"require"``,
            or ``"disable"``) if conditions are satisfied, else ``None``.
        """
        condition_results = [
            self._evaluate_condition(cond, context)
            for cond in rule.conditions
        ]
        self.logger.debug(
            "evaluate: effect=%s logic=%s conditions=%s",
            rule.effect,
            rule.logic,
            condition_results,
        )

        if rule.logic == "and":
            fires = all(condition_results) if condition_results else False
        else:  # "or"
            fires = any(condition_results) if condition_results else False

        if fires:
            return rule.effect  # type: ignore[return-value]
        return None

    def evaluate_form(
        self,
        form: "FormSchema",
        context: EvaluationContext,
    ) -> dict[str, EvaluationResult]:
        """Evaluate all field rules in the form.

        Walks fields in topological order (so chained show/hide resolves
        deterministically).  Fields hidden by an upstream rule have their
        values excluded from downstream inputs (treated as not-present).

        Args:
            form: The form schema to evaluate.
            context: The runtime evaluation context.

        Returns:
            Mapping of field_id → ``EvaluationResult`` for every field
            that carries a ``DependencyRule``.  Fields without ``depends_on``
            are omitted.
        """
        from .logic_graph import LogicGraph

        graph = LogicGraph.build(form)
        try:
            ordered = graph.topological_order()
        except Exception as exc:  # CyclicDependencyError or unexpected
            self.logger.warning(
                "evaluate_form: cycle detected, falling back to form order: %s", exc
            )
            ordered = [f.field_id for f in form.iter_all_fields()]

        # Build a field lookup by field_id
        field_map = {f.field_id: f for f in form.iter_all_fields()}

        # Track which fields are currently hidden so their answers are excluded
        hidden_fields: set[str] = set()

        results: dict[str, EvaluationResult] = {}

        for field_id in ordered:
            field = field_map.get(field_id)
            if field is None or field.depends_on is None:
                continue

            # Build a context where hidden fields' values are excluded
            effective_context = self._mask_hidden_answers(context, hidden_fields)

            effect = self.evaluate(field.depends_on, effective_context)

            if effect is not None:
                results[field_id] = EvaluationResult(
                    field_id=field_id,
                    effect=effect,
                    matched=True,
                )
                # Mark as hidden if the effect is "hide"
                if effect == "hide":
                    hidden_fields.add(field_id)
            else:
                results[field_id] = EvaluationResult(
                    field_id=field_id,
                    effect="show",
                    matched=False,
                )

        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _mask_hidden_answers(
        self,
        context: EvaluationContext,
        hidden_fields: set[str],
    ) -> EvaluationContext:
        """Return a new context with hidden fields' answers removed.

        Args:
            context: Original evaluation context.
            hidden_fields: Set of field IDs currently hidden.

        Returns:
            A new ``EvaluationContext`` with hidden field answers excluded.
        """
        if not hidden_fields:
            return context
        masked_answers = {
            k: v for k, v in context.answers.items() if k not in hidden_fields
        }
        return context.model_copy(update={"answers": masked_answers})

    def _evaluate_condition(
        self,
        condition: FieldRefCondition | LocationVarCondition | VisitContextCondition,
        context: EvaluationContext,
    ) -> bool:
        """Evaluate a single condition against the context.

        Args:
            condition: The condition to evaluate.
            context: The runtime evaluation context.

        Returns:
            ``True`` if the condition is satisfied, ``False`` otherwise.
        """
        if isinstance(condition, FieldRefCondition):
            raw = context.answers.get(condition.field_id, _SENTINEL)
        elif isinstance(condition, LocationVarCondition):
            raw = context.location_vars.get(condition.key, _SENTINEL)
        else:  # VisitContextCondition
            raw = context.visit_context.get(condition.key, _SENTINEL)

        # Key-missing semantics (RESUELTO §8)
        key_missing = raw is _SENTINEL
        actual_value = None if key_missing else raw

        return self._apply_operator(condition.operator, actual_value, condition.value, key_missing)

    @staticmethod
    def _apply_operator(
        operator: ConditionOperator,
        actual: Any,
        expected: Any,
        key_missing: bool,
    ) -> bool:
        """Apply a ConditionOperator to resolve a boolean result.

        Key-missing semantics:
        - ``IS_EMPTY`` → ``True`` (missing counts as empty).
        - All other operators → ``False``.

        Args:
            operator: The condition operator.
            actual: The resolved value (``None`` if key was missing).
            expected: The condition's declared comparison value.
            key_missing: Whether the source key was absent from the context.

        Returns:
            ``True`` if the condition is satisfied.
        """
        # Handle IS_EMPTY / IS_NOT_EMPTY first (no comparison value needed)
        if operator == ConditionOperator.IS_EMPTY:
            if key_missing:
                return True
            return _is_empty(actual)

        if operator == ConditionOperator.IS_NOT_EMPTY:
            if key_missing:
                return False
            return not _is_empty(actual)

        # For all other operators: key-missing → False
        if key_missing:
            return False

        if operator == ConditionOperator.EQ:
            return _coerce_compare(actual, expected) == 0

        if operator == ConditionOperator.NEQ:
            return _coerce_compare(actual, expected) != 0

        if operator == ConditionOperator.GT:
            try:
                return _coerce_compare(actual, expected) > 0
            except (TypeError, ValueError):
                return False

        if operator == ConditionOperator.GTE:
            try:
                return _coerce_compare(actual, expected) >= 0
            except (TypeError, ValueError):
                return False

        if operator == ConditionOperator.LT:
            try:
                return _coerce_compare(actual, expected) < 0
            except (TypeError, ValueError):
                return False

        if operator == ConditionOperator.LTE:
            try:
                return _coerce_compare(actual, expected) <= 0
            except (TypeError, ValueError):
                return False

        if operator == ConditionOperator.IN:
            if not isinstance(expected, (list, tuple, set)):
                return False
            return actual in expected

        if operator == ConditionOperator.NOT_IN:
            if not isinstance(expected, (list, tuple, set)):
                logger.warning(
                    "NOT_IN operator requires a list/tuple/set value; got %s "
                    "— treating as always-true (rule misconfiguration)",
                    type(expected).__name__,
                )
                return True
            return actual not in expected

        # Unknown operator — fail safe
        logger.warning("Unknown ConditionOperator: %s", operator)
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_empty(value: Any) -> bool:
    """Return True if value is considered empty.

    Empty: None, empty string, empty list, empty dict, empty set.

    Args:
        value: The value to check.

    Returns:
        ``True`` if the value is considered empty.
    """
    if value is None:
        return True
    if isinstance(value, (str, list, dict, set, tuple)):
        return len(value) == 0
    return False


def _coerce_compare(actual: Any, expected: Any) -> int:
    """Compare two values, coercing to comparable types when possible.

    Attempts numeric coercion for string/number comparisons (e.g. "5" vs 5).
    Falls back to string comparison for EQ/NEQ.

    Args:
        actual: The runtime value.
        expected: The condition's declared comparison value.

    Returns:
        Negative if actual < expected, 0 if equal, positive if actual > expected.

    Raises:
        TypeError: When the values cannot be compared.
        ValueError: When numeric coercion fails for ordered operators.
    """
    # Both numeric → numeric comparison
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        if actual < expected:
            return -1
        if actual > expected:
            return 1
        return 0

    # Try numeric coercion (e.g. "5" vs 5 or 5 vs "5")
    try:
        a_num = float(actual)  # type: ignore[arg-type]
        e_num = float(expected)  # type: ignore[arg-type]
        if a_num < e_num:
            return -1
        if a_num > e_num:
            return 1
        return 0
    except (TypeError, ValueError):
        pass

    # String comparison
    a_str = str(actual)
    e_str = str(expected)
    if a_str < e_str:
        return -1
    if a_str > e_str:
        return 1
    return 0


#: Module-level stateless singleton — RuleEvaluator holds no per-request state,
#: so renderers and handlers share this instance instead of re-instantiating.
DEFAULT_EVALUATOR = RuleEvaluator()

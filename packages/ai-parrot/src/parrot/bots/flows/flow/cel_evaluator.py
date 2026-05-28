"""CEL Predicate Evaluator for AgentsFlow transition conditions.

Uses cel-python to compile and evaluate Common Expression Language (CEL)
expressions as flow transition predicates. CEL provides safe, sandboxed
evaluation without arbitrary code execution risks.

Example::

    >>> evaluator = CELPredicateEvaluator('result.decision == "pizza"')
    >>> evaluator({"decision": "pizza"})
    True
    >>> evaluator({"decision": "sushi"})
    False
"""
from __future__ import annotations

from typing import Any, Optional

import celpy
from celpy import celtypes
from navconfig.logging import logging


def _python_to_cel(value: Any) -> Any:
    """Convert a Python value to a CEL-compatible type.

    Handles nested dicts, lists, strings, numbers, booleans, and None.
    """
    if value is None:
        return celtypes.StringType("")
    if isinstance(value, bool):
        return celtypes.BoolType(value)
    if isinstance(value, int):
        return celtypes.IntType(value)
    if isinstance(value, float):
        return celtypes.DoubleType(value)
    if isinstance(value, str):
        return celtypes.StringType(value)
    if isinstance(value, dict):
        return celtypes.MapType({
            celtypes.StringType(str(k)): _python_to_cel(v)
            for k, v in value.items()
        })
    if isinstance(value, (list, tuple)):
        return celtypes.ListType([_python_to_cel(item) for item in value])
    # Fallback: stringify
    return celtypes.StringType(str(value))


class CELPredicateEvaluator:
    """Evaluate CEL expression strings as flow transition predicates.

    CEL (Common Expression Language) provides safe, sandboxed evaluation
    without arbitrary code execution risks. Expressions are compiled once
    on construction and can be evaluated many times with different inputs.

    Supported variables in expressions:
        - ``result``: Output from the source node (dict or Pydantic model)
        - ``error``: Exception message string (empty if no error)
        - ``ctx``: Shared flow context dict

    Example::

        >>> evaluator = CELPredicateEvaluator('result.confidence > 0.8')
        >>> evaluator({"confidence": 0.95})
        True
        >>> evaluator({"confidence": 0.5})
        False
    """

    def __init__(self, expression: str) -> None:
        """Compile the CEL expression.

        Args:
            expression: CEL expression string.

        Raises:
            ValueError: If the expression has invalid syntax.
        """
        self.expression = expression
        self.logger = logging.getLogger("parrot.cel")

        try:
            env = celpy.Environment()
            ast = env.compile(expression)
            self._program = env.program(ast)
        except Exception as e:
            raise ValueError(
                f"Invalid CEL expression: {expression!r} — {e}"
            ) from e

    def __call__(
        self,
        result: Any,
        error: Optional[Exception] = None,
        **ctx: Any,
    ) -> bool:
        """Evaluate the predicate against a result.

        Args:
            result: Output from the source node.
            error: Exception if the node failed, ``None`` otherwise.
            **ctx: Shared flow context key-value pairs.

        Returns:
            ``True`` if the predicate matches, ``False`` otherwise
            (including on evaluation errors — fail-safe).
        """
        coerced_result = self._coerce(result)

        activation = {
            "result": _python_to_cel(coerced_result),
            "error": celtypes.StringType(str(error) if error else ""),
            "ctx": _python_to_cel(ctx),
        }

        try:
            cel_result = self._program.evaluate(activation)
            return bool(cel_result)
        except Exception as e:
            self.logger.warning(
                f"CEL evaluation failed for '{self.expression}': {e}"
            )
            return False

    @staticmethod
    def _coerce(value: Any) -> Any:
        """Coerce Python objects to CEL-compatible base types.

        Pydantic models are converted via ``model_dump()``, objects with
        ``__dict__`` are converted via ``vars()``.
        """
        if hasattr(value, "model_dump"):
            return value.model_dump()
        if hasattr(value, "__dict__") and not isinstance(value, type):
            return vars(value)
        return value

    def __repr__(self) -> str:
        return f"CELPredicateEvaluator({self.expression!r})"

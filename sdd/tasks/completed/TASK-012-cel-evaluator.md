# TASK-012: CEL Predicate Evaluator

**Feature**: AgentsFlow Persistency
**Spec**: `sdd/specs/agentsflow-persistency.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: fdc88691-08f0-4537-968c-cbf4a40a46a6

---

## Context

> Conditional transitions in AgentsFlow use Python lambdas which cannot be serialized. The spec chose CEL (Common Expression Language) for safe, sandboxed predicate evaluation. This task wraps `cel-python` to evaluate predicate strings. Implements Module 3 from the spec.

---

## Scope

> Implement `CELPredicateEvaluator` to compile and evaluate CEL expressions.

- Install `cel-python` dependency
- Implement `CELPredicateEvaluator` class with compile-once, evaluate-many pattern
- Support variables: `result` (node output), `ctx` (shared context), `error` (exception message)
- Coerce Pydantic models to dicts via `model_dump()`
- Provide clear error messages for invalid expressions
- Write comprehensive unit tests covering common predicate patterns

**NOT in scope**:
- Integration with `FlowTransition` (TASK-013)
- Custom CEL functions (explicitly out of scope per spec)
- Modifying `cel-python` library

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/flow/cel_evaluator.py` | CREATE | CEL evaluator implementation |
| `parrot/bots/flow/__init__.py` | MODIFY | Export `CELPredicateEvaluator` |
| `pyproject.toml` | MODIFY | Add `cel-python>=0.4` dependency |
| `tests/test_cel_evaluator.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow
```python
# parrot/bots/flow/cel_evaluator.py
import celpy
from celpy import celtypes
from typing import Any, Optional
from navconfig.logging import logging


class CELPredicateEvaluator:
    """Evaluates CEL expression strings as flow transition predicates.

    CEL (Common Expression Language) provides safe, sandboxed evaluation
    without arbitrary code execution risks.

    Example:
        >>> evaluator = CELPredicateEvaluator('result.final_decision == "pizza"')
        >>> evaluator({"final_decision": "pizza"})
        True
    """

    def __init__(self, expression: str):
        """Compile the CEL expression.

        Args:
            expression: CEL expression string

        Raises:
            ValueError: If expression is invalid
        """
        self.expression = expression
        self.logger = logging.getLogger("parrot.cel")

        try:
            env = celpy.Environment()
            ast = env.compile(expression)
            self._program = env.program(ast)
        except Exception as e:
            raise ValueError(
                f"Invalid CEL expression: {expression!r}\n"
                f"Error: {e}"
            ) from e

    def __call__(
        self,
        result: Any,
        error: Optional[Exception] = None,
        **ctx: Any
    ) -> bool:
        """Evaluate the predicate.

        Args:
            result: Output from the source node
            error: Exception if node failed, None otherwise
            **ctx: Shared flow context

        Returns:
            True if predicate matches
        """
        activation = {
            "result": self._coerce(result),
            "error": str(error) if error else "",
            "ctx": ctx,
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
        """Coerce Python objects to CEL-compatible types."""
        if hasattr(value, "model_dump"):
            return value.model_dump()
        if hasattr(value, "__dict__"):
            return vars(value)
        return value
```

### Key Constraints
- Compile expression once in `__init__`, not on every evaluation (performance)
- Return `False` on evaluation errors (fail-safe for conditional routing)
- Log evaluation errors for debugging
- Full `ctx` access is allowed (per spec Section 7 resolution)
- Support common patterns: equality, comparisons, `in` operator, boolean logic

### CEL Syntax Reference
| Python | CEL |
|--------|-----|
| `r.decision == "pizza"` | `result.decision == "pizza"` |
| `r.confidence > 0.8` | `result.confidence > 0.8` |
| `"error" not in r` | `!("error" in result)` |
| `r.decision in ["a", "b"]` | `result.decision in ["a", "b"]` |
| `ctx.get("retries", 0) < 3` | `ctx.retries < 3` |

### References in Codebase
- `parrot/bots/flow/fsm.py:152-158` — Current lambda predicate evaluation

---

## Acceptance Criteria

- [ ] `cel-python>=0.4` added to `pyproject.toml`
- [ ] `CELPredicateEvaluator` compiles expression in `__init__`
- [ ] Invalid expressions raise `ValueError` with helpful message
- [ ] Evaluator supports: equality, comparisons, `in`, boolean ops
- [ ] Pydantic models coerced to dicts automatically
- [ ] Evaluation errors return `False` (fail-safe)
- [ ] All tests pass: `pytest tests/test_cel_evaluator.py -v`
- [ ] Import works: `from parrot.bots.flow import CELPredicateEvaluator`

---

## Test Specification

```python
# tests/test_cel_evaluator.py
import pytest
from pydantic import BaseModel
from parrot.bots.flow.cel_evaluator import CELPredicateEvaluator


class DecisionResult(BaseModel):
    final_decision: str
    confidence: float


class TestCELCompilation:
    def test_valid_expression_compiles(self):
        """Valid CEL expression compiles without error."""
        evaluator = CELPredicateEvaluator('result.value == "test"')
        assert evaluator.expression == 'result.value == "test"'

    def test_invalid_expression_raises(self):
        """Invalid CEL expression raises ValueError."""
        with pytest.raises(ValueError, match="Invalid CEL expression"):
            CELPredicateEvaluator('result..value')  # syntax error

    def test_unknown_function_raises(self):
        """Unknown function in expression raises ValueError."""
        with pytest.raises(ValueError):
            CELPredicateEvaluator('unknown_func(result)')


class TestCELEvaluation:
    def test_simple_equality(self):
        """Simple equality comparison."""
        evaluator = CELPredicateEvaluator('result.decision == "pizza"')

        assert evaluator({"decision": "pizza"}) is True
        assert evaluator({"decision": "sushi"}) is False

    def test_numeric_comparison(self):
        """Numeric comparisons work."""
        evaluator = CELPredicateEvaluator('result.confidence > 0.8')

        assert evaluator({"confidence": 0.9}) is True
        assert evaluator({"confidence": 0.7}) is False

    def test_boolean_logic(self):
        """Boolean AND/OR operators."""
        evaluator = CELPredicateEvaluator(
            'result.approved && result.confidence > 0.5'
        )

        assert evaluator({"approved": True, "confidence": 0.8}) is True
        assert evaluator({"approved": True, "confidence": 0.3}) is False
        assert evaluator({"approved": False, "confidence": 0.9}) is False

    def test_in_operator(self):
        """List membership with 'in' operator."""
        evaluator = CELPredicateEvaluator(
            'result.category in ["A", "B", "C"]'
        )

        assert evaluator({"category": "A"}) is True
        assert evaluator({"category": "Z"}) is False

    def test_ctx_access(self):
        """Access shared context variables."""
        evaluator = CELPredicateEvaluator('ctx.retries < 3')

        assert evaluator({}, retries=2) is True
        assert evaluator({}, retries=5) is False

    def test_error_variable(self):
        """Error variable available for on_error transitions."""
        evaluator = CELPredicateEvaluator('error != ""')

        assert evaluator({}, error=Exception("failed")) is True
        assert evaluator({}, error=None) is False


class TestPydanticCoercion:
    def test_pydantic_model_coerced(self):
        """Pydantic models are coerced to dicts."""
        evaluator = CELPredicateEvaluator('result.final_decision == "pizza"')

        result = DecisionResult(final_decision="pizza", confidence=0.95)
        assert evaluator(result) is True

    def test_nested_pydantic_access(self):
        """Nested field access on coerced model."""
        evaluator = CELPredicateEvaluator('result.confidence > 0.9')

        result = DecisionResult(final_decision="pizza", confidence=0.95)
        assert evaluator(result) is True


class TestErrorHandling:
    def test_evaluation_error_returns_false(self):
        """Evaluation errors return False (fail-safe)."""
        evaluator = CELPredicateEvaluator('result.missing_field == "value"')

        # Field doesn't exist - should return False, not raise
        assert evaluator({"other": "data"}) is False

    def test_type_mismatch_returns_false(self):
        """Type mismatches return False."""
        evaluator = CELPredicateEvaluator('result.value > 10')

        # String vs number comparison - should return False
        assert evaluator({"value": "not a number"}) is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agentsflow-persistency.spec.md` Section 2 and the brainstorm's CEL section
2. **Check dependencies** — this task has no dependencies
3. **Add dependency** — Add `cel-python>=0.4` to `pyproject.toml`
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-012-cel-evaluator.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: fdc88691-08f0-4537-968c-cbf4a40a46a6
**Date**: 2026-02-22
**Notes**: Implemented `CELPredicateEvaluator` in `parrot/bots/flow/cel_evaluator.py` (140 lines). Added `cel-python>=0.4` to `pyproject.toml`. Created 18 tests in `tests/test_cel_evaluator.py` covering compilation, equality/numeric/boolean/string/ctx/error evaluation, Pydantic coercion, and fail-safe error handling. Key design: `_python_to_cel()` recursively converts Python values to CEL types (`MapType`, `StringType`, etc.) since `cel-python` requires typed activation values.

**Deviations from spec**: Used `_python_to_cel()` recursive conversion instead of the spec's raw dict approach, since `cel-python` requires CEL-typed activation values.

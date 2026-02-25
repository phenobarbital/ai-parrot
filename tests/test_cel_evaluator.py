"""Tests for CEL Predicate Evaluator.

Tests compilation, evaluation of various CEL expression patterns, Pydantic
model coercion, and error handling (fail-safe behavior).
"""
import pytest
from pydantic import BaseModel

from parrot.bots.flow.cel_evaluator import CELPredicateEvaluator


class DecisionResult(BaseModel):
    """Test Pydantic model for coercion tests."""
    final_decision: str
    confidence: float


class TestCELCompilation:
    """Tests for CEL expression compilation."""

    def test_valid_expression_compiles(self):
        """Valid CEL expression compiles without error."""
        evaluator = CELPredicateEvaluator('result.value == "test"')
        assert evaluator.expression == 'result.value == "test"'

    def test_invalid_expression_raises(self):
        """Invalid CEL syntax raises ValueError."""
        with pytest.raises(ValueError, match="Invalid CEL expression"):
            CELPredicateEvaluator("result..value")  # syntax error

    def test_repr(self):
        """Repr shows the expression."""
        evaluator = CELPredicateEvaluator('result.x == 1')
        assert "result.x == 1" in repr(evaluator)


class TestCELEvaluation:
    """Tests for CEL expression evaluation."""

    def test_simple_equality(self):
        """Simple string equality comparison."""
        evaluator = CELPredicateEvaluator('result.decision == "pizza"')

        assert evaluator({"decision": "pizza"}) is True
        assert evaluator({"decision": "sushi"}) is False

    def test_numeric_comparison(self):
        """Numeric greater-than comparison."""
        evaluator = CELPredicateEvaluator("result.confidence > 0.8")

        assert evaluator({"confidence": 0.9}) is True
        assert evaluator({"confidence": 0.7}) is False

    def test_boolean_logic(self):
        """Boolean AND operator."""
        evaluator = CELPredicateEvaluator(
            "result.approved && result.confidence > 0.5"
        )

        assert evaluator({"approved": True, "confidence": 0.8}) is True
        assert evaluator({"approved": True, "confidence": 0.3}) is False
        assert evaluator({"approved": False, "confidence": 0.9}) is False

    def test_boolean_or(self):
        """Boolean OR operator."""
        evaluator = CELPredicateEvaluator(
            "result.fast || result.cheap"
        )

        assert evaluator({"fast": True, "cheap": False}) is True
        assert evaluator({"fast": False, "cheap": True}) is True
        assert evaluator({"fast": False, "cheap": False}) is False

    def test_string_contains(self):
        """String contains check using CEL."""
        evaluator = CELPredicateEvaluator(
            'result.message.contains("error")'
        )

        assert evaluator({"message": "An error occurred"}) is True
        assert evaluator({"message": "All good"}) is False

    def test_error_variable_with_error(self):
        """Error variable available for on_error transitions."""
        evaluator = CELPredicateEvaluator('error != ""')

        assert evaluator({}, error=Exception("failed")) is True
        assert evaluator({}, error=None) is False

    def test_ctx_access(self):
        """Access shared context variables."""
        evaluator = CELPredicateEvaluator("ctx.retries < 3")

        assert evaluator({}, retries=2) is True
        assert evaluator({}, retries=5) is False

    def test_negation(self):
        """Negation operator."""
        evaluator = CELPredicateEvaluator("!result.failed")

        assert evaluator({"failed": False}) is True
        assert evaluator({"failed": True}) is False


class TestPydanticCoercion:
    """Tests for Pydantic model auto-coercion."""

    def test_pydantic_model_coerced(self):
        """Pydantic models are coerced to dicts automatically."""
        evaluator = CELPredicateEvaluator('result.final_decision == "pizza"')

        model = DecisionResult(final_decision="pizza", confidence=0.95)
        assert evaluator(model) is True

    def test_nested_pydantic_field(self):
        """Nested field access on coerced Pydantic model."""
        evaluator = CELPredicateEvaluator("result.confidence > 0.9")

        model = DecisionResult(final_decision="pizza", confidence=0.95)
        assert evaluator(model) is True

        model_low = DecisionResult(final_decision="pizza", confidence=0.5)
        assert evaluator(model_low) is False


class TestErrorHandling:
    """Tests for fail-safe error handling."""

    def test_missing_field_returns_false(self):
        """Accessing a missing field returns False (fail-safe)."""
        evaluator = CELPredicateEvaluator('result.missing_field == "value"')

        # Field doesn't exist — should return False, not raise
        assert evaluator({"other": "data"}) is False

    def test_type_mismatch_returns_false(self):
        """Type mismatch in comparison returns False."""
        evaluator = CELPredicateEvaluator("result.value > 10")

        # String vs number — should return False
        assert evaluator({"value": "not a number"}) is False

    def test_empty_result(self):
        """Empty dict result doesn't crash."""
        evaluator = CELPredicateEvaluator('result.key == "val"')
        assert evaluator({}) is False

    def test_none_result(self):
        """None result doesn't crash."""
        evaluator = CELPredicateEvaluator('error != ""')
        assert evaluator(None) is False


class TestImports:
    """Test public API imports."""

    def test_import_from_flow_module(self):
        """CELPredicateEvaluator importable from parrot.bots.flow."""
        from parrot.bots.flow import CELPredicateEvaluator as Imported  # noqa: F811

        assert Imported is CELPredicateEvaluator

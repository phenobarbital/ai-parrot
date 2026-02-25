"""Tests for parrot.bots.flow.cel_evaluator — CEL Predicate Evaluator.

TASK-012: CEL compilation, evaluation, Pydantic coercion, fail-safe.
"""
import pytest
from pydantic import BaseModel

from parrot.bots.flow.cel_evaluator import CELPredicateEvaluator


class DecisionResult(BaseModel):
    final_decision: str
    confidence: float


# ---------------------------------------------------------------------------
# Compilation Tests
# ---------------------------------------------------------------------------

class TestCELCompilation:
    def test_valid_expression_compiles(self):
        evaluator = CELPredicateEvaluator('result.value == "test"')
        assert evaluator.expression == 'result.value == "test"'

    def test_invalid_expression_raises(self):
        with pytest.raises(ValueError, match="Invalid CEL expression"):
            CELPredicateEvaluator("result..value")

    def test_repr(self):
        evaluator = CELPredicateEvaluator('result == "x"')
        assert "CELPredicateEvaluator" in repr(evaluator)


# ---------------------------------------------------------------------------
# Simple Evaluation Tests
# ---------------------------------------------------------------------------

class TestCELEvaluation:
    def test_simple_equality_true(self):
        evaluator = CELPredicateEvaluator('result.decision == "pizza"')
        assert evaluator({"decision": "pizza"}) is True

    def test_simple_equality_false(self):
        evaluator = CELPredicateEvaluator('result.decision == "pizza"')
        assert evaluator({"decision": "sushi"}) is False

    def test_numeric_gt(self):
        evaluator = CELPredicateEvaluator("result.confidence > 0.8")
        assert evaluator({"confidence": 0.9}) is True
        assert evaluator({"confidence": 0.7}) is False

    def test_numeric_lt(self):
        evaluator = CELPredicateEvaluator("result.score < 50")
        assert evaluator({"score": 30}) is True
        assert evaluator({"score": 80}) is False

    def test_boolean_and(self):
        evaluator = CELPredicateEvaluator(
            "result.approved && result.confidence > 0.5"
        )
        assert evaluator({"approved": True, "confidence": 0.8}) is True
        assert evaluator({"approved": True, "confidence": 0.3}) is False
        assert evaluator({"approved": False, "confidence": 0.9}) is False

    def test_boolean_or(self):
        evaluator = CELPredicateEvaluator(
            'result.status == "ok" || result.status == "accepted"'
        )
        assert evaluator({"status": "ok"}) is True
        assert evaluator({"status": "accepted"}) is True
        assert evaluator({"status": "rejected"}) is False

    def test_negation(self):
        evaluator = CELPredicateEvaluator('!(result.failed)')
        assert evaluator({"failed": False}) is True
        assert evaluator({"failed": True}) is False

    def test_string_equality(self):
        evaluator = CELPredicateEvaluator('result == "hello"')
        assert evaluator("hello") is True
        assert evaluator("world") is False

    def test_in_operator_list(self):
        evaluator = CELPredicateEvaluator(
            'result.category in ["A", "B", "C"]'
        )
        assert evaluator({"category": "A"}) is True
        assert evaluator({"category": "Z"}) is False


# ---------------------------------------------------------------------------
# Context & Error Tests
# ---------------------------------------------------------------------------

class TestCELContextAccess:
    def test_ctx_access(self):
        evaluator = CELPredicateEvaluator("ctx.retries < 3")
        assert evaluator({}, retries=2) is True
        assert evaluator({}, retries=5) is False

    def test_error_variable_with_exception(self):
        evaluator = CELPredicateEvaluator('error != ""')
        assert evaluator({}, error=Exception("failed")) is True

    def test_error_variable_no_error(self):
        evaluator = CELPredicateEvaluator('error != ""')
        assert evaluator({}, error=None) is False


# ---------------------------------------------------------------------------
# Pydantic Coercion Tests
# ---------------------------------------------------------------------------

class TestPydanticCoercion:
    def test_pydantic_model_coerced(self):
        evaluator = CELPredicateEvaluator('result.final_decision == "pizza"')
        result = DecisionResult(final_decision="pizza", confidence=0.95)
        assert evaluator(result) is True

    def test_pydantic_nested_access(self):
        evaluator = CELPredicateEvaluator("result.confidence > 0.9")
        result = DecisionResult(final_decision="pizza", confidence=0.95)
        assert evaluator(result) is True

    def test_pydantic_model_false(self):
        evaluator = CELPredicateEvaluator('result.final_decision == "sushi"')
        result = DecisionResult(final_decision="pizza", confidence=0.5)
        assert evaluator(result) is False


# ---------------------------------------------------------------------------
# Error Handling (fail-safe)
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_missing_field_returns_false(self):
        evaluator = CELPredicateEvaluator('result.missing_field == "value"')
        assert evaluator({"other": "data"}) is False

    def test_type_mismatch_returns_false(self):
        evaluator = CELPredicateEvaluator("result.value > 10")
        assert evaluator({"value": "not a number"}) is False

    def test_none_result(self):
        evaluator = CELPredicateEvaluator('result == "test"')
        assert evaluator(None) is False


# ---------------------------------------------------------------------------
# Import Tests
# ---------------------------------------------------------------------------

class TestImports:
    def test_import_from_package(self):
        from parrot.bots.flow import CELPredicateEvaluator as CEL

        assert CEL is CELPredicateEvaluator

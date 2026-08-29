"""Tests for FunctionEvaluator and basic_functions (FEAT-470 TASK-2537)."""

from __future__ import annotations

import pytest
from parrot.outputs.a2ui.catalog.base import (
    INVALID_FUNCTION_CALL,
    CatalogValidationError,
)
from parrot.outputs.a2ui.catalog.basic import basic_functions
from parrot.outputs.a2ui.catalog.basic.functions import FunctionEvaluator
from parrot.outputs.a2ui.models import (
    CheckRule,
    DataBinding,
    FunctionCall,
    ValidationResult,
)


@pytest.fixture
def evaluator() -> FunctionEvaluator:
    return FunctionEvaluator()


class TestFormatStringPathsAndEscape:
    def test_format_string_paths_and_escape(self, evaluator):
        result = evaluator.format_string("${/a} \\${x}", data_model={"a": 1})
        assert result == "1 ${x}"

    def test_format_string_relative_path(self, evaluator):
        out = evaluator.format_string("${name}", data_model={"items": [{"name": "Alice"}]}, scope_path="/items/0")
        assert out == "Alice"

    def test_format_string_absolute_path(self, evaluator):
        out = evaluator.format_string("${/user/name}", data_model={"user": {"name": "Bob"}})
        assert out == "Bob"


class TestFormatStringFunctionNamedArgs:
    def test_format_string_function_named_args(self, evaluator):
        template = "Date: ${formatDate(value:${/d}, format:'yyyy-MM-dd')}"
        out = evaluator.format_string(template, data_model={"d": "2026-01-16T00:00:00"})
        assert out == "Date: 2026-01-16"

    def test_format_string_nested_literal_and_binding_args(self, evaluator):
        out = evaluator.format_string("${formatNumber(value:${/n}, decimals:1)}", data_model={"n": 3.14159})
        assert out == "3.1"


class TestFormatDateTokenOrderingDoesNotCorrupt:
    """Post-review fix: sequential .replace() let `a` (-> %p) re-match and
    corrupt the literal `a` inside `E`'s own `%a` replacement output.
    A single-pass tokenizer must not exhibit this cross-token corruption.
    """

    def test_e_token_survives_alongside_a_token(self, evaluator):
        """`E` (-> %a, weekday) must not be corrupted by the `a` (-> %p) token."""
        call = FunctionCall(
            call="formatDate",
            args={"value": "2026-01-16T15:30:00", "format": "E, MMM dd"},
        )
        result = evaluator.evaluate(call, data_model={})
        assert result == "Fri, Jan 16"

    def test_e_and_a_tokens_together(self, evaluator):
        """Both `E` and a real `a` (AM/PM) token in the same format, unmangled."""
        call = FunctionCall(
            call="formatDate",
            args={"value": "2026-01-16T15:30:00", "format": "E hh:mm a"},
        )
        result = evaluator.evaluate(call, data_model={})
        assert result == "Fri 03:30 PM"


class TestIndexOnlyInTemplateScope:
    def test_index_in_template_scope(self, evaluator):
        out = evaluator.format_string("Row ${@index}", data_model={}, index=2)
        assert out == "Row 2"

    def test_index_with_offset(self, evaluator):
        out = evaluator.format_string("Row ${@index(offset:1)}", data_model={}, index=2)
        assert out == "Row 3"

    def test_index_outside_template_scope_raises(self, evaluator):
        with pytest.raises(CatalogValidationError) as exc:
            evaluator.format_string("${@index}", data_model={})
        assert exc.value.code == INVALID_FUNCTION_CALL


class TestValidatorsReturnValidationResult:
    def test_required(self, evaluator):
        assert evaluator.evaluate(FunctionCall(call="required", args={"value": ""}), data_model={}) == ValidationResult(
            valid=False, code="REQUIRED", message="This value is required."
        )
        assert evaluator.evaluate(FunctionCall(call="required", args={"value": "x"}), data_model={}).valid

    def test_regex(self, evaluator):
        assert evaluator.evaluate(
            FunctionCall(call="regex", args={"value": "abc123", "pattern": r"^\w+$"}),
            data_model={},
        ).valid
        assert not evaluator.evaluate(
            FunctionCall(call="regex", args={"value": "a b", "pattern": r"^\w+$"}),
            data_model={},
        ).valid

    def test_length(self, evaluator):
        assert evaluator.evaluate(
            FunctionCall(call="length", args={"value": "hello", "min": 3, "max": 10}),
            data_model={},
        ).valid
        assert not evaluator.evaluate(FunctionCall(call="length", args={"value": "hi", "min": 3}), data_model={}).valid

    def test_numeric(self, evaluator):
        assert evaluator.evaluate(
            FunctionCall(call="numeric", args={"value": 5, "min": 0, "max": 10}), data_model={}
        ).valid
        assert not evaluator.evaluate(FunctionCall(call="numeric", args={"value": 15, "max": 10}), data_model={}).valid

    def test_email(self, evaluator):
        assert evaluator.evaluate(FunctionCall(call="email", args={"value": "a@b.com"}), data_model={}).valid
        assert not evaluator.evaluate(FunctionCall(call="email", args={"value": "not-an-email"}), data_model={}).valid

    def test_check_uses_rule_message_as_fallback_only(self, evaluator):
        """CheckRule.message is a FALLBACK — only used when the result has none."""
        rule = CheckRule(
            condition=FunctionCall(call="required", args={"value": ""}),
            message="Custom fallback",
        )
        result = evaluator.check(rule, data_model={})
        assert result.valid is False
        # `required` always supplies its own message, so the rule fallback is unused.
        assert result.message == "This value is required."

    def test_check_with_data_binding_condition(self, evaluator):
        rule = CheckRule(condition=DataBinding(path="/precomputed"))
        data_model = {"precomputed": {"valid": False, "message": "Server said no"}}
        result = evaluator.check(rule, data_model=data_model)
        assert result.valid is False
        assert result.message == "Server said no"


class TestBooleanFunctions:
    def test_and(self, evaluator):
        assert evaluator.evaluate(FunctionCall(call="and", args={"values": [True, True]}), data_model={}) is True
        assert evaluator.evaluate(FunctionCall(call="and", args={"values": [True, False]}), data_model={}) is False

    def test_or(self, evaluator):
        assert evaluator.evaluate(FunctionCall(call="or", args={"values": [False, True]}), data_model={}) is True
        assert evaluator.evaluate(FunctionCall(call="or", args={"values": [False, False]}), data_model={}) is False

    def test_not(self, evaluator):
        assert evaluator.evaluate(FunctionCall(call="not", args={"value": True}), data_model={}) is False
        assert evaluator.evaluate(FunctionCall(call="not", args={"value": False}), data_model={}) is True


class TestUnknownFunctionInvalidCall:
    def test_unknown_function_invalid_call(self, evaluator):
        with pytest.raises(CatalogValidationError) as exc:
            evaluator.evaluate(FunctionCall(call="bogus", args={}), data_model={})
        assert exc.value.code == INVALID_FUNCTION_CALL


class TestOpenUrlNoOp:
    def test_open_url_returns_none(self, evaluator):
        result = evaluator.evaluate(FunctionCall(call="openUrl", args={"url": "https://example.com"}), data_model={})
        assert result is None


class TestBasicFunctionsCount14:
    def test_basic_functions_count_14(self):
        functions = basic_functions()
        assert len(functions) == 14
        assert {f.name for f in functions} == {
            "required",
            "regex",
            "length",
            "numeric",
            "email",
            "formatString",
            "formatNumber",
            "formatCurrency",
            "formatDate",
            "pluralize",
            "openUrl",
            "and",
            "or",
            "not",
        }

    def test_open_url_requires_user_activation(self):
        functions = {f.name: f for f in basic_functions()}
        assert functions["openUrl"].requires_user_activation is True
        assert functions["required"].requires_user_activation is False

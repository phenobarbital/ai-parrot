"""Tests for FEAT-234 TASK-1530: RuleEvaluator service."""

import pytest

from parrot_formdesigner.core import (
    ConditionOperator,
    DependencyOperation,
    DependencyRule,
    FieldCondition,
    FieldType,
    FormField,
    FormSchema,
    FormSection,
    PostDependency,
)
from parrot_formdesigner.services import RuleEvaluator, RuleResolution


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _field(field_id: str, field_type: FieldType = FieldType.TEXT, **kwargs) -> FormField:
    return FormField(field_id=field_id, field_type=field_type, label=field_id, **kwargs)


def _form(*fields: FormField) -> FormSchema:
    return FormSchema(
        form_id="test",
        title="Test",
        sections=[FormSection(section_id="s1", fields=list(fields))],
    )


def _cond(field_id: str, operator: str = "eq", value: str = "yes") -> FieldCondition:
    return FieldCondition(field_id=field_id, operator=operator, value=value)


# ---------------------------------------------------------------------------
# Basic resolution
# ---------------------------------------------------------------------------


class TestBasicResolution:
    @pytest.mark.asyncio
    async def test_resolve_returns_rule_resolution(self) -> None:
        evaluator = RuleEvaluator()
        form = _form(_field("f1"), _field("f2"))
        result = await evaluator.resolve(form, {})
        assert isinstance(result, RuleResolution)

    @pytest.mark.asyncio
    async def test_all_fields_visible_by_default(self) -> None:
        evaluator = RuleEvaluator()
        form = _form(_field("f1"), _field("f2"))
        result = await evaluator.resolve(form, {})
        assert result.visible["f1"] is True
        assert result.visible["f2"] is True

    @pytest.mark.asyncio
    async def test_no_rules_empty_computed_and_cleared(self) -> None:
        evaluator = RuleEvaluator()
        form = _form(_field("f1"), _field("f2"))
        result = await evaluator.resolve(form, {})
        assert result.computed == {}
        assert result.cleared == []


# ---------------------------------------------------------------------------
# Pre-dependency (depends_on) — logic gates
# ---------------------------------------------------------------------------


class TestPreDependencyLogicGates:
    @pytest.mark.asyncio
    async def test_and_logic_show_when_all_true(self) -> None:
        f1 = _field("f1")
        f2 = _field("f2")
        f3 = FormField(
            field_id="f3",
            field_type=FieldType.TEXT,
            label="f3",
            depends_on=DependencyRule(
                conditions=[_cond("f1"), _cond("f2")],
                logic="and",
                effect="show",
            ),
        )
        form = _form(f1, f2, f3)
        evaluator = RuleEvaluator()
        result = await evaluator.resolve(form, {"f1": "yes", "f2": "yes"})
        assert result.visible["f3"] is True

    @pytest.mark.asyncio
    async def test_and_logic_hides_when_not_all_true(self) -> None:
        f1 = _field("f1")
        f2 = _field("f2")
        f3 = FormField(
            field_id="f3",
            field_type=FieldType.TEXT,
            label="f3",
            depends_on=DependencyRule(
                conditions=[_cond("f1"), _cond("f2")],
                logic="and",
                effect="show",
            ),
        )
        form = _form(f1, f2, f3)
        evaluator = RuleEvaluator()
        result = await evaluator.resolve(form, {"f1": "yes", "f2": "no"})
        assert result.visible["f3"] is False

    @pytest.mark.asyncio
    async def test_or_logic_show_when_any_true(self) -> None:
        f1 = _field("f1")
        f2 = _field("f2")
        f3 = FormField(
            field_id="f3",
            field_type=FieldType.TEXT,
            label="f3",
            depends_on=DependencyRule(
                conditions=[_cond("f1"), _cond("f2")],
                logic="or",
                effect="show",
            ),
        )
        form = _form(f1, f2, f3)
        evaluator = RuleEvaluator()
        result = await evaluator.resolve(form, {"f1": "yes", "f2": "no"})
        assert result.visible["f3"] is True

    @pytest.mark.asyncio
    async def test_xor_logic_visible_when_exactly_one_true(self) -> None:
        f1 = _field("f1")
        f2 = _field("f2")
        f3 = FormField(
            field_id="f3",
            field_type=FieldType.TEXT,
            label="f3",
            depends_on=DependencyRule(
                conditions=[_cond("f1"), _cond("f2")],
                logic="xor",
                effect="show",
            ),
        )
        form = _form(f1, f2, f3)
        evaluator = RuleEvaluator()

        # Exactly one true → visible
        result = await evaluator.resolve(form, {"f1": "yes", "f2": "no"})
        assert result.visible["f3"] is True

        # Both true → NOT visible (xor fails)
        result2 = await evaluator.resolve(form, {"f1": "yes", "f2": "yes"})
        assert result2.visible["f3"] is False

    @pytest.mark.asyncio
    async def test_not_logic_negates_and_group(self) -> None:
        """NOT negates the AND-combination of conditions (spec §8)."""
        f1 = _field("f1")
        f2 = _field("f2")
        f3 = FormField(
            field_id="f3",
            field_type=FieldType.TEXT,
            label="f3",
            depends_on=DependencyRule(
                conditions=[_cond("f1")],
                logic="not",
                effect="show",
            ),
        )
        form = _form(f1, f2, f3)
        evaluator = RuleEvaluator()

        # f1 = "yes" → AND-group = True → NOT → False → f3 hidden
        result = await evaluator.resolve(form, {"f1": "yes"})
        assert result.visible["f3"] is False

        # f1 = "no" → AND-group = False → NOT → True → f3 shown
        result2 = await evaluator.resolve(form, {"f1": "no"})
        assert result2.visible["f3"] is True


# ---------------------------------------------------------------------------
# Pre-dependency — effects
# ---------------------------------------------------------------------------


class TestPreDependencyEffects:
    @pytest.mark.asyncio
    async def test_hide_effect(self) -> None:
        f1 = _field("f1")
        f2 = FormField(
            field_id="f2",
            field_type=FieldType.TEXT,
            label="f2",
            depends_on=DependencyRule(
                conditions=[_cond("f1")],
                logic="and",
                effect="hide",
            ),
        )
        form = _form(f1, f2)
        evaluator = RuleEvaluator()
        result = await evaluator.resolve(form, {"f1": "yes"})
        assert result.visible["f2"] is False

    @pytest.mark.asyncio
    async def test_require_effect(self) -> None:
        f1 = _field("f1")
        f2 = _field("f2")
        f3 = FormField(
            field_id="f3",
            field_type=FieldType.TEXT,
            label="f3",
            depends_on=DependencyRule(
                conditions=[_cond("f1")],
                logic="and",
                effect="require",
            ),
        )
        form = _form(f1, f2, f3)
        evaluator = RuleEvaluator()
        result = await evaluator.resolve(form, {"f1": "yes"})
        assert result.required["f3"] is True


# ---------------------------------------------------------------------------
# Operations (computed values)
# ---------------------------------------------------------------------------


class TestOperations:
    @pytest.mark.asyncio
    async def test_copy_operation(self) -> None:
        f1 = _field("f1")
        f2 = FormField(
            field_id="f2",
            field_type=FieldType.TEXT,
            label="f2",
            depends_on=DependencyRule(
                conditions=[_cond("f1")],
                logic="and",
                effect="show",
                operations=[
                    DependencyOperation(op="copy", operands=["f1"], target="f3")
                ],
            ),
        )
        f3 = _field("f3")
        form = _form(f1, f2, f3)
        evaluator = RuleEvaluator()
        result = await evaluator.resolve(form, {"f1": "yes"})
        assert result.computed.get("f3") == "yes"

    @pytest.mark.asyncio
    async def test_add_operation(self) -> None:
        f_price = _field("price", FieldType.NUMBER)
        f_qty = _field("qty", FieldType.INTEGER)
        f_total = FormField(
            field_id="total",
            field_type=FieldType.NUMBER,
            label="total",
            depends_on=DependencyRule(
                conditions=[],
                logic="and",
                effect="show",
                operations=[
                    DependencyOperation(op="add", operands=["price", "qty"], target="total")
                ],
            ),
        )
        form = _form(f_price, f_qty, f_total)
        evaluator = RuleEvaluator()
        result = await evaluator.resolve(form, {"price": 10, "qty": 5})
        assert result.computed.get("total") == 15.0

    @pytest.mark.asyncio
    async def test_subtract_operation(self) -> None:
        fa = _field("a", FieldType.NUMBER)
        fb = _field("b", FieldType.NUMBER)
        fc = FormField(
            field_id="c",
            field_type=FieldType.NUMBER,
            label="c",
            depends_on=DependencyRule(
                conditions=[],
                logic="and",
                effect="show",
                operations=[
                    DependencyOperation(op="subtract", operands=["a", "b"], target="c")
                ],
            ),
        )
        form = _form(fa, fb, fc)
        evaluator = RuleEvaluator()
        result = await evaluator.resolve(form, {"a": 20, "b": 8})
        assert result.computed.get("c") == 12.0

    @pytest.mark.asyncio
    async def test_multiply_operation(self) -> None:
        fa = _field("a", FieldType.NUMBER)
        fb = _field("b", FieldType.NUMBER)
        fc = FormField(
            field_id="c",
            field_type=FieldType.NUMBER,
            label="c",
            depends_on=DependencyRule(
                conditions=[],
                logic="and",
                effect="show",
                operations=[
                    DependencyOperation(op="multiply", operands=["a", "b"], target="c")
                ],
            ),
        )
        form = _form(fa, fb, fc)
        evaluator = RuleEvaluator()
        result = await evaluator.resolve(form, {"a": 3, "b": 4})
        assert result.computed.get("c") == 12.0

    @pytest.mark.asyncio
    async def test_divide_operation(self) -> None:
        fa = _field("a", FieldType.NUMBER)
        fb = _field("b", FieldType.NUMBER)
        fc = FormField(
            field_id="c",
            field_type=FieldType.NUMBER,
            label="c",
            depends_on=DependencyRule(
                conditions=[],
                logic="and",
                effect="show",
                operations=[
                    DependencyOperation(op="divide", operands=["a", "b"], target="c")
                ],
            ),
        )
        form = _form(fa, fb, fc)
        evaluator = RuleEvaluator()
        result = await evaluator.resolve(form, {"a": 10, "b": 4})
        assert result.computed.get("c") == 2.5

    @pytest.mark.asyncio
    async def test_divide_by_zero_is_safe(self) -> None:
        fa = _field("a", FieldType.NUMBER)
        fb = _field("b", FieldType.NUMBER)
        fc = FormField(
            field_id="c",
            field_type=FieldType.NUMBER,
            label="c",
            depends_on=DependencyRule(
                conditions=[],
                logic="and",
                effect="show",
                operations=[
                    DependencyOperation(op="divide", operands=["a", "b"], target="c")
                ],
            ),
        )
        form = _form(fa, fb, fc)
        evaluator = RuleEvaluator()
        # No exception, computed is absent (None skipped)
        result = await evaluator.resolve(form, {"a": 10, "b": 0})
        assert "c" not in result.computed

    @pytest.mark.asyncio
    async def test_percent_operation(self) -> None:
        fa = _field("a", FieldType.NUMBER)
        fb = _field("b", FieldType.NUMBER)
        fc = FormField(
            field_id="c",
            field_type=FieldType.NUMBER,
            label="c",
            depends_on=DependencyRule(
                conditions=[],
                logic="and",
                effect="show",
                operations=[
                    DependencyOperation(op="percent", operands=["a", "b"], target="c")
                ],
            ),
        )
        form = _form(fa, fb, fc)
        evaluator = RuleEvaluator()
        result = await evaluator.resolve(form, {"a": 200, "b": 50})
        assert result.computed.get("c") == 100.0

    @pytest.mark.asyncio
    async def test_concat_operation(self) -> None:
        fa = _field("first")
        fb = _field("last")
        fc = FormField(
            field_id="full",
            field_type=FieldType.TEXT,
            label="full",
            depends_on=DependencyRule(
                conditions=[],
                logic="and",
                effect="show",
                operations=[
                    DependencyOperation(
                        op="concat",
                        operands=["first", "last"],
                        target="full",
                        options={"sep": " "},
                    )
                ],
            ),
        )
        form = _form(fa, fb, fc)
        evaluator = RuleEvaluator()
        result = await evaluator.resolve(form, {"first": "Jane", "last": "Doe"})
        assert result.computed.get("full") == "Jane Doe"

    @pytest.mark.asyncio
    async def test_date_diff_operation(self) -> None:
        fa = _field("start", FieldType.DATE)
        fb = _field("end", FieldType.DATE)
        fc = FormField(
            field_id="days",
            field_type=FieldType.INTEGER,
            label="days",
            depends_on=DependencyRule(
                conditions=[],
                logic="and",
                effect="show",
                operations=[
                    DependencyOperation(
                        op="date_diff",
                        operands=["start", "end"],
                        target="days",
                        options={"unit": "days"},
                    )
                ],
            ),
        )
        form = _form(fa, fb, fc)
        evaluator = RuleEvaluator()
        result = await evaluator.resolve(form, {"start": "2026-01-01", "end": "2026-01-11"})
        assert result.computed.get("days") == 10


# ---------------------------------------------------------------------------
# Post-dependencies
# ---------------------------------------------------------------------------


class TestPostDependencies:
    @pytest.mark.asyncio
    async def test_post_show_effect(self) -> None:
        f1 = FormField(
            field_id="f1",
            field_type=FieldType.TEXT,
            label="f1",
            post_depends=[
                PostDependency(
                    target="f2",
                    effect="show",
                    conditions=[_cond("f1")],
                    logic="and",
                )
            ],
        )
        f2 = _field("f2")
        form = _form(f1, f2)
        evaluator = RuleEvaluator()
        result = await evaluator.resolve(form, {"f1": "yes"})
        assert result.visible["f2"] is True

    @pytest.mark.asyncio
    async def test_post_hide_effect(self) -> None:
        f1 = FormField(
            field_id="f1",
            field_type=FieldType.TEXT,
            label="f1",
            post_depends=[
                PostDependency(
                    target="f2",
                    effect="hide",
                    conditions=[_cond("f1")],
                    logic="and",
                )
            ],
        )
        f2 = _field("f2")
        form = _form(f1, f2)
        evaluator = RuleEvaluator()
        result = await evaluator.resolve(form, {"f1": "yes"})
        assert result.visible["f2"] is False

    @pytest.mark.asyncio
    async def test_post_require_effect(self) -> None:
        f1 = FormField(
            field_id="f1",
            field_type=FieldType.TEXT,
            label="f1",
            post_depends=[
                PostDependency(
                    target="f2",
                    effect="require",
                    conditions=[_cond("f1")],
                    logic="and",
                )
            ],
        )
        f2 = _field("f2")
        form = _form(f1, f2)
        evaluator = RuleEvaluator()
        result = await evaluator.resolve(form, {"f1": "yes"})
        assert result.required["f2"] is True

    @pytest.mark.asyncio
    async def test_post_cascade_clear(self) -> None:
        f1 = FormField(
            field_id="f1",
            field_type=FieldType.TEXT,
            label="f1",
            post_depends=[
                PostDependency(target="f2", effect="cascade_clear")
            ],
        )
        f2 = _field("f2")
        form = _form(f1, f2)
        evaluator = RuleEvaluator()
        # f1 has a non-empty answer → cascade fires
        result = await evaluator.resolve(form, {"f1": "changed"})
        assert "f2" in result.cleared

    @pytest.mark.asyncio
    async def test_post_cascade_clear_no_duplicate(self) -> None:
        """cascade_clear adds the target only once even if two rules fire."""
        f1 = FormField(
            field_id="f1",
            field_type=FieldType.TEXT,
            label="f1",
            post_depends=[
                PostDependency(target="f2", effect="cascade_clear"),
                PostDependency(target="f2", effect="cascade_clear"),
            ],
        )
        f2 = _field("f2")
        form = _form(f1, f2)
        evaluator = RuleEvaluator()
        result = await evaluator.resolve(form, {"f1": "value"})
        assert result.cleared.count("f2") == 1

    @pytest.mark.asyncio
    async def test_post_calc_effect(self) -> None:
        f_price = _field("price", FieldType.NUMBER)
        f_qty = FormField(
            field_id="qty",
            field_type=FieldType.INTEGER,
            label="qty",
            post_depends=[
                PostDependency(
                    target="total",
                    effect="calc",
                    operation=DependencyOperation(
                        op="multiply",
                        operands=["price", "qty"],
                        target="total",
                    ),
                )
            ],
        )
        f_total = _field("total", FieldType.NUMBER)
        form = _form(f_price, f_qty, f_total)
        evaluator = RuleEvaluator()
        result = await evaluator.resolve(form, {"price": 5, "qty": 3})
        assert result.computed.get("total") == 15.0

    @pytest.mark.asyncio
    async def test_post_reload_options_sets_sentinel(self) -> None:
        """reload_options sets __reload__ sentinel in computed (open question placeholder)."""
        f1 = FormField(
            field_id="country",
            field_type=FieldType.SELECT,
            label="country",
            post_depends=[
                PostDependency(
                    target="city",
                    effect="reload_options",
                    conditions=[],
                    logic="and",
                )
            ],
        )
        f_city = _field("city", FieldType.SELECT)
        form = _form(f1, f_city)
        evaluator = RuleEvaluator()
        # country has a non-empty answer → reload fires
        result = await evaluator.resolve(form, {"country": "ES"})
        assert result.computed.get("city") == "__reload__"


# ---------------------------------------------------------------------------
# Safe-on-missing behaviour
# ---------------------------------------------------------------------------


class TestSafeOnMissingValues:
    @pytest.mark.asyncio
    async def test_no_crash_on_missing_condition_field(self) -> None:
        f1 = _field("f1")
        f2 = FormField(
            field_id="f2",
            field_type=FieldType.TEXT,
            label="f2",
            depends_on=DependencyRule(
                conditions=[_cond("f_ghost")],
                logic="and",
                effect="show",
            ),
        )
        form = _form(f1, f2)
        evaluator = RuleEvaluator()
        # No answers at all — should not raise
        result = await evaluator.resolve(form, {})
        assert isinstance(result, RuleResolution)
        assert result.visible["f2"] is False  # condition not met (missing → False)

    @pytest.mark.asyncio
    async def test_operation_with_missing_operand_is_noop(self) -> None:
        fa = _field("a", FieldType.NUMBER)
        fb = FormField(
            field_id="b",
            field_type=FieldType.NUMBER,
            label="b",
            depends_on=DependencyRule(
                conditions=[],
                logic="and",
                effect="show",
                operations=[
                    DependencyOperation(op="add", operands=["a", "ghost"], target="result")
                ],
            ),
        )
        form = _form(fa, fb)
        evaluator = RuleEvaluator()
        # "ghost" is missing — add should still work with available values
        result = await evaluator.resolve(form, {"a": 10})
        # "ghost" is None, float(None) raises → sum of non-None = [10.0]
        assert result.computed.get("result") == 10.0

    @pytest.mark.asyncio
    async def test_no_crash_on_empty_answers(self) -> None:
        f1 = _field("f1")
        f2 = _field("f2")
        form = _form(f1, f2)
        evaluator = RuleEvaluator()
        result = await evaluator.resolve(form, {})
        assert isinstance(result, RuleResolution)

    @pytest.mark.asyncio
    async def test_is_empty_operator_on_missing(self) -> None:
        f1 = _field("f1")
        f2 = FormField(
            field_id="f2",
            field_type=FieldType.TEXT,
            label="f2",
            depends_on=DependencyRule(
                conditions=[
                    FieldCondition(
                        field_id="f1",
                        operator=ConditionOperator.IS_EMPTY,
                        value=None,
                    )
                ],
                logic="and",
                effect="show",
            ),
        )
        form = _form(f1, f2)
        evaluator = RuleEvaluator()
        # f1 has no answer → is_empty is True → f2 shows
        result = await evaluator.resolve(form, {})
        assert result.visible["f2"] is True

    @pytest.mark.asyncio
    async def test_gt_operator_on_non_numeric_is_safe(self) -> None:
        f1 = _field("f1")
        f2 = FormField(
            field_id="f2",
            field_type=FieldType.TEXT,
            label="f2",
            depends_on=DependencyRule(
                conditions=[
                    FieldCondition(
                        field_id="f1",
                        operator=ConditionOperator.GT,
                        value=5,
                    )
                ],
                logic="and",
                effect="show",
            ),
        )
        form = _form(f1, f2)
        evaluator = RuleEvaluator()
        # Non-numeric answer → gt returns False, no exception
        result = await evaluator.resolve(form, {"f1": "not-a-number"})
        assert isinstance(result, RuleResolution)
        assert result.visible["f2"] is False

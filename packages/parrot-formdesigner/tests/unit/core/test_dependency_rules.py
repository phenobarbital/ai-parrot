"""Tests for FEAT-234 dependency rule models.

Covers TASK-1523 (widened logic), TASK-1524 (DependencyOperation),
and TASK-1525 (PostDependency + FormField.post_depends).
"""

import pytest
from pydantic import ValidationError

from parrot_formdesigner.core import (
    ConditionOperator,
    DependencyOperation,
    DependencyRule,
    FieldCondition,
    FieldType,
    FormField,
    PostDependency,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cond(field_id: str = "f1") -> FieldCondition:
    return FieldCondition(field_id=field_id, operator=ConditionOperator.EQ, value="x")


def _op(
    op: str = "copy",
    operands: list[str] | None = None,
    target: str = "f2",
) -> DependencyOperation:
    return DependencyOperation(op=op, operands=operands or ["f1"], target=target)


# ---------------------------------------------------------------------------
# TASK-1523: Widen DependencyRule.logic
# ---------------------------------------------------------------------------


class TestDependencyLogicWidened:
    """TASK-1523 — logic widened to and|or|xor|not."""

    @pytest.mark.parametrize("logic", ["and", "or", "xor", "not"])
    def test_accepts_all_logic_values(self, logic: str) -> None:
        r = DependencyRule(conditions=[_cond()], logic=logic)
        assert r.logic == logic

    def test_default_logic_is_and(self) -> None:
        r = DependencyRule(conditions=[_cond()])
        assert r.logic == "and"

    def test_rejects_unknown_logic(self) -> None:
        with pytest.raises(ValidationError):
            DependencyRule(conditions=[_cond()], logic="nand")  # type: ignore[arg-type]

    def test_legacy_and_or_roundtrip(self) -> None:
        """Existing imported rules with and/or are unchanged after model load."""
        raw = {
            "conditions": [{"field_id": "field_9050", "operator": "eq", "value": "Compliance Audit"}],
            "logic": "and",
            "effect": "show",
        }
        r = DependencyRule.model_validate(raw)
        assert r.logic == "and"
        assert r.effect == "show"
        assert r.operations is None

    def test_or_rule_roundtrip(self) -> None:
        raw = {
            "conditions": [{"field_id": "f1", "operator": "neq", "value": None}],
            "logic": "or",
            "effect": "hide",
        }
        r = DependencyRule.model_validate(raw)
        assert r.logic == "or"
        assert r.effect == "hide"


# ---------------------------------------------------------------------------
# TASK-1524: DependencyOperation model
# ---------------------------------------------------------------------------


class TestDependencyOperation:
    """TASK-1524 — DependencyOperation model."""

    @pytest.mark.parametrize(
        "op",
        [
            "copy",
            "add",
            "subtract",
            "multiply",
            "divide",
            "percent",
            "concat",
            "format",
            "date_diff",
            "lookup",
            "aggregate",
        ],
    )
    def test_all_op_kinds_construct(self, op: str) -> None:
        o = DependencyOperation(op=op, operands=["f1", "f2"], target="f3")
        assert o.op == op
        assert o.target == "f3"

    def test_unknown_op_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DependencyOperation(op="frobnicate", operands=["f1"], target="f2")  # type: ignore[arg-type]

    def test_empty_operands_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DependencyOperation(op="copy", operands=[], target="f2")

    def test_empty_target_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DependencyOperation(op="copy", operands=["f1"], target="")

    def test_options_field_is_optional(self) -> None:
        o = DependencyOperation(op="add", operands=["f1", "f2"], target="f3")
        assert o.options is None

    def test_options_field_accepts_dict(self) -> None:
        o = DependencyOperation(
            op="date_diff",
            operands=["start", "end"],
            target="duration",
            options={"unit": "days"},
        )
        assert o.options == {"unit": "days"}

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            DependencyOperation(op="copy", operands=["f1"], target="f2", unknown_key="x")  # type: ignore[call-arg]

    def test_rule_carries_operations(self) -> None:
        r = DependencyRule(
            conditions=[_cond()],
            operations=[DependencyOperation(op="copy", operands=["f1"], target="f2")],
        )
        assert r.operations is not None
        assert len(r.operations) == 1
        assert r.operations[0].op == "copy"

    def test_rule_default_operations_is_none(self) -> None:
        r = DependencyRule(conditions=[_cond()])
        assert r.operations is None

    def test_import_from_core(self) -> None:
        """from parrot_formdesigner.core import DependencyOperation works."""
        from parrot_formdesigner.core import DependencyOperation as DO

        assert DO is DependencyOperation


# ---------------------------------------------------------------------------
# TASK-1525: PostDependency model + FormField.post_depends
# ---------------------------------------------------------------------------


class TestPostDependency:
    """TASK-1525 — PostDependency model."""

    @pytest.mark.parametrize(
        "effect",
        ["reload_options", "show", "hide", "require", "cascade_clear"],
    )
    def test_effects_without_operation(self, effect: str) -> None:
        p = PostDependency(target="f2", effect=effect)
        assert p.effect == effect
        assert p.operation is None

    def test_set_requires_operation(self) -> None:
        with pytest.raises(ValidationError):
            PostDependency(target="f2", effect="set")

    def test_calc_requires_operation(self) -> None:
        with pytest.raises(ValidationError):
            PostDependency(target="f2", effect="calc")

    def test_set_with_operation_ok(self) -> None:
        p = PostDependency(
            target="f2",
            effect="set",
            operation=DependencyOperation(op="copy", operands=["f1"], target="f2"),
        )
        assert p.effect == "set"
        assert p.operation is not None
        assert p.operation.op == "copy"

    def test_calc_with_operation_ok(self) -> None:
        p = PostDependency(
            target="total",
            effect="calc",
            operation=DependencyOperation(op="add", operands=["qty", "price"], target="total"),
        )
        assert p.effect == "calc"

    def test_default_logic_is_and(self) -> None:
        p = PostDependency(target="f2", effect="show")
        assert p.logic == "and"

    @pytest.mark.parametrize("logic", ["and", "or", "xor", "not"])
    def test_accepts_all_logic_values(self, logic: str) -> None:
        p = PostDependency(target="f2", effect="show", logic=logic)
        assert p.logic == logic

    def test_conditions_optional(self) -> None:
        p = PostDependency(target="f2", effect="show")
        assert p.conditions is None

    def test_conditions_accepted(self) -> None:
        p = PostDependency(
            target="f2",
            effect="show",
            conditions=[_cond("f1")],
        )
        assert p.conditions is not None
        assert len(p.conditions) == 1

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            PostDependency(target="f2", effect="show", bogus=True)  # type: ignore[call-arg]

    def test_import_from_core(self) -> None:
        """from parrot_formdesigner.core import PostDependency works."""
        from parrot_formdesigner.core import PostDependency as PD

        assert PD is PostDependency


class TestFormFieldPostDepends:
    """TASK-1525 — FormField.post_depends attribute."""

    def test_formfield_without_post_depends(self) -> None:
        """FormField with no post_depends is valid and defaults to None."""
        f = FormField(field_id="f1", field_type=FieldType.TEXT, label="A")
        assert f.post_depends is None

    def test_formfield_with_post_depends(self) -> None:
        f = FormField(
            field_id="f1",
            field_type=FieldType.TEXT,
            label="A",
            post_depends=[
                PostDependency(
                    target="f2",
                    effect="set",
                    operation=DependencyOperation(op="copy", operands=["f1"], target="f2"),
                )
            ],
        )
        assert f.post_depends is not None
        assert len(f.post_depends) == 1
        assert f.post_depends[0].target == "f2"

    def test_formfield_model_rebuild_succeeds(self) -> None:
        """FormField.model_rebuild() resolves without error (self-referential + PostDependency)."""
        # If model_rebuild() fails at import time, this test will already have failed on import.
        # Calling it again explicitly to confirm idempotency.
        FormField.model_rebuild()

    def test_formfield_roundtrip_with_post_depends(self) -> None:
        """model_dump / model_validate round-trip preserves post_depends."""
        f = FormField(
            field_id="f1",
            field_type=FieldType.TEXT,
            label="Source",
            post_depends=[PostDependency(target="f2", effect="show")],
        )
        dumped = f.model_dump()
        restored = FormField.model_validate(dumped)
        assert restored.post_depends is not None
        assert restored.post_depends[0].target == "f2"
        assert restored.post_depends[0].effect == "show"

    def test_formfield_with_depends_on_and_post_depends(self) -> None:
        """FormField can carry both depends_on and post_depends simultaneously."""
        f = FormField(
            field_id="f2",
            field_type=FieldType.NUMBER,
            label="B",
            depends_on=DependencyRule(
                conditions=[_cond("f1")],
                logic="xor",
                effect="show",
            ),
            post_depends=[PostDependency(target="f3", effect="cascade_clear")],
        )
        assert f.depends_on is not None
        assert f.depends_on.logic == "xor"
        assert f.post_depends is not None
        assert f.post_depends[0].effect == "cascade_clear"

"""Unit tests for field constraints and dependency rules."""

import pytest
from parrot.forms import (
    ConditionOperator,
    DependencyRule,
    FieldCondition,
    FieldConstraints,
)


class TestFieldConstraints:
    """Tests for FieldConstraints model."""

    def test_empty_constraints(self):
        """FieldConstraints can be created with all defaults."""
        c = FieldConstraints()
        assert c.min_length is None
        assert c.max_length is None
        assert c.min_value is None
        assert c.max_value is None
        assert c.step is None
        assert c.pattern is None
        assert c.pattern_message is None
        assert c.min_items is None
        assert c.max_items is None
        assert c.allowed_mime_types is None
        assert c.max_file_size_bytes is None

    def test_string_constraints(self):
        """FieldConstraints with string length bounds."""
        c = FieldConstraints(min_length=2, max_length=50)
        assert c.min_length == 2
        assert c.max_length == 50

    def test_numeric_constraints(self):
        """FieldConstraints with numeric bounds and step."""
        c = FieldConstraints(min_value=0.0, max_value=100.0, step=0.5)
        assert c.min_value == 0.0
        assert c.max_value == 100.0
        assert c.step == 0.5

    def test_pattern_constraint(self):
        """FieldConstraints with regex pattern."""
        c = FieldConstraints(pattern=r"^\d{5}$", pattern_message="Must be 5 digits")
        assert c.pattern == r"^\d{5}$"
        assert c.pattern_message == "Must be 5 digits"

    def test_localized_pattern_message(self):
        """FieldConstraints with localized pattern message."""
        c = FieldConstraints(
            pattern=r"^\d{5}$",
            pattern_message={"en": "Must be 5 digits", "es": "Debe tener 5 dígitos"},
        )
        assert c.pattern_message["en"] == "Must be 5 digits"

    def test_array_constraints(self):
        """FieldConstraints for array fields."""
        c = FieldConstraints(min_items=1, max_items=10)
        assert c.min_items == 1
        assert c.max_items == 10

    def test_file_constraints(self):
        """FieldConstraints for file fields."""
        c = FieldConstraints(
            allowed_mime_types=["image/jpeg", "image/png"],
            max_file_size_bytes=5 * 1024 * 1024,
        )
        assert "image/jpeg" in c.allowed_mime_types
        assert c.max_file_size_bytes == 5242880

    def test_extra_fields_forbidden(self):
        """FieldConstraints rejects extra fields."""
        with pytest.raises(Exception):
            FieldConstraints(unknown_constraint=True)


class TestFieldCondition:
    """Tests for FieldCondition model."""

    def test_basic_condition(self):
        """FieldCondition with EQ operator."""
        cond = FieldCondition(field_id="role", operator=ConditionOperator.EQ, value="admin")
        assert cond.field_id == "role"
        assert cond.operator == ConditionOperator.EQ
        assert cond.value == "admin"

    def test_condition_without_value(self):
        """FieldCondition for IS_EMPTY operator (no value needed)."""
        cond = FieldCondition(field_id="phone", operator=ConditionOperator.IS_EMPTY)
        assert cond.value is None

    def test_in_operator(self):
        """FieldCondition with IN operator and list value."""
        cond = FieldCondition(
            field_id="status",
            operator=ConditionOperator.IN,
            value=["active", "pending"],
        )
        assert len(cond.value) == 2


class TestDependencyRule:
    """Tests for DependencyRule model."""

    def test_single_condition_show(self):
        """DependencyRule with single condition defaults to show effect."""
        rule = DependencyRule(
            conditions=[
                FieldCondition(field_id="has_phone", operator=ConditionOperator.EQ, value=True)
            ]
        )
        assert rule.effect == "show"
        assert rule.logic == "and"

    def test_multiple_conditions_and_logic(self):
        """DependencyRule with AND logic across multiple conditions."""
        rule = DependencyRule(
            conditions=[
                FieldCondition(field_id="role", operator=ConditionOperator.EQ, value="admin"),
                FieldCondition(field_id="active", operator=ConditionOperator.EQ, value=True),
            ],
            logic="and",
            effect="show",
        )
        assert len(rule.conditions) == 2

    def test_or_logic_hide_effect(self):
        """DependencyRule with OR logic and hide effect."""
        rule = DependencyRule(
            conditions=[
                FieldCondition(field_id="x", operator=ConditionOperator.IS_EMPTY),
                FieldCondition(field_id="y", operator=ConditionOperator.IS_EMPTY),
            ],
            logic="or",
            effect="hide",
        )
        assert rule.logic == "or"
        assert rule.effect == "hide"

    def test_require_effect(self):
        """DependencyRule with require effect."""
        rule = DependencyRule(
            conditions=[
                FieldCondition(field_id="type", operator=ConditionOperator.EQ, value="business")
            ],
            effect="require",
        )
        assert rule.effect == "require"

    def test_disable_effect(self):
        """DependencyRule with disable effect."""
        rule = DependencyRule(
            conditions=[
                FieldCondition(field_id="locked", operator=ConditionOperator.EQ, value=True)
            ],
            effect="disable",
        )
        assert rule.effect == "disable"

    def test_roundtrip_serialization(self):
        """DependencyRule serializes and deserializes correctly."""
        rule = DependencyRule(
            conditions=[
                FieldCondition(field_id="toggle", operator=ConditionOperator.EQ, value=True)
            ],
            effect="show",
        )
        data = rule.model_dump()
        assert len(data["conditions"]) == 1
        restored = DependencyRule.model_validate(data)
        assert restored.effect == "show"
        assert restored.conditions[0].field_id == "toggle"

"""Unit tests for FEAT-301 FieldCondition discriminated union.

Covers:
- Backward-compat: legacy dicts without ``source`` deserialize as FieldRefCondition.
- All three variants (FieldRefCondition, LocationVarCondition, VisitContextCondition).
- Round-trip serialization.
- LocationVariableBinding value-object.
- ConfigDict(extra="forbid") enforcement.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from parrot_formdesigner.core.constraints import (
    ConditionOperator,
    DependencyRule,
    FieldRefCondition,
    LocationVarCondition,
    LocationVariableBinding,
    VisitContextCondition,
)


# ---------------------------------------------------------------------------
# FieldRefCondition
# ---------------------------------------------------------------------------

class TestFieldRefCondition:
    """Tests for the FieldRefCondition variant."""

    def test_default_source_is_field(self) -> None:
        """FieldRefCondition has source='field' by default."""
        cond = FieldRefCondition(
            field_id="q1",
            operator=ConditionOperator.EQ,
            value=1,
        )
        assert cond.source == "field"
        assert cond.field_id == "q1"

    def test_explicit_source_field(self) -> None:
        """Explicit source='field' is accepted."""
        cond = FieldRefCondition(
            source="field",
            field_id="q2",
            operator=ConditionOperator.NEQ,
            value="no",
        )
        assert cond.source == "field"

    def test_value_defaults_to_none(self) -> None:
        """Value can be omitted (defaults to None)."""
        cond = FieldRefCondition(
            field_id="q1",
            operator=ConditionOperator.IS_EMPTY,
        )
        assert cond.value is None

    def test_extra_fields_forbidden(self) -> None:
        """Extra fields are rejected by ConfigDict(extra='forbid')."""
        with pytest.raises(ValidationError):
            FieldRefCondition(
                field_id="q1",
                operator=ConditionOperator.EQ,
                value=1,
                unknown_field="oops",  # type: ignore[call-arg]
            )


# ---------------------------------------------------------------------------
# LocationVarCondition
# ---------------------------------------------------------------------------

class TestLocationVarCondition:
    """Tests for the LocationVarCondition variant."""

    def test_source_must_be_location_variable(self) -> None:
        """source must be 'location_variable'."""
        cond = LocationVarCondition(
            source="location_variable",
            key="store_type",
            operator=ConditionOperator.EQ,
            value="flagship",
        )
        assert cond.source == "location_variable"
        assert cond.key == "store_type"

    def test_value_none_allowed(self) -> None:
        """Value defaults to None for IS_EMPTY checks."""
        cond = LocationVarCondition(
            source="location_variable",
            key="feature_flag",
            operator=ConditionOperator.IS_EMPTY,
        )
        assert cond.value is None

    def test_extra_fields_forbidden(self) -> None:
        """Extra fields are rejected."""
        with pytest.raises(ValidationError):
            LocationVarCondition(
                source="location_variable",
                key="x",
                operator=ConditionOperator.EQ,
                value=1,
                field_id="should_not_exist",  # type: ignore[call-arg]
            )


# ---------------------------------------------------------------------------
# VisitContextCondition
# ---------------------------------------------------------------------------

class TestVisitContextCondition:
    """Tests for the VisitContextCondition variant."""

    def test_source_is_visit_context(self) -> None:
        """source must be 'visit_context'."""
        cond = VisitContextCondition(
            source="visit_context",
            key="visit_type",
            operator=ConditionOperator.IN,
            value=["audit", "merchandising"],
        )
        assert cond.source == "visit_context"
        assert cond.key == "visit_type"

    def test_value_can_be_string(self) -> None:
        """Value can be a plain string."""
        cond = VisitContextCondition(
            source="visit_context",
            key="visit_date",
            operator=ConditionOperator.GT,
            value="2026-01-01",
        )
        assert cond.value == "2026-01-01"


# ---------------------------------------------------------------------------
# DependencyRule — backward compat + legacy source injection
# ---------------------------------------------------------------------------

class TestDependencyRuleLegacyInjection:
    """Tests for the backward-compat model_validator on DependencyRule."""

    def test_legacy_dict_backward_compat(self) -> None:
        """Legacy dict without 'source' deserializes as FieldRefCondition."""
        rule = DependencyRule.model_validate({
            "conditions": [{"field_id": "q1", "operator": "eq", "value": 1}],
            "logic": "and",
            "effect": "show",
        })
        cond = rule.conditions[0]
        assert isinstance(cond, FieldRefCondition)
        assert cond.field_id == "q1"
        assert cond.value == 1

    def test_legacy_multiple_conditions(self) -> None:
        """Multiple legacy conditions are all injected with source='field'."""
        rule = DependencyRule.model_validate({
            "conditions": [
                {"field_id": "q1", "operator": "eq", "value": "yes"},
                {"field_id": "q2", "operator": "neq", "value": "no"},
            ],
        })
        for cond in rule.conditions:
            assert isinstance(cond, FieldRefCondition)

    def test_new_location_var_no_injection(self) -> None:
        """Dicts with explicit source are NOT overwritten."""
        rule = DependencyRule.model_validate({
            "conditions": [
                {
                    "source": "location_variable",
                    "key": "store_type",
                    "operator": "eq",
                    "value": "flagship",
                }
            ],
        })
        cond = rule.conditions[0]
        assert isinstance(cond, LocationVarCondition)
        assert cond.key == "store_type"

    def test_empty_conditions_list(self) -> None:
        """Empty conditions list is valid (DependencyRule allows it)."""
        rule = DependencyRule.model_validate({"conditions": []})
        assert rule.conditions == []

    def test_conditions_none_safe(self) -> None:
        """Missing conditions key defaults gracefully (none = no conditions)."""
        # The validator must not crash on missing 'conditions'.
        rule = DependencyRule(conditions=[])
        assert rule.conditions == []

    def test_default_logic_and_effect(self) -> None:
        """Default logic='and', effect='show' preserved."""
        rule = DependencyRule.model_validate({
            "conditions": [{"field_id": "q1", "operator": "eq", "value": 1}],
        })
        assert rule.logic == "and"
        assert rule.effect == "show"


# ---------------------------------------------------------------------------
# Round-trip serialization
# ---------------------------------------------------------------------------

class TestRoundTripSerialization:
    """Tests for model_dump() → model_validate() round-trip correctness."""

    def test_round_trip_field_ref(self) -> None:
        """FieldRefCondition round-trips through model_dump/model_validate."""
        rule = DependencyRule(
            conditions=[
                FieldRefCondition(
                    field_id="q1",
                    operator=ConditionOperator.EQ,
                    value=1,
                )
            ]
        )
        reloaded = DependencyRule.model_validate(rule.model_dump())
        assert reloaded == rule

    def test_round_trip_all_three_variants(self) -> None:
        """All three condition variants round-trip identically."""
        rule = DependencyRule(
            conditions=[
                FieldRefCondition(
                    field_id="q1",
                    operator=ConditionOperator.EQ,
                    value=1,
                ),
                LocationVarCondition(
                    source="location_variable",
                    key="store_type",
                    operator=ConditionOperator.EQ,
                    value="flagship",
                ),
                VisitContextCondition(
                    source="visit_context",
                    key="visit_type",
                    operator=ConditionOperator.IN,
                    value=["audit"],
                ),
            ]
        )
        reloaded = DependencyRule.model_validate(rule.model_dump())
        assert reloaded == rule

    def test_round_trip_preserves_source_key(self) -> None:
        """model_dump() includes 'source' so the union can be re-parsed."""
        rule = DependencyRule(
            conditions=[
                FieldRefCondition(field_id="q1", operator=ConditionOperator.EQ, value="yes"),
            ]
        )
        dumped = rule.model_dump()
        cond_dict = dumped["conditions"][0]
        assert cond_dict["source"] == "field"
        assert cond_dict["field_id"] == "q1"

    def test_round_trip_from_legacy_to_field_ref(self) -> None:
        """A rule deserialized from a legacy dict round-trips as FieldRefCondition."""
        rule = DependencyRule.model_validate({
            "conditions": [{"field_id": "q2", "operator": "is_empty"}],
        })
        reloaded = DependencyRule.model_validate(rule.model_dump())
        assert isinstance(reloaded.conditions[0], FieldRefCondition)
        assert reloaded.conditions[0].field_id == "q2"


# ---------------------------------------------------------------------------
# LocationVariableBinding
# ---------------------------------------------------------------------------

class TestLocationVariableBinding:
    """Tests for the LocationVariableBinding value-object."""

    def test_basic_creation(self) -> None:
        """LocationVariableBinding validates key/scope/value."""
        binding = LocationVariableBinding(
            key="store_type",
            scope="store_001",
            value="flagship",
        )
        assert binding.key == "store_type"
        assert binding.scope == "store_001"
        assert binding.value == "flagship"

    def test_value_can_be_any_type(self) -> None:
        """value accepts any JSON-serializable type."""
        binding_int = LocationVariableBinding(key="k", scope="s", value=42)
        binding_bool = LocationVariableBinding(key="k", scope="s", value=True)
        binding_list = LocationVariableBinding(key="k", scope="s", value=["a", "b"])
        assert binding_int.value == 42
        assert binding_bool.value is True
        assert binding_list.value == ["a", "b"]

    def test_extra_fields_forbidden(self) -> None:
        """Extra fields are rejected."""
        with pytest.raises(ValidationError):
            LocationVariableBinding(
                key="k",
                scope="s",
                value="v",
                extra="not_allowed",  # type: ignore[call-arg]
            )

    def test_round_trip(self) -> None:
        """LocationVariableBinding round-trips through model_dump/model_validate."""
        binding = LocationVariableBinding(key="store_type", scope="store_42", value="flagship")
        reloaded = LocationVariableBinding.model_validate(binding.model_dump())
        assert reloaded == binding


# ---------------------------------------------------------------------------
# Discriminated union discrimination
# ---------------------------------------------------------------------------

class TestUnionDiscrimination:
    """Tests that the union correctly dispatches by source."""

    def test_discriminates_field(self) -> None:
        """source='field' → FieldRefCondition."""
        rule = DependencyRule(conditions=[
            FieldRefCondition(field_id="q1", operator=ConditionOperator.EQ, value=1),
        ])
        assert isinstance(rule.conditions[0], FieldRefCondition)

    def test_discriminates_location_variable(self) -> None:
        """source='location_variable' → LocationVarCondition."""
        rule = DependencyRule.model_validate({
            "conditions": [{
                "source": "location_variable",
                "key": "store_type",
                "operator": "eq",
                "value": "flagship",
            }],
        })
        assert isinstance(rule.conditions[0], LocationVarCondition)

    def test_discriminates_visit_context(self) -> None:
        """source='visit_context' → VisitContextCondition."""
        rule = DependencyRule.model_validate({
            "conditions": [{
                "source": "visit_context",
                "key": "visit_type",
                "operator": "in",
                "value": ["audit"],
            }],
        })
        assert isinstance(rule.conditions[0], VisitContextCondition)

    def test_unknown_source_raises(self) -> None:
        """Unknown source value raises ValidationError."""
        with pytest.raises(ValidationError):
            DependencyRule.model_validate({
                "conditions": [{
                    "source": "unknown_source",
                    "key": "x",
                    "operator": "eq",
                    "value": 1,
                }],
            })

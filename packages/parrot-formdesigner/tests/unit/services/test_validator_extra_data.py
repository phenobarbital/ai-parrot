"""Unit tests for ValidationResult.extra_data + the validator's payload-side
diff (FEAT-458 Module 3).

Covers the new attribute's default, the diff's correctness for basic,
declared-but-empty, and nested (GROUP/ARRAY) cases, policy-blindness
(spec AC16), and the early-return paths.
"""

import pytest
from parrot_formdesigner.core.constraints import (
    ConditionOperator,
    DependencyRule,
    FieldCondition,
)
from parrot_formdesigner.core.resolution import resolve_rule_references
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.validators import FormValidator, ValidationResult


def _field(field_id: str, **kw) -> FormField:
    """Build a minimal FormField."""
    kw.setdefault("field_type", FieldType.TEXT)
    kw.setdefault("label", field_id)
    return FormField(field_id=field_id, **kw)


def _form(sections: list[FormSection], form_id: str = "f") -> FormSchema:
    """Build a minimal FormSchema."""
    return FormSchema(form_id=form_id, title="Test", sections=sections)


@pytest.fixture
def simple_form() -> FormSchema:
    """A form declaring a single required "name" field."""
    return _form([FormSection(section_id="s", fields=[_field("name", required=True)])])


@pytest.fixture
def form_with_optional_field() -> FormSchema:
    """A form declaring a single optional "note" field."""
    return _form([FormSection(section_id="s", fields=[_field("note", required=False)])])


@pytest.fixture
def form_with_group_and_array() -> FormSchema:
    """A form with a GROUP (children) and an ARRAY (item_template) —
    exercises the recursive traversal (spec AC9)."""
    group = _field(
        "address",
        field_type=FieldType.GROUP,
        children=[_field("address_street"), _field("address_city")],
    )
    array_field = _field(
        "items",
        field_type=FieldType.ARRAY,
        item_template=_field("item"),
    )
    return _form([FormSection(section_id="s", fields=[group, array_field])])


@pytest.fixture
def circular_form() -> FormSchema:
    """A form with a mutual depends_on cycle (f1 <-> f2), so validate()
    takes the __circular__ early return."""
    f1 = _field(
        "f1",
        depends_on=DependencyRule(conditions=[FieldCondition(field_id="f2", operator=ConditionOperator.EQ, value="x")]),
    )
    f2 = _field(
        "f2",
        depends_on=DependencyRule(conditions=[FieldCondition(field_id="f1", operator=ConditionOperator.EQ, value="x")]),
    )
    form = _form([FormSection(section_id="s", fields=[f1, f2])])
    return resolve_rule_references(form)


def test_validation_result_extra_data_defaults_empty():
    """Existing three-field construction sites keep working."""
    r = ValidationResult(is_valid=True, errors={}, sanitized_data={})
    assert r.extra_data == {}


class TestValidateReportsExtras:
    async def test_reports_undeclared_keys(self, simple_form):
        result = await FormValidator().validate(simple_form, {"name": "Ana", "legacy_id": 42, "_client_ms": 1180})
        assert result.extra_data == {"legacy_id": 42, "_client_ms": 1180}
        assert "legacy_id" not in result.sanitized_data

    async def test_empty_when_payload_matches_schema(self, simple_form):
        result = await FormValidator().validate(simple_form, {"name": "Ana"})
        assert result.extra_data == {}

    async def test_declared_but_empty_is_not_an_extra(self, form_with_optional_field):
        """Spec AC8 — the sanitized_data.keys() trap."""
        result = await FormValidator().validate(form_with_optional_field, {"note": None})
        assert result.extra_data == {}

    async def test_group_and_array_children_not_extras(self, form_with_group_and_array):
        """Spec AC9 — the recursive traversal is used."""
        result = await FormValidator().validate(
            form_with_group_and_array,
            {"address_street": "Main 1", "items": [], "junk": 1},
        )
        assert result.extra_data == {"junk": 1}

    async def test_array_item_template_field_id_not_an_extra(self, form_with_group_and_array):
        """Code-review fix — a top-level payload key literally matching an
        ARRAY's item_template field_id ("item") must not be misclassified
        as an extra (spec AC9), and must NOT be validated/coerced as an
        ordinary top-level field either (it stays absent from sanitized_data,
        since item_template is a template for repeated elements, not a real
        submission key)."""
        result = await FormValidator().validate(
            form_with_group_and_array,
            {"address_street": "Main 1", "items": [], "item": "sneaky", "junk": 1},
        )
        assert result.extra_data == {"junk": 1}
        assert "item" not in result.sanitized_data

    async def test_policy_blind(self, simple_form):
        """Spec AC16 — same result under every policy."""
        payload = {"name": "Ana", "junk": 1}
        results = []
        for policy in ("drop", "keep", "reject"):
            form = simple_form.model_copy(update={"unknown_fields": policy})
            results.append((await FormValidator().validate(form, payload)).extra_data)
        assert results[0] == results[1] == results[2] == {"junk": 1}

    async def test_extras_do_not_affect_is_valid(self, simple_form):
        result = await FormValidator().validate(simple_form, {"name": "Ana", "junk": 1})
        assert result.is_valid is True

    async def test_circular_early_return_has_empty_extras(self, circular_form):
        result = await FormValidator().validate(circular_form, {"junk": 1})
        assert result.is_valid is False
        assert "__circular__" in result.errors
        assert result.extra_data == {}

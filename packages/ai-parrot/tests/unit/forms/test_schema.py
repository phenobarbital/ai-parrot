"""Unit tests for form schema models."""

import pytest
from parrot.forms import (
    ConditionOperator,
    DependencyRule,
    FieldCondition,
    FieldConstraints,
    FieldOption,
    FieldType,
    FormField,
    FormSchema,
    FormSection,
    LayoutType,
    RenderedForm,
    StyleSchema,
    SubmitAction,
)


class TestFormField:
    """Tests for FormField model."""

    def test_basic_field(self):
        """FormField with minimal required fields."""
        field = FormField(field_id="name", field_type=FieldType.TEXT, label="Name")
        assert field.field_id == "name"
        assert field.required is False

    def test_localized_label_str(self):
        """Label as a simple string."""
        field = FormField(field_id="x", field_type=FieldType.TEXT, label="Name")
        assert field.label == "Name"

    def test_localized_label_dict(self):
        """Label as an i18n dictionary."""
        field = FormField(
            field_id="x",
            field_type=FieldType.TEXT,
            label={"en": "Name", "es": "Nombre"},
        )
        assert field.label["en"] == "Name"

    def test_self_referential_children(self):
        """GROUP field with child fields."""
        child = FormField(field_id="street", field_type=FieldType.TEXT, label="Street")
        parent = FormField(
            field_id="address",
            field_type=FieldType.GROUP,
            label="Address",
            children=[child],
        )
        assert len(parent.children) == 1
        assert parent.children[0].field_id == "street"

    def test_field_with_constraints(self):
        """FormField with constraint configuration."""
        field = FormField(
            field_id="email",
            field_type=FieldType.EMAIL,
            label="Email",
            constraints=FieldConstraints(pattern=r".+@.+\..+"),
        )
        assert field.constraints.pattern is not None

    def test_array_field_with_item_template(self):
        """ARRAY field with item_template."""
        item = FormField(field_id="tag", field_type=FieldType.TEXT, label="Tag")
        field = FormField(
            field_id="tags",
            field_type=FieldType.ARRAY,
            label="Tags",
            item_template=item,
        )
        assert field.item_template.field_id == "tag"

    def test_field_with_options(self):
        """SELECT field with static options."""
        opts = [
            FieldOption(value="a", label="Option A"),
            FieldOption(value="b", label="Option B"),
        ]
        field = FormField(
            field_id="choice",
            field_type=FieldType.SELECT,
            label="Pick one",
            options=opts,
        )
        assert len(field.options) == 2

    def test_field_extra_forbidden(self):
        """FormField rejects extra fields."""
        with pytest.raises(Exception):
            FormField(
                field_id="x",
                field_type=FieldType.TEXT,
                label="X",
                unknown_field="oops",
            )

    def test_read_only_field(self):
        """FormField can be marked read_only."""
        field = FormField(
            field_id="id",
            field_type=FieldType.HIDDEN,
            label="ID",
            read_only=True,
        )
        assert field.read_only is True

    def test_required_field(self):
        """FormField required flag."""
        field = FormField(
            field_id="name",
            field_type=FieldType.TEXT,
            label="Name",
            required=True,
        )
        assert field.required is True


class TestFormSchema:
    """Tests for FormSchema model."""

    def test_json_roundtrip(self):
        """FormSchema serializes and deserializes correctly."""
        schema = FormSchema(
            form_id="test",
            title="Test",
            sections=[
                FormSection(
                    section_id="s1",
                    fields=[
                        FormField(field_id="f1", field_type=FieldType.TEXT, label="F1")
                    ],
                )
            ],
        )
        json_str = schema.model_dump_json()
        restored = FormSchema.model_validate_json(json_str)
        assert restored.form_id == schema.form_id
        assert len(restored.sections) == 1

    def test_all_field_types(self):
        """Every FieldType can be used in a FormField."""
        for ft in FieldType:
            field = FormField(field_id=f"f_{ft.value}", field_type=ft, label=ft.value)
            assert field.field_type == ft

    def test_default_version(self):
        """FormSchema defaults to version 1.0."""
        schema = FormSchema(
            form_id="x",
            title="X",
            sections=[FormSection(section_id="s1", fields=[])],
        )
        assert schema.version == "1.0"

    def test_cancel_allowed_default(self):
        """FormSchema cancel_allowed defaults to True."""
        schema = FormSchema(
            form_id="x",
            title="X",
            sections=[],
        )
        assert schema.cancel_allowed is True

    def test_with_submit_action(self):
        """FormSchema with submit action."""
        schema = FormSchema(
            form_id="x",
            title="X",
            sections=[],
            submit=SubmitAction(action_type="tool_call", action_ref="my_tool"),
        )
        assert schema.submit.action_ref == "my_tool"

    def test_localized_title(self):
        """FormSchema title can be a dict."""
        schema = FormSchema(
            form_id="x",
            title={"en": "My Form", "es": "Mi Formulario"},
            sections=[],
        )
        assert schema.title["en"] == "My Form"

    def test_with_meta(self):
        """FormSchema accepts meta dict."""
        schema = FormSchema(
            form_id="x",
            title="X",
            sections=[],
            meta={"tenant": "acme"},
        )
        assert schema.meta["tenant"] == "acme"


class TestDependencyRule:
    """Tests for DependencyRule model."""

    def test_serialization(self):
        """DependencyRule serializes and deserializes with nested conditions."""
        rule = DependencyRule(
            conditions=[
                FieldCondition(
                    field_id="toggle",
                    operator=ConditionOperator.EQ,
                    value=True,
                )
            ],
            effect="show",
        )
        data = rule.model_dump()
        assert len(data["conditions"]) == 1
        restored = DependencyRule.model_validate(data)
        assert restored.effect == "show"

    def test_default_logic(self):
        """DependencyRule defaults to AND logic."""
        rule = DependencyRule(
            conditions=[
                FieldCondition(field_id="a", operator=ConditionOperator.EQ, value=1)
            ],
        )
        assert rule.logic == "and"

    def test_or_logic(self):
        """DependencyRule supports OR logic."""
        rule = DependencyRule(
            conditions=[
                FieldCondition(field_id="a", operator=ConditionOperator.IS_EMPTY),
                FieldCondition(field_id="b", operator=ConditionOperator.IS_EMPTY),
            ],
            logic="or",
            effect="hide",
        )
        assert rule.logic == "or"
        assert rule.effect == "hide"

    def test_all_operators(self):
        """All ConditionOperator values can be used."""
        for op in ConditionOperator:
            cond = FieldCondition(field_id="x", operator=op)
            assert cond.operator == op


class TestSubmitAction:
    """Tests for SubmitAction model."""

    def test_tool_call(self):
        """SubmitAction with tool_call type."""
        action = SubmitAction(action_type="tool_call", action_ref="process_form")
        assert action.action_type == "tool_call"
        assert action.method == "POST"

    def test_endpoint(self):
        """SubmitAction with endpoint type."""
        action = SubmitAction(
            action_type="endpoint",
            action_ref="https://api.example.com/submit",
            method="PUT",
        )
        assert action.method == "PUT"

    def test_with_confirm_message(self):
        """SubmitAction with localized confirm message."""
        action = SubmitAction(
            action_type="event",
            action_ref="form.submitted",
            confirm_message={"en": "Are you sure?", "es": "¿Está seguro?"},
        )
        assert "en" in action.confirm_message


class TestRenderedForm:
    """Tests for RenderedForm model."""

    def test_basic_rendered_form(self):
        """RenderedForm with content and content_type."""
        rf = RenderedForm(content={"type": "AdaptiveCard"}, content_type="application/vnd.microsoft.card.adaptive")
        assert rf.content_type == "application/vnd.microsoft.card.adaptive"
        assert rf.style_output is None
        assert rf.metadata is None

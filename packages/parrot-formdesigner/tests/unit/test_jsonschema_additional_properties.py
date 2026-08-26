"""Unit tests for JsonSchemaRenderer's `additionalProperties: false` under
the `reject` unknown-fields policy (FEAT-458, TASK-2439 — spec Module 10).
"""

import pytest
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer


def _form(*, unknown_fields: str = "drop") -> FormSchema:
    return FormSchema(
        form_id="test-form",
        title="Test Form",
        sections=[FormSection(section_id="s1", fields=[FormField(field_id="name", field_type=FieldType.TEXT, label="Name")])],
        unknown_fields=unknown_fields,
    )


class TestAdditionalProperties:
    async def test_reject_emits_false(self):
        form = _form(unknown_fields="reject")
        result = await JsonSchemaRenderer().render(form)
        assert result.content["additionalProperties"] is False

    @pytest.mark.parametrize("policy", ["drop", "keep"])
    async def test_non_reject_omits_key(self, policy):
        form = _form(unknown_fields=policy)
        result = await JsonSchemaRenderer().render(form)
        assert "additionalProperties" not in result.content

    async def test_drop_and_keep_output_identical(self):
        """Spec AC22 — byte-identical output for drop/keep (no visible policy trace)."""
        drop = await JsonSchemaRenderer().render(_form(unknown_fields="drop"))
        keep = await JsonSchemaRenderer().render(_form(unknown_fields="keep"))
        assert drop.content == keep.content

    async def test_other_schema_keys_intact(self):
        result = await JsonSchemaRenderer().render(_form(unknown_fields="reject"))
        assert result.content["type"] == "object"
        assert result.content["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert "properties" in result.content

    async def test_content_type_unchanged(self):
        result = await JsonSchemaRenderer().render(_form(unknown_fields="reject"))
        assert result.content_type == "application/schema+json"

    async def test_style_output_unaffected(self):
        result = await JsonSchemaRenderer().render(_form(unknown_fields="reject"))
        assert result.style_output is None

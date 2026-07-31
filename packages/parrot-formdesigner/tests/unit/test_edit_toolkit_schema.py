"""Unit tests for EditToolkit's schema-aware creation methods (FEAT-388, TASK-1970)."""

import pytest
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.tools.edit_toolkit import EditToolkit


@pytest.fixture
def base_form():
    return FormSchema(
        form_id="test-form",
        title="Test Form",
        sections=[
            FormSection(
                section_id="main",
                title="Main",
                fields=[
                    FormField(
                        field_id="existing",
                        field_type=FieldType.TEXT,
                        label="Existing Field",
                    ),
                ],
            ),
        ],
    )


@pytest.fixture
def toolkit(base_form):
    return EditToolkit(base_form)


class TestAddFieldFromSchema:
    @pytest.mark.asyncio
    async def test_with_shortcuts(self, toolkit):
        result = await toolkit.add_field_from_schema(
            str(toolkit.form.sections[0].section_uid),
            {"label": "Email Address", "field_type": "email", "required": True},
        )
        assert result["success"] is True
        assert result["field_id"] == "email_address"

    @pytest.mark.asyncio
    async def test_with_full_field(self, toolkit):
        result = await toolkit.add_field_from_schema(
            str(toolkit.form.sections[0].section_uid),
            {"field_id": "custom_id", "field_type": "text", "label": "Custom"},
        )
        assert result["success"] is True
        assert result["field_id"] == "custom_id"

    @pytest.mark.asyncio
    async def test_with_position(self, toolkit):
        result = await toolkit.add_field_from_schema(
            str(toolkit.form.sections[0].section_uid),
            {"label": "First", "field_type": "text"},
            position=0,
        )
        assert result["success"] is True
        assert toolkit.form.sections[0].fields[0].field_id == "first"

    @pytest.mark.asyncio
    async def test_invalid_schema(self, toolkit):
        result = await toolkit.add_field_from_schema(
            str(toolkit.form.sections[0].section_uid), {}
        )
        assert "error" in result


class TestAddSectionFromSchema:
    @pytest.mark.asyncio
    async def test_with_shortcuts(self, toolkit):
        result = await toolkit.add_section_from_schema({
            "title": "Contact Info",
            "fields": [
                {"label": "Phone", "field_type": "phone"},
            ],
        })
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_with_position(self, toolkit):
        result = await toolkit.add_section_from_schema(
            {"title": "First Section", "fields": []},
            position=0,
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_invalid_section(self, toolkit):
        result = await toolkit.add_section_from_schema({"invalid": True})
        assert "error" in result

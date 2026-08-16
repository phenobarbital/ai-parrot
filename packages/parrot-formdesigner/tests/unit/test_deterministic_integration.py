"""Integration tests for the deterministic CreateFormTool pipeline (FEAT-388, TASK-1971).

Verifies the full pipeline works end-to-end across all three modules:
FormAssembler (TASK-1968), CreateFormTool deterministic input (TASK-1969),
and EditToolkit schema-aware methods (TASK-1970).
"""

from unittest.mock import MagicMock

import pytest
from parrot_formdesigner.assembler import FormAssembler
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer
from parrot_formdesigner.services.validators import FormValidator
from parrot_formdesigner.tools.create_form import CreateFormTool
from parrot_formdesigner.tools.edit_toolkit import EditToolkit


class TestRoundtrip:
    @pytest.mark.asyncio
    async def test_jsonschema_roundtrip(self):
        """JSON Schema → assemble → render preserves field structure."""
        original = {
            "type": "object",
            "title": "Feedback",
            "properties": {
                "name": {"type": "string", "minLength": 1},
                "email": {"type": "string", "format": "email"},
                "rating": {"type": "integer", "minimum": 1, "maximum": 5},
            },
            "required": ["name", "email"],
        }
        assembler = FormAssembler()
        form = assembler.assemble(original, form_id="feedback")

        renderer = JsonSchemaRenderer()
        # JsonSchemaRenderer.render() is async and returns a RenderedForm —
        # the JSON Schema dict is on `.content` (see corrected Codebase
        # Contract in TASK-1971).
        rendered = (await renderer.render(form)).content

        assert "name" in rendered.get("properties", {})
        assert "email" in rendered.get("properties", {})
        assert "rating" in rendered.get("properties", {})


class TestEquivalence:
    def test_shortcut_equals_explicit(self):
        """Same form via shortcuts and explicit construction are equivalent."""
        assembler = FormAssembler()
        shortcut_form = assembler.assemble({
            "form_id": "equiv-test",
            "title": "Test",
            "sections": [{
                "section_id": "main",
                "fields": [
                    {"field_id": "name", "field_type": "text", "label": "Name", "required": True},
                    {"field_id": "age", "field_type": "integer", "label": "Age"},
                ],
            }],
        })

        explicit_form = FormSchema(
            form_id="equiv-test",
            title="Test",
            sections=[FormSection(
                section_id="main",
                fields=[
                    FormField(field_id="name", field_type=FieldType.TEXT, label="Name", required=True),
                    FormField(field_id="age", field_type=FieldType.INTEGER, label="Age"),
                ],
            )],
        )

        assert shortcut_form.model_dump() == explicit_form.model_dump()


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_create_then_edit(self):
        """CreateFormTool produces form, EditToolkit adds field from schema."""
        mock_client = MagicMock()
        tool = CreateFormTool(client=mock_client)
        result = await tool.execute(
            schema={
                "form_id": "e2e-test",
                "title": "E2E",
                "sections": [{"section_id": "s1", "fields": [
                    {"field_id": "name", "field_type": "text", "label": "Name"},
                ]}],
            },
        )
        assert result.success is True

        form = FormSchema.model_validate(result.metadata["form"])
        toolkit = EditToolkit(form)
        add_result = await toolkit.add_field_from_schema(
            str(form.sections[0].section_uid),
            {"label": "Email", "field_type": "email", "required": True},
        )
        assert add_result["success"] is True
        assert len(toolkit.form.sections[0].fields) == 2


class TestValidatorIntegration:
    def test_no_circular_deps_on_deterministic(self):
        """Deterministic forms pass circular dependency check."""
        assembler = FormAssembler()
        form = assembler.assemble_from_fields(
            [
                {"label": "A", "field_type": "text"},
                {"label": "B", "field_type": "text"},
            ],
            title="Validator Test",
        )
        validator = FormValidator()
        errors = validator.check_schema(form)
        assert errors == []

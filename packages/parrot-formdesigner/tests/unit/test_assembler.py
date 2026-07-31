"""Unit tests for FormAssembler (FEAT-388, TASK-1968)."""

import pytest
from parrot_formdesigner.assembler import FormAssembler
from parrot_formdesigner.core.types import FieldType
from pydantic import ValidationError


@pytest.fixture
def assembler():
    return FormAssembler()


class TestDetectFormat:
    def test_jsonschema_detected(self, assembler):
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        assert assembler.detect_format(schema) == "jsonschema"

    def test_native_with_sections(self, assembler):
        schema = {"title": "Test", "sections": []}
        assert assembler.detect_format(schema) == "native"

    def test_native_with_fields(self, assembler):
        schema = {"title": "Test", "fields": []}
        assert assembler.detect_format(schema) == "native"

    def test_neither_shape_falls_back_to_native(self, assembler):
        assert assembler.detect_format({"invalid": "data"}) == "native"


class TestExpandShortcuts:
    def test_field_id_from_label(self, assembler):
        field = {"label": "First Name", "field_type": "text"}
        expanded = assembler.expand_shortcuts({"sections": [{"fields": [field]}]})
        assert expanded["sections"][0]["fields"][0]["field_id"] == "first_name"

    def test_section_id_auto_generated(self, assembler):
        section = {"title": "Info", "fields": []}
        expanded = assembler.expand_shortcuts({"sections": [section]})
        assert expanded["sections"][0]["section_id"] == "section-1"

    def test_section_id_sequential(self, assembler):
        expanded = assembler.expand_shortcuts(
            {"sections": [{"fields": []}, {"fields": []}]}
        )
        assert expanded["sections"][0]["section_id"] == "section-1"
        assert expanded["sections"][1]["section_id"] == "section-2"

    def test_form_id_from_title(self, assembler):
        expanded = assembler.expand_shortcuts({"title": "Customer Feedback", "sections": []})
        assert expanded["form_id"] == "customer-feedback"

    def test_top_level_fields_wrapped_in_default_section(self, assembler):
        expanded = assembler.expand_shortcuts(
            {"title": "Test", "fields": [{"label": "Name", "field_type": "text"}]}
        )
        assert "sections" in expanded
        assert expanded["sections"][0]["fields"][0]["field_id"] == "name"

    def test_field_id_collision_gets_numeric_suffix(self, assembler):
        fields = [
            {"label": "Name", "field_type": "text"},
            {"label": "Name", "field_type": "text"},
        ]
        expanded = assembler.expand_shortcuts({"sections": [{"fields": fields}]})
        ids = [f["field_id"] for f in expanded["sections"][0]["fields"]]
        assert ids == ["name", "name_2"]

    def test_string_field_type_accepted(self, assembler):
        field = {"field_id": "x", "label": "X", "field_type": "email"}
        result = assembler.assemble_field(field)
        assert result.field_type == FieldType.EMAIL

    def test_does_not_mutate_input(self, assembler):
        original = {"sections": [{"fields": [{"label": "Name", "field_type": "text"}]}]}
        assembler.expand_shortcuts(original)
        assert "section_id" not in original["sections"][0]
        assert "field_id" not in original["sections"][0]["fields"][0]


class TestAssemble:
    def test_from_jsonschema(self, assembler):
        schema = {
            "type": "object",
            "title": "Test",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name"],
        }
        form = assembler.assemble(schema, form_id="test-form")
        assert form.form_id == "test-form"
        assert len(form.sections) >= 1

    def test_from_native(self, assembler):
        schema = {
            "form_id": "native-form",
            "title": "Native",
            "sections": [{
                "section_id": "s1",
                "fields": [
                    {"field_id": "name", "field_type": "text", "label": "Name"},
                ],
            }],
        }
        form = assembler.assemble(schema)
        assert form.form_id == "native-form"

    def test_invalid_schema_fails_fast(self, assembler):
        with pytest.raises((ValidationError, ValueError)):
            assembler.assemble({"invalid": "data"})

    def test_unknown_field_type_fails(self, assembler):
        schema = {
            "form_id": "f",
            "title": "T",
            "sections": [{"section_id": "s", "fields": [
                {"field_id": "x", "field_type": "nonexistent_type", "label": "X"}
            ]}],
        }
        with pytest.raises(ValidationError):
            assembler.assemble(schema)


class TestAssembleFromSections:
    def test_basic(self, assembler):
        sections = [{"title": "Info", "fields": [
            {"label": "Name", "field_type": "text"},
        ]}]
        form = assembler.assemble_from_sections(sections, title="Test")
        assert len(form.sections) == 1
        assert form.sections[0].fields[0].field_type == FieldType.TEXT


class TestAssembleFromFields:
    def test_wraps_in_default_section(self, assembler):
        fields = [
            {"label": "Name", "field_type": "text", "required": True},
            {"label": "Age", "field_type": "integer"},
        ]
        form = assembler.assemble_from_fields(fields, title="Test")
        assert len(form.sections) == 1
        assert len(form.sections[0].fields) == 2


class TestAssembleField:
    def test_basic(self, assembler):
        field = assembler.assemble_field({"label": "Email", "field_type": "email"})
        assert field.field_id == "email"
        assert field.field_type == FieldType.EMAIL

    def test_invalid_field_raises(self, assembler):
        with pytest.raises((ValidationError, ValueError)):
            assembler.assemble_field({})


class TestAssembleSection:
    def test_basic(self, assembler):
        section = assembler.assemble_section({
            "title": "Contact",
            "fields": [{"label": "Phone", "field_type": "phone"}],
        })
        assert section.section_id is not None
        assert len(section.fields) == 1

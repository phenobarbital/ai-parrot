"""Unit tests for parrot-formdesigner extractors."""
import pytest
from parrot.formdesigner.core import FormSchema
from parrot.formdesigner.extractors import (
    PydanticExtractor,
    ToolExtractor,
    YAMLExtractor,
    JSONSchemaExtractor,
)
from pydantic import BaseModel


class SampleModel(BaseModel):
    name: str
    age: int
    email: str


class TestPydanticExtractor:
    def test_extract_from_pydantic_model(self):
        extractor = PydanticExtractor()
        schema = extractor.extract(SampleModel)
        assert isinstance(schema, FormSchema)
        all_fields = [f for s in schema.sections for f in s.fields]
        assert len(all_fields) == 3

    def test_field_names_preserved(self):
        extractor = PydanticExtractor()
        schema = extractor.extract(SampleModel)
        field_names = [f.field_id for s in schema.sections for f in s.fields]
        assert "name" in field_names
        assert "email" in field_names


class TestYAMLExtractor:
    def test_extract_from_yaml_string(self):
        yaml_content = """
form_id: contact
title: Contact Form
fields:
  - name: subject
    field_type: text
    label: Subject
"""
        extractor = YAMLExtractor()
        schema = extractor.extract(yaml_content)
        assert isinstance(schema, FormSchema)
        assert schema.form_id == "contact"

    def test_extract_with_sections(self):
        yaml_content = """
form_id: test_form
title: Test Form
sections:
  - section_id: main
    title: Main
    fields:
      - name: email
        type: email
        label: Email
"""
        extractor = YAMLExtractor()
        schema = extractor.extract(yaml_content)
        assert isinstance(schema, FormSchema)
        assert schema.form_id == "test_form"
        assert len(schema.sections) == 1


class TestJSONSchemaExtractor:
    def test_extract_from_json_schema(self):
        json_schema = {
            "title": "Sample Form",
            "type": "object",
            "properties": {
                "name": {"type": "string", "title": "Name"},
                "age": {"type": "integer", "title": "Age"},
            },
            "required": ["name"],
        }
        extractor = JSONSchemaExtractor()
        schema = extractor.extract(json_schema, form_id="sample")
        assert isinstance(schema, FormSchema)
        assert schema.form_id == "sample"
        all_fields = [f for s in schema.sections for f in s.fields]
        assert len(all_fields) == 2

    def test_required_fields(self):
        json_schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "optional_field": {"type": "string"},
            },
            "required": ["name"],
        }
        extractor = JSONSchemaExtractor()
        schema = extractor.extract(json_schema)
        all_fields = [f for s in schema.sections for f in s.fields]
        name_field = next(f for f in all_fields if f.field_id == "name")
        optional_field = next(f for f in all_fields if f.field_id == "optional_field")
        assert name_field.required is True
        assert optional_field.required is False


class TestToolExtractor:
    def test_extract_raises_without_args_schema(self):
        class FakeTool:
            name = "fake_tool"
            description = "A fake tool"
            args_schema = None

        extractor = ToolExtractor()
        with pytest.raises(ValueError):
            extractor.extract(FakeTool())

    def test_extract_from_tool_with_args_schema(self):
        class ToolArgs(BaseModel):
            query: str
            limit: int

        class FakeTool:
            name = "search_tool"
            description = "A search tool"
            args_schema = ToolArgs

        extractor = ToolExtractor()
        schema = extractor.extract(FakeTool())
        assert isinstance(schema, FormSchema)
        assert schema.form_id == "search_tool_form"

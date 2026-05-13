"""Unit tests for parrot-formdesigner extractors."""
import pytest
from parrot_formdesigner.core import FormSchema
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.extractors import (
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


class TestYamlExtractorNewFieldTypes:
    """Roundtrip tests for new FieldType values added in FEAT-167."""

    def test_extractor_yaml_signature_roundtrip(self):
        """YAML key 'signature' extracts to FieldType.SIGNATURE."""
        yaml_content = """
form_id: test_sig
title: Test
sections:
  - section_id: s1
    fields:
      - field_id: sig
        type: signature
        label: Your Signature
"""
        extractor = YAMLExtractor()
        form = extractor.extract(yaml_content)
        assert form.sections[0].fields[0].field_type == FieldType.SIGNATURE

    def test_extractor_yaml_nps_roundtrip(self):
        """YAML key 'nps' extracts to FieldType.NPS."""
        yaml_content = """
form_id: test_nps
title: Test
sections:
  - section_id: s1
    fields:
      - field_id: score
        type: nps
        label: Net Promoter Score
"""
        extractor = YAMLExtractor()
        form = extractor.extract(yaml_content)
        assert form.sections[0].fields[0].field_type == FieldType.NPS

    def test_extractor_yaml_likert_roundtrip(self):
        """YAML key 'likert' extracts to FieldType.LIKERT."""
        yaml_content = """
form_id: test_likert
title: Test
sections:
  - section_id: s1
    fields:
      - field_id: rating
        type: likert
        label: Satisfaction
"""
        extractor = YAMLExtractor()
        form = extractor.extract(yaml_content)
        assert form.sections[0].fields[0].field_type == FieldType.LIKERT

    def test_extractor_yaml_ranking_roundtrip(self):
        """YAML key 'ranking' extracts to FieldType.RANKING."""
        yaml_content = """
form_id: test_ranking
title: Test
sections:
  - section_id: s1
    fields:
      - field_id: rank
        type: ranking
        label: Ranking
"""
        extractor = YAMLExtractor()
        form = extractor.extract(yaml_content)
        assert form.sections[0].fields[0].field_type == FieldType.RANKING

    def test_extractor_yaml_tags_roundtrip(self):
        """YAML key 'tags' extracts to FieldType.TAGS."""
        yaml_content = """
form_id: test_tags
title: Test
sections:
  - section_id: s1
    fields:
      - field_id: kw
        type: tags
        label: Tags
"""
        extractor = YAMLExtractor()
        form = extractor.extract(yaml_content)
        assert form.sections[0].fields[0].field_type == FieldType.TAGS

    def test_extractor_yaml_location_roundtrip(self):
        """YAML key 'location' extracts to FieldType.LOCATION."""
        yaml_content = """
form_id: test_loc
title: Test
sections:
  - section_id: s1
    fields:
      - field_id: country
        type: location
        label: Country
"""
        extractor = YAMLExtractor()
        form = extractor.extract(yaml_content)
        assert form.sections[0].fields[0].field_type == FieldType.LOCATION

    def test_extractor_yaml_availability_roundtrip(self):
        """YAML key 'availability' extracts to FieldType.AVAILABILITY."""
        yaml_content = """
form_id: test_avail
title: Test
sections:
  - section_id: s1
    fields:
      - field_id: slots
        type: availability
        label: Availability
"""
        extractor = YAMLExtractor()
        form = extractor.extract(yaml_content)
        assert form.sections[0].fields[0].field_type == FieldType.AVAILABILITY

    def test_extractor_yaml_dynamic_select_roundtrip(self):
        """YAML key 'dynamic_select' extracts to FieldType.DYNAMIC_SELECT."""
        yaml_content = """
form_id: test_ds
title: Test
sections:
  - section_id: s1
    fields:
      - field_id: country
        type: dynamic_select
        label: Dynamic Select
"""
        extractor = YAMLExtractor()
        form = extractor.extract(yaml_content)
        assert form.sections[0].fields[0].field_type == FieldType.DYNAMIC_SELECT

    def test_extractor_yaml_transfer_list_roundtrip(self):
        """YAML key 'transfer_list' extracts to FieldType.TRANSFER_LIST."""
        yaml_content = """
form_id: test_tl
title: Test
sections:
  - section_id: s1
    fields:
      - field_id: items
        type: transfer_list
        label: Transfer List
"""
        extractor = YAMLExtractor()
        form = extractor.extract(yaml_content)
        assert form.sections[0].fields[0].field_type == FieldType.TRANSFER_LIST

    def test_extractor_yaml_remote_response_roundtrip(self):
        """YAML key 'remote_response' extracts to FieldType.REMOTE_RESPONSE."""
        yaml_content = """
form_id: test_rr
title: Test
sections:
  - section_id: s1
    fields:
      - field_id: result
        type: remote_response
        label: Remote Response
"""
        extractor = YAMLExtractor()
        form = extractor.extract(yaml_content)
        assert form.sections[0].fields[0].field_type == FieldType.REMOTE_RESPONSE


class TestJsonSchemaExtractorNewFieldTypes:
    """Roundtrip tests for new FieldType values via JSON Schema format."""

    def test_extractor_jsonschema_signature_roundtrip(self):
        """JSON Schema format 'signature' → FieldType.SIGNATURE."""
        json_schema = {
            "type": "object",
            "properties": {
                "sig": {"type": "string", "format": "signature"},
            },
        }
        extractor = JSONSchemaExtractor()
        form = extractor.extract(json_schema, form_id="test")
        field = form.sections[0].fields[0]
        assert field.field_type == FieldType.SIGNATURE

    def test_extractor_jsonschema_dynamic_select_roundtrip(self):
        """JSON Schema format 'dynamic-select' + x-options-source → DYNAMIC_SELECT + OptionsSource."""
        json_schema = {
            "type": "object",
            "properties": {
                "country": {
                    "type": "string",
                    "format": "dynamic-select",
                    "x-options-source": {
                        "source_type": "endpoint",
                        "source_ref": "/api/countries",
                        "value_field": "code",
                        "label_field": "name",
                        "http_method": "GET",
                        "auth_ref": "basic-auth",
                    },
                },
            },
        }
        extractor = JSONSchemaExtractor()
        form = extractor.extract(json_schema, form_id="test")
        field = form.sections[0].fields[0]
        assert field.field_type == FieldType.DYNAMIC_SELECT
        assert field.options_source is not None
        assert field.options_source.source_ref == "/api/countries"
        assert field.options_source.value_field == "code"
        assert field.options_source.label_field == "name"
        assert field.options_source.http_method == "GET"
        assert field.options_source.auth_ref == "basic-auth"

    def test_extractor_jsonschema_nps_roundtrip(self):
        """JSON Schema format 'nps' → FieldType.NPS."""
        json_schema = {
            "type": "object",
            "properties": {
                "score": {"type": "integer", "format": "nps"},
            },
        }
        extractor = JSONSchemaExtractor()
        form = extractor.extract(json_schema, form_id="test")
        field = form.sections[0].fields[0]
        assert field.field_type == FieldType.NPS

    def test_extractor_jsonschema_likert_roundtrip(self):
        """JSON Schema format 'likert' → FieldType.LIKERT."""
        json_schema = {
            "type": "object",
            "properties": {
                "rating": {"type": "integer", "format": "likert"},
            },
        }
        extractor = JSONSchemaExtractor()
        form = extractor.extract(json_schema, form_id="test")
        field = form.sections[0].fields[0]
        assert field.field_type == FieldType.LIKERT

    def test_extractor_jsonschema_ranking_roundtrip(self):
        """JSON Schema format 'ranking' → FieldType.RANKING."""
        json_schema = {
            "type": "object",
            "properties": {
                "rank": {"type": "integer", "format": "ranking"},
            },
        }
        extractor = JSONSchemaExtractor()
        form = extractor.extract(json_schema, form_id="test")
        field = form.sections[0].fields[0]
        assert field.field_type == FieldType.RANKING

    def test_extractor_jsonschema_tags_roundtrip(self):
        """JSON Schema format 'tags' → FieldType.TAGS."""
        json_schema = {
            "type": "object",
            "properties": {
                "kw": {"type": "array", "format": "tags"},
            },
        }
        extractor = JSONSchemaExtractor()
        form = extractor.extract(json_schema, form_id="test")
        field = form.sections[0].fields[0]
        assert field.field_type == FieldType.TAGS

    def test_extractor_jsonschema_location_roundtrip(self):
        """JSON Schema format 'location' → FieldType.LOCATION."""
        json_schema = {
            "type": "object",
            "properties": {
                "country": {"type": "string", "format": "location"},
            },
        }
        extractor = JSONSchemaExtractor()
        form = extractor.extract(json_schema, form_id="test")
        field = form.sections[0].fields[0]
        assert field.field_type == FieldType.LOCATION

    def test_extractor_jsonschema_availability_roundtrip(self):
        """JSON Schema format 'availability' → FieldType.AVAILABILITY."""
        json_schema = {
            "type": "object",
            "properties": {
                "slots": {"type": "array", "format": "availability"},
            },
        }
        extractor = JSONSchemaExtractor()
        form = extractor.extract(json_schema, form_id="test")
        field = form.sections[0].fields[0]
        assert field.field_type == FieldType.AVAILABILITY

    def test_extractor_jsonschema_transfer_list_roundtrip(self):
        """JSON Schema format 'transfer-list' → FieldType.TRANSFER_LIST."""
        json_schema = {
            "type": "object",
            "properties": {
                "items": {"type": "array", "format": "transfer-list"},
            },
        }
        extractor = JSONSchemaExtractor()
        form = extractor.extract(json_schema, form_id="test")
        field = form.sections[0].fields[0]
        assert field.field_type == FieldType.TRANSFER_LIST

    def test_extractor_jsonschema_remote_response_roundtrip(self):
        """JSON Schema format 'remote-response' → FieldType.REMOTE_RESPONSE."""
        json_schema = {
            "type": "object",
            "properties": {
                "result": {"type": "object", "format": "remote-response"},
            },
        }
        extractor = JSONSchemaExtractor()
        form = extractor.extract(json_schema, form_id="test")
        field = form.sections[0].fields[0]
        assert field.field_type == FieldType.REMOTE_RESPONSE

    def test_extractor_jsonschema_underscore_variants(self):
        """JSON Schema underscore format variants also map correctly."""
        extractor = JSONSchemaExtractor()

        for fmt, expected in [
            ("dynamic_select", FieldType.DYNAMIC_SELECT),
            ("transfer_list", FieldType.TRANSFER_LIST),
            ("remote_response", FieldType.REMOTE_RESPONSE),
        ]:
            json_schema = {
                "type": "object",
                "properties": {
                    "f": {"type": "string", "format": fmt},
                },
            }
            form = extractor.extract(json_schema, form_id="test")
            field = form.sections[0].fields[0]
            assert field.field_type == expected, f"format '{fmt}' should map to {expected}"

    def test_extractor_jsonschema_options_source_defaults(self):
        """x-options-source with minimal keys uses correct defaults."""
        json_schema = {
            "type": "object",
            "properties": {
                "item": {
                    "type": "string",
                    "format": "dynamic-select",
                    "x-options-source": {
                        "source_type": "tool",
                        "source_ref": "get_items",
                    },
                },
            },
        }
        extractor = JSONSchemaExtractor()
        form = extractor.extract(json_schema, form_id="test")
        field = form.sections[0].fields[0]
        assert field.options_source is not None
        assert field.options_source.value_field == "value"
        assert field.options_source.label_field == "label"
        assert field.options_source.http_method == "GET"
        assert field.options_source.auth_ref is None

"""Unit tests for JsonSchemaExtractor."""

import pytest
from parrot.forms import FieldType
from parrot.forms.extractors.jsonschema import JsonSchemaExtractor


@pytest.fixture
def extractor():
    """JsonSchemaExtractor instance."""
    return JsonSchemaExtractor()


class TestJsonSchemaExtractorBasic:
    """Tests for basic type and required mapping."""

    def test_basic_types(self, extractor):
        """Basic JSON Schema types map to correct FieldTypes."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "score": {"type": "number"},
                "active": {"type": "boolean"},
            },
            "required": ["name"],
        }
        form = extractor.extract(schema)
        fields = {f.field_id: f for f in form.sections[0].fields}
        assert fields["name"].field_type == FieldType.TEXT
        assert fields["name"].required is True
        assert fields["age"].field_type == FieldType.INTEGER
        assert fields["score"].field_type == FieldType.NUMBER
        assert fields["active"].field_type == FieldType.BOOLEAN

    def test_required_false_by_default(self, extractor):
        """Fields not in required array are not required."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
        }
        form = extractor.extract(schema)
        assert form.sections[0].fields[0].required is False

    def test_form_id_defaults(self, extractor):
        """form_id defaults to 'form' when not provided."""
        form = extractor.extract({"type": "object", "properties": {}})
        assert form.form_id == "form"

    def test_custom_form_id(self, extractor):
        """Custom form_id is used."""
        form = extractor.extract({"type": "object", "properties": {}}, form_id="my_form")
        assert form.form_id == "my_form"

    def test_title_from_schema(self, extractor):
        """title is extracted from schema."""
        form = extractor.extract({"type": "object", "title": "My Form", "properties": {}})
        assert form.title == "My Form"

    def test_custom_title_overrides(self, extractor):
        """Custom title overrides schema title."""
        form = extractor.extract(
            {"type": "object", "title": "Schema Title", "properties": {}},
            title="Custom Title",
        )
        assert form.title == "Custom Title"

    def test_unknown_type_defaults_to_text(self, extractor):
        """Unknown type defaults to TEXT without raising."""
        schema = {
            "type": "object",
            "properties": {
                "x": {"type": "unknowntype"},
            },
        }
        form = extractor.extract(schema)
        assert form.sections[0].fields[0].field_type == FieldType.TEXT


class TestJsonSchemaExtractorConstraints:
    """Tests for constraint extraction."""

    def test_constraints(self, extractor):
        """minLength, maxLength, pattern map to FieldConstraints."""
        schema = {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "minLength": 3,
                    "maxLength": 10,
                    "pattern": "^[A-Z]+$",
                }
            },
        }
        form = extractor.extract(schema)
        c = form.sections[0].fields[0].constraints
        assert c is not None
        assert c.min_length == 3
        assert c.max_length == 10
        assert c.pattern == "^[A-Z]+$"

    def test_numeric_constraints(self, extractor):
        """minimum, maximum map to FieldConstraints."""
        schema = {
            "type": "object",
            "properties": {
                "age": {"type": "integer", "minimum": 0, "maximum": 150}
            },
        }
        form = extractor.extract(schema)
        c = form.sections[0].fields[0].constraints
        assert c.min_value == 0.0
        assert c.max_value == 150.0

    def test_no_constraints_when_absent(self, extractor):
        """Fields without constraints have constraints=None."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"}
            },
        }
        form = extractor.extract(schema)
        assert form.sections[0].fields[0].constraints is None


class TestJsonSchemaExtractorEnum:
    """Tests for enum handling."""

    def test_enum_to_select(self, extractor):
        """enum values produce SELECT field with options."""
        schema = {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["active", "inactive", "pending"]},
            },
        }
        form = extractor.extract(schema)
        field = form.sections[0].fields[0]
        assert field.field_type == FieldType.SELECT
        assert len(field.options) == 3

    def test_enum_option_values(self, extractor):
        """enum option values are correct strings."""
        schema = {
            "type": "object",
            "properties": {
                "color": {"type": "string", "enum": ["red", "green", "blue"]},
            },
        }
        form = extractor.extract(schema)
        values = {opt.value for opt in form.sections[0].fields[0].options}
        assert values == {"red", "green", "blue"}


class TestJsonSchemaExtractorRefResolution:
    """Tests for $ref and $defs resolution."""

    def test_ref_resolution(self, extractor):
        """$ref to $defs produces GROUP field with children."""
        schema = {
            "type": "object",
            "properties": {
                "address": {"$ref": "#/$defs/Address"},
            },
            "$defs": {
                "Address": {
                    "type": "object",
                    "properties": {
                        "street": {"type": "string"},
                        "city": {"type": "string"},
                    },
                },
            },
        }
        form = extractor.extract(schema)
        addr = form.sections[0].fields[0]
        assert addr.field_type == FieldType.GROUP
        assert len(addr.children) == 2

    def test_definitions_resolution(self, extractor):
        """$ref to definitions (legacy) produces GROUP."""
        schema = {
            "type": "object",
            "properties": {
                "contact": {"$ref": "#/definitions/Contact"},
            },
            "definitions": {
                "Contact": {
                    "type": "object",
                    "properties": {
                        "email": {"type": "string", "format": "email"},
                    },
                },
            },
        }
        form = extractor.extract(schema)
        contact = form.sections[0].fields[0]
        assert contact.field_type == FieldType.GROUP
        assert len(contact.children) == 1


class TestJsonSchemaExtractorFormat:
    """Tests for format keyword mapping."""

    def test_format_mapping(self, extractor):
        """Format keywords map to semantic FieldTypes."""
        schema = {
            "type": "object",
            "properties": {
                "email": {"type": "string", "format": "email"},
                "website": {"type": "string", "format": "uri"},
                "birthday": {"type": "string", "format": "date"},
                "created_at": {"type": "string", "format": "date-time"},
            },
        }
        form = extractor.extract(schema)
        fields = {f.field_id: f for f in form.sections[0].fields}
        assert fields["email"].field_type == FieldType.EMAIL
        assert fields["website"].field_type == FieldType.URL
        assert fields["birthday"].field_type == FieldType.DATE
        assert fields["created_at"].field_type == FieldType.DATETIME

    def test_array_type(self, extractor):
        """array type produces ARRAY field."""
        schema = {
            "type": "object",
            "properties": {
                "tags": {"type": "array", "items": {"type": "string"}},
            },
        }
        form = extractor.extract(schema)
        field = form.sections[0].fields[0]
        assert field.field_type == FieldType.ARRAY
        assert field.item_template is not None
        assert field.item_template.field_type == FieldType.TEXT

    def test_oneof_picks_first_non_null(self, extractor):
        """oneOf with null alternative picks the non-null schema."""
        schema = {
            "type": "object",
            "properties": {
                "value": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "null"},
                    ]
                }
            },
        }
        form = extractor.extract(schema)
        assert form.sections[0].fields[0].field_type == FieldType.TEXT

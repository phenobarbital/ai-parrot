"""Unit tests for FieldType.REST round-trip in JsonSchemaExtractor — FEAT-170."""

from __future__ import annotations

import pytest

from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.extractors.jsonschema import JsonSchemaExtractor


@pytest.fixture
def extractor() -> JsonSchemaExtractor:
    return JsonSchemaExtractor()


# ---------------------------------------------------------------------------
# x-parrot-rest extension detection
# ---------------------------------------------------------------------------


class TestJsonSchemaExtractorREST:
    def test_x_parrot_rest_yields_rest_field_type(self, extractor: JsonSchemaExtractor):
        """Property with x-parrot-rest extension must map to FieldType.REST."""
        schema = {
            "type": "object",
            "title": "Test Form",
            "properties": {
                "planogram_photo": {
                    "type": "object",
                    "title": "Planogram Photo",
                    "x-parrot-rest": {
                        "mode": "callback",
                        "callback_ref": "planogram_compliance",
                        "response_path": "$.compliance_score",
                        "persist_binary": True,
                    },
                }
            },
        }
        form = extractor.extract(schema)
        field = form.sections[0].fields[0]
        assert field.field_type == FieldType.REST

    def test_x_parrot_rest_meta_preserved(self, extractor: JsonSchemaExtractor):
        """meta['rest'] must be populated from x-parrot-rest."""
        schema = {
            "type": "object",
            "properties": {
                "photo": {
                    "type": "object",
                    "x-parrot-rest": {
                        "mode": "remote",
                        "endpoint": "https://api.vendor.test/analyse",
                    },
                }
            },
        }
        form = extractor.extract(schema)
        field = form.sections[0].fields[0]
        assert field.meta is not None
        assert "rest" in field.meta
        assert field.meta["rest"]["mode"] == "remote"
        assert field.meta["rest"]["endpoint"] == "https://api.vendor.test/analyse"

    def test_x_parrot_rest_required_propagated(self, extractor: JsonSchemaExtractor):
        """required=True must be carried through for REST fields."""
        schema = {
            "type": "object",
            "required": ["upload"],
            "properties": {
                "upload": {
                    "type": "object",
                    "x-parrot-rest": {"mode": "callback", "callback_ref": "fn"},
                }
            },
        }
        form = extractor.extract(schema)
        field = form.sections[0].fields[0]
        assert field.required is True

    def test_format_rest_yields_rest_field_type(self, extractor: JsonSchemaExtractor):
        """format: 'rest' in JSON Schema must map to FieldType.REST."""
        schema = {
            "type": "object",
            "properties": {
                "upload_field": {
                    "type": "string",
                    "format": "rest",
                    "title": "Upload Field",
                }
            },
        }
        form = extractor.extract(schema)
        field = form.sections[0].fields[0]
        assert field.field_type == FieldType.REST

    def test_non_rest_fields_unaffected(self, extractor: JsonSchemaExtractor):
        """Properties without x-parrot-rest must not become REST fields."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "email": {"type": "string", "format": "email"},
            },
        }
        form = extractor.extract(schema)
        field_types = {f.field_id: f.field_type for f in form.sections[0].fields}
        assert field_types["name"] == FieldType.TEXT
        assert field_types["email"] == FieldType.EMAIL

"""Unit tests for the JSON Schema renderer's FileEnvelope shapes (FEAT-460)."""

import pytest
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.jsonschema import type_level_value_shape


class TestFileEnvelopeJsonSchema:
    def test_file_union_shape(self):
        schema = type_level_value_shape(FieldType.FILE)
        assert "oneOf" in schema
        types = [s.get("type") for s in schema["oneOf"]]
        assert "string" in types
        assert "object" in types

    def test_image_union_shape(self):
        schema = type_level_value_shape(FieldType.IMAGE)
        assert "oneOf" in schema
        types = [s.get("type") for s in schema["oneOf"]]
        assert "string" in types
        assert "object" in types

    def test_file_envelope_properties(self):
        schema = type_level_value_shape(FieldType.FILE)
        obj_schema = [s for s in schema["oneOf"] if s.get("type") == "object"][0]
        props = obj_schema["properties"]
        assert "filename" in props
        assert "content_type" in props
        assert "size" in props
        assert "blob_ref" in props
        assert "data_url" in props

    def test_dropzone_envelope_shape(self):
        schema = type_level_value_shape(FieldType.IMAGE_DROPZONE)
        assert "oneOf" in schema
        obj_schema = [s for s in schema["oneOf"] if s.get("type") == "object"][0]
        assert "filename" in obj_schema.get("properties", {})

    def test_multi_upload_envelope_shape(self):
        schema = type_level_value_shape(FieldType.MULTI_UPLOAD)
        assert schema.get("type") == "array"
        items = schema.get("items", {})
        assert "filename" in items.get("properties", {})

    def test_rest_unchanged(self):
        """REST field type schema should NOT change."""
        schema = type_level_value_shape(FieldType.REST)
        # REST should remain as-is, no FileEnvelope involvement
        assert "oneOf" not in schema or "filename" not in str(schema)

    def test_returned_shapes_are_independent_copies(self):
        """Mutating one returned shape must not corrupt the shared schema."""
        first = type_level_value_shape(FieldType.FILE)
        first["oneOf"][1]["properties"]["filename"]["type"] = "MUTATED"
        second = type_level_value_shape(FieldType.FILE)
        assert second["oneOf"][1]["properties"]["filename"]["type"] == "string"

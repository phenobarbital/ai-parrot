"""Unit tests for FieldType.REST round-trip in YamlExtractor — FEAT-170."""

from __future__ import annotations

import textwrap

import pytest

from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.extractors.yaml import YamlExtractor


@pytest.fixture
def extractor() -> YamlExtractor:
    return YamlExtractor()


_REST_YAML = textwrap.dedent(
    """
    form_id: test_form
    title: Test Form
    sections:
      - section_id: main
        title: Main
        fields:
          - field_id: planogram_photo
            field_type: rest
            label: "Subir foto para planogram compliance"
            required: true
            constraints:
              allowed_mime_types:
                - image/jpeg
                - image/png
              max_file_size_bytes: 10485760
            meta:
              rest:
                mode: callback
                callback_ref: planogram_compliance
                response_path: "$.compliance_score"
                persist_binary: true
    """
)


class TestYamlExtractorREST:
    def test_rest_field_type_extracted(self, extractor: YamlExtractor):
        """YAML with field_type: rest must produce FieldType.REST."""
        schema = extractor.extract_from_string(_REST_YAML)
        field = schema.sections[0].fields[0]
        assert field.field_type == FieldType.REST

    def test_rest_field_id(self, extractor: YamlExtractor):
        """field_id must be preserved."""
        schema = extractor.extract_from_string(_REST_YAML)
        field = schema.sections[0].fields[0]
        assert field.field_id == "planogram_photo"

    def test_rest_required_preserved(self, extractor: YamlExtractor):
        """required=True must be preserved."""
        schema = extractor.extract_from_string(_REST_YAML)
        field = schema.sections[0].fields[0]
        assert field.required is True

    def test_rest_meta_preserved(self, extractor: YamlExtractor):
        """meta.rest dict must be preserved through extraction."""
        schema = extractor.extract_from_string(_REST_YAML)
        field = schema.sections[0].fields[0]
        assert field.meta is not None
        rest_meta = field.meta["rest"]
        assert rest_meta["mode"] == "callback"
        assert rest_meta["callback_ref"] == "planogram_compliance"
        assert rest_meta["response_path"] == "$.compliance_score"

    def test_rest_constraints_preserved(self, extractor: YamlExtractor):
        """MIME types and file size constraints must be preserved."""
        schema = extractor.extract_from_string(_REST_YAML)
        field = schema.sections[0].fields[0]
        assert field.constraints is not None
        assert "image/jpeg" in (field.constraints.allowed_mime_types or [])
        assert field.constraints.max_file_size_bytes == 10485760

    def test_rest_type_alias_works(self, extractor: YamlExtractor):
        """type: rest (instead of field_type: rest) must also work."""
        yaml_text = textwrap.dedent(
            """
            form_id: x
            title: X
            sections:
              - section_id: s
                title: S
                fields:
                  - name: rest_field
                    type: rest
                    label: REST Field
            """
        )
        schema = extractor.extract_from_string(yaml_text)
        field = schema.sections[0].fields[0]
        assert field.field_type == FieldType.REST

"""Tests for YAML extractor — FieldType.REST mapping (FEAT-170)."""

import pytest

from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.extractors.yaml import YamlExtractor


@pytest.fixture()
def extractor() -> YamlExtractor:
    return YamlExtractor()


def test_yaml_rest_field_type(extractor: YamlExtractor) -> None:
    yaml_text = """
form_id: test_form
title: Test
sections:
  - section_id: s1
    fields:
      - field_id: endpoint_field
        field_type: rest
        label: REST Endpoint
"""
    schema = extractor.extract_from_string(yaml_text)
    field = schema.sections[0].fields[0]
    assert field.field_type == FieldType.REST
    assert field.field_type.value == "rest"


def test_yaml_rest_meta_preserved(extractor: YamlExtractor) -> None:
    yaml_text = """
form_id: test_form
title: Test
sections:
  - section_id: s1
    fields:
      - field_id: cb_field
        field_type: rest
        label: Callback
        meta:
          rest:
            mode: callback
            callback_ref: my_callback
"""
    schema = extractor.extract_from_string(yaml_text)
    field = schema.sections[0].fields[0]
    assert field.field_type == FieldType.REST
    assert field.meta is not None
    assert field.meta["rest"]["mode"] == "callback"
    assert field.meta["rest"]["callback_ref"] == "my_callback"


def test_yaml_rest_roundtrip(extractor: YamlExtractor) -> None:
    yaml_text = """
form_id: rt_form
title: RoundTrip
sections:
  - section_id: s1
    fields:
      - field_id: x
        field_type: rest
        label: X
        meta:
          rest:
            mode: callback
            callback_ref: cb
"""
    schema = extractor.extract_from_string(yaml_text)
    field = schema.sections[0].fields[0]
    assert field.field_id == "x"
    assert field.field_type == FieldType.REST
    assert field.meta["rest"]["mode"] == "callback"
    assert field.meta["rest"]["callback_ref"] == "cb"

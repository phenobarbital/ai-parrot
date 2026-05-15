"""Tests for JSON Schema extractor — FieldType.REST mapping (FEAT-170)."""

import pytest

from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.extractors.jsonschema import JsonSchemaExtractor


@pytest.fixture()
def extractor() -> JsonSchemaExtractor:
    return JsonSchemaExtractor()


def test_jsonschema_x_parrot_rest_detected(extractor: JsonSchemaExtractor) -> None:
    schema = {
        "title": "Test Form",
        "type": "object",
        "properties": {
            "endpoint": {
                "type": "string",
                "title": "REST Endpoint",
                "x-parrot-rest": {"mode": "endpoint", "url": "/api/data"},
            }
        },
    }
    form = extractor.extract(schema)
    field = form.sections[0].fields[0]
    assert field.field_type == FieldType.REST


def test_jsonschema_x_parrot_rest_meta_populated(extractor: JsonSchemaExtractor) -> None:
    schema = {
        "title": "Test",
        "type": "object",
        "properties": {
            "cb_field": {
                "type": "string",
                "x-parrot-rest": {"mode": "callback", "callback_ref": "my_cb"},
            }
        },
    }
    form = extractor.extract(schema)
    field = form.sections[0].fields[0]
    assert field.field_type == FieldType.REST
    assert field.meta is not None
    assert field.meta["rest"]["mode"] == "callback"
    assert field.meta["rest"]["callback_ref"] == "my_cb"


def test_jsonschema_rest_roundtrip(extractor: JsonSchemaExtractor) -> None:
    rest_config = {"mode": "endpoint", "url": "/api/items", "method": "GET"}
    schema = {
        "title": "RT Form",
        "type": "object",
        "properties": {
            "items": {
                "type": "string",
                "title": "Items",
                "x-parrot-rest": rest_config,
            }
        },
    }
    form = extractor.extract(schema)
    field = form.sections[0].fields[0]
    assert field.field_type == FieldType.REST
    assert field.meta["rest"] == rest_config


def test_jsonschema_without_x_parrot_rest_unaffected(extractor: JsonSchemaExtractor) -> None:
    schema = {
        "title": "Normal Form",
        "type": "object",
        "properties": {
            "name": {"type": "string", "title": "Name"},
        },
    }
    form = extractor.extract(schema)
    field = form.sections[0].fields[0]
    assert field.field_type == FieldType.TEXT
    assert field.meta is None

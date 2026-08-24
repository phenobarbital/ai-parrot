"""Unit tests for extractor relation mappings — YAML ``relation:`` block
and JSON Schema ``x-relation`` (FEAT-456, TASK-2413)."""

import pytest
from parrot_formdesigner.extractors.jsonschema import JsonSchemaExtractor
from parrot_formdesigner.extractors.yaml import YamlExtractor

YAML_FORM = """
form_id: order
title: Order
sections:
  - section_id: main
    fields:
      - field_id: customer
        field_type: select
        label: Customer
        relation:
          cardinality: one
          mode: reference
          target: {namespace: odoo, entity: res.partner}
          display_field: name
          on_delete: restrict
"""


def test_yaml_relation_block_parses():
    form = YamlExtractor().extract(YAML_FORM)
    field = form.sections[0].fields[0]
    rel = field.relation
    assert rel.cardinality == "one" and rel.mode == "reference"
    assert rel.target.namespace == "odoo" and rel.target.entity == "res.partner"
    assert rel.display_field == "name" and rel.on_delete == "restrict"


def test_yaml_relation_absent_defaults_none():
    form = YamlExtractor().extract(
        """
form_id: t
title: T
sections:
  - section_id: main
    fields:
      - field_id: name
        field_type: text
        label: Name
"""
    )
    field = form.sections[0].fields[0]
    assert field.relation is None


def test_yaml_relation_full_field_roundtrip():
    yaml_src = """
form_id: order
title: Order
sections:
  - section_id: main
    fields:
      - field_id: tags
        field_type: multi_select
        label: Tags
        relation:
          cardinality: many
          mode: reference
          target: {namespace: db, entity: public.tags, key_field: id}
          display_field: label
          filters: {active: true}
"""
    form = YamlExtractor().extract(yaml_src)
    field = form.sections[0].fields[0]
    rel = field.relation
    assert rel.cardinality == "many"
    assert rel.target.key_field == "id"
    assert rel.display_field == "label"
    assert rel.filters == {"active": True}


def test_yaml_malformed_relation_raises():
    bad = YAML_FORM.replace("cardinality: one", "cardinality: banana")
    with pytest.raises(Exception, match="customer"):
        YamlExtractor().extract(bad)


def test_yaml_relation_missing_target_raises():
    bad = YAML_FORM.replace(
        "target: {namespace: odoo, entity: res.partner}", "target: not-a-mapping"
    )
    with pytest.raises(Exception, match="customer"):
        YamlExtractor().extract(bad)


JSON_SCHEMA_FORM = {
    "title": "Order",
    "type": "object",
    "properties": {
        "customer": {
            "type": "string",
            "title": "Customer",
            "x-field-type": "select",
            "x-relation": {
                "cardinality": "one",
                "mode": "reference",
                "target": {"namespace": "odoo", "entity": "res.partner"},
                "display_field": "name",
                "on_delete": "restrict",
            },
        }
    },
}


def test_jsonschema_x_relation_parses():
    form = JsonSchemaExtractor().extract(JSON_SCHEMA_FORM, form_id="order")
    field = form.sections[0].fields[0]
    rel = field.relation
    assert rel is not None
    assert rel.cardinality == "one" and rel.mode == "reference"
    assert rel.target.namespace == "odoo" and rel.target.entity == "res.partner"
    assert rel.display_field == "name" and rel.on_delete == "restrict"


def test_jsonschema_no_x_relation_defaults_none():
    schema = {
        "title": "Order",
        "type": "object",
        "properties": {
            "name": {"type": "string", "title": "Name"},
        },
    }
    form = JsonSchemaExtractor().extract(schema, form_id="t")
    field = form.sections[0].fields[0]
    assert field.relation is None


def test_jsonschema_malformed_x_relation_raises():
    schema = {
        "title": "Order",
        "type": "object",
        "properties": {
            "customer": {
                "type": "string",
                "title": "Customer",
                "x-field-type": "select",
                "x-relation": {
                    "cardinality": "banana",
                    "target": {"namespace": "odoo", "entity": "res.partner"},
                },
            }
        },
    }
    with pytest.raises(Exception, match="customer"):
        JsonSchemaExtractor().extract(schema, form_id="order")

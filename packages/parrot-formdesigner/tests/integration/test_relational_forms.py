"""End-to-end integration tests for FEAT-456 (Relational Field
Cardinality): YAML -> extract -> resolve -> render -> validate, plus
persisted-schema backward compatibility.

``RELATIONAL_YAML`` is the SAME fixture referenced by the "Relational
Fields" docs page (``docs/formdesigner-relational-fields.md``) — keep the
two in sync.
"""

from __future__ import annotations

import pytest
from parrot_formdesigner.core.resolution import resolve_rule_references
from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.extractors.yaml import YamlExtractor
from parrot_formdesigner.renderers.html5 import HTML5Renderer
from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer
from parrot_formdesigner.services.validators import FormValidator

pytestmark = pytest.mark.asyncio

# All three relation kinds: Many2one (customer, SELECT), Many2many (tags,
# MULTI_SELECT), One2many (lines, ARRAY + item_template, embed).
RELATIONAL_YAML = """
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
      - field_id: tags
        field_type: multi_select
        label: Tags
        relation:
          cardinality: many
          mode: reference
          target: {namespace: db, entity: public.tags}
      - field_id: lines
        field_type: array
        label: Lines
        item_template:
          field_id: line
          field_type: group
          label: Line
          children:
            - field_id: order_id
              field_type: hidden
              label: Order Id
            - field_id: qty
              field_type: integer
              label: Qty
        relation:
          cardinality: many
          mode: embed
          inverse_field: order_id
          target: {namespace: db, entity: public.lines}
"""

# The same form, with every `relation:` block stripped — used to prove
# non-jsonschema renderer output is unaffected by the presence of relations.
NON_RELATIONAL_YAML = """
form_id: order
title: Order
sections:
  - section_id: main
    fields:
      - field_id: customer
        field_type: select
        label: Customer
      - field_id: tags
        field_type: multi_select
        label: Tags
      - field_id: lines
        field_type: array
        label: Lines
        item_template:
          field_id: line
          field_type: group
          label: Line
          children:
            - field_id: order_id
              field_type: hidden
              label: Order Id
            - field_id: qty
              field_type: integer
              label: Qty
"""


def _build_form(yaml_src: str) -> FormSchema:
    return resolve_rule_references(YamlExtractor().extract(yaml_src))


async def test_relational_form_end_to_end():
    form = _build_form(RELATIONAL_YAML)

    # Render both html and jsonschema.
    html = await HTML5Renderer().render(form)
    js = await JsonSchemaRenderer().render(form)

    # x-relation present in jsonschema output for all three fields.
    props = js.content["properties"]
    assert props["customer"]["x-relation"]["cardinality"] == "one"
    assert props["tags"]["x-relation"]["cardinality"] == "many"
    assert props["lines"]["x-relation"]["mode"] == "embed"

    # html renders normally (non-empty content, no crash).
    assert html.content

    # Validate a good and a bad submission.
    good = {
        "customer": "42",
        "tags": ["1", "2"],
        "lines": [{"order_id": "42", "qty": 1}],
    }
    bad = {"customer": ["42"], "tags": "1", "lines": [{"qty": "x"}]}

    good_result = await FormValidator().validate(form, good)
    bad_result = await FormValidator().validate(form, bad)
    assert good_result.is_valid, good_result.errors
    assert not bad_result.is_valid


async def test_only_jsonschema_output_differs_from_non_relational_baseline():
    """Building the same form with vs without `relation:` blocks must
    produce identical HTML5 output — only the JSON Schema renderer
    surfaces relation metadata (spec acceptance criterion)."""
    with_rel = _build_form(RELATIONAL_YAML)
    without_rel = _build_form(NON_RELATIONAL_YAML)

    # Pin every UID so the comparison is genuinely about `relation`, not
    # incidental uuid4 differences between the two independently-extracted
    # forms (renderers embed field_uid/section_uid/form_uid in their output).
    without_rel = without_rel.model_copy(
        update={"form_uid": with_rel.form_uid}, deep=True
    )
    without_rel.sections[0].section_uid = with_rel.sections[0].section_uid
    for wr_field, rel_field in zip(
        without_rel.sections[0].fields, with_rel.sections[0].fields, strict=True
    ):
        wr_field.field_uid = rel_field.field_uid
        if wr_field.item_template is not None:
            wr_field.item_template.field_uid = rel_field.item_template.field_uid
            for wr_child, rel_child in zip(
                wr_field.item_template.children or [],
                rel_field.item_template.children or [],
                strict=True,
            ):
                wr_child.field_uid = rel_child.field_uid

    with_rel_html = await HTML5Renderer().render(with_rel)
    without_rel_html = await HTML5Renderer().render(without_rel)
    assert with_rel_html.content == without_rel_html.content


STORED_PRE_FEAT_456: dict = {
    "form_id": "legacy",
    "title": "Legacy Form",
    "sections": [
        {
            "section_id": "s",
            "fields": [
                {
                    "field_id": "name",
                    "field_type": "text",
                    "label": "Name",
                    "required": True,
                }
            ],
        }
    ],
}


async def test_persisted_schema_backcompat():
    """A stored pre-FEAT-456 FormSchema dict (no `relation` keys anywhere)
    loads, renders, and validates unchanged."""
    form = FormSchema(**STORED_PRE_FEAT_456)
    field = form.sections[0].fields[0]
    assert field.relation is None
    assert field.is_relational is False

    html = await HTML5Renderer().render(form)
    assert html.content

    result = await FormValidator().validate(form, {"name": "Alice"})
    assert result.is_valid

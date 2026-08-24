"""Unit tests for JsonSchemaRenderer x-relation emission + the
byte-identical no-op contract for the other renderers (FEAT-456,
TASK-2414)."""

import pytest
from parrot_formdesigner.core.relations import EntityRef, RelationSpec
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.extractors.jsonschema import JsonSchemaExtractor
from parrot_formdesigner.renderers.adaptive_card import AdaptiveCardRenderer
from parrot_formdesigner.renderers.html5 import HTML5Renderer
from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer

pytestmark = pytest.mark.asyncio

REL = RelationSpec(cardinality="one", target=EntityRef(namespace="odoo", entity="res.partner"))


def _form_with_relation() -> FormSchema:
    f = FormField(field_id="customer", field_type=FieldType.SELECT, label="Customer", relation=REL)
    return FormSchema(form_id="t", title="T", sections=[FormSection(section_id="s", fields=[f])])


def _form_without_relation(with_relation_form: FormSchema) -> FormSchema:
    """Deep-copy ``with_relation_form`` and strip the relation, so every
    UID (form/section/field) stays identical — required for a genuine
    byte-identical comparison (renderers embed field_uid in their output).
    """
    form = with_relation_form.model_copy(deep=True)
    form.sections[0].fields[0].relation = None
    return form


async def test_jsonschema_emits_x_relation():
    form = _form_with_relation()
    out = await JsonSchemaRenderer().render(form)
    prop = out.content["properties"]["customer"]
    assert prop["x-relation"]["cardinality"] == "one"
    assert prop["x-relation"]["target"] == {
        "namespace": "odoo",
        "entity": "res.partner",
    }


async def test_jsonschema_non_relational_field_has_no_x_relation():
    form = _form_without_relation(_form_with_relation())
    out = await JsonSchemaRenderer().render(form)
    prop = out.content["properties"]["customer"]
    assert "x-relation" not in prop


async def test_jsonschema_x_relation_roundtrip():
    with_rel = _form_with_relation()
    rendered = await JsonSchemaRenderer().render(with_rel)
    extracted = JsonSchemaExtractor().extract(rendered.content, form_id="t")
    field = extracted.sections[0].fields[0]
    assert field.relation == with_rel.sections[0].fields[0].relation


async def test_html5_byte_identical_with_relation():
    with_rel_form = _form_with_relation()
    without_rel_form = _form_without_relation(with_rel_form)
    with_rel = await HTML5Renderer().render(with_rel_form)
    without_rel = await HTML5Renderer().render(without_rel_form)
    assert with_rel.content == without_rel.content


async def test_adaptive_card_byte_identical_with_relation():
    with_rel_form = _form_with_relation()
    without_rel_form = _form_without_relation(with_rel_form)
    with_rel = await AdaptiveCardRenderer().render(with_rel_form)
    without_rel = await AdaptiveCardRenderer().render(without_rel_form)
    assert with_rel.content == without_rel.content

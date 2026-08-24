"""Unit tests for the embed-mode inverse_field existence check at the
resolution boundary (FEAT-456, TASK-2412)."""

import pytest
from parrot_formdesigner.core.relations import EntityRef, RelationSpec
from parrot_formdesigner.core.resolution import resolve_rule_references
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType


def _embed_form(inverse: str) -> FormSchema:
    item = FormField(
        field_id="line",
        field_type=FieldType.GROUP,
        label="Line",
        children=[
            FormField(field_id="order_id", field_type=FieldType.HIDDEN, label="oid"),
            FormField(field_id="qty", field_type=FieldType.INTEGER, label="Qty"),
        ],
    )
    lines = FormField(
        field_id="lines",
        field_type=FieldType.ARRAY,
        label="Lines",
        item_template=item,
        relation=RelationSpec(
            cardinality="many",
            mode="embed",
            inverse_field=inverse,
            target=EntityRef(namespace="db", entity="public.lines"),
        ),
    )
    return FormSchema(form_id="t", title="T", sections=[FormSection(section_id="s", fields=[lines])])


def test_inverse_field_exists_passes():
    resolve_rule_references(_embed_form("order_id"))


def test_inverse_field_nested_in_group_passes():
    resolve_rule_references(_embed_form("qty"))


def test_inverse_field_missing_raises():
    with pytest.raises(ValueError, match="lines"):
        resolve_rule_references(_embed_form("nope"))


def test_reference_mode_relation_unaffected():
    field = FormField(
        field_id="customer",
        field_type=FieldType.SELECT,
        label="Customer",
        relation=RelationSpec(
            cardinality="one",
            mode="reference",
            target=EntityRef(namespace="odoo", entity="res.partner"),
        ),
    )
    form = FormSchema(
        form_id="t2",
        title="T2",
        sections=[FormSection(section_id="s", fields=[field])],
    )
    resolve_rule_references(form)  # must not raise


def test_form_without_relations_unaffected():
    field = FormField(field_id="name", field_type=FieldType.TEXT, label="Name")
    form = FormSchema(
        form_id="t3",
        title="T3",
        sections=[FormSection(section_id="s", fields=[field])],
    )
    resolve_rule_references(form)  # must not raise

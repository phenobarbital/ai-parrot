"""Unit tests for FormField.relation aspect + combination validator
(FEAT-456, TASK-2411)."""

import pytest
from parrot_formdesigner.core.relations import EntityRef, RelationSpec
from parrot_formdesigner.core.schema import FormField
from parrot_formdesigner.core.types import FieldType
from pydantic import ValidationError

ODOO_PARTNER = EntityRef(namespace="odoo", entity="res.partner")
DB_TAGS = EntityRef(namespace="db", entity="public.tags")
DB_LINES = EntityRef(namespace="db", entity="public.lines")


def _rel(card, mode="reference", target=ODOO_PARTNER, **kw):
    return RelationSpec(cardinality=card, mode=mode, target=target, **kw)


def test_select_reference_one_ok():
    f = FormField(
        field_id="customer",
        field_type=FieldType.SELECT,
        label="Customer",
        relation=_rel("one"),
    )
    assert f.is_relational


def test_dynamic_select_reference_one_ok():
    f = FormField(
        field_id="customer",
        field_type=FieldType.DYNAMIC_SELECT,
        label="Customer",
        relation=_rel("one"),
    )
    assert f.is_relational


def test_tree_select_reference_one_ok():
    f = FormField(
        field_id="customer",
        field_type=FieldType.TREE_SELECT,
        label="Customer",
        relation=_rel("one"),
    )
    assert f.is_relational


def test_multiselect_reference_many_ok():
    f = FormField(
        field_id="tags",
        field_type=FieldType.MULTI_SELECT,
        label="Tags",
        relation=_rel("many", target=DB_TAGS),
    )
    assert f.is_relational


def test_tags_reference_many_ok():
    f = FormField(
        field_id="tags",
        field_type=FieldType.TAGS,
        label="Tags",
        relation=_rel("many", target=DB_TAGS),
    )
    assert f.is_relational


def test_transfer_list_reference_many_ok():
    f = FormField(
        field_id="tags",
        field_type=FieldType.TRANSFER_LIST,
        label="Tags",
        relation=_rel("many", target=DB_TAGS),
    )
    assert f.is_relational


def test_multiselect_reference_one_rejected():
    with pytest.raises(ValidationError, match="customer"):
        FormField(
            field_id="customer",
            field_type=FieldType.MULTI_SELECT,
            label="Customer",
            relation=_rel("one"),
        )


def test_select_reference_many_rejected():
    with pytest.raises(ValidationError, match="tags"):
        FormField(
            field_id="tags",
            field_type=FieldType.SELECT,
            label="Tags",
            relation=_rel("many", target=DB_TAGS),
        )


def test_embed_requires_array_with_template():
    with pytest.raises(ValidationError):
        FormField(
            field_id="lines",
            field_type=FieldType.ARRAY,
            label="Lines",
            relation=_rel("many", mode="embed", target=DB_LINES, inverse_field="order_id"),
        )
    # and with item_template it passes:
    item = FormField(
        field_id="line",
        field_type=FieldType.GROUP,
        label="Line",
        children=[FormField(field_id="order_id", field_type=FieldType.HIDDEN, label="oid")],
    )
    f = FormField(
        field_id="lines",
        field_type=FieldType.ARRAY,
        label="Lines",
        item_template=item,
        relation=_rel("many", mode="embed", target=DB_LINES, inverse_field="order_id"),
    )
    assert f.relation.mode == "embed"


def test_embed_wrong_field_type_rejected():
    with pytest.raises(ValidationError, match="lines"):
        FormField(
            field_id="lines",
            field_type=FieldType.SELECT,
            label="Lines",
            relation=_rel("many", mode="embed", target=DB_LINES, inverse_field="order_id"),
        )


def test_boolean_with_relation_rejected():
    with pytest.raises(ValidationError, match="flag"):
        FormField(
            field_id="flag",
            field_type=FieldType.BOOLEAN,
            label="Flag",
            relation=_rel("one"),
        )


def test_backcompat_no_relation_roundtrip():
    f = FormField(field_id="name", field_type=FieldType.TEXT, label="Name")
    assert not f.is_relational
    assert FormField(**f.model_dump()) == f


def test_relation_none_default():
    f = FormField(field_id="name", field_type=FieldType.TEXT, label="Name")
    assert f.relation is None
    assert f.is_relational is False

"""Unit tests for FormValidator shape validation of relational submissions
(FEAT-456, TASK-2415)."""

import pytest
from parrot_formdesigner.core.relations import EntityRef, RelationSpec
from parrot_formdesigner.core.schema import FormField
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.validators import FormValidator

pytestmark = pytest.mark.asyncio

ONE = RelationSpec(cardinality="one", target=EntityRef(namespace="odoo", entity="res.partner"))
MANY = RelationSpec(cardinality="many", target=EntityRef(namespace="db", entity="public.tags"))
EMBED = RelationSpec(
    cardinality="many",
    mode="embed",
    inverse_field="order_id",
    target=EntityRef(namespace="db", entity="public.lines"),
)


@pytest.fixture
def customer():
    return FormField(field_id="customer", field_type=FieldType.SELECT, label="Customer", relation=ONE)


@pytest.fixture
def tags():
    return FormField(field_id="tags", field_type=FieldType.MULTI_SELECT, label="Tags", relation=MANY)


async def test_one_accepts_scalar_str(customer):
    assert await FormValidator().validate_field(customer, "42") == []


async def test_one_accepts_scalar_int(customer):
    assert await FormValidator().validate_field(customer, 42) == []


async def test_one_rejects_list(customer):
    assert await FormValidator().validate_field(customer, ["42"]) != []


async def test_one_rejects_dict(customer):
    assert await FormValidator().validate_field(customer, {"id": "42"}) != []


async def test_many_accepts_id_list(tags):
    assert await FormValidator().validate_field(tags, ["1", "2"]) == []


async def test_many_accepts_mixed_scalar_id_list(tags):
    assert await FormValidator().validate_field(tags, [1, "2"]) == []


async def test_many_rejects_scalar(tags):
    assert await FormValidator().validate_field(tags, "1") != []


async def test_many_rejects_list_with_dict_inside(tags):
    assert await FormValidator().validate_field(tags, [{"id": "1"}, "2"]) != []


async def test_many_rejects_list_with_list_inside(tags):
    assert await FormValidator().validate_field(tags, [["1"], "2"]) != []


async def test_embed_mode_uses_existing_array_recursion():
    """Embed-mode relations get NO new validation logic — values flow
    through the existing ARRAY recursive path unchanged."""
    item_template = FormField(
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
        item_template=item_template,
        relation=EMBED,
    )
    # A plain list of rows validates via the pre-existing ARRAY path — no
    # relation-specific rejection is applied to embed mode.
    errors = await FormValidator().validate_field(lines, [{"order_id": "o1", "qty": 3}])
    assert errors == []


async def test_non_relational_field_unaffected():
    field = FormField(field_id="name", field_type=FieldType.TEXT, label="Name")
    assert await FormValidator().validate_field(field, "hello") == []

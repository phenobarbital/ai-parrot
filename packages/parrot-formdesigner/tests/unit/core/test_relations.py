"""Unit tests for the relation core models (FEAT-456, TASK-2410)."""

import pytest
from parrot_formdesigner.core.relations import EntityRef, RelationSpec
from pydantic import ValidationError


def test_reference_one_minimal():
    spec = RelationSpec(
        cardinality="one",
        target=EntityRef(namespace="odoo", entity="res.partner"),
    )
    assert spec.mode == "reference"
    assert spec.on_delete is None


def test_reference_many():
    spec = RelationSpec(
        cardinality="many",
        target=EntityRef(namespace="db", entity="public.tags"),
        mode="reference",
    )
    assert spec.cardinality == "many"
    assert spec.mode == "reference"


def test_embed_valid():
    spec = RelationSpec(
        cardinality="many",
        mode="embed",
        inverse_field="order_id",
        target=EntityRef(namespace="db", entity="public.lines"),
    )
    assert spec.mode == "embed"
    assert spec.inverse_field == "order_id"


def test_embed_requires_inverse_field():
    with pytest.raises(ValidationError):
        RelationSpec(
            cardinality="many",
            mode="embed",
            target=EntityRef(namespace="db", entity="public.lines"),
        )


def test_embed_requires_cardinality_many():
    with pytest.raises(ValidationError):
        RelationSpec(
            cardinality="one",
            mode="embed",
            inverse_field="order_id",
            target=EntityRef(namespace="db", entity="public.lines"),
        )


def test_extra_forbidden_entity_ref():
    with pytest.raises(ValidationError):
        EntityRef(namespace="odoo", entity="res.partner", bogus=1)


def test_extra_forbidden_relation_spec():
    with pytest.raises(ValidationError):
        RelationSpec(
            cardinality="one",
            target=EntityRef(namespace="odoo", entity="res.partner"),
            bogus=1,
        )


def test_entity_ref_key_field_optional():
    ref = EntityRef(namespace="odoo", entity="res.partner", key_field="id")
    assert ref.key_field == "id"


def test_unknown_namespace_allowed():
    # Free-form by design — no central registry, no validation.
    ref = EntityRef(namespace="mystery-system", entity="whatever")
    assert ref.namespace == "mystery-system"


def test_on_delete_passthrough_hint():
    spec = RelationSpec(
        cardinality="one",
        target=EntityRef(namespace="odoo", entity="res.partner"),
        on_delete="restrict",
    )
    assert spec.on_delete == "restrict"


def test_filters_passthrough():
    spec = RelationSpec(
        cardinality="many",
        target=EntityRef(namespace="db", entity="public.tags"),
        filters={"active": True},
    )
    assert spec.filters == {"active": True}

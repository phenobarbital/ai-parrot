"""Unit tests for UnknownFieldsPolicy + FormSchema.unknown_fields (FEAT-458 Module 1).

Tests cover:
- The enum's exact three members and wire serialization
- The default policy (DROP) — the no-breaking-change guarantee (AC1/AC2)
- String coercion, invalid values, round-tripping
- Legacy form JSON (no unknown_fields key) still loads and defaults to DROP
"""
import pytest
from parrot_formdesigner.core.schema import FormSchema, UnknownFieldsPolicy


@pytest.fixture
def minimal_form_kwargs():
    """Minimal kwargs to construct a valid FormSchema."""
    return {"form_id": "test-form", "title": "Test Form", "sections": []}


def test_policy_enum_values():
    """Members serialize as the three wire strings."""
    assert UnknownFieldsPolicy.DROP.value == "drop"
    assert UnknownFieldsPolicy.KEEP.value == "keep"
    assert UnknownFieldsPolicy.REJECT.value == "reject"
    assert len(UnknownFieldsPolicy) == 3


def test_formschema_defaults_to_drop(minimal_form_kwargs):
    """A form authored without the field gets DROP — the no-breaking-change guarantee."""
    form = FormSchema(**minimal_form_kwargs)
    assert form.unknown_fields is UnknownFieldsPolicy.DROP


def test_formschema_accepts_string_policy(minimal_form_kwargs):
    """The wire form ("keep") coerces to the enum."""
    form = FormSchema(**minimal_form_kwargs, unknown_fields="keep")
    assert form.unknown_fields is UnknownFieldsPolicy.KEEP


def test_formschema_rejects_unknown_policy(minimal_form_kwargs):
    """An invalid policy string fails at authoring time."""
    with pytest.raises(ValueError):
        FormSchema(**minimal_form_kwargs, unknown_fields="capture-everything")


def test_formschema_roundtrip_preserves_policy(minimal_form_kwargs):
    """model_dump -> FormSchema keeps the policy."""
    form = FormSchema(**minimal_form_kwargs, unknown_fields="reject")
    assert FormSchema(**form.model_dump()).unknown_fields is UnknownFieldsPolicy.REJECT


def test_legacy_form_json_loads(minimal_form_kwargs):
    """Stored form JSON with no unknown_fields key still validates (spec AC2)."""
    dumped = FormSchema(**minimal_form_kwargs).model_dump(mode="json")
    dumped.pop("unknown_fields", None)
    assert FormSchema(**dumped).unknown_fields is UnknownFieldsPolicy.DROP

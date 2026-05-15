"""Tests for core/types.py — FieldType enum."""

from parrot_formdesigner.core.types import FieldType


def test_field_type_rest_present() -> None:
    assert FieldType.REST.value == "rest"
    assert FieldType("rest") is FieldType.REST


def test_field_type_rest_is_str() -> None:
    assert isinstance(FieldType.REST, str)
    assert FieldType.REST == "rest"


def test_all_field_types_roundtrip() -> None:
    for member in FieldType:
        assert FieldType(member.value) is member

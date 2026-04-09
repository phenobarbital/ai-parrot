"""Unit tests for form field helper utilities."""

from parrot.formdesigner.core.types import FieldType
from parrot.formdesigner.tools.field_helpers import (
    get_form_field_schema_snippets,
    list_supported_form_field_types,
)


def test_supported_field_types_match_enum() -> None:
    values = list_supported_form_field_types()
    assert values == [member.value for member in FieldType]


def test_field_schema_snippets_cover_all_types() -> None:
    snippets = get_form_field_schema_snippets()
    expected_types = {member.value for member in FieldType}
    assert set(snippets.keys()) == expected_types


def test_field_schema_snippets_are_defensive_copy() -> None:
    snippets = get_form_field_schema_snippets()
    snippets["text"]["label"] = "Changed"

    fresh = get_form_field_schema_snippets()
    assert fresh["text"]["label"] == "Full name"

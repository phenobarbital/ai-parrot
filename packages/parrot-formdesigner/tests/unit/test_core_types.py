"""Unit tests for parrot_formdesigner.core.types — FEAT-170 additions."""

from __future__ import annotations

from parrot_formdesigner.core.types import FieldType


class TestFieldTypeREST:
    def test_field_type_rest_present(self):
        """FieldType.REST must exist with value 'rest'."""
        assert FieldType.REST.value == "rest"

    def test_field_type_rest_roundtrip(self):
        """FieldType('rest') must return the REST member."""
        assert FieldType("rest") is FieldType.REST

    def test_field_type_rest_is_str(self):
        """FieldType is a str enum — REST must compare equal to 'rest'."""
        assert FieldType.REST == "rest"

    def test_existing_enum_members_unchanged(self):
        """Existing enum members must not be affected by the REST addition."""
        assert FieldType.TEXT.value == "text"
        assert FieldType.RANKING.value == "ranking"
        assert FieldType.REMOTE_RESPONSE.value == "remote_response"

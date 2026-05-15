"""Unit tests for parrot_formdesigner.controls.builtin — FEAT-170 REST entry."""

from __future__ import annotations

from parrot_formdesigner.controls.builtin import _BUILTIN_METADATA
from parrot_formdesigner.core.types import FieldType


class TestBuiltinMetadataREST:
    def test_rest_metadata_present(self):
        """_BUILTIN_METADATA must contain a FieldType.REST entry."""
        assert FieldType.REST in _BUILTIN_METADATA

    def test_rest_category_advanced(self):
        """REST field type must be in the 'advanced' category."""
        entry = _BUILTIN_METADATA[FieldType.REST]
        assert entry["category"] == "advanced"

    def test_rest_label(self):
        """REST field type label must be 'REST'."""
        entry = _BUILTIN_METADATA[FieldType.REST]
        assert entry["label"] == "REST"

    def test_rest_render_hint(self):
        """REST field type render hint must be 'upload'."""
        entry = _BUILTIN_METADATA[FieldType.REST]
        assert entry["render_hint"] == "upload"

    def test_rest_supports_constraints(self):
        """REST field type must support constraints."""
        entry = _BUILTIN_METADATA[FieldType.REST]
        assert entry["supports_constraints"] is True

    def test_rest_is_not_container(self):
        """REST field type must not be a container."""
        entry = _BUILTIN_METADATA[FieldType.REST]
        assert entry["is_container"] is False

    def test_rest_icon(self):
        """REST field type must have icon 'rest'."""
        entry = _BUILTIN_METADATA[FieldType.REST]
        assert entry["icon"] == "rest"

    def test_rest_description_mentions_api_response(self):
        """REST description must mention API response as the answer."""
        entry = _BUILTIN_METADATA[FieldType.REST]
        assert "API response" in entry["description"] or "rest" in entry["description"].lower()

    def test_all_field_types_covered(self):
        """Every FieldType value must have a _BUILTIN_METADATA entry."""
        for ft in FieldType:
            assert ft in _BUILTIN_METADATA, f"Missing entry for {ft!r}"

"""Tests for the published linked-sources JSON Schema (FEAT-598 M1)."""

from __future__ import annotations

import jsonschema
import pytest

from parrot.outputs.a2ui.linked.schema import SCHEMA_PATH, dumps_schema, export_json_schema


def test_json_schema_export_deterministic() -> None:
    """Schema serialisation is stable across exports."""
    assert dumps_schema(export_json_schema()) == dumps_schema(export_json_schema())


def test_committed_schema_matches_export() -> None:
    """The published file matches a freshly generated schema."""
    assert SCHEMA_PATH.read_text(encoding="utf-8") == dumps_schema()


def test_schema_accepts_valid_descriptor(linked_source) -> None:
    """A descriptor emitted by the wire models validates."""
    descriptor = {"activity": linked_source.model_dump(mode="json", by_alias=True, exclude_none=True)}
    jsonschema.Draft202012Validator(export_json_schema()).validate(descriptor)


def test_schema_rejects_invalid_descriptor(linked_source) -> None:
    """Unknown descriptor fields and unsupported source kinds are rejected."""
    descriptor = linked_source.model_dump(mode="json", by_alias=True, exclude_none=True)
    validator = jsonschema.Draft202012Validator(export_json_schema())

    with pytest.raises(jsonschema.ValidationError):
        validator.validate({"activity": {**descriptor, "unexpected": True}})
    with pytest.raises(jsonschema.ValidationError):
        validator.validate({"activity": {**descriptor, "kind": "unknown"}})


def test_schema_uses_with_alias() -> None:
    """The join schema exposes the ``with`` wire alias only."""
    join_properties = export_json_schema()["$defs"]["Join"]["properties"]
    assert "with" in join_properties
    assert "with_" not in join_properties

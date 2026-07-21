"""Unit tests for the A2UI serialization layer (TASK-1720 / Module 1)."""

import pytest
from pydantic import ValidationError

from parrot.outputs.a2ui.models import Component, CreateSurface, UpdateDataModel
from parrot.outputs.a2ui.serialization import (
    A2UI_VERSION,
    VERSION_FIELD,
    deserialize,
    iter_jsonl,
    serialize,
    to_jsonl,
)


def _surface() -> CreateSurface:
    return CreateSurface(
        surfaceId="main",
        catalogId="https://parrot.dev/catalogs/v1",
        components=[Component(id="blk-000", component="Column")],
    )


class TestSerialization:
    def test_version_set_by_serialization_layer_only(self):
        """`version` appears in serialized output but is not a settable model field."""
        msg = _surface()
        # No model in models.py declares `version`.
        assert VERSION_FIELD not in CreateSurface.model_fields
        with pytest.raises(ValidationError):
            CreateSurface(
                surfaceId="main",
                catalogId="c",
                version="9.9",  # extra=forbid → rejected
            )
        payload = serialize(msg)
        assert payload[VERSION_FIELD] == A2UI_VERSION

    def test_serialize_uses_wire_aliases(self):
        payload = serialize(_surface())
        assert payload["messageType"] == "createSurface"
        assert payload["surfaceId"] == "main"
        assert payload["catalogId"] == "https://parrot.dev/catalogs/v1"

    def test_jsonl_emit_one_message_per_line(self):
        """JSONL emit produces one complete parseable message per line."""
        jsonl = to_jsonl([_surface(), UpdateDataModel(surfaceId="main", contents={"/x": 1})])
        lines = jsonl.splitlines()
        assert len(lines) == 2
        parsed = list(iter_jsonl(jsonl))
        assert len(parsed) == 2
        assert isinstance(parsed[0], CreateSurface)
        assert isinstance(parsed[1], UpdateDataModel)

    def test_unknown_message_type_rejected(self):
        """Deserializing an unknown message type raises a structured validation error."""
        with pytest.raises(ValidationError):
            deserialize({"messageType": "teleport", "surfaceId": "main"})

    def test_version_stripped_on_parse(self):
        payload = serialize(_surface())
        restored = deserialize(payload)
        assert VERSION_FIELD not in type(restored).model_fields
        assert restored == _surface()

    def test_non_string_version_rejected(self):
        payload = serialize(_surface())
        payload[VERSION_FIELD] = 1.0
        with pytest.raises(ValueError):
            deserialize(payload)

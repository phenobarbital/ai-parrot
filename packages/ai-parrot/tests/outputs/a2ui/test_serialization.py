"""Unit tests for the A2UI v1.0 serialization layer (FEAT-470 TASK-2533)."""

import warnings

import pytest
from parrot.outputs.a2ui.models import (
    A2UIAgentMessage,
    CreateSurface,
    UpdateDataModel,
)
from parrot.outputs.a2ui.serialization import (
    A2UI_VERSION,
    VERSION_FIELD,
    deserialize,
    iter_jsonl,
    serialize,
    to_jsonl,
)
from pydantic import ValidationError

from ._v1 import legacy_create_surface_envelope, make_create_surface


class TestSerializeEnvelopeByKey:
    def test_serialize_envelope_by_key(self):
        """serialize() produces {"version": "v1.0", "<key>": {...}} — no messageType."""
        payload = serialize(make_create_surface())
        assert payload[VERSION_FIELD] == A2UI_VERSION == "v1.0"
        assert set(payload.keys()) == {"version", "createSurface"}
        assert "messageType" not in payload["createSurface"]
        assert payload["createSurface"]["surfaceId"] == "main"

    def test_serialize_never_emits_message_type(self):
        """No serialized message, at any nesting level, carries `messageType`."""
        payload = serialize(
            UpdateDataModel(surfaceId="main", path="/x", value=1)
        )
        assert "messageType" not in payload
        assert "messageType" not in payload["updateDataModel"]

    def test_serialize_preserves_explicit_null_value(self):
        """UpdateDataModel(value=None) must serialize `"value": null`, not drop it."""
        payload = serialize(UpdateDataModel(surfaceId="main", value=None))
        assert payload["updateDataModel"]["value"] is None
        assert "value" in payload["updateDataModel"]

    def test_serialize_accepts_prebuilt_envelope(self):
        envelope = A2UIAgentMessage(version="v1.0", createSurface={"surfaceId": "s"})
        payload = serialize(envelope)
        assert payload["version"] == "v1.0"
        assert set(payload.keys()) == {"version", "createSurface"}
        assert payload["createSurface"]["surfaceId"] == "s"

    def test_version_not_a_model_field(self):
        """No model in models.py declares `version` as a settable field."""
        assert VERSION_FIELD not in CreateSurface.model_fields


class TestDeserializeRoundtrip:
    def test_version_roundtrip(self):
        payload = serialize(make_create_surface())
        restored = deserialize(payload)
        assert isinstance(restored, A2UIAgentMessage)
        assert restored.create_surface == make_create_surface()

    def test_unknown_envelope_keys_rejected(self):
        with pytest.raises(ValueError):
            deserialize({"version": "v1.0", "teleport": {}})

    def test_wrong_version_literal_rejected(self):
        with pytest.raises(ValidationError):
            deserialize({"version": "1.0", "createSurface": {"surfaceId": "s"}})


class TestLegacyNormalizeCreateSurface:
    def test_legacy_normalize_create_surface(self):
        """A legacy createSurface envelope deserializes to the v1.0 equivalent."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            restored = deserialize(legacy_create_surface_envelope())
            assert any(
                issubclass(w.category, DeprecationWarning) for w in caught
            )
        assert isinstance(restored, A2UIAgentMessage)
        assert restored.create_surface.surface_id == "main"
        assert len(restored.create_surface.components) == 2


class TestLegacyNormalizeCardToInfoCard:
    def test_legacy_normalize_card_to_infocard(self):
        legacy = legacy_create_surface_envelope()
        restored = deserialize(legacy)
        card = next(
            c for c in restored.create_surface.components if c.id == "blk-001"
        )
        assert card.component == "InfoCard"


class TestLegacyUpdateDataModelContentsSplit:
    def test_legacy_update_data_model_contents_split(self):
        """contents={a,b} normalizes to 2 v1.0 envelopes, order preserved."""
        legacy = {
            "messageType": "updateDataModel",
            "surfaceId": "main",
            "contents": {"/a": 1, "/b": 2},
        }
        restored = deserialize(legacy)
        assert isinstance(restored, list)
        assert len(restored) == 2
        assert restored[0].update_data_model.path == "/a"
        assert restored[0].update_data_model.value == 1
        assert restored[1].update_data_model.path == "/b"
        assert restored[1].update_data_model.value == 2


class TestLegacyBindOptionalToExtensions:
    def test_legacy_bind_optional_to_extensions(self):
        """{"$bind", "optional": true} normalizes to {"path"} + parrot_optional."""
        legacy = legacy_create_surface_envelope()
        restored = deserialize(legacy)
        card = next(
            c for c in restored.create_surface.components if c.id == "blk-001"
        )
        assert card.model_extra["title"] == {"path": "/title"}
        assert card.metadata.extensions.root["parrot_optional"] == ["/subtitle"]


class TestJsonlRoundtrip:
    def test_jsonl_roundtrip(self):
        surface = make_create_surface()
        udm = UpdateDataModel(surfaceId="main", path="/x", value=1)
        jsonl = to_jsonl([surface, udm])
        lines = jsonl.splitlines()
        assert len(lines) == 2
        parsed = list(iter_jsonl(jsonl))
        assert len(parsed) == 2
        assert parsed[0].create_surface == surface
        assert parsed[1].update_data_model == udm

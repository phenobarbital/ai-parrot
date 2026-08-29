"""Unit tests for parrot.outputs.a2ui.compat (FEAT-470 TASK-2533)."""

import pytest
from parrot.outputs.a2ui import compat

from ._v1 import legacy_create_surface_envelope


class TestIsLegacyEnvelope:
    def test_legacy_envelope_detected(self):
        assert compat.is_legacy_envelope(legacy_create_surface_envelope())

    def test_v1_envelope_not_legacy(self):
        assert not compat.is_legacy_envelope({"version": "v1.0", "createSurface": {"surfaceId": "s"}})


class TestNormalizeLegacyComponent:
    def test_v1_component_passthrough(self):
        """A component without `properties` (already v1.0) is untouched."""
        comp = {"id": "x", "component": "Card", "child": "y"}
        assert compat.normalize_legacy_component(comp) == comp

    def test_legacy_card_renamed_to_infocard(self):
        comp = {
            "id": "x",
            "component": "Card",
            "properties": {"title": "hi"},
            "children": [],
        }
        normalized = compat.normalize_legacy_component(comp)
        assert normalized["component"] == "InfoCard"
        assert normalized["title"] == "hi"
        assert "properties" not in normalized

    def test_bind_becomes_path(self):
        comp = {
            "id": "x",
            "component": "Text",
            "properties": {"text": {"$bind": "/a/b"}},
        }
        normalized = compat.normalize_legacy_component(comp)
        assert normalized["text"] == {"path": "/a/b"}

    def test_optional_bind_hoisted_to_extensions(self):
        comp = {
            "id": "x",
            "component": "Text",
            "properties": {"text": {"$bind": "/a/b", "optional": True}},
        }
        normalized = compat.normalize_legacy_component(comp)
        assert normalized["text"] == {"path": "/a/b"}
        assert normalized["metadata"]["extensions"]["parrot_optional"] == ["/a/b"]

    def test_children_carried_over(self):
        comp = {
            "id": "x",
            "component": "Column",
            "properties": {},
            "children": ["a", "b"],
        }
        normalized = compat.normalize_legacy_component(comp)
        assert normalized["children"] == ["a", "b"]

    def test_role_hoisted_to_parrot_role_extension(self):
        """A legacy `role` prop must NOT leak as a bare v1.0 top-level prop.

        It must be hoisted into `metadata.extensions.parrot_role` — the same
        extension key the catalog (InfoCard) and renderers already read.
        """
        comp = {
            "id": "t1",
            "component": "Text",
            "properties": {"role": "title", "text": "Hello"},
        }
        normalized = compat.normalize_legacy_component(comp)
        assert "role" not in normalized
        assert normalized["text"] == "Hello"
        assert normalized["metadata"]["extensions"]["parrot_role"] == "title"

    def test_role_and_optional_bind_coexist_in_extensions(self):
        """Both `parrot_role` and `parrot_optional` can be hoisted together."""
        comp = {
            "id": "t1",
            "component": "Text",
            "properties": {
                "role": "title",
                "text": {"$bind": "/a/b", "optional": True},
            },
        }
        normalized = compat.normalize_legacy_component(comp)
        assert "role" not in normalized
        extensions = normalized["metadata"]["extensions"]
        assert extensions["parrot_role"] == "title"
        assert extensions["parrot_optional"] == ["/a/b"]


class TestNormalizeLegacyCreateSurface:
    def test_create_surface_normalizes(self):
        result = compat.normalize_legacy(legacy_create_surface_envelope())
        assert result["version"] == "v1.0"
        assert "createSurface" in result
        assert result["createSurface"]["surfaceId"] == "main"
        assert len(result["createSurface"]["components"]) == 2


class TestNormalizeLegacyUpdateComponents:
    def test_update_components_normalizes(self):
        legacy = {
            "messageType": "updateComponents",
            "surfaceId": "main",
            "components": [{"id": "x", "component": "Card", "properties": {"title": "hi"}}],
        }
        result = compat.normalize_legacy(legacy)
        assert result["version"] == "v1.0"
        assert result["updateComponents"]["components"][0]["component"] == "InfoCard"


class TestNormalizeLegacyUpdateDataModel:
    def test_single_content_key_returns_single_dict(self):
        legacy = {
            "messageType": "updateDataModel",
            "surfaceId": "main",
            "contents": {"/a": 1},
        }
        result = compat.normalize_legacy(legacy)
        assert isinstance(result, dict)
        assert result["updateDataModel"] == {
            "surfaceId": "main",
            "path": "/a",
            "value": 1,
        }

    def test_multiple_content_keys_return_list_in_order(self):
        legacy = {
            "messageType": "updateDataModel",
            "surfaceId": "main",
            "contents": {"/a": 1, "/b": 2, "/c": 3},
        }
        result = compat.normalize_legacy(legacy)
        assert isinstance(result, list)
        assert [item["updateDataModel"]["path"] for item in result] == [
            "/a",
            "/b",
            "/c",
        ]
        assert all(item["version"] == "v1.0" for item in result)


class TestNormalizeLegacyCallFunction:
    def test_call_function_becomes_call_renderer_function(self):
        legacy = {
            "messageType": "callFunction",
            "functionName": "refresh",
            "arguments": {"id": 1},
        }
        result = compat.normalize_legacy(legacy)
        assert result["version"] == "v1.0"
        inner = result["callRendererFunction"]
        assert inner["callFunction"] == {"call": "refresh", "args": {"id": 1}}
        assert isinstance(inner["functionCallId"], str) and inner["functionCallId"]


class TestNormalizeLegacyUnsupportedType:
    def test_unsupported_message_type_raises(self):
        with pytest.raises(ValueError):
            compat.normalize_legacy({"messageType": "action", "surfaceId": "s"})

    def test_missing_message_type_raises(self):
        with pytest.raises(ValueError):
            compat.normalize_legacy({"surfaceId": "s"})

"""Unit tests for A2UI v1.0 wire models (FEAT-470 TASK-2532).

Model-only tests — intentionally do NOT import
:mod:`parrot.outputs.a2ui.serialization` (its rewrite is TASK-2533, landed
in the same session; see that task's tests for round-trip coverage).
"""

import pytest
from parrot.outputs.a2ui.models import (
    A2UIAgentMessage,
    Action,
    ChildTemplate,
    Component,
    ComponentMetadata,
    DataBinding,
    UpdateDataModel,
)
from pydantic import ValidationError

from ._v1 import make_component


class TestComponentPropsTopLevel:
    def test_component_props_top_level(self):
        """Component() dumps catalog props top-level; no 'properties' key."""
        comp = make_component("Text", text="hi", variant="caption")
        dumped = comp.model_dump(by_alias=True)
        assert "properties" not in dumped
        assert dumped["text"] == "hi"
        assert dumped["variant"] == "caption"

    def test_component_catalog_id_alias(self):
        comp = Component(id="x", component="Text", catalogId="basic", text="hi")
        assert comp.catalog_id == "basic"
        assert comp.model_dump(by_alias=True)["catalogId"] == "basic"


class TestChildrenListOrTemplate:
    def test_children_list_or_template(self):
        """Both a plain id list and a ChildTemplate are accepted for `children`."""
        as_list = Component(id="r", component="Row", children=["a", "b"])
        assert as_list.children == ["a", "b"]

        as_template = Component(id="l", component="List", children={"componentId": "tpl", "path": "/items"})
        assert isinstance(as_template.children, ChildTemplate)
        assert as_template.children.component_id == "tpl"
        assert as_template.children.path == "/items"

    def test_child_template_requires_both_fields(self):
        with pytest.raises(ValidationError):
            ChildTemplate(componentId="tpl")


class TestDataBindingPathOnly:
    def test_data_binding_path_only(self):
        """DataBinding accepts {"path"} and rejects the legacy {"$bind"} shape."""
        binding = DataBinding(path="/a/b")
        assert binding.path == "/a/b"

    def test_data_binding_rejects_bind_key(self):
        with pytest.raises(ValidationError):
            DataBinding(**{"$bind": "/a/b"})

    def test_data_binding_rejects_malformed_pointer(self):
        with pytest.raises(ValidationError):
            DataBinding(path="not-a-pointer")


class TestUpdateDataModelValueRequired:
    def test_update_data_model_value_required(self):
        """Omitting `value` is a ValidationError; `value=None` is accepted."""
        with pytest.raises(ValidationError):
            UpdateDataModel(surfaceId="s")

    def test_update_data_model_value_none_allowed(self):
        msg = UpdateDataModel(surfaceId="s", value=None)
        assert msg.value is None

    def test_update_data_model_optional_path(self):
        msg = UpdateDataModel(surfaceId="s", value={"a": 1})
        assert msg.path is None


class TestEnvelopeExactlyOneKey:
    def test_envelope_exactly_one_key(self):
        """Two message keys (or zero) raise; exactly one validates."""
        with pytest.raises(ValidationError):
            A2UIAgentMessage(
                version="v1.0",
                createSurface={"surfaceId": "s"},
                deleteSurface={"surfaceId": "s"},
            )
        with pytest.raises(ValidationError):
            A2UIAgentMessage(version="v1.0")

        ok = A2UIAgentMessage(version="v1.0", createSurface={"surfaceId": "s"})
        assert ok.create_surface.surface_id == "s"

    def test_envelope_rejects_wrong_version(self):
        with pytest.raises(ValidationError):
            A2UIAgentMessage(version="1.0", createSurface={"surfaceId": "s"})


class TestActionEventXorFunctionCall:
    def test_action_event_xor_function_call(self):
        """Action requires exactly one of `event`/`functionCall`."""
        with pytest.raises(ValidationError):
            Action()
        with pytest.raises(ValidationError):
            Action(event={"name": "submit"}, functionCall={"call": "openUrl"})

        by_event = Action(event={"name": "submit"})
        assert by_event.event.name == "submit"
        assert by_event.function_call is None

        by_call = Action(functionCall={"call": "openUrl", "args": {"url": "https://x"}})
        assert by_call.function_call.call == "openUrl"
        assert by_call.event is None


class TestExtensionsKeysUax31AndReservedPrefix:
    def test_extensions_keys_uax31_and_reserved_prefix(self):
        """Extension keys must be Unicode identifiers; `a2ui_` is reserved."""
        ok = ComponentMetadata(extensions={"parrot_role": "caption"})
        assert ok.extensions.root == {"parrot_role": "caption"}

        with pytest.raises(ValidationError):
            ComponentMetadata(extensions={"a2ui_official": True})

        with pytest.raises(ValidationError):
            ComponentMetadata(extensions={"not a valid key!": 1})

"""Unit tests for A2UI v1.0 wire models (FEAT-470 TASK-2532).

Model-only tests — intentionally do NOT import
:mod:`parrot.outputs.a2ui.serialization` (its rewrite is TASK-2533, landed
in the same session; see that task's tests for round-trip coverage).
"""

import pytest
from parrot.outputs.a2ui.models import (
    A2UIAgentMessage,
    Action,
    ActionMessage,
    AgentFunctionResponse,
    CallAgentFunction,
    ChildTemplate,
    Component,
    ComponentMetadata,
    DataBinding,
    RendererFunctionResponse,
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


def _action(**extra):
    base = {
        "name": "submit",
        "surfaceId": "s-1",
        "sourceComponentId": "btn-1",
        "timestamp": "2026-08-29T10:00:00Z",
        "context": {"k": "v"},
    }
    base.update(extra)
    return base


class TestActionDataModel:
    """TASK-2567 — G3 requires `action` to accept `sendDataModel` payloads."""

    def test_action_accepts_data_model(self):
        msg = ActionMessage.model_validate(_action(dataModel={"count": 3}))
        assert msg.data_model == {"count": 3}

    def test_action_data_model_absent_is_none(self):
        """Absent must be None, NOT {} — TASK-2570 relies on the distinction."""
        assert ActionMessage.model_validate(_action()).data_model is None

    def test_action_empty_data_model_is_not_none(self):
        assert ActionMessage.model_validate(_action(dataModel={})).data_model == {}

    def test_action_still_forbids_unknown_keys(self):
        with pytest.raises(ValidationError):
            ActionMessage.model_validate(_action(datamodel={"typo": 1}))

    def test_call_agent_function_rejects_data_model(self):
        """renderer_to_agent.json sets additionalProperties:false here."""
        with pytest.raises(ValidationError):
            CallAgentFunction.model_validate(
                {
                    "surfaceId": "s-1",
                    "functionCallId": "fc-1",
                    "callFunction": {"call": "get_weather", "args": {}},
                    "dataModel": {"nope": True},
                }
            )


class TestFunctionResponseDocstrings:
    """TASK-2567 — FEAT-470 shipped these two docstrings swapped (spec §6 FINDING 2)."""

    def test_agent_function_response_names_call_agent_function(self):
        assert "callAgentFunction" in AgentFunctionResponse.__doc__
        assert "callRendererFunction" not in AgentFunctionResponse.__doc__

    def test_renderer_function_response_names_call_renderer_function(self):
        assert "callRendererFunction" in RendererFunctionResponse.__doc__
        assert "callAgentFunction" not in RendererFunctionResponse.__doc__

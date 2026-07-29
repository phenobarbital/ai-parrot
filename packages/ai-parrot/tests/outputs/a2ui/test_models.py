"""Unit tests for A2UI v1.0 envelope models (TASK-1720 / Module 1)."""

import pytest
from pydantic import TypeAdapter, ValidationError

from parrot.outputs.a2ui.models import (
    A2UIMessage,
    Action,
    ActionResponse,
    CallFunction,
    Component,
    CreateSurface,
    UpdateComponents,
    UpdateDataModel,
    is_binding_expression,
    is_valid_pointer,
)
from parrot.outputs.a2ui.serialization import deserialize, serialize

_ADAPTER = TypeAdapter(A2UIMessage)


def _sample(message_type: str):
    """Build a minimal valid instance for each message type."""
    if message_type == "createSurface":
        return CreateSurface(
            surfaceId="main",
            catalogId="https://parrot.dev/catalogs/v1",
            components=[Component(id="blk-000", component="Column", children=[])],
        )
    if message_type == "updateComponents":
        return UpdateComponents(
            surfaceId="main",
            components=[Component(id="blk-000", component="Chart")],
        )
    if message_type == "updateDataModel":
        return UpdateDataModel(surfaceId="main", contents={"/charts/blk-000": [1, 2]})
    if message_type == "action":
        return Action(surfaceId="main", componentId="blk-000", action="submit")
    if message_type == "actionResponse":
        return ActionResponse(surfaceId="main", action="submit", payload={"ok": True})
    if message_type == "callFunction":
        return CallFunction(functionName="refresh", arguments={"id": 1})
    raise AssertionError(message_type)


class TestMessageSet:
    @pytest.mark.parametrize(
        "message_type",
        [
            "createSurface",
            "updateComponents",
            "updateDataModel",
            "action",
            "actionResponse",
            "callFunction",
        ],
    )
    def test_message_set_roundtrip(self, message_type):
        """Every v1.0 message type serializes and deserializes to an identical model."""
        original = _sample(message_type)
        restored = deserialize(serialize(original))
        assert restored == original
        assert type(restored) is type(original)

    def test_discriminated_union_dispatch(self):
        """Parsing a dict routes to the correct concrete message class."""
        parsed = _ADAPTER.validate_python(
            {
                "messageType": "updateDataModel",
                "surfaceId": "main",
                "contents": {"/x": 1},
            }
        )
        assert isinstance(parsed, UpdateDataModel)

    def test_binding_syntax_valid_pointer_accepted(self):
        """A well-formed pointer-shaped binding passes light syntax validation."""
        comp = Component(
            id="blk-000",
            component="Chart",
            properties={"series": {"$bind": "/charts/blk-000/series"}},
        )
        assert comp.properties["series"]["$bind"] == "/charts/blk-000/series"

    def test_binding_syntax_malformed_rejected(self):
        """A malformed binding expression raises a validation error."""
        with pytest.raises(ValidationError):
            Component(
                id="blk-000",
                component="Chart",
                properties={"series": {"$bind": "not a pointer"}},
            )

    def test_is_valid_pointer(self):
        assert is_valid_pointer("")
        assert is_valid_pointer("/a/b/c")
        assert is_valid_pointer("/i18n/title~1sub")
        assert not is_valid_pointer("no-leading-slash")
        assert not is_valid_pointer("/has space")

    def test_is_binding_expression(self):
        assert is_binding_expression({"$bind": "/x"})
        assert not is_binding_expression({"value": 1})
        assert not is_binding_expression("/x")

    def test_datamodel_rejects_non_pointer_key(self):
        with pytest.raises(ValidationError):
            UpdateDataModel(surfaceId="main", contents={"bad key": 1})

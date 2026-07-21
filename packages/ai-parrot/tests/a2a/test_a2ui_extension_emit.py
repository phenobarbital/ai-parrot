"""A2UI-A2A extension emit tests (TASK-1741 / Module 13)."""

from types import SimpleNamespace

import pytest

# Ensure catalog components are registered so display-only enforcement can see flags.
import parrot.outputs.a2ui.catalog.components  # noqa: F401
from parrot.a2a.models import (
    A2UI_EXTENSION_URI,
    A2UI_MEDIA_TYPE,
    Artifact,
)
from parrot.outputs.a2ui.models import Component, CreateSurface
from parrot.outputs.a2ui.serialization import serialize


def _display_envelope() -> dict:
    return serialize(
        CreateSurface(
            surfaceId="main",
            catalogId="https://parrot.dev/catalogs/v1",
            components=[Component(id="b0", component="Card", properties={"title": "Hi"})],
        )
    )


def _action_envelope() -> dict:
    return serialize(
        CreateSurface(
            surfaceId="main",
            catalogId="https://parrot.dev/catalogs/v1",
            components=[
                Component(
                    id="b0",
                    component="Form",
                    properties={"fields": [{"name": "e", "input": "text"}], "submit": {"action": "s"}},
                )
            ],
        )
    )


class TestA2UIA2AEmit:
    def test_envelope_wrapped_in_artifact_parts(self):
        art = Artifact.from_a2ui_envelope(_display_envelope(), name="surface")
        assert len(art.parts) == 1
        part = art.parts[0]
        assert part.data is not None
        assert part.metadata["extensionUri"] == A2UI_EXTENSION_URI
        assert part.metadata["mediaType"] == A2UI_MEDIA_TYPE
        assert art.metadata["extensionUri"] == A2UI_EXTENSION_URI

    def test_artifact_to_dict_roundtrips_envelope(self):
        env = _display_envelope()
        art = Artifact.from_a2ui_envelope(env)
        d = art.to_dict()
        part = d["parts"][0]
        assert part["kind"] == "data"
        # Envelope preserved verbatim (A2A layer never re-shapes it).
        assert part["data"]["data"] == env
        assert part["metadata"]["extensionUri"] == A2UI_EXTENSION_URI

    def test_display_only_rejects_requires_actions(self):
        with pytest.raises(ValueError, match="action-bearing"):
            Artifact.from_a2ui_envelope(_action_envelope())

    def test_rejects_non_createsurface(self):
        with pytest.raises(ValueError, match="createSurface"):
            Artifact.from_a2ui_envelope({"messageType": "updateDataModel", "surfaceId": "m"})

    def test_from_response_routes_a2ui_envelope(self):
        resp = SimpleNamespace(a2ui_envelope=_display_envelope(), content="ignored")
        art = Artifact.from_response(resp, name="r")
        assert art.parts[0].data is not None
        assert art.metadata["extensionUri"] == A2UI_EXTENSION_URI

    def test_legacy_artifact_serialization_unchanged(self):
        # No a2ui_envelope → legacy text path, no a2ui keys leak.
        resp = SimpleNamespace(a2ui_envelope=None, content="hello world")
        art = Artifact.from_response(resp, name="r")
        d = art.to_dict()
        assert d["parts"][0]["kind"] == "text"
        assert d["parts"][0]["text"] == "hello world"
        assert d["metadata"] is None

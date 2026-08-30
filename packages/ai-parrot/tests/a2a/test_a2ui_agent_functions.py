"""A2UI Agent Card + Artifact tests (FEAT-469 TASK-2572)."""

from __future__ import annotations

import pytest
from parrot.a2a.models import (
    A2UI_EXTENSION_URI,
    AgentCapabilities,
    AgentExtension,
    Artifact,
    register_a2ui_extension,
)
from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID
from parrot.outputs.a2ui.models import Action, Component, CreateSurface, EventAction
from parrot.outputs.a2ui.serialization import serialize


def _action_envelope() -> dict:
    return serialize(
        CreateSurface(
            surfaceId="main",
            catalogId=DEFAULT_CATALOG_ID,
            components=[
                Component(
                    id="root",
                    component="Button",
                    child="lbl",
                    action=Action(event=EventAction(name="submit")),
                )
            ],
        )
    )


def _build_capabilities_with_a2ui() -> AgentCapabilities:
    caps = AgentCapabilities()
    register_a2ui_extension(caps, [DEFAULT_CATALOG_ID])
    return caps


class TestAgentCard:
    def test_declares_a2ui_extension_with_capabilities(self):
        caps = _build_capabilities_with_a2ui()
        ext = next(e for e in caps.extensions if e.uri == A2UI_EXTENSION_URI)
        assert ext.params["a2uiAgentCapabilities"]["v1.0"]["supportedCatalogIds"] == [DEFAULT_CATALOG_ID]

    def test_registration_is_idempotent(self):
        caps = AgentCapabilities()
        register_a2ui_extension(caps, [DEFAULT_CATALOG_ID])
        register_a2ui_extension(caps, [DEFAULT_CATALOG_ID])
        matches = [e for e in caps.extensions if e.uri == A2UI_EXTENSION_URI]
        assert len(matches) == 1

    def test_preserves_preexisting_extensions(self):
        caps = AgentCapabilities(extensions=[AgentExtension(uri="https://example.com/other-extension")])
        register_a2ui_extension(caps, [DEFAULT_CATALOG_ID])
        uris = {e.uri for e in caps.extensions}
        assert "https://example.com/other-extension" in uris
        assert A2UI_EXTENSION_URI in uris
        assert len(caps.extensions) == 2


class TestArtifactAllowActions:
    def test_allows_actions_when_flagged(self):
        art = Artifact.from_a2ui_envelope(_action_envelope(), allow_actions=True)
        assert len(art.parts) == 1

    def test_default_still_rejects(self):
        with pytest.raises(ValueError, match="action-bearing"):
            Artifact.from_a2ui_envelope(_action_envelope())

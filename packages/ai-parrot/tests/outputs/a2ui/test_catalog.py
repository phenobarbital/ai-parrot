"""Unit tests for the A2UI component catalog (TASK-1721 / Module 2)."""

import pytest

from parrot.outputs.a2ui.catalog import (
    DEFAULT_CATALOG_ID,
    BasicNode,
    CatalogValidationError,
    ComponentContractError,
    ComponentDefinition,
    ProducerOrigin,
    get_component,
    register_component,
    unregister_component,
    validate_envelope,
)
from parrot.outputs.a2ui.models import Component, CreateSurface


@pytest.fixture
def cleanup_catalog():
    """Track and remove any components registered during a test."""
    registered: list[str] = []
    yield registered
    for name in registered:
        unregister_component(name)


def _surface(*component_names: str) -> CreateSurface:
    return CreateSurface(
        surfaceId="main",
        catalogId=DEFAULT_CATALOG_ID,
        components=[
            Component(id=f"blk-{i}", component=name)
            for i, name in enumerate(component_names)
        ],
    )


class TestComponentRegistration:
    def test_register_component_roundtrip(self, cleanup_catalog):
        @register_component("Widget")
        class Widget:
            SCHEMA = {"type": "object"}
            INSTRUCTIONS = "A widget."

            def lower(self, component, data_model):
                return BasicNode(component="Column")

        cleanup_catalog.append("Widget")
        entry = get_component("Widget")
        assert entry.definition.name == "Widget"
        assert entry.definition.schema_ == {"type": "object"}
        assert entry.definition.instructions == "A widget."
        assert Widget.definition.name == "Widget"

    def test_register_without_lower_rejected(self):
        with pytest.raises(ComponentContractError):

            @register_component("NoLower")
            class NoLower:  # no lower() → cannot register
                SCHEMA = {}

    def test_register_with_non_callable_lower_rejected(self):
        with pytest.raises(ComponentContractError):

            @register_component("BadLower")
            class BadLower:
                lower = "not callable"

    def test_catalog_id_default(self, cleanup_catalog):
        @register_component("Defaulted")
        class Defaulted:
            def lower(self, component, data_model):
                return BasicNode(component="Column")

        cleanup_catalog.append("Defaulted")
        assert get_component("Defaulted").definition.catalog_id == DEFAULT_CATALOG_ID

    def test_definition_wire_alias(self):
        d = ComponentDefinition(name="X", schema={"a": 1})
        assert d.schema_ == {"a": 1}
        assert d.model_dump(by_alias=True)["schema"] == {"a": 1}


class TestEnvelopeValidation:
    def test_envelope_rejects_unknown_component(self):
        with pytest.raises(CatalogValidationError) as exc:
            validate_envelope(_surface("TotallyUnknown"))
        assert "TotallyUnknown" in exc.value.unknown_components

    def test_envelope_reports_all_unknown(self):
        with pytest.raises(CatalogValidationError) as exc:
            validate_envelope(_surface("UnknownA", "UnknownB"))
        assert set(exc.value.unknown_components) == {"UnknownA", "UnknownB"}

    def test_llm_envelope_rejects_requires_actions(self, cleanup_catalog):
        @register_component("SubmitForm", requires_actions=True)
        class SubmitForm:
            def lower(self, component, data_model):
                return BasicNode(component="Column")

        cleanup_catalog.append("SubmitForm")
        with pytest.raises(CatalogValidationError) as exc:
            validate_envelope(_surface("SubmitForm"), origin=ProducerOrigin.LLM)
        assert "SubmitForm" in exc.value.action_components

    def test_tool_envelope_allows_requires_actions(self, cleanup_catalog):
        @register_component("ToolForm", requires_actions=True)
        class ToolForm:
            def lower(self, component, data_model):
                return BasicNode(component="Column")

        cleanup_catalog.append("ToolForm")
        # Tool origin → action-bearing components are allowed (degrade at render).
        validate_envelope(_surface("ToolForm"), origin=ProducerOrigin.TOOL)

    def test_valid_display_envelope_passes(self, cleanup_catalog):
        @register_component("DisplayOnlyDummy")
        class DisplayOnlyDummy:
            def lower(self, component, data_model):
                return BasicNode(component="Column")

        cleanup_catalog.append("DisplayOnlyDummy")
        validate_envelope(_surface("DisplayOnlyDummy"), origin=ProducerOrigin.LLM)

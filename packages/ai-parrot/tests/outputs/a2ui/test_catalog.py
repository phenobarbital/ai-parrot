"""Unit tests for the A2UI component catalog (TASK-1721 / Module 2, updated FEAT-470).

FEAT-529 Module 0 adds the keyed-registry (``(catalog_id, name)``) regression
tests at the bottom of this file.
"""

from typing import ClassVar

import pytest
from parrot.outputs.a2ui.catalog import (
    DEFAULT_CATALOG_ID,
    BasicNode,
    CatalogError,
    CatalogValidationError,
    ComponentContractError,
    ComponentDefinition,
    ProducerOrigin,
    get_component,
    list_components,
    register_component,
    unregister_component,
    validate_envelope,
)
from parrot.outputs.a2ui.catalog.viz_core import VIZ_CORE_CATALOG_ID
from parrot.outputs.a2ui.models import Component, CreateSurface


@pytest.fixture
def cleanup_catalog():
    """Track and remove any components registered during a test."""
    registered: list[str] = []
    yield registered
    for name in registered:
        unregister_component(name)


def _surface(*component_names: str) -> CreateSurface:
    """Build a surface with a ``root`` Column wrapping each named component."""
    children = [Component(id=f"blk-{i}", component=name) for i, name in enumerate(component_names)]
    root = Component(id="root", component="Column", children=[c.id for c in children])
    return CreateSurface(
        surfaceId="main",
        catalogId=DEFAULT_CATALOG_ID,
        components=[root, *children],
    )


class TestComponentRegistration:
    def test_register_component_roundtrip(self, cleanup_catalog):
        @register_component("Widget")
        class Widget:
            SCHEMA: ClassVar[dict] = {"type": "object"}
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
                SCHEMA: ClassVar[dict] = {}

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

    def test_tool_only_default_false(self, cleanup_catalog):
        """FEAT-527."""

        @register_component("NotToolOnly")
        class NotToolOnly:
            def lower(self, component, data_model):
                return BasicNode(component="Column")

        cleanup_catalog.append("NotToolOnly")
        assert get_component("NotToolOnly").definition.tool_only is False

    def test_tool_only_true_when_registered(self, cleanup_catalog):
        """FEAT-527."""

        @register_component("ToolOnly", tool_only=True)
        class ToolOnly:
            def lower(self, component, data_model):
                return BasicNode(component="Column")

        cleanup_catalog.append("ToolOnly")
        assert get_component("ToolOnly").definition.tool_only is True


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


class TestKeyedRegistry:
    """FEAT-529 Module 0: ``_CATALOG`` keyed by ``(catalog_id, name)``."""

    def test_registry_keyed_by_catalog_and_name(self):
        @register_component("KeyedProbe", catalog_id=DEFAULT_CATALOG_ID)
        class KeyedProbeDefault:
            def lower(self, component, data_model):
                return BasicNode(component="Column")

        @register_component("KeyedProbe", catalog_id=VIZ_CORE_CATALOG_ID)
        class KeyedProbeVizCore:
            def lower(self, component, data_model):
                return BasicNode(component="Column")

        try:
            with pytest.raises(CatalogError) as exc:
                get_component("KeyedProbe")
            assert set(exc.value.candidates) == {DEFAULT_CATALOG_ID, VIZ_CORE_CATALOG_ID}

            assert get_component("KeyedProbe", DEFAULT_CATALOG_ID).component_cls is KeyedProbeDefault
            assert get_component("KeyedProbe", VIZ_CORE_CATALOG_ID).component_cls is KeyedProbeVizCore
        finally:
            unregister_component("KeyedProbe", DEFAULT_CATALOG_ID)
            unregister_component("KeyedProbe", VIZ_CORE_CATALOG_ID)

    def test_registry_rejects_duplicate_pair(self, cleanup_catalog):
        @register_component("DupPair")
        class DupPair:
            def lower(self, component, data_model):
                return BasicNode(component="Column")

        cleanup_catalog.append("DupPair")

        with pytest.raises(CatalogError):

            @register_component("DupPair")
            class DupPairAgain:
                def lower(self, component, data_model):
                    return BasicNode(component="Column")

    def test_bare_name_lookup_stays_unique_today(self):
        """Pins that no registered name is ambiguous until the charts spec."""
        for definition in list_components():
            get_component(definition.name)  # must not raise CatalogError

    def test_component_exists_third_catalog(self, cleanup_catalog):
        from parrot.outputs.a2ui.catalog import _component_exists

        @register_component("VizCoreExistsProbe", catalog_id=VIZ_CORE_CATALOG_ID)
        class VizCoreExistsProbe:
            def lower(self, component, data_model):
                return BasicNode(component="Column")

        try:
            assert _component_exists("VizCoreExistsProbe", VIZ_CORE_CATALOG_ID) is True
            assert _component_exists("VizCoreExistsProbe", DEFAULT_CATALOG_ID) is False
            assert _component_exists("Text", VIZ_CORE_CATALOG_ID) is False
        finally:
            unregister_component("VizCoreExistsProbe", VIZ_CORE_CATALOG_ID)

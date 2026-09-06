"""Tests for export_catalog_definition (FEAT-470 TASK-2540)."""

from __future__ import annotations

import jsonschema
import pytest
from parrot.outputs.a2ui.catalog import (
    register_component,
    unregister_component,
)
from parrot.outputs.a2ui.catalog import (
    parrot as _register_parrot_components,  # noqa: F401
)
from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID, BasicNode
from parrot.outputs.a2ui.catalog.basic import (
    BASIC_CATALOG_ID,
    load_spec,
    schema_registry,
)
from parrot.outputs.a2ui.catalog.export import export_catalog_definition, write_catalog_definition
from parrot.outputs.a2ui.catalog.viz_core import VIZ_CORE_CATALOG_ID, VIZ_CORE_INSTRUCTIONS


class TestExportCatalogDefinitionValid:
    def test_export_catalog_definition_valid(self):
        doc = export_catalog_definition()
        schema = load_spec("catalog_definition")
        registry = schema_registry()
        validator_cls = jsonschema.validators.validator_for(schema)
        validator_cls(schema, registry=registry).validate(doc)  # raises on failure

    def test_export_top_level_fields(self):
        doc = export_catalog_definition()
        assert doc["protocolVersion"] == "1.0"
        assert doc["catalogId"] == DEFAULT_CATALOG_ID
        assert isinstance(doc["instructions"], str) and doc["instructions"]


class TestExportIncludesBasicRefsAndInstructions:
    def test_export_includes_basic_refs_and_instructions(self):
        doc = export_catalog_definition()
        assert doc["components"]["Text"] == {"$ref": f"{BASIC_CATALOG_ID}#/components/Text"}
        assert "returnType" in doc["functions"]["required"]
        assert "InfoCard" in doc["instructions"]

    def test_export_excludes_basic_when_disabled(self):
        doc = export_catalog_definition(include_basic=False)
        assert "Text" not in doc["components"]
        assert "required" not in doc["functions"]
        assert "InfoCard" in doc["components"]

    def test_export_parrot_components_carry_allowed_parents(self):
        doc = export_catalog_definition()
        assert doc["components"]["Report"].get("allowedParents") == ["root", "Column"]


@pytest.fixture
def viz_core_probe():
    """Register a throwaway viz-core component for the export tests below."""

    @register_component("VizCoreExportProbe", catalog_id=VIZ_CORE_CATALOG_ID)
    class VizCoreExportProbe:
        SCHEMA = {"type": "object", "properties": {"kind": {"type": "string"}}}
        INSTRUCTIONS = "Use VizCoreExportProbe for probing exports."

        def lower(self, component, data_model):
            return BasicNode(component="Column")

    yield "VizCoreExportProbe"
    unregister_component("VizCoreExportProbe", VIZ_CORE_CATALOG_ID)


class TestExportScopedToVizCore:
    """FEAT-529 Module 0: catalog-scoped export."""

    def test_export_viz_core_catalog_validates(self, viz_core_probe):
        doc = export_catalog_definition(catalog_id=VIZ_CORE_CATALOG_ID)
        schema = load_spec("catalog_definition")
        registry = schema_registry()
        validator_cls = jsonschema.validators.validator_for(schema)
        validator_cls(schema, registry=registry).validate(doc)  # raises on failure

        assert doc["catalogId"] == VIZ_CORE_CATALOG_ID
        assert "VizCoreExportProbe" in doc["components"]
        # include_basic=True (default) still $ref's the Basic Catalog primitives.
        assert doc["components"]["Text"] == {"$ref": f"{BASIC_CATALOG_ID}#/components/Text"}
        assert doc["instructions"].startswith(VIZ_CORE_INSTRUCTIONS)
        assert "InfoCard" not in doc["instructions"]

    def test_write_catalog_definition_catalog_id(self, tmp_path, viz_core_probe):
        path = tmp_path / "viz_core_catalog_definition.json"
        write_catalog_definition(path, catalog_id=VIZ_CORE_CATALOG_ID)

        import json

        doc = json.loads(path.read_text())
        assert doc["catalogId"] == VIZ_CORE_CATALOG_ID
        assert "VizCoreExportProbe" in doc["components"]

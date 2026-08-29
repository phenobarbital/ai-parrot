"""Tests for export_catalog_definition (FEAT-470 TASK-2540)."""

from __future__ import annotations

import jsonschema
from parrot.outputs.a2ui.catalog import (
    parrot as _register_parrot_components,  # noqa: F401
)
from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID
from parrot.outputs.a2ui.catalog.basic import (
    BASIC_CATALOG_ID,
    load_spec,
    schema_registry,
)
from parrot.outputs.a2ui.catalog.export import export_catalog_definition


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

"""Tests for FEAT-473 TASK-2560 — catalog parity, derived schemas, LLM-origin guard."""

from __future__ import annotations

import jsonschema
import pytest
from parrot.models.outputs import (
    StructuredChartConfig,
    StructuredMapConfig,
    StructuredTableConfig,
)
from parrot.outputs.a2ui.catalog import validate_envelope
from parrot.outputs.a2ui.catalog.base import CatalogValidationError, ProducerOrigin
from parrot.outputs.a2ui.catalog.basic import load_spec, schema_registry
from parrot.outputs.a2ui.catalog.export import export_catalog_definition
from parrot.outputs.a2ui.catalog.parrot import chart as chart_mod
from parrot.outputs.a2ui.catalog.parrot import datatable as datatable_mod
from parrot.outputs.a2ui.catalog.parrot import map as map_mod
from parrot.outputs.a2ui.models import Component, CreateSurface


def test_derived_chart_schema_has_all_config_fields():
    """Every StructuredChartConfig alias except `data` is a CHART_SCHEMA property."""
    aliases = {
        field.alias or name for name, field in StructuredChartConfig.model_fields.items()
    } - {"data"}
    assert aliases <= set(chart_mod.CHART_SCHEMA["properties"])


def test_derived_table_schema_has_all_config_fields():
    """Every StructuredTableConfig alias except `data` is a DATATABLE_SCHEMA property."""
    aliases = {
        field.alias or name for name, field in StructuredTableConfig.model_fields.items()
    } - {"data"}
    # total_rows/truncated have no pydantic alias — derive_schema camelCases them.
    camel_aliases = {
        "".join(part.title() if i else part for i, part in enumerate(a.split("_"))) for a in aliases
    }
    assert camel_aliases <= set(datatable_mod.DATATABLE_SCHEMA["properties"])


def test_derived_map_schema_keeps_defs_and_validates_export():
    """MAP_SCHEMA has $defs; export_catalog_definition() validates against the vendored spec."""
    aliases = {
        field.alias or name for name, field in StructuredMapConfig.model_fields.items()
    } - {"data", "datasets"}
    assert aliases <= set(map_mod.MAP_SCHEMA["properties"])
    assert "$defs" in map_mod.MAP_SCHEMA
    assert {"MapLayer", "MapViewport", "MapQuery", "MapColumn"} <= set(map_mod.MAP_SCHEMA["$defs"])

    doc = export_catalog_definition()
    schema = load_spec("catalog_definition")
    registry = schema_registry()
    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls(schema, registry=registry).validate(doc)  # raises on failure


def test_datatable_schema_parity_unchanged():
    """Derived DATATABLE_SCHEMA is a superset of the prior hand-written schema.

    NOTE: the prior hand-written schema declared a ``title`` property that
    ``StructuredTableConfig`` never actually had — the derived schema (by
    construction, G2) correctly drops it since it does not hallucinate fields
    absent from the config model.
    """
    previous_hand_written = {"columns", "totalRows", "truncated", "data"}
    assert previous_hand_written <= set(datatable_mod.DATATABLE_SCHEMA["properties"])


def _surface(component: Component) -> CreateSurface:
    return CreateSurface(
        surfaceId="s",
        catalogId="https://parrot.dev/catalogs/v1",
        components=[Component(id="root", component="Column", children=[component.id]), component],
    )


def test_llm_origin_rejects_inline_rows():
    comp = Component(
        id="c1",
        component="Chart",
        type="bar",
        x="a",
        y=["b"],
        data=[{"a": 1, "b": 2}],
    )
    with pytest.raises(CatalogValidationError):
        validate_envelope(_surface(comp), origin=ProducerOrigin.LLM)


def test_llm_origin_accepts_path_binding():
    comp = Component(
        id="c1",
        component="Chart",
        type="bar",
        x="a",
        y=["b"],
        data={"path": "/rows"},
    )
    validate_envelope(_surface(comp), origin=ProducerOrigin.LLM)  # must not raise


def test_tool_origin_allows_inline_rows():
    comp = Component(
        id="c1",
        component="Chart",
        type="bar",
        x="a",
        y=["b"],
        data=[{"a": 1, "b": 2}],
    )
    validate_envelope(_surface(comp), origin=ProducerOrigin.TOOL)  # must not raise


def test_chart_lower_renders_axis_labels_and_trendline():
    comp = Component(
        id="c1",
        component="Chart",
        type="bar",
        x="a",
        y=["b"],
        xAxisLabel="Category",
        yAxisLabel="Revenue",
        trendline=True,
    )
    tree = chart_mod.ChartComponent().lower(comp, {})
    texts = _all_texts(tree)
    assert any("x-axis: Category" in t and "y-axis: Revenue" in t for t in texts)
    assert any("Trendline" in t for t in texts)


def test_map_lower_renders_layer_fields():
    comp = Component(
        id="m1",
        component="Map",
        layers=[
            {
                "layer": "stores",
                "labelField": "name",
                "markerColor": "red",
                "totalCount": 100,
                "capped": True,
            }
        ],
    )
    tree = map_mod.MapComponent().lower(comp, {})
    texts = _all_texts(tree)
    assert any(
        "stores" in t and "label=name" in t and "color=red" in t and "total=100" in t and "capped" in t
        for t in texts
    )


def _all_texts(node) -> list[str]:
    texts: list[str] = []
    if getattr(node, "component", None) == "Text" and isinstance(getattr(node, "text", None), str):
        texts.append(node.text)
    if node.child is not None:
        texts.extend(_all_texts(node.child))
    if isinstance(node.children, list):
        for child in node.children:
            texts.extend(_all_texts(child))
    return texts

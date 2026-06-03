"""Tests for FEAT-221: StructuredMapConfig + OutputMode.STRUCTURED_MAP.

TASK-1445: OutputMode.STRUCTURED_MAP enum member + MapColumn + MapLayer +
MapViewport + MapQuery + StructuredMapConfig.
"""
from __future__ import annotations

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# TASK-1445 — OutputMode.STRUCTURED_MAP enum member
# ─────────────────────────────────────────────────────────────────────────────


def test_output_mode_value():
    """OutputMode.STRUCTURED_MAP exists with the correct string value."""
    from parrot.models.outputs import OutputMode

    assert OutputMode.STRUCTURED_MAP.value == "structured_map"
    assert OutputMode("structured_map") is OutputMode.STRUCTURED_MAP


# ─────────────────────────────────────────────────────────────────────────────
# TASK-1445 — MapColumn model
# ─────────────────────────────────────────────────────────────────────────────


def test_map_column_basic():
    """MapColumn accepts name, type, title and optional format."""
    from parrot.models.outputs import MapColumn

    col = MapColumn(name="amount", type="number", title="Amount")
    assert col.name == "amount"
    assert col.type == "number"
    assert col.title == "Amount"
    assert col.format is None


def test_column_vocabulary_matches_table():
    """MapColumn.type/format accept the same vocabulary as TableColumn."""
    from parrot.models.outputs import MapColumn

    col = MapColumn(name="price", type="number", title="Price", format="currency")
    assert col.format == "currency"


def test_map_column_all_formats():
    """MapColumn accepts all defined format hints."""
    from parrot.models.outputs import MapColumn

    for fmt in ("currency", "percent", "email", "uri", "enum", "id", "code"):
        col = MapColumn(name="x", type="string", title="X", format=fmt)
        assert col.format == fmt


# ─────────────────────────────────────────────────────────────────────────────
# TASK-1445 — MapLayer model
# ─────────────────────────────────────────────────────────────────────────────


def test_map_layer_basic():
    """MapLayer accepts layer id and columns with defaults."""
    from parrot.models.outputs import MapLayer, MapColumn

    layer = MapLayer(
        layer="schools",
        columns=[MapColumn(name="name", type="string", title="Name")],
    )
    assert layer.layer == "schools"
    assert len(layer.columns) == 1
    assert layer.tooltip_template is None
    assert layer.label_field is None
    assert layer.data_shape == "geojson"
    assert layer.total_count == 0
    assert layer.capped is False
    assert layer.geodesic is None


def test_map_layer_alias_fields():
    """MapLayer serializes with camelCase aliases."""
    from parrot.models.outputs import MapLayer, MapColumn

    layer = MapLayer(
        layer="schools",
        columns=[MapColumn(name="name", type="string", title="Name")],
        tooltip_template="{name}",
        label_field="name",
        data_shape="rows",
        total_count=50,
        capped=True,
    )
    dumped = layer.model_dump(mode="json", by_alias=True)
    assert dumped["tooltipTemplate"] == "{name}"
    assert dumped["labelField"] == "name"
    assert dumped["dataShape"] == "rows"
    assert dumped["totalCount"] == 50
    assert dumped["capped"] is True


# ─────────────────────────────────────────────────────────────────────────────
# TASK-1445 — MapViewport model
# ─────────────────────────────────────────────────────────────────────────────


def test_map_viewport_defaults():
    """MapViewport all fields default to None."""
    from parrot.models.outputs import MapViewport

    vp = MapViewport()
    assert vp.bbox is None
    assert vp.center is None
    assert vp.zoom is None


def test_map_viewport_full():
    """MapViewport accepts all fields."""
    from parrot.models.outputs import MapViewport

    vp = MapViewport(bbox=[-74.1, 40.6, -73.9, 40.8], center=(40.7, -74.0), zoom=12)
    assert vp.bbox == [-74.1, 40.6, -73.9, 40.8]
    assert vp.center == (40.7, -74.0)
    assert vp.zoom == 12


# ─────────────────────────────────────────────────────────────────────────────
# TASK-1445 — MapQuery model
# ─────────────────────────────────────────────────────────────────────────────


def test_map_query_fields():
    """MapQuery accepts point, radius, unit."""
    from parrot.models.outputs import MapQuery

    q = MapQuery(point=(40.7, -74.0), radius=5.0, unit="mi")
    assert q.point == (40.7, -74.0)
    assert q.radius == 5.0
    assert q.unit == "mi"


# ─────────────────────────────────────────────────────────────────────────────
# TASK-1445 — StructuredMapConfig model + dump exclusion
# ─────────────────────────────────────────────────────────────────────────────


def test_config_excludes_data():
    """model_dump(exclude={'data'}) omits data rows; layers/viewport retained."""
    from parrot.models.outputs import StructuredMapConfig, MapLayer, MapColumn

    cfg = StructuredMapConfig(
        layers=[MapLayer(layer="schools", columns=[MapColumn(name="name", type="string", title="Name")])],
        data=[{"name": "PS 1"}],
    )
    out = cfg.model_dump(mode="json", by_alias=True, exclude={"data"})
    assert "data" not in out
    assert out["layers"][0]["layer"] == "schools"


def test_config_data_accessible_on_model():
    """data is accessible on the model instance even though excluded from dump."""
    from parrot.models.outputs import StructuredMapConfig, MapLayer, MapColumn

    cfg = StructuredMapConfig(
        layers=[MapLayer(layer="schools", columns=[MapColumn(name="name", type="string", title="Name")])],
        data=[{"name": "PS 1"}, {"name": "PS 2"}],
    )
    assert len(cfg.data) == 2


def test_config_defaults():
    """viewport, query, base_layer, title, description, explanation default to None."""
    from parrot.models.outputs import StructuredMapConfig, MapLayer, MapColumn

    cfg = StructuredMapConfig(
        layers=[MapLayer(layer="schools", columns=[MapColumn(name="name", type="string", title="Name")])],
    )
    assert cfg.viewport is None
    assert cfg.query is None
    assert cfg.base_layer is None
    assert cfg.title is None
    assert cfg.description is None
    assert cfg.explanation is None


def test_config_all_fields():
    """StructuredMapConfig accepts all optional fields."""
    from parrot.models.outputs import (
        StructuredMapConfig, MapLayer, MapColumn, MapViewport, MapQuery
    )

    cfg = StructuredMapConfig(
        layers=[MapLayer(layer="schools", columns=[MapColumn(name="name", type="string", title="Name")])],
        data=[{"name": "PS 1"}],
        viewport=MapViewport(bbox=[-74.1, 40.6, -73.9, 40.8]),
        query=MapQuery(point=(40.7, -74.0), radius=5.0, unit="mi"),
        base_layer="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        title="Schools near warehouse",
        description="5 mi radius",
        explanation="Found 1 school.",
    )
    assert cfg.title == "Schools near warehouse"
    assert cfg.viewport.bbox == [-74.1, 40.6, -73.9, 40.8]
    assert cfg.query.radius == 5.0


def test_config_base_layer_alias():
    """StructuredMapConfig serializes baseLayer with camelCase alias."""
    from parrot.models.outputs import StructuredMapConfig, MapLayer, MapColumn

    cfg = StructuredMapConfig(
        layers=[MapLayer(layer="schools", columns=[MapColumn(name="name", type="string", title="Name")])],
        base_layer="osm",
    )
    out = cfg.model_dump(mode="json", by_alias=True, exclude={"data"})
    assert "baseLayer" in out
    assert out["baseLayer"] == "osm"


# ─────────────────────────────────────────────────────────────────────────────
# TASK-1445 — @model_validator column-name check
# ─────────────────────────────────────────────────────────────────────────────


def test_validate_column_names():
    """Column names absent from non-empty data[0] raise ValueError."""
    from parrot.models.outputs import StructuredMapConfig, MapLayer, MapColumn

    with pytest.raises((ValueError, Exception), match="not present in data rows"):
        StructuredMapConfig(
            layers=[MapLayer(layer="x", columns=[MapColumn(name="missing", type="string", title="M")])],
            data=[{"name": "PS 1"}],
        )


def test_validate_column_names_ok():
    """All column names present in data[0] — no error."""
    from parrot.models.outputs import StructuredMapConfig, MapLayer, MapColumn

    cfg = StructuredMapConfig(
        layers=[MapLayer(layer="x", columns=[MapColumn(name="name", type="string", title="Name")])],
        data=[{"name": "PS 1", "extra": "ignored"}],
    )
    assert len(cfg.layers) == 1


def test_validate_empty_data_skips_check():
    """Empty data list does not trigger column-name validation."""
    from parrot.models.outputs import StructuredMapConfig, MapLayer, MapColumn

    cfg = StructuredMapConfig(
        layers=[MapLayer(layer="x", columns=[MapColumn(name="anything", type="any", title="X")])],
        data=[],
    )
    assert cfg.data == []


# ─────────────────────────────────────────────────────────────────────────────
# TASK-1445 — Import smoke test
# ─────────────────────────────────────────────────────────────────────────────


def test_importable():
    """from parrot.models.outputs import ... works for all map models."""
    from parrot.models.outputs import (  # noqa: F401
        OutputMode,
        StructuredMapConfig,
        MapLayer,
        MapColumn,
        MapViewport,
        MapQuery,
    )

    assert OutputMode.STRUCTURED_MAP
    assert StructuredMapConfig
    assert MapLayer
    assert MapColumn
    assert MapViewport
    assert MapQuery

"""Unit tests for FEAT-219 Module 3: SpatialCompiler engine push-down (pg + bigquery).

Tests:
    test_compile_pg_snapshot — compile() for pg emits ST_DWITHIN + ST_AsGeoJSON, no DB.
    test_compile_bigquery_snapshot — same for bigquery dialect.
    test_geodesic_verify — geography column → geodesic True; non-geography → False + warning.
    test_compile_is_io_free — compile() does not import asyncdb or touch a DB.
    test_compiled_query_is_immutable — CompiledQuery is frozen (no attribute mutation).
    test_engine_path_set_correctly — compile() with pg/bigquery source uses engine path.
    test_pandas_path_for_unknown_driver — compile() with unknown driver uses pandas path.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Minimal module stubs to avoid broken parrot import chain
# ---------------------------------------------------------------------------

def _load_spatial_module(name: str, relpath: str) -> types.ModuleType:
    """Load a spatial module by path relative to the spatial package directory."""
    import importlib.util
    from pathlib import Path
    # Resolve base path dynamically from this test file's location.
    # This file lives at packages/ai-parrot/tests/unit/ — walk up 3 levels to
    # reach packages/ai-parrot/, then descend into src/parrot/tools/dataset_manager/spatial.
    base = (
        Path(__file__).parents[2]
        / "src" / "parrot" / "tools" / "dataset_manager" / "spatial"
    )
    full_path = str(base / relpath)
    spec = importlib.util.spec_from_file_location(name, full_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _ensure_stubs() -> None:
    """Install minimal package stubs so relative imports resolve."""
    for pkg in (
        "parrot",
        "parrot.tools",
        "parrot.tools.dataset_manager",
        "parrot.tools.dataset_manager.spatial",
        "parrot.tools.dataset_manager.sources",
    ):
        if pkg not in sys.modules:
            sys.modules[pkg] = types.ModuleType(pkg)


_ensure_stubs()
_contracts = _load_spatial_module(
    "parrot.tools.dataset_manager.spatial.contracts",
    "contracts.py",
)
_registry = _load_spatial_module(
    "parrot.tools.dataset_manager.spatial.registry",
    "registry.py",
)
_compiler_mod = _load_spatial_module(
    "parrot.tools.dataset_manager.spatial.compiler",
    "compiler.py",
)

SpatialFilterSpec = _contracts.SpatialFilterSpec
DatasetSpatialProfile = _contracts.DatasetSpatialProfile
SpatialFeatureCollection = _contracts.SpatialFeatureCollection
SPATIAL_PROFILE_REGISTRY = _registry.SPATIAL_PROFILE_REGISTRY
SpatialCompiler = _compiler_mod.SpatialCompiler
CompiledQuery = _compiler_mod.CompiledQuery


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def compiler() -> SpatialCompiler:
    """Return a SpatialCompiler instance."""
    return SpatialCompiler()


@pytest.fixture
def warehouse_spec() -> SpatialFilterSpec:
    """A sample spatial filter spec."""
    return SpatialFilterSpec(
        point=(40.7128, -74.0060),
        radius=5.0,
        unit="mi",
        datasets=["schools"],
    )


@pytest.fixture
def pg_school_profile() -> DatasetSpatialProfile:
    """A pg school profile with a geography column."""
    return DatasetSpatialProfile(
        dataset="schools",
        geom_col="geog",
        layer="schools",
        property_cols=["name", "type"],
        description_template="{name} ({type})",
        geodesic=True,
    )


@pytest.fixture
def bq_school_profile() -> DatasetSpatialProfile:
    """A BigQuery school profile with a GEOGRAPHY column."""
    return DatasetSpatialProfile(
        dataset="schools",
        geom_col="location",
        layer="schools",
        property_cols=["name", "type"],
        description_template="{name} ({type})",
        geodesic=True,
    )


@pytest.fixture
def pg_source() -> MagicMock:
    """A mock pg TableSource."""
    src = MagicMock()
    src.driver = "pg"
    src.table = "public.schools"
    src._schema = {"geog": "geography", "name": "text", "type": "text"}
    return src


@pytest.fixture
def bq_source() -> MagicMock:
    """A mock BigQuery TableSource."""
    src = MagicMock()
    src.driver = "bigquery"
    src.table = "my_dataset.schools"
    src._schema = {"location": "geography", "name": "STRING", "type": "STRING"}
    return src


# ---------------------------------------------------------------------------
# compile() engine push-down tests
# ---------------------------------------------------------------------------


class TestCompileEnginePassDown:
    """Tests for SpatialCompiler.compile() on engine drivers."""

    def test_compile_pg_snapshot(self, compiler, warehouse_spec, pg_school_profile, pg_source):
        """compile() for pg emits ST_DWithin + ST_AsGeoJSON (no DB required).

        Note: The spec (G7) calls for syrupy snapshot tests.  Until syrupy is
        added as a dev dependency (``uv add --dev syrupy``), we use deterministic
        string assertions that are functionally equivalent.  When syrupy is
        available, replace ``assert cq.sql is not None`` with
        ``assert cq.sql == snapshot``.
        """
        cq = compiler.compile(warehouse_spec, pg_school_profile, source=pg_source)

        assert cq.path == "engine"
        assert cq.driver == "pg"
        assert cq.profile_dataset == "schools"
        assert cq.geodesic is True

        sql = cq.sql
        assert sql is not None
        # Must contain the engine push-down keywords
        assert "ST_DWithin" in sql
        assert "ST_AsGeoJSON" in sql
        assert "ST_MakePoint" in sql
        # Column identifiers are double-quoted for pg
        assert '"geog"' in sql
        assert "public.schools" in sql
        # Coordinates must be baked in
        assert "40.7128" in sql
        assert "-74.006" in sql
        # count_sql must be present for true_count support
        assert cq.count_sql is not None
        assert "COUNT(*)" in cq.count_sql
        # count_sql must NOT have a LIMIT
        assert "LIMIT" not in cq.count_sql

    def test_compile_bigquery_snapshot(
        self, compiler, warehouse_spec, bq_school_profile, bq_source
    ):
        """compile() for bigquery emits ST_DWITHIN + ST_ASGEOJSON (no DB required).

        Note: The spec (G7) calls for syrupy snapshot tests.  Until syrupy is
        added as a dev dependency (``uv add --dev syrupy``), we use deterministic
        string assertions.  When syrupy is available, replace the sql assertions
        with ``assert cq.sql == snapshot``.
        """
        cq = compiler.compile(warehouse_spec, bq_school_profile, source=bq_source)

        assert cq.path == "engine"
        assert cq.driver == "bigquery"
        assert cq.geodesic is True

        sql = cq.sql
        assert sql is not None
        assert "ST_DWITHIN" in sql
        assert "ST_ASGEOJSON" in sql
        assert "ST_GEOGPOINT" in sql
        # Column identifiers are backtick-quoted for BigQuery
        assert "`location`" in sql
        assert "my_dataset.schools" in sql
        assert "40.7128" in sql
        # count_sql must be present for true_count support
        assert cq.count_sql is not None
        assert "COUNT(*)" in cq.count_sql
        assert "LIMIT" not in cq.count_sql

    def test_compile_is_io_free(self, compiler, warehouse_spec, pg_school_profile, pg_source):
        """compile() does not import asyncdb or perform any I/O."""
        # Temporarily block asyncdb import to confirm compile() never touches it
        import sys as _sys
        original = _sys.modules.get("asyncdb")
        _sys.modules["asyncdb"] = None  # type: ignore[assignment]
        try:
            cq = compiler.compile(warehouse_spec, pg_school_profile, source=pg_source)
            assert cq.sql is not None  # compile succeeded
        finally:
            if original is None:
                _sys.modules.pop("asyncdb", None)
            else:
                _sys.modules["asyncdb"] = original

    def test_compiled_query_is_immutable(
        self, compiler, warehouse_spec, pg_school_profile, pg_source
    ):
        """CompiledQuery is frozen (attempting mutation raises TypeError)."""
        cq = compiler.compile(warehouse_spec, pg_school_profile, source=pg_source)
        with pytest.raises((TypeError, AttributeError)):
            cq.sql = "modified"  # type: ignore[misc]

    def test_engine_path_for_pg(self, compiler, warehouse_spec, pg_school_profile, pg_source):
        """compile() with a pg source uses the engine push-down path."""
        cq = compiler.compile(warehouse_spec, pg_school_profile, source=pg_source)
        assert cq.path == "engine"

    def test_engine_path_for_bigquery(
        self, compiler, warehouse_spec, bq_school_profile, bq_source
    ):
        """compile() with a bigquery source uses the engine push-down path."""
        cq = compiler.compile(warehouse_spec, bq_school_profile, source=bq_source)
        assert cq.path == "engine"

    def test_pandas_path_for_unknown_driver(
        self, compiler, warehouse_spec, pg_school_profile
    ):
        """compile() with an unknown driver falls back to the pandas path."""
        src = MagicMock()
        src.driver = "mysql"
        src.table = "mysql_db.schools"
        src._schema = {}

        # Use a profile with lat/lng for the fallback path
        latlon_profile = DatasetSpatialProfile(
            dataset="schools",
            lat_col="lat",
            lng_col="lng",
            layer="schools",
            property_cols=["name"],
            description_template="{name}",
            geodesic=False,
        )
        cq = compiler.compile(warehouse_spec, latlon_profile, source=src)
        assert cq.path == "pandas"
        assert cq.sql is None
        assert cq.geodesic is False

    def test_pandas_path_for_no_source(
        self, compiler, warehouse_spec
    ):
        """compile() with source=None falls back to the pandas path."""
        latlon_profile = DatasetSpatialProfile(
            dataset="schools",
            lat_col="lat",
            lng_col="lng",
            layer="schools",
            property_cols=["name"],
            description_template="{name}",
            geodesic=False,
        )
        cq = compiler.compile(warehouse_spec, latlon_profile, source=None)
        assert cq.path == "pandas"

    def test_latlon_profile_pg_pushdown(self, compiler, warehouse_spec, pg_source):
        """compile() uses lat/lng template when profile has lat_col/lng_col but no geom_col."""
        latlon_profile = DatasetSpatialProfile(
            dataset="schools",
            lat_col="latitude",
            lng_col="longitude",
            layer="schools",
            property_cols=["name"],
            description_template="{name}",
            geodesic=False,
        )
        pg_source._schema = {"latitude": "double precision", "longitude": "double precision"}
        cq = compiler.compile(warehouse_spec, latlon_profile, source=pg_source)
        assert cq.path == "engine"
        assert cq.sql is not None
        assert "ST_DWithin" in cq.sql
        assert "latitude" in cq.sql
        assert "longitude" in cq.sql


# ---------------------------------------------------------------------------
# Geodesic declare + verify tests
# ---------------------------------------------------------------------------


class TestGeodesicVerify:
    """Tests for the declare + verify discipline."""

    def test_geography_column_geodesic_true(
        self, compiler, warehouse_spec, pg_source
    ):
        """pg geography column → geodesic=True recorded in CompiledQuery."""
        profile = DatasetSpatialProfile(
            dataset="schools", geom_col="geog", layer="schools",
            property_cols=["name"], description_template="{name}", geodesic=True,
        )
        pg_source._schema = {"geog": "geography", "name": "text"}
        cq = compiler.compile(warehouse_spec, profile, source=pg_source)
        assert cq.geodesic is True
        assert cq.geodesic_warning == ""

    def test_non_geography_pg_column_records_false(
        self, compiler, warehouse_spec, pg_source
    ):
        """pg geometry (planar) column → geodesic=False recorded + warning."""
        profile = DatasetSpatialProfile(
            dataset="schools", geom_col="geom", layer="schools",
            property_cols=["name"], description_template="{name}", geodesic=True,  # declared True
        )
        pg_source._schema = {"geom": "geometry", "name": "text"}
        cq = compiler.compile(warehouse_spec, profile, source=pg_source)
        # Actual: geometry is NOT geography, so geodesic should be False
        assert cq.geodesic is False
        assert cq.geodesic_warning != ""
        assert "geodesic" in cq.geodesic_warning.lower() or "geometry" in cq.geodesic_warning

    def test_bigquery_always_geodesic(self, compiler, warehouse_spec, bq_source):
        """BigQuery GEOGRAPHY is always geodesic regardless of declared hint."""
        profile = DatasetSpatialProfile(
            dataset="schools", geom_col="location", layer="schools",
            property_cols=["name"], description_template="{name}", geodesic=False,  # declared False
        )
        bq_source._schema = {"location": "geography"}
        cq = compiler.compile(warehouse_spec, profile, source=bq_source)
        assert cq.geodesic is True  # BigQuery overrides the declared hint
        assert cq.geodesic_warning != ""  # Mismatch should be warned

    def test_schema_not_available_falls_back_to_declared(
        self, compiler, warehouse_spec, pg_source
    ):
        """When the schema is empty, the declared geodesic hint is used."""
        profile = DatasetSpatialProfile(
            dataset="schools", geom_col="geog", layer="schools",
            property_cols=["name"], description_template="{name}", geodesic=True,
        )
        pg_source._schema = {}  # No schema available
        cq = compiler.compile(warehouse_spec, profile, source=pg_source)
        assert cq.geodesic is True
        assert cq.geodesic_warning == ""


# ---------------------------------------------------------------------------
# Unit conversion tests
# ---------------------------------------------------------------------------


class TestToMeters:
    """Tests for the _to_meters helper."""

    def test_miles_to_meters(self):
        """5 miles → approx 8046.72 m."""
        from parrot.tools.dataset_manager.spatial.compiler import _to_meters
        result = _to_meters(5.0, "mi")
        assert abs(result - 8046.72) < 1.0

    def test_km_to_meters(self):
        """10 km → 10000 m."""
        from parrot.tools.dataset_manager.spatial.compiler import _to_meters
        result = _to_meters(10.0, "km")
        assert result == 10000.0

    def test_m_to_meters(self):
        """500 m → 500 m (identity)."""
        from parrot.tools.dataset_manager.spatial.compiler import _to_meters
        result = _to_meters(500.0, "m")
        assert result == 500.0

    def test_invalid_unit_raises(self):
        """Unknown unit raises ValueError."""
        from parrot.tools.dataset_manager.spatial.compiler import _to_meters
        with pytest.raises(ValueError, match="furlongs"):
            _to_meters(1.0, "furlongs")

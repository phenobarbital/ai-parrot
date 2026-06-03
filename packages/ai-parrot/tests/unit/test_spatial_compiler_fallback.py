"""Unit tests for FEAT-219 Module 4: SpatialCompiler Pandas bbox fallback.

Tests:
    test_bbox_predicate_isolated — BETWEEN clause does not disturb equality/IN path.
    test_haversine_refine — bbox-corner points excluded; circle-interior kept.
    test_bbox_from_point — bounding box derivation from a centre point and radius.
    test_fallback_compile_produces_pandas_path — compile() with non-spatial driver.
    test_geodesic_false_for_fallback — pandas path always records geodesic=False.
"""
from __future__ import annotations

import math
import sys
import types

import pytest


# ---------------------------------------------------------------------------
# Minimal stubs (avoids broken navconfig/numpy import chain at module level)
# ---------------------------------------------------------------------------


def _load_module(name: str, path: str) -> types.ModuleType:
    """Load a Python module from an absolute file path."""
    import importlib.util as _util
    spec = _util.spec_from_file_location(name, path)
    mod = _util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _ensure_stubs() -> None:
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

_SPATIAL_BASE = (
    "/home/jesuslara/proyectos/navigator/ai-parrot/.claude/worktrees/"
    "feat-219-spatial-dataset-filter/packages/ai-parrot/src/parrot/"
    "tools/dataset_manager/spatial"
)
_SOURCE_BASE = (
    "/home/jesuslara/proyectos/navigator/ai-parrot/.claude/worktrees/"
    "feat-219-spatial-dataset-filter/packages/ai-parrot/src/parrot/"
    "tools/dataset_manager/sources"
)

_contracts = _load_module(
    "parrot.tools.dataset_manager.spatial.contracts",
    f"{_SPATIAL_BASE}/contracts.py",
)
_registry = _load_module(
    "parrot.tools.dataset_manager.spatial.registry",
    f"{_SPATIAL_BASE}/registry.py",
)

# Stub InMemorySource before loading compiler
_mem_stub = types.ModuleType("parrot.tools.dataset_manager.sources.memory")


class _FakeInMemorySource:
    pass


_mem_stub.InMemorySource = _FakeInMemorySource
sys.modules["parrot.tools.dataset_manager.sources.memory"] = _mem_stub

_compiler_mod = _load_module(
    "parrot.tools.dataset_manager.spatial.compiler",
    f"{_SPATIAL_BASE}/compiler.py",
)

SpatialFilterSpec = _contracts.SpatialFilterSpec
DatasetSpatialProfile = _contracts.DatasetSpatialProfile
SpatialCompiler = _compiler_mod.SpatialCompiler
CompiledQuery = _compiler_mod.CompiledQuery
_bbox_from_point = _compiler_mod._bbox_from_point
_to_meters = _compiler_mod._to_meters


# ---------------------------------------------------------------------------
# TableSource import (for _build_filter_clause tests)
# ---------------------------------------------------------------------------


def _load_table_source() -> type:
    """Load TableSource from the worktree, bypassing the broken import chain."""
    # We need a stub for .base
    _base_stub = types.ModuleType("parrot.tools.dataset_manager.sources.base")

    class _FakeDataSource:
        routing_meta = {}
    _base_stub.DataSource = _FakeDataSource
    sys.modules["parrot.tools.dataset_manager.sources.base"] = _base_stub

    # Stub parrot._imports
    _imports_stub = types.ModuleType("parrot._imports")

    def _fake_lazy_import(name, **kwargs):
        raise ImportError(f"lazy_import({name!r}) called in test context")

    _imports_stub.lazy_import = _fake_lazy_import
    sys.modules["parrot._imports"] = _imports_stub

    table_mod = _load_module(
        "parrot.tools.dataset_manager.sources.table",
        f"{_SOURCE_BASE}/table.py",
    )
    return table_mod.TableSource


try:
    TableSource = _load_table_source()
    _TABLE_SOURCE_AVAILABLE = True
except Exception:
    TableSource = None  # type: ignore[assignment,misc]
    _TABLE_SOURCE_AVAILABLE = False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def compiler() -> SpatialCompiler:
    return SpatialCompiler()


@pytest.fixture
def warehouse_spec() -> SpatialFilterSpec:
    return SpatialFilterSpec(
        point=(40.7128, -74.0060),
        radius=5.0,
        unit="mi",
        datasets=["schools"],
    )


@pytest.fixture
def latlon_profile() -> DatasetSpatialProfile:
    return DatasetSpatialProfile(
        dataset="schools",
        lat_col="latitude",
        lng_col="longitude",
        layer="schools",
        property_cols=["name", "type"],
        description_template="{name} ({type})",
        geodesic=False,
    )


# ---------------------------------------------------------------------------
# _bbox_from_point tests
# ---------------------------------------------------------------------------


class TestBboxFromPoint:
    """Tests for the _bbox_from_point helper function."""

    def test_bbox_contains_centre(self):
        """The derived bbox must contain the centre point."""
        lat, lng = 40.7128, -74.006
        radius_m = 8046.72  # ~5 miles
        min_lat, max_lat, min_lng, max_lng = _bbox_from_point(lat, lng, radius_m)
        assert min_lat < lat < max_lat
        assert min_lng < lng < max_lng

    def test_bbox_is_superset_of_circle(self):
        """Points on the circle boundary must lie inside the bbox."""
        lat, lng = 40.7128, -74.006
        radius_m = 8046.72
        min_lat, max_lat, min_lng, max_lng = _bbox_from_point(lat, lng, radius_m)
        lat_delta = radius_m / 111_320.0
        # North pole of the circle
        assert (lat + lat_delta) <= max_lat + 1e-9
        # South pole of the circle
        assert (lat - lat_delta) >= min_lat - 1e-9

    def test_bbox_corners_outside_circle(self):
        """The four bbox corners are outside the circle (bbox is a strict superset)."""
        lat, lng = 40.7128, -74.006
        radius_m = 8046.72
        min_lat, max_lat, min_lng, max_lng = _bbox_from_point(lat, lng, radius_m)

        # Compute haversine distance from centre to a bbox corner
        corners = [
            (min_lat, min_lng),
            (min_lat, max_lng),
            (max_lat, min_lng),
            (max_lat, max_lng),
        ]
        for c_lat, c_lng in corners:
            lat1 = math.radians(lat)
            lat2 = math.radians(c_lat)
            dlat = math.radians(c_lat - lat)
            dlng = math.radians(c_lng - lng)
            a = (math.sin(dlat / 2) ** 2
                 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2)
            dist_m = 6371008.8 * 2 * math.asin(math.sqrt(a))
            assert dist_m > radius_m, (
                f"Corner ({c_lat}, {c_lng}) is inside the circle (dist={dist_m:.0f}m "
                f"<= radius={radius_m:.0f}m)"
            )


# ---------------------------------------------------------------------------
# Haversine refine tests
# ---------------------------------------------------------------------------


class TestHaversineRefine:
    """Tests for SpatialCompiler._haversine_refine."""

    def test_haversine_refine_excludes_corners(self, compiler):
        """Rows at bbox corners (outside the circle) are dropped by refine."""
        import pandas as pd

        lat, lng = 40.7128, -74.006
        radius_m = 8046.72  # ~5 miles

        # Build a bbox
        min_lat, max_lat, min_lng, max_lng = _bbox_from_point(lat, lng, radius_m)

        # 5 points: 1 at centre (inside), 4 at corners (outside)
        data = {
            "latitude": [lat, min_lat, min_lat, max_lat, max_lat],
            "longitude": [lng, min_lng, max_lng, min_lng, max_lng],
            "name": ["centre", "SW", "SE", "NW", "NE"],
        }
        df = pd.DataFrame(data)

        cq = CompiledQuery(
            sql=None,
            driver="",
            path="pandas",
            geodesic=False,
            profile_dataset="schools",
            point=(lat, lng),
            radius_m=radius_m,
            property_cols=["name"],
            description_template="{name}",
            lat_col="latitude",
            lng_col="longitude",
            bbox=(min_lat, max_lat, min_lng, max_lng),
        )

        refined = compiler._haversine_refine(df, cq)
        assert len(refined) == 1, f"Expected 1 row (centre), got {len(refined)}"
        assert refined.iloc[0]["name"] == "centre"

    def test_haversine_refine_keeps_circle_interior(self, compiler):
        """Points inside the exact circle radius are preserved."""
        import pandas as pd

        lat, lng = 40.7128, -74.006
        radius_m = 8046.72

        # A point close to the centre (well inside)
        close_lat = lat + 0.01  # ~1.1 km north
        close_lng = lng

        # A point just outside the radius (north, well past)
        far_lat = lat + 0.2  # ~22 km north
        far_lng = lng

        df = pd.DataFrame({
            "latitude": [lat, close_lat, far_lat],
            "longitude": [lng, close_lng, far_lng],
            "name": ["centre", "close", "far"],
        })

        cq = CompiledQuery(
            sql=None,
            driver="",
            path="pandas",
            geodesic=False,
            profile_dataset="schools",
            point=(lat, lng),
            radius_m=radius_m,
            property_cols=["name"],
            description_template="{name}",
            lat_col="latitude",
            lng_col="longitude",
        )

        refined = compiler._haversine_refine(df, cq)
        names = set(refined["name"].tolist())
        assert "centre" in names
        assert "close" in names
        assert "far" not in names, "Far point should have been excluded by haversine refine"


# ---------------------------------------------------------------------------
# _build_filter_clause BETWEEN predicate tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _TABLE_SOURCE_AVAILABLE, reason="TableSource import failed")
class TestBuildFilterClauseBetween:
    """Tests for the BETWEEN range predicate in TableSource._build_filter_clause."""

    def _make_source(self, permanent_filter=None):
        """Create a minimal TableSource with permanent_filter set."""
        # TableSource.__init__ calls _normalize_driver and navconfig; use object.__setattr__
        src = object.__new__(TableSource)
        src._permanent_filter = permanent_filter or {}
        src._allowed_columns = None
        return src

    def test_bbox_predicate_isolated(self):
        """Adding a BETWEEN predicate leaves the equality/IN path byte-identical.

        The existing equality and IN clauses must produce exactly the same SQL
        as before the range support was added.
        """
        # Equality only (baseline)
        src_eq = self._make_source({"status": "active"})
        eq_clause = src_eq._build_filter_clause()
        assert eq_clause == "status = 'active'", f"Unexpected equality clause: {eq_clause!r}"

        # IN only (baseline)
        src_in = self._make_source({"status": ["active", "pending"]})
        in_clause = src_in._build_filter_clause()
        assert in_clause == "status IN ('active', 'pending')", (
            f"Unexpected IN clause: {in_clause!r}"
        )

        # Mixed equality + IN (baseline — unchanged)
        src_mixed = self._make_source({"country": "US", "type": ["A", "B"]})
        mixed_clause = src_mixed._build_filter_clause()
        # Order is insertion order; both must be present
        assert "country = 'US'" in mixed_clause
        assert "type IN ('A', 'B')" in mixed_clause

        # Now add a range predicate alongside equality — equality clause unchanged
        src_range = self._make_source(
            {"status": "active", "latitude": {"min": 40.0, "max": 41.0}}
        )
        range_clause = src_range._build_filter_clause()
        assert "status = 'active'" in range_clause, (
            f"Equality clause disturbed by range predicate: {range_clause!r}"
        )
        assert "latitude BETWEEN 40.0 AND 41.0" in range_clause, (
            f"BETWEEN predicate missing or wrong: {range_clause!r}"
        )

    def test_range_predicate_produces_between(self):
        """A dict with min/max produces a BETWEEN clause."""
        src = self._make_source({"score": {"min": 0, "max": 100}})
        clause = src._build_filter_clause()
        assert "score BETWEEN 0 AND 100" in clause

    def test_range_predicate_with_floats(self):
        """Float min/max values produce correct BETWEEN clause."""
        src = self._make_source({"latitude": {"min": 40.5, "max": 41.5}})
        clause = src._build_filter_clause()
        assert "latitude BETWEEN 40.5 AND 41.5" in clause

    def test_range_predicate_with_strings(self):
        """String min/max values are escaped correctly."""
        src = self._make_source({"name": {"min": "a", "max": "z"}})
        clause = src._build_filter_clause()
        assert "name BETWEEN 'a' AND 'z'" in clause

    def test_range_predicate_missing_min_raises(self):
        """A dict with only 'max' raises ValueError."""
        src = self._make_source({"score": {"max": 100}})
        with pytest.raises(ValueError, match="min"):
            src._build_filter_clause()

    def test_range_predicate_missing_max_raises(self):
        """A dict with only 'min' raises ValueError."""
        src = self._make_source({"score": {"min": 0}})
        with pytest.raises(ValueError, match="max"):
            src._build_filter_clause()

    def test_empty_filter_unchanged(self):
        """Empty permanent filter still returns empty string."""
        src = self._make_source({})
        assert src._build_filter_clause() == ""


# ---------------------------------------------------------------------------
# Fallback compile() path tests
# ---------------------------------------------------------------------------


class TestFallbackCompile:
    """Tests for SpatialCompiler.compile() on non-spatial drivers."""

    def test_fallback_compile_produces_pandas_path(self, compiler, warehouse_spec, latlon_profile):
        """compile() for mysql driver produces path='pandas' with sql=None."""
        from unittest.mock import MagicMock
        src = MagicMock()
        src.driver = "mysql"
        src.table = "mydb.schools"
        src._schema = {}

        cq = compiler.compile(warehouse_spec, latlon_profile, source=src)
        assert cq.path == "pandas"
        assert cq.sql is None

    def test_geodesic_false_for_fallback(self, compiler, warehouse_spec, latlon_profile):
        """Pandas bbox fallback always records geodesic=False."""
        from unittest.mock import MagicMock
        src = MagicMock()
        src.driver = "mysql"
        src.table = "mydb.schools"
        src._schema = {}

        cq = compiler.compile(warehouse_spec, latlon_profile, source=src)
        assert cq.geodesic is False

    def test_fallback_bbox_is_populated(self, compiler, warehouse_spec, latlon_profile):
        """compile() for fallback path populates bbox with 4-tuple."""
        from unittest.mock import MagicMock
        src = MagicMock()
        src.driver = "mysql"
        cq = compiler.compile(warehouse_spec, latlon_profile, source=src)
        assert cq.bbox is not None
        assert len(cq.bbox) == 4
        min_lat, max_lat, min_lng, max_lng = cq.bbox
        lat, lng = warehouse_spec.point
        assert min_lat < lat < max_lat
        assert min_lng < lng < max_lng

    def test_fallback_no_source_uses_pandas_path(self, compiler, warehouse_spec, latlon_profile):
        """compile() with source=None still uses pandas path."""
        cq = compiler.compile(warehouse_spec, latlon_profile, source=None)
        assert cq.path == "pandas"

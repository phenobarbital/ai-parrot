"""Tests for the FEAT-600 schema-plane tier in ``CachePartition``.

Covers: plane hit populates hot_cache without touching the vector store,
the ``plane_write`` gate on ``store_table_metadata``, and the AC13
import-isolation guarantee (``parrot.bots.database.cache`` never imports
``parrot.knowledge.wiki`` at runtime).
"""

import sys
import importlib

import pytest

from parrot.bots.database.cache import CachePartition
from parrot.bots.database.models import Completeness, TableMetadata


class FakePlane:
    """Minimal stand-in for ``SchemaPlaneReader`` (get_table/put_table/list_tables)."""

    def __init__(self, meta):
        self.meta = meta
        self.puts = []

    async def get_table(self, origin, schema, table):
        return self.meta

    async def put_table(self, origin, dialect, meta):
        self.puts.append((origin, dialect, meta.tablename))

    async def list_tables(self, origin, schema=None):
        return []


@pytest.fixture
def sales_metadata() -> TableMetadata:
    return TableMetadata(
        schema="epson",
        tablename="sales",
        table_type="BASE TABLE",
        full_name="epson.sales",
        completeness=Completeness.FULL,
    )


class TestPlaneTier:
    async def test_plane_tier_hit(self, sales_metadata: TableMetadata):
        """A plane hit is returned and cached in the LRU tier (AC8)."""
        plane = FakePlane(sales_metadata)
        part = CachePartition(namespace="t", plane=plane, origin="bigquery")
        assert (await part.get("epson", "sales")) is sales_metadata
        assert part._table_cache_key("epson", "sales") in part.hot_cache

    async def test_plane_tier_miss_falls_through_to_vector_store(self):
        """A plane miss (None) falls through without raising; vector store not configured."""
        plane = FakePlane(None)
        part = CachePartition(namespace="t", plane=plane, origin="bigquery")
        assert (await part.get("epson", "sales")) is None

    async def test_plane_not_consulted_when_origin_missing(self, sales_metadata: TableMetadata):
        """No ``origin`` means the plane tier is skipped even when a plane is configured."""
        plane = FakePlane(sales_metadata)
        part = CachePartition(namespace="t", plane=plane, origin=None)
        assert (await part.get("epson", "sales")) is None

    async def test_plane_lookup_error_is_swallowed(self):
        """Errors from the plane are logged, never raised (best-effort tier)."""

        class ExplodingPlane(FakePlane):
            async def get_table(self, origin, schema, table):
                raise RuntimeError("boom")

        part = CachePartition(namespace="t", plane=ExplodingPlane(None), origin="bigquery")
        assert (await part.get("epson", "sales")) is None


class TestWriteThroughGate:
    async def test_write_through_gate_enabled(self, sales_metadata: TableMetadata):
        plane = FakePlane(None)
        part = CachePartition(namespace="t", plane=plane, origin="bigquery", plane_write=True)
        await part.store_table_metadata(sales_metadata)
        assert plane.puts == [("bigquery", "bigquery", "sales")]

    async def test_write_through_gate_disabled_by_default(self, sales_metadata: TableMetadata):
        plane = FakePlane(None)
        part = CachePartition(namespace="t", plane=plane, origin="bigquery")
        await part.store_table_metadata(sales_metadata)
        assert plane.puts == []

    async def test_write_through_requires_plane(self, sales_metadata: TableMetadata):
        """``plane_write=True`` with no plane never enables the flag (constructor guard)."""
        part = CachePartition(namespace="t", plane=None, origin="bigquery", plane_write=True)
        assert part.plane_write is False
        await part.store_table_metadata(sales_metadata)  # must not raise

    async def test_write_through_error_is_swallowed(self, sales_metadata: TableMetadata):
        class ExplodingPlane(FakePlane):
            async def put_table(self, origin, dialect, meta):
                raise RuntimeError("boom")

        part = CachePartition(namespace="t", plane=ExplodingPlane(None), origin="bigquery", plane_write=True)
        await part.store_table_metadata(sales_metadata)  # must not raise


class TestParityWhenPlaneIsNone:
    async def test_plane_none_is_a_no_op(self, sales_metadata: TableMetadata):
        """With plane=None every code path is unchanged (AC8)."""
        part = CachePartition(namespace="t")
        assert part.plane is None
        assert part.plane_write is False
        await part.store_table_metadata(sales_metadata)
        assert (await part.get("epson", "sales")) is sales_metadata


class TestDatabaseToolkitOrigin:
    def test_config_origin_defaults_to_none(self):
        from parrot.bots.database.toolkits.base import DatabaseToolkitConfig

        cfg = DatabaseToolkitConfig(origin=None, database_type="bigquery")
        assert cfg.origin is None  # config field itself stays unset; the toolkit applies the default

    def test_toolkit_origin_defaults_to_database_type(self, fake_postgres_toolkit):
        """``DatabaseToolkit(...).origin == database_type`` by default."""
        assert fake_postgres_toolkit.origin == fake_postgres_toolkit.database_type == "postgresql"

    def test_toolkit_origin_explicit_override(self):
        from parrot.bots.database.toolkits.base import DatabaseToolkit

        class _MinimalToolkit(DatabaseToolkit):
            async def start(self) -> None:
                pass

            async def stop(self) -> None:
                pass

            async def search_schema(self, search_term, schema_name=None, limit=10):
                return []

            async def execute_query(self, query, limit=1000, timeout=30):
                raise NotImplementedError

        tk = _MinimalToolkit(
            dsn="postgresql://test:test@localhost:5432/testdb",
            allowed_schemas=["public"],
            primary_schema="public",
            database_type="postgresql",
            origin="bigquery",
        )
        assert tk.origin == "bigquery"
        assert tk.database_type == "postgresql"


def test_no_wiki_import_at_runtime(monkeypatch):
    """AC13: importing ``parrot.bots.database.cache`` must not import ``parrot.knowledge.wiki``."""
    monkeypatch.setitem(sys.modules, "parrot.knowledge.wiki", None)
    for m in [k for k in sys.modules if k.startswith("parrot.bots.database.cache")]:
        monkeypatch.delitem(sys.modules, m)
    importlib.import_module("parrot.bots.database.cache")

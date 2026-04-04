"""Unit tests for CacheManager and CachePartition."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(__file__))
from conftest_db import setup_worktree_imports  # noqa: E402
setup_worktree_imports()

import pytest  # noqa: E402
from parrot.bots.database.cache import (  # noqa: E402
    CacheManager,
    CachePartition,
    CachePartitionConfig,
)
from parrot.bots.database.models import TableMetadata  # noqa: E402


@pytest.fixture
def cache_manager():
    return CacheManager(redis_url=None, vector_store=None)


@pytest.fixture
def sample_table():
    return TableMetadata(
        schema="public", tablename="orders", table_type="BASE TABLE",
        full_name='"public"."orders"',
        columns=[{"name": "id", "type": "integer", "nullable": False}],
        primary_keys=["id"], foreign_keys=[], indexes=[], row_count=1000,
    )


def _make_table(schema: str, name: str) -> TableMetadata:
    return TableMetadata(
        schema=schema, tablename=name, table_type="BASE TABLE",
        full_name=f'"{schema}"."{name}"',
        columns=[{"name": "id", "type": "integer", "nullable": False}],
        primary_keys=["id"], foreign_keys=[], indexes=[],
    )


class TestCachePartitionIsolation:
    @pytest.mark.asyncio
    async def test_partitions_independent(self, cache_manager, sample_table):
        p1 = cache_manager.create_partition(CachePartitionConfig(namespace="db1"))
        p2 = cache_manager.create_partition(CachePartitionConfig(namespace="db2"))
        await p1.store_table_metadata(sample_table)
        assert await p2.get_table_metadata("public", "orders") is None

    @pytest.mark.asyncio
    async def test_partition_stores_and_retrieves(self, cache_manager, sample_table):
        p = cache_manager.create_partition(CachePartitionConfig(namespace="test"))
        await p.store_table_metadata(sample_table)
        result = await p.get_table_metadata("public", "orders")
        assert result is not None and result.tablename == "orders"

    @pytest.mark.asyncio
    async def test_partition_lru_eviction(self, cache_manager):
        p = cache_manager.create_partition(CachePartitionConfig(namespace="small", lru_maxsize=2))
        for i in range(3):
            await p.store_table_metadata(_make_table("public", f"table_{i}"))
        p.schema_cache.clear()
        assert await p.get_table_metadata("public", "table_0") is None

    @pytest.mark.asyncio
    async def test_partition_independent_lru_sizes(self, cache_manager):
        p_small = cache_manager.create_partition(CachePartitionConfig(namespace="small", lru_maxsize=2))
        p_large = cache_manager.create_partition(CachePartitionConfig(namespace="large", lru_maxsize=100))
        for i in range(3):
            t = _make_table("public", f"item_{i}")
            await p_small.store_table_metadata(t)
            await p_large.store_table_metadata(t)
        p_small.schema_cache.clear()
        assert await p_small.get_table_metadata("public", "item_0") is None
        p_large.schema_cache.clear()
        assert await p_large.get_table_metadata("public", "item_0") is not None

    def test_duplicate_namespace_raises(self, cache_manager):
        cache_manager.create_partition(CachePartitionConfig(namespace="dup"))
        with pytest.raises(ValueError, match="already exists"):
            cache_manager.create_partition(CachePartitionConfig(namespace="dup"))


class TestCrossPartitionSearch:
    @pytest.mark.asyncio
    async def test_search_across_databases(self, cache_manager, sample_table):
        p1 = cache_manager.create_partition(CachePartitionConfig(namespace="db1"))
        p2 = cache_manager.create_partition(CachePartitionConfig(namespace="db2"))
        await p1.store_table_metadata(sample_table)
        await p2.store_table_metadata(_make_table("analytics", "orders_bq"))
        results = await cache_manager.search_across_databases("orders", limit=10)
        assert len(results) >= 2

    @pytest.mark.asyncio
    async def test_search_respects_limit(self, cache_manager):
        p = cache_manager.create_partition(CachePartitionConfig(namespace="db"))
        for i in range(10):
            await p.store_table_metadata(_make_table("public", f"order_{i}"))
        results = await cache_manager.search_across_databases("order", limit=3)
        assert len(results) <= 3


class TestCacheManagerFallback:
    def test_no_redis(self):
        assert CacheManager(redis_url=None, vector_store=None)._redis_pool is None

    @pytest.mark.asyncio
    async def test_close_without_redis(self):
        await CacheManager(redis_url=None, vector_store=None).close()

    def test_get_partition(self, cache_manager):
        cache_manager.create_partition(CachePartitionConfig(namespace="pg"))
        assert cache_manager.get_partition("pg") is not None
        assert cache_manager.get_partition("nonexistent") is None


class TestSchemaOverview:
    @pytest.mark.asyncio
    async def test_schema_overview_after_store(self, cache_manager, sample_table):
        p = cache_manager.create_partition(CachePartitionConfig(namespace="pg"))
        await p.store_table_metadata(sample_table)
        overview = p.get_schema_overview("public")
        assert overview is not None and "orders" in overview.tables

    @pytest.mark.asyncio
    async def test_hot_tables_tracking(self, cache_manager, sample_table):
        p = cache_manager.create_partition(CachePartitionConfig(namespace="pg"))
        await p.store_table_metadata(sample_table)
        for _ in range(5):
            await p.get_table_metadata("public", "orders")
        hot = p.get_hot_tables(["public"], limit=5)
        assert len(hot) >= 1 and hot[0][2] >= 5


class TestImports:
    def test_public_imports(self):
        assert all([CacheManager, CachePartition, CachePartitionConfig])

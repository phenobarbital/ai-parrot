"""Unit tests for CacheManager and CachePartition.

Note: The ``parrot`` package is editable-installed from the main repo.
To test worktree changes, we reload ``parrot.bots.database.cache`` from the
worktree path at import time.
"""
import importlib
import os
import sys
import types
import pytest

# ---------------------------------------------------------------------------
# Workaround: parrot.bots.database.__init__ imports AbstractDBAgent which has
# broken imports (parrot.tools.database.pg / bq).  Stub them before touching
# the database sub-package.
# ---------------------------------------------------------------------------
for _path, _cls_name in [
    ("parrot.tools.database.pg", "PgSchemaSearchTool"),
    ("parrot.tools.database.bq", "BQSchemaSearchTool"),
]:
    if _path not in sys.modules:
        _stub = types.ModuleType(_path)
        setattr(_stub, _cls_name, type(_cls_name, (), {}))
        sys.modules[_path] = _stub

# Now force-reload the cache module from the **worktree** copy so that our
# new CacheManager/CachePartition classes are available even though the
# installed editable package still points to the main repo.
_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKTREE_SRC = os.path.normpath(
    os.path.join(_HERE, os.pardir, os.pardir, "packages", "ai-parrot", "src")
)
_CACHE_FILE = os.path.join(
    _WORKTREE_SRC, "parrot", "bots", "database", "cache.py"
)

if os.path.isfile(_CACHE_FILE):
    # Import models first (they are unchanged, use the installed copy)
    from parrot.bots.database.models import (  # noqa: E402
        SchemaMetadata,
        TableMetadata,
    )

    # Load cache module from worktree file
    _spec = importlib.util.spec_from_file_location(
        "parrot.bots.database.cache", _CACHE_FILE
    )
    _cache_mod = importlib.util.module_from_spec(_spec)
    sys.modules["parrot.bots.database.cache"] = _cache_mod
    _spec.loader.exec_module(_cache_mod)

    CacheManager = _cache_mod.CacheManager
    CachePartition = _cache_mod.CachePartition
    CachePartitionConfig = _cache_mod.CachePartitionConfig
else:
    # Fallback: if running from main repo (already has the new code)
    from parrot.bots.database.cache import (  # noqa: E402
        CacheManager,
        CachePartition,
        CachePartitionConfig,
    )
    from parrot.bots.database.models import TableMetadata  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cache_manager():
    """CacheManager in LRU-only mode (no Redis, no vector store)."""
    return CacheManager(redis_url=None, vector_store=None)


@pytest.fixture
def sample_table():
    return TableMetadata(
        schema="public",
        tablename="orders",
        table_type="BASE TABLE",
        full_name='"public"."orders"',
        columns=[{"name": "id", "type": "integer", "nullable": False}],
        primary_keys=["id"],
        foreign_keys=[],
        indexes=[],
        row_count=1000,
    )


def _make_table(schema: str, name: str) -> TableMetadata:
    """Helper to quickly build a TableMetadata stub."""
    return TableMetadata(
        schema=schema,
        tablename=name,
        table_type="BASE TABLE",
        full_name=f'"{schema}"."{name}"',
        columns=[{"name": "id", "type": "integer", "nullable": False}],
        primary_keys=["id"],
        foreign_keys=[],
        indexes=[],
    )


# ---------------------------------------------------------------------------
# Partition isolation
# ---------------------------------------------------------------------------

class TestCachePartitionIsolation:
    @pytest.mark.asyncio
    async def test_partitions_independent(self, cache_manager, sample_table):
        """Two partitions don't share entries."""
        p1 = cache_manager.create_partition(CachePartitionConfig(namespace="db1"))
        p2 = cache_manager.create_partition(CachePartitionConfig(namespace="db2"))
        await p1.store_table_metadata(sample_table)
        result = await p2.get_table_metadata("public", "orders")
        assert result is None

    @pytest.mark.asyncio
    async def test_partition_stores_and_retrieves(self, cache_manager, sample_table):
        """Partition can store and retrieve metadata."""
        p = cache_manager.create_partition(CachePartitionConfig(namespace="test"))
        await p.store_table_metadata(sample_table)
        result = await p.get_table_metadata("public", "orders")
        assert result is not None
        assert result.tablename == "orders"

    @pytest.mark.asyncio
    async def test_partition_lru_eviction(self, cache_manager):
        """Partition respects its own maxsize — oldest entries are evicted."""
        p = cache_manager.create_partition(
            CachePartitionConfig(namespace="small", lru_maxsize=2)
        )
        for i in range(3):
            t = _make_table("public", f"table_{i}")
            await p.store_table_metadata(t)
        # table_0 should have been evicted from LRU.
        # Clear schema_cache to test LRU eviction in isolation.
        p.schema_cache.clear()
        result = await p.get_table_metadata("public", "table_0")
        assert result is None

    @pytest.mark.asyncio
    async def test_partition_independent_lru_sizes(self, cache_manager):
        """Different partitions can have different LRU maxsizes."""
        p_small = cache_manager.create_partition(
            CachePartitionConfig(namespace="small", lru_maxsize=2)
        )
        p_large = cache_manager.create_partition(
            CachePartitionConfig(namespace="large", lru_maxsize=100)
        )
        for i in range(3):
            t = _make_table("public", f"item_{i}")
            await p_small.store_table_metadata(t)
            await p_large.store_table_metadata(t)

        p_small.schema_cache.clear()
        assert await p_small.get_table_metadata("public", "item_0") is None
        p_large.schema_cache.clear()
        assert await p_large.get_table_metadata("public", "item_0") is not None

    def test_duplicate_namespace_raises(self, cache_manager):
        """Creating a partition with an existing namespace raises ValueError."""
        cache_manager.create_partition(CachePartitionConfig(namespace="dup"))
        with pytest.raises(ValueError, match="already exists"):
            cache_manager.create_partition(CachePartitionConfig(namespace="dup"))


# ---------------------------------------------------------------------------
# Cross-partition search
# ---------------------------------------------------------------------------

class TestCrossPartitionSearch:
    @pytest.mark.asyncio
    async def test_search_across_databases(self, cache_manager, sample_table):
        """Cross-partition search returns results from all partitions."""
        p1 = cache_manager.create_partition(CachePartitionConfig(namespace="db1"))
        p2 = cache_manager.create_partition(CachePartitionConfig(namespace="db2"))
        await p1.store_table_metadata(sample_table)
        t2 = _make_table("analytics", "orders_bq")
        await p2.store_table_metadata(t2)
        results = await cache_manager.search_across_databases("orders", limit=10)
        assert len(results) >= 2

    @pytest.mark.asyncio
    async def test_search_respects_limit(self, cache_manager):
        """Cross-partition search respects the limit parameter."""
        p = cache_manager.create_partition(CachePartitionConfig(namespace="db"))
        for i in range(10):
            await p.store_table_metadata(_make_table("public", f"order_{i}"))
        results = await cache_manager.search_across_databases("order", limit=3)
        assert len(results) <= 3


# ---------------------------------------------------------------------------
# Fallback / no-Redis
# ---------------------------------------------------------------------------

class TestCacheManagerFallback:
    def test_no_redis(self):
        """CacheManager works without Redis."""
        cm = CacheManager(redis_url=None, vector_store=None)
        assert cm is not None
        assert cm._redis_pool is None

    @pytest.mark.asyncio
    async def test_close_without_redis(self):
        """close() doesn't crash without Redis."""
        cm = CacheManager(redis_url=None, vector_store=None)
        await cm.close()

    def test_get_partition(self, cache_manager):
        """get_partition returns the correct partition or None."""
        cache_manager.create_partition(CachePartitionConfig(namespace="pg"))
        assert cache_manager.get_partition("pg") is not None
        assert cache_manager.get_partition("nonexistent") is None


# ---------------------------------------------------------------------------
# Schema overview & hot tables
# ---------------------------------------------------------------------------

class TestSchemaOverview:
    @pytest.mark.asyncio
    async def test_schema_overview_after_store(self, cache_manager, sample_table):
        """Schema overview is populated after storing metadata."""
        p = cache_manager.create_partition(CachePartitionConfig(namespace="pg"))
        await p.store_table_metadata(sample_table)
        overview = p.get_schema_overview("public")
        assert overview is not None
        assert "orders" in overview.tables

    @pytest.mark.asyncio
    async def test_hot_tables_tracking(self, cache_manager, sample_table):
        """Accessing tables tracks hot table statistics."""
        p = cache_manager.create_partition(CachePartitionConfig(namespace="pg"))
        await p.store_table_metadata(sample_table)
        for _ in range(5):
            await p.get_table_metadata("public", "orders")
        hot = p.get_hot_tables(["public"], limit=5)
        assert len(hot) >= 1
        assert hot[0][2] >= 5


# ---------------------------------------------------------------------------
# Import check
# ---------------------------------------------------------------------------

class TestImports:
    def test_public_imports(self):
        """Verify the expected public API is importable."""
        assert CacheManager is not None
        assert CachePartition is not None
        assert CachePartitionConfig is not None
